"""Tests for app/api/routers/data.py — retention policy, export, and backup/restore endpoints.

Uses mocks — no live DB, filesystem, or server required. Restore/backup endpoints are
async, so `_run()` drives them with `asyncio.run()` since this project has no
pytest-asyncio dependency.
"""
from __future__ import annotations

import asyncio
import io
import json
from unittest.mock import MagicMock
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi import HTTPException

from app.api.routers import data as data_router
from app.api.routers.data import (
    MAX_DATABASE_BACKUP_SIZE,
    MAX_SETTINGS_BACKUP_SIZE,
    _PayloadTooLargeError,
    _read_upload_capped,
    backup_database,
    backup_settings,
    export_events_bundle,
    export_events_csv,
    get_data_policy,
    restore_database,
    restore_settings_endpoint,
    run_retention,
)
from app.api.schemas import ExportBundlePayload
from config.settings_service import SettingsService
from tests.test_settings_service import _Clock, _Repo
from app.shared.backup_service import get_restore_lock
from config.settings_service import SettingsService
from database.errors import StorageUnavailableError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def _body(response) -> dict:
    return json.loads(response.body)


class _FakeUploadFile:
    """Minimal stand-in for FastAPI's UploadFile — serves bytes in size-bounded
    chunks, matching the real `await file.read(size)` contract."""

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk = self._data[self._pos:]
        else:
            chunk = self._data[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk


class _SyncThread:
    """Stand-in for threading.Thread that runs its target synchronously and
    immediately. A real background thread would race pytest/monkeypatch
    teardown against `time.sleep(2)`, and could deliver a real SIGTERM to the
    test process — this keeps the scheduled-restart assertion deterministic
    and safe."""

    def __init__(self, target=None, daemon=None, **_kwargs):
        self._target = target

    def start(self) -> None:
        if self._target:
            self._target()


def _valid_db_backup_bytes(tables=("users",)) -> bytes:
    manifest = {"version": 1, "created_at": "2024-01-01T00:00:00", "tables": list(tables)}
    buf = io.BytesIO()
    with ZipFile(buf, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for table in tables:
            zf.writestr(f"{table}.json", json.dumps([]))
    return buf.getvalue()


def _make_container(dsn="postgresql://user:pass@localhost/anpr", channels=None):
    container = MagicMock()
    container._resolve_dsn.return_value = dsn
    container.channel_db.list_channels.return_value = channels or []
    container.storage_503.side_effect = (
        lambda exc: HTTPException(status_code=503, detail=f"PostgreSQL недоступен: {exc}")
    )
    return container


# ---------------------------------------------------------------------------
# _read_upload_capped — the size-cap primitive behind findings #1/#2
# ---------------------------------------------------------------------------

class TestReadUploadCapped:
    def test_reads_data_under_cap(self):
        data = b"x" * 100
        result = _run(_read_upload_capped(_FakeUploadFile(data), max_bytes=1000))
        assert result == data

    def test_reads_data_exactly_at_cap(self):
        data = b"x" * 100
        result = _run(_read_upload_capped(_FakeUploadFile(data), max_bytes=100))
        assert result == data

    def test_rejects_data_one_byte_over_cap(self):
        data = b"x" * 101
        try:
            _run(_read_upload_capped(_FakeUploadFile(data), max_bytes=100))
            assert False, "expected _PayloadTooLargeError"
        except _PayloadTooLargeError:
            pass

    def test_rejects_data_spanning_many_chunks_over_cap(self):
        # Exercise the loop across multiple 1 MiB chunk reads, not just one.
        data = b"y" * (3 * 1024 * 1024)
        try:
            _run(_read_upload_capped(_FakeUploadFile(data), max_bytes=2 * 1024 * 1024))
            assert False, "expected _PayloadTooLargeError"
        except _PayloadTooLargeError:
            pass

    def test_empty_file_reads_empty_bytes(self):
        result = _run(_read_upload_capped(_FakeUploadFile(b""), max_bytes=100))
        assert result == b""


# ---------------------------------------------------------------------------
# GET/PUT /api/data/policy
# ---------------------------------------------------------------------------

class TestDataPolicy:
    def _with_service(self, stored=None):
        container = _make_container()
        container.settings_service = SettingsService(_Repo(stored), clock=_Clock())
        return container

    def test_get_policy_reads_retention_from_app_settings(self):
        container = self._with_service({"retention.events_retention_days": 45})
        result = get_data_policy(container=container, _user={})
        assert result["events_retention_days"] == 45
        assert result["media_retention_days"] == 14

    def test_get_policy_defaults_when_the_table_is_empty(self):
        result = get_data_policy(container=self._with_service(), _user={})
        assert result == {
            "auto_cleanup_enabled": True,
            "cleanup_interval_minutes": 30,
            "events_retention_days": 30,
            "media_retention_days": 14,
            "max_screenshots_mb": 4096,
        }

    def test_put_endpoint_is_gone(self):
        """Task 4.2 / P8: retention has one write path, `PUT /api/settings`."""
        assert not hasattr(data_router, "update_data_policy")
        paths = {(route.path, tuple(sorted(route.methods))) for route in data_router.router.routes}
        assert ("/api/data/policy", ("GET",)) in paths
        assert not [p for p in paths if p[0] == "/api/data/policy" and "PUT" in p[1]]

    def test_router_has_no_direct_settings_writer(self):
        import inspect

        assert "save_storage_settings" not in inspect.getsource(data_router)


# ---------------------------------------------------------------------------
# POST /api/data/retention/run
# ---------------------------------------------------------------------------

class TestRunRetention:
    def test_success_merges_result(self):
        container = _make_container()
        container.settings_service = SettingsService(_Repo({"retention.media_retention_days": 3}), clock=_Clock())
        container.lifecycle.run_retention_cycle.return_value = {"deleted_events": 3}
        result = run_retention(container=container, _user={})
        assert result == {"status": "ok", "deleted_events": 3}
        # The manual run uses the policy currently stored in app_settings.
        assert container.lifecycle.update_policy.call_args.args[0].media_retention_days == 3

    def test_storage_unavailable_returns_error_status(self):
        container = _make_container()
        container.settings_service = SettingsService(_Repo(), clock=_Clock())
        container.lifecycle.run_retention_cycle.side_effect = StorageUnavailableError("down")
        result = run_retention(container=container, _user={})
        assert result["status"] == "error"
        assert "down" in result["detail"]


# ---------------------------------------------------------------------------
# GET /api/data/export/events.csv and POST /api/data/export/bundle
# ---------------------------------------------------------------------------

class TestExportEventsCsv:
    def test_success_returns_csv_response(self):
        container = _make_container()
        container.lifecycle.export_events_csv.return_value = ("events.csv", b"a,b\n1,2\n")
        response = export_events_csv(container=container, _user={})
        assert response.media_type == "text/csv"
        assert response.body == b"a,b\n1,2\n"

    def test_storage_unavailable_raises_503(self):
        container = _make_container()
        container.lifecycle.export_events_csv.side_effect = StorageUnavailableError("down")
        try:
            export_events_csv(container=container, _user={})
            assert False, "expected HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 503


class TestExportEventsBundle:
    def test_success_returns_zip_response(self):
        container = _make_container()
        container.lifecycle.export_events_bundle.return_value = ("bundle.zip", b"PK\x03\x04")
        payload = ExportBundlePayload()
        response = export_events_bundle(payload=payload, container=container, _user={})
        assert response.media_type == "application/zip"

    def test_storage_unavailable_raises_503(self):
        container = _make_container()
        container.lifecycle.export_events_bundle.side_effect = StorageUnavailableError("down")
        payload = ExportBundlePayload()
        try:
            export_events_bundle(payload=payload, container=container, _user={})
            assert False, "expected HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 503


# ---------------------------------------------------------------------------
# GET /api/data/backup/database
# ---------------------------------------------------------------------------

class TestBackupDatabase:
    def test_missing_dsn_returns_500(self):
        container = _make_container(dsn="")
        response = backup_database(container=container, _user={})
        assert response.status_code == 500

    def test_success_returns_zip(self, monkeypatch):
        monkeypatch.setattr(
            data_router, "export_database_backup",
            lambda dsn: ("db_backup.zip", b"PK\x03\x04"),
        )
        container = _make_container()
        response = backup_database(container=container, _user={})
        assert response.media_type == "application/zip"
        assert response.body == b"PK\x03\x04"

    def test_storage_unavailable_raises_503(self, monkeypatch):
        def _raise(dsn):
            raise StorageUnavailableError("down")
        monkeypatch.setattr(data_router, "export_database_backup", _raise)
        container = _make_container()
        try:
            backup_database(container=container, _user={})
            assert False, "expected HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 503

    def test_unexpected_error_returns_500(self, monkeypatch):
        def _raise(dsn):
            raise RuntimeError("boom")
        monkeypatch.setattr(data_router, "export_database_backup", _raise)
        container = _make_container()
        response = backup_database(container=container, _user={})
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/data/backup/database/restore  (findings #1 and #2)
# ---------------------------------------------------------------------------

class TestRestoreDatabase:
    def test_rejects_when_restore_already_running(self):
        lock = get_restore_lock()
        assert lock.acquire("held_by_other_test")
        try:
            container = _make_container()
            file = _FakeUploadFile(_valid_db_backup_bytes())
            result = _run(restore_database(file=file, container=container, _user={}))
            assert result.status_code == 409
        finally:
            lock.release()

    def test_rejects_oversized_upload_with_413(self, monkeypatch):
        # Finding #2: an upload larger than the cap must be rejected before
        # it's ever handed to validate_database_backup / restore_database_backup.
        monkeypatch.setattr(data_router, "MAX_DATABASE_BACKUP_SIZE", 10)
        container = _make_container()
        file = _FakeUploadFile(b"x" * 11)
        result = _run(restore_database(file=file, container=container, _user={}))
        assert result.status_code == 413

    def test_rejects_invalid_backup_archive(self):
        container = _make_container()
        file = _FakeUploadFile(b"not a zip file at all")
        result = _run(restore_database(file=file, container=container, _user={}))
        assert result.status_code == 422

    def test_missing_dsn_returns_500(self):
        container = _make_container(dsn="")
        file = _FakeUploadFile(_valid_db_backup_bytes())
        result = _run(restore_database(file=file, container=container, _user={}))
        assert result.status_code == 500

    def test_restore_failure_returns_500_and_still_releases_lock(self, monkeypatch):
        def _raise(dsn, data):
            raise RuntimeError("db exploded")
        monkeypatch.setattr(data_router, "restore_database_backup", _raise)
        container = _make_container()
        file = _FakeUploadFile(_valid_db_backup_bytes())
        result = _run(restore_database(file=file, container=container, _user={}))
        assert result.status_code == 500
        # Lock must be released even on failure, or every later restore 409s forever.
        assert get_restore_lock().acquire("post_failure_probe")
        get_restore_lock().release()

    def test_success_stops_processor_before_restoring(self, monkeypatch):
        monkeypatch.setattr(data_router.threading, "Thread", _SyncThread)
        monkeypatch.setattr(data_router.time, "sleep", lambda *_a, **_k: None)
        monkeypatch.setattr(data_router.signal, "raise_signal", lambda sig: None)
        monkeypatch.setattr(
            data_router, "restore_database_backup",
            lambda dsn, data: {"restored_tables": {"users": 0}},
        )
        container = _make_container()
        file = _FakeUploadFile(_valid_db_backup_bytes())

        _run(restore_database(file=file, container=container, _user={}))

        container.shutdown.assert_called_once()

    def test_success_reinitializes_storage_and_restarts_channels(self, monkeypatch):
        monkeypatch.setattr(data_router.threading, "Thread", _SyncThread)
        monkeypatch.setattr(data_router.time, "sleep", lambda *_a, **_k: None)
        monkeypatch.setattr(data_router.signal, "raise_signal", lambda sig: None)
        monkeypatch.setattr(
            data_router, "restore_database_backup",
            lambda dsn, data: {"restored_tables": {"users": 2}},
        )
        container = _make_container(channels=[{"id": 1, "enabled": True}, {"id": 2, "enabled": False}])
        file = _FakeUploadFile(_valid_db_backup_bytes())

        result = _run(restore_database(file=file, container=container, _user={}))

        assert result.status_code == 200
        body = _body(result)
        assert body["status"] == "ok"
        assert body["restored_tables"] == {"users": 2}
        container.refresh_storage_clients.assert_called_once()
        # Only the enabled channel should be started.
        container.processor.ensure_channel.assert_any_call({"id": 1, "enabled": True})
        container.processor.ensure_channel.assert_any_call({"id": 2, "enabled": False})
        container.processor.start.assert_called_once_with(1)

    def test_success_requests_graceful_restart_via_sigterm_not_exit(self, monkeypatch):
        """Regression test for finding #1: the old code called os._exit(0),
        which skips uvicorn's graceful shutdown and the FastAPI lifespan's
        cleanup. It must request a SIGTERM instead."""
        monkeypatch.setattr(data_router.threading, "Thread", _SyncThread)
        monkeypatch.setattr(data_router.time, "sleep", lambda *_a, **_k: None)
        received_signals = []
        monkeypatch.setattr(data_router.signal, "raise_signal", received_signals.append)
        monkeypatch.setattr(
            data_router, "restore_database_backup",
            lambda dsn, data: {"restored_tables": {}},
        )
        container = _make_container()
        file = _FakeUploadFile(_valid_db_backup_bytes())

        _run(restore_database(file=file, container=container, _user={}))

        assert received_signals == [data_router.signal.SIGTERM]


# ---------------------------------------------------------------------------
# GET /api/data/backup/settings
# ---------------------------------------------------------------------------

class TestBackupSettings:
    def _with_service(self, stored=None):
        container = _make_container()
        container.settings_service = SettingsService(_Repo(stored), clock=_Clock())
        return container

    def test_returns_a_json_dump_of_the_explicit_overrides(self):
        container = self._with_service({"retention.events_retention_days": 90})
        response = backup_settings(container=container, _user={})
        assert response.media_type == "application/json"
        document = json.loads(response.body)
        assert document["format"] == "anpr-app-settings" and document["version"] == 1
        assert document["settings"] == {"retention.events_retention_days": 90}
        assert 'filename="settings_' in response.headers["content-disposition"]
        assert response.headers["content-disposition"].endswith('.json"')

    def test_database_outage_is_503(self):
        container = self._with_service()
        container.settings_service._repository.down = True  # the database was never readable
        with pytest.raises(HTTPException) as exc:
            backup_settings(container=container, _user={})
        assert exc.value.status_code == 503


# ---------------------------------------------------------------------------
# POST /api/data/backup/settings/restore  (finding #2)
# ---------------------------------------------------------------------------

def _dump(settings, **overrides):
    document = {"format": "anpr-app-settings", "version": 1, "exported_at": "2026-09-21T00:00:00+00:00", "settings": settings}
    document.update(overrides)
    return json.dumps(document).encode("utf-8")


class TestRestoreSettings:
    def _with_service(self, stored=None):
        container = _make_container()
        container.settings_service = SettingsService(_Repo(stored), clock=_Clock())
        container.get_reconnect_settings.return_value = {}
        return container

    def test_rejects_when_restore_already_running(self):
        lock = get_restore_lock()
        assert lock.acquire("held_by_other_test")
        try:
            container = self._with_service()
            file = _FakeUploadFile(_dump({}))
            result = _run(restore_settings_endpoint(file=file, container=container, _user={}))
            assert result.status_code == 409
        finally:
            lock.release()

    def test_rejects_oversized_upload_with_413(self, monkeypatch):
        monkeypatch.setattr(data_router, "MAX_SETTINGS_BACKUP_SIZE", 10)
        container = self._with_service()
        file = _FakeUploadFile(b"x" * 11)
        result = _run(restore_settings_endpoint(file=file, container=container, _user={}))
        assert result.status_code == 413

    def test_rejects_malformed_json(self):
        container = self._with_service()
        result = _run(restore_settings_endpoint(file=_FakeUploadFile(b"{not json"), container=container, _user={}))
        assert result.status_code == 422

    def test_rejects_the_old_yaml_format(self):
        container = self._with_service()
        result = _run(restore_settings_endpoint(file=_FakeUploadFile(b"auto_cleanup_enabled: true\nreconnect:\n  periodic: {}\n"), container=container, _user={}))
        assert result.status_code == 422
        assert container.settings_service._repository.writes == []

    def test_rejects_a_dump_with_unknown_keys_and_writes_nothing(self):
        container = self._with_service({"logging.level": "INFO"})
        result = _run(restore_settings_endpoint(file=_FakeUploadFile(_dump({"logging.level": "DEBUG", "nope.key": 1})), container=container, _user={}))
        assert result.status_code == 422 and "nope.key" in _body(result)["detail"]
        assert container.settings_service._repository.replaced == []

    def test_success_applies_the_dump_and_restarts_only_when_needed(self):
        container = self._with_service()
        file = _FakeUploadFile(_dump({"logging.level": "WARNING"}))
        result = _run(restore_settings_endpoint(file=file, container=container, _user={"id": 4}))
        assert result.status_code == 200
        body = _body(result)
        assert body["status"] == "ok" and body["restored_keys"] == 1 and body["requires_restart"] == []
        assert container.settings_service._repository.replaced == [({"logging.level": "WARNING"}, 4)]
        container.logging_applier.apply.assert_called_once()
        container.processor.update_reconnect_settings.assert_called_once()
        container.restart_processor_for_settings.assert_not_called()

    def test_a_restart_key_triggers_exactly_one_processor_restart(self):
        container = self._with_service()
        result = _run(restore_settings_endpoint(file=_FakeUploadFile(_dump({"plates.enabled_countries": ["RU"]})), container=container, _user={}))
        assert _body(result)["requires_restart"] == ["plates.enabled_countries"]
        container.restart_processor_for_settings.assert_called_once()

    def test_the_file_system_is_not_touched(self, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("settings restore must not use the file system")

        monkeypatch.setattr("builtins.open", boom)
        container = self._with_service()
        result = _run(restore_settings_endpoint(file=_FakeUploadFile(_dump({"logging.level": "ERROR"})), container=container, _user={}))
        assert result.status_code == 200

    def test_lock_released_when_restore_raises(self, monkeypatch):
        def _raise(service, data, updated_by=None):
            raise ValueError("bad settings")
        monkeypatch.setattr(data_router, "restore_settings", _raise)
        container = self._with_service()
        result = _run(restore_settings_endpoint(file=_FakeUploadFile(_dump({})), container=container, _user={}))
        assert result.status_code == 422
        assert get_restore_lock().acquire("post_failure_probe")
        get_restore_lock().release()
