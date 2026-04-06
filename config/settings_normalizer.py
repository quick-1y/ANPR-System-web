"""Нормализация и валидация системных настроек."""

#!/usr/bin/env python3

from __future__ import annotations

import copy
from typing import Any, Dict, Optional

from common.logging import get_logger
from config.settings_migrations import run_settings_migrations
from config.settings_schema import (
    SETTINGS_VERSION,
    SUPPORTED_CONTROLLER_TYPES,
    channel_defaults,
    debug_defaults,
    detector_defaults,
    direction_defaults,
    inference_defaults,
    logging_defaults,
    model_defaults,
    normalize_hotkey,
    normalize_log_level,
    normalize_region_config,
    ocr_defaults,
    plate_defaults,
    reconnect_defaults,
    relay_defaults,
    storage_defaults,
    time_defaults,
)

logger = get_logger(__name__)


class SettingsNormalizer:
    def _normalize_relay(self, relay: Dict[str, Any]) -> Dict[str, Any]:
        defaults = relay_defaults()
        normalized = dict(defaults)
        normalized.update(relay or {})
        mode = str(normalized.get("mode", "pulse") or "pulse")
        if mode not in ("pulse", "pulse_timer"):
            mode = "pulse"
        normalized["mode"] = mode
        try:
            timer = int(normalized.get("timer_seconds", 1) or 1)
        except (TypeError, ValueError):
            timer = 1
        if mode == "pulse":
            timer = 1
        normalized["timer_seconds"] = max(1, timer)
        normalized["hotkey"] = normalize_hotkey(normalized.get("hotkey", ""), strict=False)
        return normalized

    @staticmethod
    def _validate_controller_type(controller: Dict[str, Any]) -> None:
        controller_type = str(controller.get("type") or "").strip()
        if not controller_type:
            controller["type"] = "DTWONDER2CH"
            return
        if controller_type not in SUPPORTED_CONTROLLER_TYPES:
            supported = ", ".join(SUPPORTED_CONTROLLER_TYPES)
            raise ValueError(
                f"Неподдерживаемый тип контроллера '{controller_type}'. Поддерживаемые типы: {supported}"
            )

    def _fill_channel_defaults(self, channel: Dict[str, Any], tracking_defaults: Dict[str, Any]) -> bool:
        defaults = channel_defaults(tracking_defaults)
        changed = False
        for key, value in defaults.items():
            if key not in channel:
                channel[key] = value
                changed = True
        if "debug" in channel:
            channel.pop("debug", None)
            changed = True

        dir_defaults = defaults.get("direction", direction_defaults())
        channel_direction = channel.get("direction")
        if channel_direction is None:
            channel["direction"] = dict(dir_defaults)
            changed = True
        else:
            for key, value in dir_defaults.items():
                if key not in channel_direction:
                    channel_direction[key] = value
                    changed = True

        upgraded_region = normalize_region_config(channel.get("region"))
        if channel.get("region") != upgraded_region:
            channel["region"] = upgraded_region
            changed = True

        controller_id = channel.get("controller_id")
        if controller_id in ("", 0, "0"):
            controller_id = None
        elif controller_id is not None:
            try:
                controller_id = int(controller_id)
            except (TypeError, ValueError):
                controller_id = None
        if channel.get("controller_id") != controller_id:
            channel["controller_id"] = controller_id
            changed = True
        if channel.get("controller_id") is None and channel.get("controller_relay") != 0:
            channel["controller_relay"] = 0
            changed = True

        if "controller_action" in channel:
            channel.pop("controller_action", None)
            changed = True

        try:
            controller_relay = int(channel.get("controller_relay", 0) or 0)
        except (TypeError, ValueError):
            controller_relay = 0
        if controller_relay not in (0, 1):
            controller_relay = 0
        if channel.get("controller_relay") != controller_relay:
            channel["controller_relay"] = controller_relay
            changed = True

        mode = str(channel.get("list_filter_mode") or "all").strip().lower()
        if mode not in {"all", "whitelist", "custom"}:
            mode = "all"
        if channel.get("list_filter_mode") != mode:
            channel["list_filter_mode"] = mode
            changed = True

        raw_ids = channel.get("list_filter_list_ids")
        if not isinstance(raw_ids, list):
            raw_ids = []
        normalized_ids = []
        for item in raw_ids:
            try:
                value = int(item)
            except (TypeError, ValueError):
                continue
            if value > 0 and value not in normalized_ids:
                normalized_ids.append(value)
        if channel.get("list_filter_list_ids") != normalized_ids:
            channel["list_filter_list_ids"] = normalized_ids
            changed = True
        return changed

    def _fill_reconnect_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        if "reconnect" not in data:
            data["reconnect"] = defaults
            return True

        changed = False
        reconnect_section = data.get("reconnect", {})
        for key, default_value in defaults.items():
            if key not in reconnect_section:
                reconnect_section[key] = default_value
                changed = True
            elif isinstance(default_value, dict):
                for sub_key, sub_val in default_value.items():
                    if sub_key not in reconnect_section[key]:
                        reconnect_section[key][sub_key] = sub_val
                        changed = True
        data["reconnect"] = reconnect_section
        return changed

    def _fill_debug_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        if "debug" not in data:
            data["debug"] = defaults
            return True

        changed = False
        debug_section = data.get("debug", {})
        for key, value in defaults.items():
            if key not in debug_section:
                debug_section[key] = value
                changed = True
        data["debug"] = debug_section
        return changed

    def _fill_controller_defaults(self, data: Dict[str, Any]) -> bool:
        if "controllers" not in data:
            data["controllers"] = []
            return True
        controllers = data.get("controllers", [])
        changed = False
        max_id = 0
        for controller in controllers:
            try:
                controller_id = int(controller.get("id", 0))
            except (TypeError, ValueError):
                controller_id = 0
            max_id = max(max_id, controller_id)

        for controller in controllers:
            try:
                controller_id = int(controller.get("id", 0))
            except (TypeError, ValueError):
                controller_id = 0
            if controller_id <= 0:
                max_id += 1
                controller["id"] = max_id
                changed = True
            prev_type = controller.get("type")
            self._validate_controller_type(controller)
            if controller.get("type") != prev_type:
                changed = True
            if "name" not in controller:
                controller["name"] = f"Контроллер {controller_id or max_id}"
                changed = True
            if "address" not in controller:
                controller["address"] = ""
                changed = True
            if "password" not in controller:
                controller["password"] = "0"
                changed = True
            relays = controller.get("relays")
            if not isinstance(relays, list) or len(relays) != 2:
                controller["relays"] = [relay_defaults(), relay_defaults()]
                changed = True
                relays = controller["relays"]
            normalized_relays = [self._normalize_relay(relay) for relay in relays[:2]]
            if controller.get("relays") != normalized_relays:
                controller["relays"] = normalized_relays
                changed = True
            hotkeys = [relay.get("hotkey", "") for relay in normalized_relays if relay.get("hotkey")]
            if len(hotkeys) != len(set(hotkeys)):
                logger.warning(
                    "Контроллер %s содержит дубли hotkey в settings; значения сохранены без скрытой модификации",
                    controller.get("name") or controller.get("id") or "unknown",
                )
        data["controllers"] = controllers
        return changed

    def _fill_storage_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        if "storage" not in data:
            data["storage"] = defaults
            return True

        changed = False
        storage = data.get("storage", {})
        for key, val in defaults.items():
            if key not in storage:
                storage[key] = val
                changed = True
        if "export_dir" in storage:
            storage.pop("export_dir", None)
            changed = True
        data["storage"] = storage
        return changed

    def _fill_plate_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        if "plates" not in data:
            data["plates"] = defaults
            return True

        changed = False
        plates = data.get("plates", {})
        for key, val in defaults.items():
            if key not in plates:
                plates[key] = val
                changed = True
        data["plates"] = plates
        return changed

    def _fill_model_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        if "models" not in data:
            data["models"] = defaults
            return True

        changed = False
        models = data.get("models", {})
        for key, val in defaults.items():
            if key not in models:
                models[key] = val
                changed = True
        data["models"] = models
        return changed

    def _fill_ocr_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        if "ocr" not in data:
            data["ocr"] = defaults
            return True

        changed = False
        ocr = data.get("ocr", {})
        for key, val in defaults.items():
            if key not in ocr:
                ocr[key] = val
                changed = True
        # Remove legacy confidence_threshold — OCR confidence is per-channel (ocr_min_confidence)
        if "confidence_threshold" in ocr:
            del ocr["confidence_threshold"]
            changed = True
        data["ocr"] = ocr
        return changed

    def _fill_detector_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        if "detector" not in data:
            data["detector"] = defaults
            return True

        changed = False
        detector = data.get("detector", {})
        for key, val in defaults.items():
            if key not in detector:
                detector[key] = val
                changed = True
        data["detector"] = detector
        return changed

    def _fill_inference_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        if "inference" not in data:
            data["inference"] = defaults
            return True

        changed = False
        inference = data.get("inference", {})
        for key, val in defaults.items():
            if key not in inference:
                inference[key] = val
                changed = True
        data["inference"] = inference
        return changed

    def _fill_time_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        if "time" not in data:
            data["time"] = defaults
            return True

        changed = False
        time_section = data.get("time", {})
        for key, val in defaults.items():
            if key not in time_section:
                time_section[key] = val
                changed = True
        data["time"] = time_section
        return changed

    def _fill_logging_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        if "logging" not in data:
            data["logging"] = defaults
            return True

        changed = False
        logging_section = data.get("logging", {})
        for key, val in defaults.items():
            if key not in logging_section:
                logging_section[key] = val
                changed = True

        normalized_level = normalize_log_level(logging_section.get("level"))
        if logging_section.get("level") != normalized_level:
            logging_section["level"] = normalized_level
            changed = True

        allowed_levels = defaults.get("allowed_levels") or []
        if list(logging_section.get("allowed_levels") or []) != list(allowed_levels):
            logging_section["allowed_levels"] = list(allowed_levels)
            changed = True

        data["logging"] = logging_section
        return changed

    def normalize_with_meta(self, data: dict) -> tuple[dict, bool]:
        normalized = copy.deepcopy(data)
        normalized, changed = run_settings_migrations(normalized, SETTINGS_VERSION)
        tracking_defaults = normalized.get("tracking", {})

        if not normalized.get("theme"):
            normalized["theme"] = "dark"
            changed = True

        if "sidebar_locked" not in normalized:
            normalized["sidebar_locked"] = False
            changed = True

        dir_defaults = direction_defaults()
        direction_settings = tracking_defaults.get("direction")
        if direction_settings is None:
            tracking_defaults["direction"] = dir_defaults
            normalized["tracking"] = tracking_defaults
            changed = True
        else:
            for key, value in dir_defaults.items():
                if key not in direction_settings:
                    direction_settings[key] = value
                    changed = True

        for channel in normalized.get("channels", []):
            if self._fill_channel_defaults(channel, tracking_defaults):
                changed = True

        if self._fill_reconnect_defaults(normalized, reconnect_defaults()):
            changed = True
        if self._fill_model_defaults(normalized, model_defaults()):
            changed = True
        if self._fill_ocr_defaults(normalized, ocr_defaults()):
            changed = True
        if self._fill_detector_defaults(normalized, detector_defaults()):
            changed = True
        if self._fill_inference_defaults(normalized, inference_defaults()):
            changed = True
        if self._fill_storage_defaults(normalized, storage_defaults()):
            changed = True
        if self._fill_plate_defaults(normalized, plate_defaults()):
            changed = True
        if self._fill_time_defaults(normalized, time_defaults()):
            changed = True
        if self._fill_logging_defaults(normalized, logging_defaults()):
            changed = True
        if self._fill_debug_defaults(normalized, debug_defaults()):
            changed = True
        if self._fill_controller_defaults(normalized):
            changed = True

        return normalized, changed

    def normalize(self, data: dict) -> dict:
        normalized, _ = self.normalize_with_meta(data)
        return normalized
