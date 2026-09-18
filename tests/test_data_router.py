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
    update_data_policy,
)
from app.api.schemas import ExportBundlePayload, RetentionPolicyPayload
from app.shared.backup_service import get_restore_lock
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
    container.settings.get_storage_settings.return_value = {"postgres_dsn": dsn}
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
    def test_get_policy_returns_storage_dict(self):
        container = _make_container()
        container.lifecycle.policy.to_storage.return_value = {"events_retention_days": 30}
        result = get_data_policy(container=container, _user={})
        assert result == {"events_retention_days": 30}

    def test_update_policy_saves_and_returns_policy(self):
        container = _make_container()
        payload = RetentionPolicyPayload(events_retention_days=45)
        result = update_data_policy(payload=payload, container=container, _user={})
        assert result["status"] == "updated"
        assert result["policy"]["events_retention_days"] == 45
        container.lifecycle.update_policy.assert_called_once()
        container.settings.save_storage_settings.assert_called_once()


# ---------------------------------------------------------------------------
# POST /api/data/retention/run
# ---------------------------------------------------------------------------

class TestRunRetention:
    def test_success_merges_result(self):
        container = _make_container()
        container.lifecycle.run_retention_cycle.return_value = {"deleted_events": 3}
        result = run_retention(container=container, _user={})
        assert result == {"status": "ok", "deleted_events": 3}

    def test_storage_unavailable_returns_error_status(self):
        container = _make_container()
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
    def test_missing_file_returns_404(self):
        container = _make_container()
        container.settings._repo.path = "/nonexistent/path/settings.yaml"
        response = backup_settings(container=container, _user={})
        assert response.status_code == 404

    def test_success_returns_yaml(self, monkeypatch):
        monkeypatch.setattr(
            data_router, "export_settings",
            lambda path: ("settings.yaml", b"auto_cleanup_enabled: true\n"),
        )
        container = _make_container()
        response = backup_settings(container=container, _user={})
        assert response.media_type == "application/x-yaml"
        assert response.body == b"auto_cleanup_enabled: true\n"


# ---------------------------------------------------------------------------
# POST /api/data/backup/settings/restore  (finding #2)
# ---------------------------------------------------------------------------

class TestRestoreSettings:
    def test_rejects_when_restore_already_running(self):
        lock = get_restore_lock()
        assert lock.acquire("held_by_other_test")
        try:
            container = _make_container()
            file = _FakeUploadFile(b"auto_cleanup_enabled: true\n")
            result = _run(restore_settings_endpoint(file=file, container=container, _user={}))
            assert result.status_code == 409
        finally:
            lock.release()

    def test_rejects_oversized_upload_with_413(self, monkeypatch):
        monkeypatch.setattr(data_router, "MAX_SETTINGS_BACKUP_SIZE", 10)
        container = _make_container()
        file = _FakeUploadFile(b"x" * 11)
        result = _run(restore_settings_endpoint(file=file, container=container, _user={}))
        assert result.status_code == 413

    def test_rejects_invalid_yaml(self):
        container = _make_container()
        file = _FakeUploadFile(b"not: [valid: yaml: at: all")
        result = _run(restore_settings_endpoint(file=file, container=container, _user={}))
        assert result.status_code == 422

    def test_rejects_non_dict_yaml(self):
        container = _make_container()
        file = _FakeUploadFile(b"- just\n- a\n- list\n")
        result = _run(restore_settings_endpoint(file=file, container=container, _user={}))
        assert result.status_code == 422

    def test_success_normalizes_reloads_and_restarts(self):
        container = _make_container()
        file = _FakeUploadFile(b"{}\n")  # empty dict — normalizer fills in every default section

        result = _run(restore_settings_endpoint(file=file, container=container, _user={}))

        assert result.status_code == 200
        assert _body(result)["status"] == "ok"
        container.settings._repo.save.assert_called_once()
        container.settings.refresh.assert_called_once()
        container.refresh_storage_clients.assert_called_once()
        container.restart_processor_for_settings.assert_called_once()

    def test_lock_released_when_normalization_raises(self, monkeypatch):
        # Distinct from the validate_settings_yaml checks above: this fails
        # one step later, inside restore_settings() itself.
        def _raise(repo, normalizer_class, data):
            raise ValueError("bad settings")
        monkeypatch.setattr(data_router, "restore_settings", _raise)
        container = _make_container()
        file = _FakeUploadFile(b"{}\n")

        result = _run(restore_settings_endpoint(file=file, container=container, _user={}))

        assert result.status_code == 422
        assert get_restore_lock().acquire("post_failure_probe")
        get_restore_lock().release()
