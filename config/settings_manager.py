#!/usr/bin/env python3
#/config/settings_manager.py
import copy
import os
from typing import Any, Dict

from config.settings_normalizer import SettingsNormalizer
from config.settings_repository import SettingsRepository
from database.app_settings_repository import AppSettingsDatabase
from database.errors import StorageUnavailableError
from config.settings_schema import (
    build_default_settings,
    debug_defaults,
    detector_defaults,
    inference_defaults,
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
        self._db_repo = self._build_db_repo()
        self.settings = self._load_initial_settings()

    def _build_db_repo(self) -> AppSettingsDatabase | None:
        dsn = os.getenv("POSTGRES_DSN", "").strip()
        if not dsn:
            return None
        try:
            return AppSettingsDatabase(dsn)
        except Exception:
            return None

    def _load_initial_settings(self) -> Dict[str, Any]:
        file_settings = self._repo.settings
        if not self._db_repo:
            return self._normalize_and_persist_if_changed(file_settings)
        try:
            db_payload = self._db_repo.load()
            if db_payload is None:
                normalized = self._normalize_and_persist_if_changed(file_settings)
                self._db_repo.save(normalized)
                return normalized
            return self._normalize_and_persist_if_changed(db_payload)
        except StorageUnavailableError:
            return self._normalize_and_persist_if_changed(file_settings)

    def _normalize_and_persist_if_changed(self, raw_settings: Dict[str, Any]) -> Dict[str, Any]:
        normalized, changed = self._normalizer.normalize_with_meta(raw_settings)
        if changed:
            self._persist(normalized)
        return normalized

    def _persist(self, data: Dict[str, Any]) -> None:
        self._repo.save(data)
        if not self._db_repo:
            return
        try:
            self._db_repo.save(data)
        except StorageUnavailableError:
            pass

    def _default(self) -> Dict[str, Any]:
        return build_default_settings()

    def get_grid(self) -> str:
        with self._file_lock:
            return self.settings.get("grid", "2x2")

    def save_grid(self, grid: str) -> None:
        with self._file_lock:
            self.settings["grid"] = grid
            settings_snapshot = copy.deepcopy(self.settings)
        self._persist(settings_snapshot)

    def get_theme(self) -> str:
        with self._file_lock:
            return self.settings.get("theme", "light")

    def save_theme(self, theme: str) -> None:
        with self._file_lock:
            self.settings["theme"] = theme
            settings_snapshot = copy.deepcopy(self.settings)
        self._persist(settings_snapshot)

    def get_reconnect(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_reconnect_defaults(self.settings, reconnect_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._persist(settings_snapshot)
            return copy.deepcopy(self.settings.get("reconnect", {}))

    def save_reconnect(self, reconnect_conf: Dict[str, Any]) -> None:
        with self._file_lock:
            self.settings["reconnect"] = reconnect_conf
            settings_snapshot = copy.deepcopy(self.settings)
        self._persist(settings_snapshot)

    def save_screenshot_dir(self, path: str) -> None:
        with self._file_lock:
            storage = self.settings.get("storage", {})
            storage["screenshots_dir"] = path
            self.settings["storage"] = storage
            settings_snapshot = copy.deepcopy(self.settings)
        self._persist(settings_snapshot)

    def save_logs_dir(self, path: str) -> None:
        with self._file_lock:
            storage = self.settings.get("storage", {})
            storage["logs_dir"] = path
            self.settings["storage"] = storage
            settings_snapshot = copy.deepcopy(self.settings)
        self._persist(settings_snapshot)

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
                self._persist(settings_snapshot)
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
        self._persist(settings_snapshot)

    def get_time_settings(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_time_defaults(self.settings, time_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._persist(settings_snapshot)
            return copy.deepcopy(self.settings.get("time", {}))

    def save_time_settings(self, time_settings: Dict[str, Any]) -> None:
        with self._file_lock:
            self.settings["time"] = time_settings
            settings_snapshot = copy.deepcopy(self.settings)
        self._persist(settings_snapshot)

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
            if self._normalizer._fill_plate_defaults(self.settings, plate_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._persist(settings_snapshot)
            return copy.deepcopy(self.settings.get("plates", {}))

    def save_plate_settings(self, plate_settings: Dict[str, Any]) -> None:
        with self._file_lock:
            self.settings["plates"] = plate_settings
            settings_snapshot = copy.deepcopy(self.settings)
        self._persist(settings_snapshot)

    def get_logging_config(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_logging_defaults(self.settings, logging_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._persist(settings_snapshot)
            if self._normalizer._fill_storage_defaults(self.settings, storage_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._persist(settings_snapshot)
            logging_config = copy.deepcopy(self.settings.get("logging", {}))
            storage = self.settings.get("storage", {})
            logging_config["logs_dir"] = storage.get("logs_dir", "logs")
            return logging_config

    def save_logging_config(self, logging_config: Dict[str, Any]) -> None:
        with self._file_lock:
            current = self.settings.get("logging", {})
            current.update(logging_config)
            current["level"] = normalize_log_level(current.get("level"))
            current["allowed_levels"] = list(logging_defaults().get("allowed_levels", []))
            self.settings["logging"] = current
            settings_snapshot = copy.deepcopy(self.settings)
        self._persist(settings_snapshot)

    def get_debug_settings(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_debug_defaults(self.settings, debug_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._persist(settings_snapshot)
            return copy.deepcopy(self.settings.get("debug", {}))

    def save_debug_settings(self, debug_settings: Dict[str, Any]) -> None:
        with self._file_lock:
            self.settings["debug"] = debug_settings
            settings_snapshot = copy.deepcopy(self.settings)
        self._persist(settings_snapshot)

    def get_model_settings(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_model_defaults(self.settings, model_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._persist(settings_snapshot)
            return copy.deepcopy(self.settings.get("models", {}))

    def get_ocr_settings(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_ocr_defaults(self.settings, ocr_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._persist(settings_snapshot)
            return copy.deepcopy(self.settings.get("ocr", {}))

    def get_detector_settings(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_detector_defaults(self.settings, detector_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._persist(settings_snapshot)
            return copy.deepcopy(self.settings.get("detector", {}))

    def get_inference_settings(self) -> Dict[str, Any]:
        with self._file_lock:
            if self._normalizer._fill_inference_defaults(self.settings, inference_defaults()):
                settings_snapshot = copy.deepcopy(self.settings)
                self._persist(settings_snapshot)
            return copy.deepcopy(self.settings.get("inference", {}))

    def refresh(self) -> None:
        raw_settings = self._repo.load()
        self.settings = self._normalize_and_persist_if_changed(raw_settings)
