"""Нормализация и валидация системных настроек."""

#!/usr/bin/env python3

from __future__ import annotations

import copy
from typing import Any, Dict

from common.logging import get_logger
from config.settings_schema import (
    debug_defaults,
    logging_defaults,
    model_defaults,
    normalize_log_level,
    plate_defaults,
    reconnect_defaults,
    storage_defaults,
    time_defaults,
)

logger = get_logger(__name__)


class SettingsNormalizer:
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

        if "offset_minutes" in time_section:
            time_section.pop("offset_minutes", None)
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

        if "allowed_levels" in logging_section:
            logging_section.pop("allowed_levels", None)
            changed = True

        data["logging"] = logging_section
        return changed

    def normalize_with_meta(self, data: dict) -> tuple[dict, bool]:
        normalized = copy.deepcopy(data)
        changed = False

        for obsolete_key in ("grid", "theme", "sidebar_locked", "tracking", "inference", "ocr", "detector"):
            if obsolete_key in normalized:
                normalized.pop(obsolete_key, None)
                changed = True

        if self._fill_reconnect_defaults(normalized, reconnect_defaults()):
            changed = True
        if self._fill_model_defaults(normalized, model_defaults()):
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

        return normalized, changed

    def normalize(self, data: dict) -> dict:
        normalized, _ = self.normalize_with_meta(data)
        return normalized
