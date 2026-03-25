from __future__ import annotations

import json

import pytest

from app.shared.backup_restore import BackupRestoreService, parse_database_backup_payload


def _valid_db_backup_payload() -> bytes:
    payload = {
        "backup_kind": "anpr_postgres_backup",
        "format_version": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "backend": "postgresql",
        "tables": {
            "events": [
                {
                    "id": 1,
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "channel_id": 1,
                    "channel": "Канал 1",
                    "plate": "A123AA77",
                    "plate_display": "A123AA77",
                    "country": "RU",
                    "confidence": 0.95,
                    "source": "rtsp://camera",
                    "frame_path": None,
                    "plate_path": None,
                    "direction": "front",
                }
            ],
            "plate_lists": [{"id": 3, "name": "Белый", "type": "white"}],
            "plate_list_entries": [
                {
                    "id": 11,
                    "list_id": 3,
                    "plate": "A123AA77",
                    "plate_normalized": "A123AA77",
                    "comment": "",
                }
            ],
        },
    }
    return json.dumps(payload).encode("utf-8")


class _RepoStub:
    def __init__(self) -> None:
        self.path = "config/settings.yaml"
        self.saved = None

    def save(self, data):
        self.saved = data


class _NormalizerStub:
    def normalize_with_meta(self, data):
        normalized = dict(data)
        normalized["normalized"] = True
        return normalized, True


class _SettingsStub:
    def __init__(self) -> None:
        self._repo = _RepoStub()
        self._normalizer = _NormalizerStub()
        self.reloaded = False

    def reload(self) -> None:
        self.reloaded = True


class TestDbBackupValidation:
    def test_accepts_valid_backup_payload(self):
        payload = parse_database_backup_payload(_valid_db_backup_payload())
        assert payload["backup_kind"] == "anpr_postgres_backup"

    def test_rejects_wrong_backup_kind(self):
        invalid = json.loads(_valid_db_backup_payload().decode("utf-8"))
        invalid["backup_kind"] = "other"
        with pytest.raises(ValueError, match="Неверный тип бэкапа"):
            parse_database_backup_payload(json.dumps(invalid).encode("utf-8"))

    def test_rejects_missing_required_event_field(self):
        invalid = json.loads(_valid_db_backup_payload().decode("utf-8"))
        invalid["tables"]["events"][0].pop("plate")
        with pytest.raises(ValueError, match="plate"):
            parse_database_backup_payload(json.dumps(invalid).encode("utf-8"))


class TestSettingsRestoreValidation:
    def test_restore_settings_yaml_saves_normalized_data(self):
        settings = _SettingsStub()
        service = BackupRestoreService(settings=settings, postgres_dsn="postgresql://user:pass@localhost/db")

        service.restore_settings_yaml(b"theme: dark\nchannels: []\n")

        assert settings._repo.saved["theme"] == "dark"
        assert settings._repo.saved["normalized"] is True
        assert settings.reloaded is True

    def test_restore_settings_yaml_rejects_non_mapping_yaml(self):
        settings = _SettingsStub()
        service = BackupRestoreService(settings=settings, postgres_dsn="postgresql://user:pass@localhost/db")

        with pytest.raises(ValueError, match="YAML-объект"):
            service.restore_settings_yaml(b"- a\n- b\n")
