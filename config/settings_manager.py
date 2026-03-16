#!/usr/bin/env python3
#/anpr/infrastructure/settings_manager.py
import copy
import os
from typing import Any, Dict, List, Optional

from common.logging import get_logger

from config.settings_normalizer import SettingsNormalizer
from config.settings_repository import SettingsRepository
from config.settings_schema import (
    build_default_settings,
    channel_defaults,
    debug_defaults,
    detector_defaults,
    direction_defaults as schema_direction_defaults,
    inference_defaults,
    logging_defaults,
    model_defaults,
    normalize_log_level,
    normalize_region_config as schema_normalize_region_config,
    ocr_defaults,
    plate_defaults,
    plate_size_defaults as schema_plate_size_defaults,
    reconnect_defaults,
    relay_defaults,
    storage_defaults,
    time_defaults,
)


logger = get_logger(__name__)


def normalize_region_config(region: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return schema_normalize_region_config(region)


class SettingsManager:
    """Управляет конфигурацией приложения и каналами."""

    def __init__(self, path: str | None = None) -> None:
        self._normalizer = SettingsNormalizer()
        self._repo = SettingsRepository(self, path)
        self._file_lock = self._repo._file_lock
        self.settings = self._normalize_and_persist_if_changed(self._repo.settings)

    def _normalize_and_persist_if_changed(self, raw_settings: Dict[str, Any]) -> Dict[str, Any]:
        normalized, changed = self._normalizer.normalize_with_meta(raw_settings)
        if changed:
            self._repo.save(normalized)
        return normalized

    def _default(self) -> Dict[str, Any]:
        return build_default_settings()


    @staticmethod
    def _channel_defaults(tracking_defaults: Dict[str, Any]) -> Dict[str, Any]:
        return channel_defaults(tracking_defaults)

    @staticmethod
    def _debug_defaults() -> Dict[str, Any]:
        return debug_defaults()

    @staticmethod
    def _relay_defaults() -> Dict[str, Any]:
        return relay_defaults()

    @staticmethod
    def _reconnect_defaults() -> Dict[str, Any]:
        return reconnect_defaults()

    @staticmethod
    def _storage_defaults() -> Dict[str, Any]:
        return storage_defaults()

    @staticmethod
    def _plate_defaults() -> Dict[str, Any]:
        return plate_defaults()

    @staticmethod
    def _model_defaults() -> Dict[str, Any]:
        return model_defaults()

    @staticmethod
    def _inference_defaults() -> Dict[str, Any]:
        return inference_defaults()

    @staticmethod
    def _plate_size_defaults() -> Dict[str, Dict[str, int]]:
        return schema_plate_size_defaults()

    @staticmethod
    def _direction_defaults() -> Dict[str, float | int]:
        return schema_direction_defaults()

    @staticmethod
    def _ocr_defaults() -> Dict[str, Any]:
        return ocr_defaults()

    @staticmethod
    def _detector_defaults() -> Dict[str, Any]:
        return detector_defaults()

    @staticmethod
    def _time_defaults() -> Dict[str, Any]:
        return time_defaults()

    @staticmethod
    def _logging_defaults() -> Dict[str, Any]:
        return logging_defaults()


    def _normalize_hotkey(self, value: Any) -> str:
        return self._normalizer._normalize_hotkey(value)

    def _normalize_relay(self, relay: Dict[str, Any]) -> Dict[str, Any]:
        return self._normalizer._normalize_relay(relay)

    def _fill_channel_defaults(self, channel: Dict[str, Any], tracking_defaults: Dict[str, Any]) -> bool:
        return self._normalizer._fill_channel_defaults(channel, tracking_defaults)

    def _fill_reconnect_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        return self._normalizer._fill_reconnect_defaults(data, defaults)

    def _fill_debug_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        return self._normalizer._fill_debug_defaults(data, defaults)

    def _fill_controller_defaults(self, data: Dict[str, Any]) -> bool:
        return self._normalizer._fill_controller_defaults(data)

    def _fill_storage_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        return self._normalizer._fill_storage_defaults(data, defaults)

    def _fill_plate_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        return self._normalizer._fill_plate_defaults(data, defaults)

    def _fill_model_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        return self._normalizer._fill_model_defaults(data, defaults)

    def _fill_ocr_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        return self._normalizer._fill_ocr_defaults(data, defaults)

    def _fill_detector_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        return self._normalizer._fill_detector_defaults(data, defaults)

    def _fill_inference_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        return self._normalizer._fill_inference_defaults(data, defaults)

    def _fill_time_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        return self._normalizer._fill_time_defaults(data, defaults)

    def _fill_logging_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        return self._normalizer._fill_logging_defaults(data, defaults)


    def get_channels(self) -> List[Dict[str, Any]]:
        with self._file_lock:
            channels = self.settings.get("channels", [])
            tracking_defaults = self.settings.get("tracking", {})
        changed = False
        max_id = 0
        for channel in channels:
            try:
                channel_id = int(channel.get("id", 0))
            except (TypeError, ValueError):
                channel_id = 0
            max_id = max(max_id, channel_id)

        for channel in channels:
            try:
                channel_id = int(channel.get("id", 0))
            except (TypeError, ValueError):
                channel_id = 0
            if channel_id <= 0:
                max_id += 1
                channel["id"] = max_id
                changed = True
            if self._normalizer._fill_channel_defaults(channel, tracking_defaults):
                changed = True

        if changed:
            self.save_channels(channels)
        return copy.deepcopy(channels)

    def save_channels(self, channels: List[Dict[str, Any]]) -> None:
        with self._file_lock:
            self.settings["channels"] = copy.deepcopy(channels)
            settings_snapshot = copy.deepcopy(self.settings)
        self._repo.save(settings_snapshot)

    def get_controllers(self) -> List[Dict[str, Any]]:
        with self._file_lock:
            controllers = self.settings.get("controllers", [])
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
            self._normalizer._validate_controller_type(controller)
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
                controller["relays"] = [self._relay_defaults(), self._relay_defaults()]
                changed = True
                relays = controller["relays"]
            normalized_relays = [self._normalizer._normalize_relay(relay) for relay in relays[:2]]
            if controller.get("relays") != normalized_relays:
                controller["relays"] = normalized_relays
                changed = True
            hotkeys = [relay.get("hotkey", "") for relay in normalized_relays if relay.get("hotkey")]
            if len(hotkeys) != len(set(hotkeys)):
                logger.warning(
                    "Контроллер %s содержит дубли hotkey в settings; значения сохранены без скрытой модификации",
                    controller.get("name") or controller.get("id") or "unknown",
                )
        if changed:
            self.save_controllers(controllers)
        return copy.deepcopy(controllers)

    def save_controllers(self, controllers: List[Dict[str, Any]]) -> None:
        with self._file_lock:
            self.settings["controllers"] = copy.deepcopy(controllers)
            settings_snapshot = copy.deepcopy(self.settings)
        self._repo.save(settings_snapshot)

    def get_grid(self) -> str:
        with self._file_lock:
            return self.settings.get("grid", "2x2")

    def save_grid(self, grid: str) -> None:
        with self._file_lock:
            self.settings["grid"] = grid
            settings_snapshot = copy.deepcopy(self.settings)
        self._repo.save(settings_snapshot)

    def get_theme(self) -> str:
        with self._file_lock:
            return self.settings.get("theme", "dark")

    def save_theme(self, theme: str) -> None:
        with self._file_lock:
            self.settings["theme"] = theme
            settings_snapshot = copy.deepcopy(self.settings)
        self._repo.save(settings_snapshot)

    def get_reconnect(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_reconnect_defaults(self.settings, self._reconnect_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._repo.save(settings_snapshot)
            return copy.deepcopy(self.settings.get("reconnect", {}))

    def save_reconnect(self, reconnect_conf: Dict[str, Any]) -> None:
        with self._file_lock:
            self.settings["reconnect"] = reconnect_conf
            settings_snapshot = copy.deepcopy(self.settings)
        self._repo.save(settings_snapshot)

    def save_screenshot_dir(self, path: str) -> None:
        with self._file_lock:
            storage = self.settings.get("storage", {})
            storage["screenshots_dir"] = path
            self.settings["storage"] = storage
            settings_snapshot = copy.deepcopy(self.settings)
        self._repo.save(settings_snapshot)

    def save_logs_dir(self, path: str) -> None:
        with self._file_lock:
            storage = self.settings.get("storage", {})
            storage["logs_dir"] = path
            self.settings["storage"] = storage
            settings_snapshot = copy.deepcopy(self.settings)
        self._repo.save(settings_snapshot)

    def get_screenshot_dir(self) -> str:
        with self._file_lock:
            storage = self.settings.get("storage", {})
            return storage.get("screenshots_dir", "data/screenshots")

    def get_logs_dir(self) -> str:
        with self._file_lock:
            storage = self.settings.get("storage", {})
            return storage.get("logs_dir", "logs")

    def get_storage_settings(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_storage_defaults(self.settings, self._storage_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._repo.save(settings_snapshot)
            storage = copy.deepcopy(self.settings.get("storage", {}))

        env_postgres_dsn = os.getenv("POSTGRES_DSN", "postgresql://anpr:anpr@postgres:5432/anpr").strip()
        storage["postgres_dsn"] = env_postgres_dsn
        return storage

    def save_storage_settings(self, storage_settings: Dict[str, Any]) -> None:
        with self._file_lock:
            current = self.settings.get("storage", {})
            sanitized = copy.deepcopy(storage_settings)
            sanitized.pop("postgres_dsn", None)
            current.update(sanitized)
            self.settings["storage"] = current
            settings_snapshot = copy.deepcopy(self.settings)
        self._repo.save(settings_snapshot)

    def get_time_settings(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_time_defaults(self.settings, self._time_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._repo.save(settings_snapshot)
            return copy.deepcopy(self.settings.get("time", {}))

    def save_time_settings(self, time_settings: Dict[str, Any]) -> None:
        with self._file_lock:
            self.settings["time"] = time_settings
            settings_snapshot = copy.deepcopy(self.settings)
        self._repo.save(settings_snapshot)

    def get_timezone(self) -> str:
        time_settings = self.get_time_settings()
        return str(time_settings.get("timezone") or "UTC")

    def get_time_offset_minutes(self) -> int:
        time_settings = self.get_time_settings()
        try:
            return int(time_settings.get("offset_minutes", 0))
        except (TypeError, ValueError):
            return 0

    def get_plate_settings(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_plate_defaults(self.settings, self._plate_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._repo.save(settings_snapshot)
            return copy.deepcopy(self.settings.get("plates", {}))

    def save_plate_settings(self, plate_settings: Dict[str, Any]) -> None:
        with self._file_lock:
            self.settings["plates"] = plate_settings
            settings_snapshot = copy.deepcopy(self.settings)
        self._repo.save(settings_snapshot)

    def get_logging_config(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_logging_defaults(self.settings, self._logging_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._repo.save(settings_snapshot)
            if self._normalizer._fill_storage_defaults(self.settings, self._storage_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._repo.save(settings_snapshot)
            logging_config = copy.deepcopy(self.settings.get("logging", {}))
            storage = self.settings.get("storage", {})
            logging_config["logs_dir"] = storage.get("logs_dir", "logs")
            return logging_config

    def save_logging_config(self, logging_config: Dict[str, Any]) -> None:
        with self._file_lock:
            current = self.settings.get("logging", {})
            current.update(logging_config)
            current["level"] = normalize_log_level(current.get("level"))
            current["allowed_levels"] = list(self._logging_defaults().get("allowed_levels", []))
            self.settings["logging"] = current
            settings_snapshot = copy.deepcopy(self.settings)
        self._repo.save(settings_snapshot)

    def get_debug_settings(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_debug_defaults(self.settings, self._debug_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._repo.save(settings_snapshot)
            return copy.deepcopy(self.settings.get("debug", {}))

    def save_debug_settings(self, debug_settings: Dict[str, Any]) -> None:
        with self._file_lock:
            self.settings["debug"] = debug_settings
            settings_snapshot = copy.deepcopy(self.settings)
        self._repo.save(settings_snapshot)

    def get_model_settings(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_model_defaults(self.settings, self._model_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._repo.save(settings_snapshot)
            return copy.deepcopy(self.settings.get("models", {}))

    def get_ocr_settings(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_ocr_defaults(self.settings, self._ocr_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._repo.save(settings_snapshot)
            return copy.deepcopy(self.settings.get("ocr", {}))

    def get_detector_settings(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_detector_defaults(self.settings, self._detector_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._repo.save(settings_snapshot)
            return copy.deepcopy(self.settings.get("detector", {}))

    def get_inference_settings(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_inference_defaults(self.settings, self._inference_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._repo.save(settings_snapshot)
            return copy.deepcopy(self.settings.get("inference", {}))

    def refresh(self) -> None:
        raw_settings = self._repo.load()
        self.settings = self._normalize_and_persist_if_changed(raw_settings)

    def update_channel(self, channel_id: int, data: Dict[str, Any]) -> None:
        channels = self.get_channels()
        for idx, channel in enumerate(channels):
            if channel.get("id") == channel_id:
                channels[idx].update(data)
                break
        else:
            channels.append(data)
        self.save_channels(channels)


def plate_size_defaults() -> Dict[str, Dict[str, int]]:
    """Единый источник дефолтов размеров рамки номера."""
    defaults = SettingsManager._plate_size_defaults()
    return {key: value.copy() for key, value in defaults.items()}


def direction_defaults() -> Dict[str, float | int]:
    """Единый источник дефолтов определения направления движения."""
    defaults = SettingsManager._direction_defaults()
    return dict(defaults)
