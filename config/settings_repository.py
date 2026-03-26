import copy
import os
import tempfile
import threading
from typing import Any, Dict

import yaml


class SettingsRepository:
    _file_lock = threading.RLock()

    def __init__(self, manager: Any, path: str | None = None) -> None:
        self._manager = manager
        self.path = path or os.getenv("SETTINGS_PATH", "config/settings.yaml")
        self.settings = self._load()

    def load(self) -> Dict[str, Any]:
        self.settings = self._load()
        return self.settings

    def save(self, data: Dict[str, Any]) -> None:
        self._save(data)
        self.settings = data

    def _load(self) -> Dict[str, Any]:
        with self._file_lock:
            if not os.path.exists(self.path):
                defaults = self._manager._default()
                self._write_to_disk(defaults)
                return defaults
            with open(self.path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data is None:
                data = {}
            if not isinstance(data, dict):
                raise ValueError(f"Некорректный формат {self.path}: ожидается YAML-объект")
        return data

    def _save(self, data: Dict[str, Any]) -> None:
        with self._file_lock:
            snapshot = copy.deepcopy(data)
        self._write_to_disk(snapshot)

    def _write_to_disk(self, data: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with self._file_lock:
            fd, tmp_path = tempfile.mkstemp(
                dir=os.path.dirname(self.path) or ".", prefix=".settings_", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, self.path)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

    def refresh(self) -> None:
        with self._file_lock:
            self.settings = self._load()
