"""Settings backup/restore is a JSON dump of app_settings, not a file copy
(roadmap task 9.1)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.shared import backup_service
from app.shared.backup_service import (
    SETTINGS_DUMP_FORMAT,
    export_settings,
    restore_settings,
    validate_settings_dump,
)
from config.registry import SettingValidationError
from config.settings_service import SettingsService
from database.errors import StorageUnavailableError
from database.settings_repository import AppSettingsRepository
from tests.test_settings_service import _Clock, _Repo
from tests.test_user_repository import _mock_conn


def _service(stored=None):
    repo = _Repo(stored)
    return SettingsService(repo, clock=_Clock()), repo


def _dump(service) -> bytes:
    return export_settings(service)[1]


class TestExport:
    def test_dump_carries_only_explicit_overrides_not_defaults(self):
        service, _ = _service({"logging.level": "DEBUG", "plates.enabled_countries": ["RU"]})
        document = json.loads(_dump(service))
        assert document["settings"] == {"logging.level": "DEBUG", "plates.enabled_countries": ["RU"]}
        assert document["format"] == SETTINGS_DUMP_FORMAT and document["version"] == 1

    def test_an_untouched_instance_exports_an_empty_settings_object(self):
        service, _ = _service()
        assert json.loads(_dump(service))["settings"] == {}

    def test_the_filename_says_json(self):
        assert export_settings(_service()[0])[0].endswith(".json")

    def test_a_dump_is_never_built_from_defaults_when_the_database_was_unreadable(self):
        service, repo = _service({"logging.level": "DEBUG"})
        repo.down = True
        with pytest.raises(StorageUnavailableError):
            export_settings(service)

    def test_invalid_rows_in_the_table_are_not_exported(self):
        service, _ = _service({"logging.level": "LOUD", "retention.events_retention_days": 7})
        assert json.loads(_dump(service))["settings"] == {"retention.events_retention_days": 7}


class TestValidation:
    def _doc(self, settings=None, **extra):
        return json.dumps({"format": SETTINGS_DUMP_FORMAT, "version": 1, "settings": settings or {}, **extra}).encode()

    def test_a_valid_dump_returns_the_settings(self):
        assert validate_settings_dump(self._doc({"logging.level": "INFO"})) == {"logging.level": "INFO"}

    @pytest.mark.parametrize("raw", [b"", b"{oops", b"[]", b"null", "не json".encode("utf-16")])
    def test_garbage_is_rejected(self, raw):
        with pytest.raises(ValueError):
            validate_settings_dump(raw)

    def test_yaml_is_not_accepted(self):
        with pytest.raises(ValueError):
            validate_settings_dump(b"reconnect:\n  periodic:\n    enabled: true\n")

    def test_foreign_format_and_version_are_rejected(self):
        with pytest.raises(ValueError):
            validate_settings_dump(json.dumps({"format": "other", "version": 1, "settings": {}}).encode())
        with pytest.raises(ValueError):
            validate_settings_dump(self._doc(version=2))

    def test_unknown_keys_are_rejected_and_named(self):
        with pytest.raises(ValueError) as exc:
            validate_settings_dump(self._doc({"logging.level": "INFO", "made.up": 1, "theme": "dark"}))
        assert "made.up" in str(exc.value) and "theme" in str(exc.value)

    def test_class_u_class_d_and_reserved_keys_are_not_settings_backup_material(self):
        for key in ("sidebar_locked", "JWT_SECRET_KEY", "interface.default_locale"):
            with pytest.raises(ValueError):
                validate_settings_dump(self._doc({key: True}))

    def test_values_are_validated_by_the_registry(self):
        with pytest.raises(ValueError):
            validate_settings_dump(self._doc({"logging.level": "LOUD"}))
        with pytest.raises(ValueError):
            validate_settings_dump(self._doc({"auth.token_ttl_minutes": 1}))


class TestRestoreCycle:
    def test_export_change_restore_returns_to_the_exported_state(self):
        service, repo = _service({"logging.level": "DEBUG", "retention.events_retention_days": 90})
        dump = _dump(service)

        service.update({"logging.level": "ERROR", "auth.token_ttl_minutes": 60})   # changes after the export
        assert service.get("logging.level") == "ERROR"

        outcome = restore_settings(service, dump, updated_by=3)
        assert outcome["restored_keys"] == 2
        assert repo.stored == {"logging.level": "DEBUG", "retention.events_retention_days": 90}
        service._checked_at = None
        assert service.get("logging.level") == "DEBUG"
        assert service.get("auth.token_ttl_minutes") == 480, "a key set after the export reverts to its default"
        assert repo.replaced[-1][1] == 3

    def test_restore_is_one_atomic_replace(self):
        service, repo = _service()
        restore_settings(service, _dump(_service({"logging.level": "INFO"})[0]))
        assert len(repo.replaced) == 1 and repo.writes == []

    def test_restore_reports_restart_keys_only_when_they_change(self):
        service, _ = _service({"plates.enabled_countries": ["RU"]})
        same = restore_settings(service, _dump(service))
        assert same["requires_restart"] == []
        other = _dump(_service({"plates.enabled_countries": ["BY"]})[0])
        assert restore_settings(service, other)["requires_restart"] == ["plates.enabled_countries"]

    def test_a_dump_with_an_invalid_value_writes_nothing(self):
        service, repo = _service({"logging.level": "INFO"})
        bad = json.dumps({"format": SETTINGS_DUMP_FORMAT, "version": 1, "settings": {"logging.level": "LOUD"}}).encode()
        with pytest.raises(ValueError):
            restore_settings(service, bad)
        assert repo.replaced == [] and repo.stored == {"logging.level": "INFO"}

    def test_service_replace_validates_everything_before_writing(self):
        service, repo = _service()
        with pytest.raises(SettingValidationError):
            service.replace({"logging.level": "INFO", "logging.retention_days": 0})
        assert repo.replaced == []


class TestBoundaryWithTheDatabaseBackup:
    def test_app_settings_is_not_in_the_database_backup(self):
        assert "app_settings" not in backup_service._BACKUP_TABLES
        assert "app_settings_revision" not in backup_service._BACKUP_TABLES

    def test_restoring_the_database_never_touches_the_instance_configuration(self):
        source = open(backup_service.__file__, encoding="utf-8").read()
        restore_body = source[source.index("def restore_database_backup"):source.index("# ── Settings backup")]
        assert "app_settings" not in restore_body

    def test_the_settings_path_of_the_module_does_not_use_the_file_system(self):
        source = open(backup_service.__file__, encoding="utf-8").read()
        settings_part = source[source.index("# ── Settings backup"):]
        for banned in ("open(", "os.path", "Path(", "yaml"):
            assert banned not in settings_part, banned

    def test_yaml_helpers_are_gone(self):
        assert not hasattr(backup_service, "validate_settings_yaml")
        assert "import yaml" not in open(backup_service.__file__, encoding="utf-8").read()


class TestRepositoryReplaceAll:
    def _repo(self, existing):
        repo = object.__new__(AppSettingsRepository)
        repo._dsn = "postgresql://mock"
        repo._initialized = True
        conn, cursor = _mock_conn(fetchall=[(k, v) for k, v in existing.items()])
        cursor.fetchone.return_value = (7,)
        repo._connect = lambda: conn
        return repo, conn, cursor

    def _statements(self, cursor):
        return [(c.args[0], c.args[1] if len(c.args) > 1 else None) for c in cursor.execute.call_args_list]

    def test_it_deletes_stale_rows_upserts_the_rest_and_bumps_the_revision_once(self):
        repo, conn, cursor = self._repo({"a.old": 1, "logging.level": "INFO"})
        revision = repo.replace_all({"logging.level": "DEBUG", "logging.retention_days": 5}, updated_by=2)
        sql = [s for s, _ in self._statements(cursor)]
        assert sum("DELETE FROM app_settings" in s for s in sql) == 1
        assert sum("INSERT INTO app_settings" in s for s in sql) == 2
        assert sum("UPDATE app_settings_revision" in s for s in sql) == 1
        assert revision == 7
        conn.commit.assert_called_once()

    def test_identical_rows_are_left_alone_and_no_change_means_no_revision_bump(self):
        repo, conn, cursor = self._repo({"logging.level": "INFO"})
        assert repo.replace_all({"logging.level": "INFO"}) is None
        assert not any("INSERT" in s or "UPDATE" in s or "DELETE" in s for s, _ in self._statements(cursor)[1:])

    def test_database_errors_surface_as_storage_unavailable(self):
        repo, conn, cursor = self._repo({})
        cursor.execute.side_effect = RuntimeError("boom")
        with pytest.raises(StorageUnavailableError):
            repo.replace_all({"logging.level": "INFO"})
