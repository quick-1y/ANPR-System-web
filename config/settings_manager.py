#!/usr/bin/env python3
#/config/settings_manager.py
import copy
import os
from typing import Any, Dict

from config.settings_normalizer import SettingsNormalizer
from config.settings_repository import SettingsRepository
from config.settings_schema import (
    build_default_settings,
    debug_defaults,
    detector_defaults,
    logging_defaults,
    model_defaults,
    normalize_log_level,
    ocr_defaults,
    plate_defaults,
    reconnect_defaults,
    storage_defaults,
    time_defaults,
)


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


    def get_reconnect(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_reconnect_defaults(self.settings, reconnect_defaults()):
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
            if self._normalizer._fill_storage_defaults(self.settings, storage_defaults()):
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
            if self._normalizer._fill_time_defaults(self.settings, time_defaults()):
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


    def get_plate_settings(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_plate_defaults(self.settings, plate_defaults()):
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
            if self._normalizer._fill_logging_defaults(self.settings, logging_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._repo.save(settings_snapshot)
            if self._normalizer._fill_storage_defaults(self.settings, storage_defaults()):
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
            current.pop("allowed_levels", None)
            self.settings["logging"] = current
            settings_snapshot = copy.deepcopy(self.settings)
        self._repo.save(settings_snapshot)

    def get_debug_settings(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_debug_defaults(self.settings, debug_defaults()):
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
            if self._normalizer._fill_model_defaults(self.settings, model_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._repo.save(settings_snapshot)
            return copy.deepcopy(self.settings.get("models", {}))

    def get_ocr_settings(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_ocr_defaults(self.settings, ocr_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._repo.save(settings_snapshot)
            return copy.deepcopy(self.settings.get("ocr", {}))

    def get_detector_settings(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_detector_defaults(self.settings, detector_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._repo.save(settings_snapshot)
            return copy.deepcopy(self.settings.get("detector", {}))

    def refresh(self) -> None:
        raw_settings = self._repo.load()
        self.settings = self._normalize_and_persist_if_changed(raw_settings)


