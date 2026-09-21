"""Reconnect settings live in app_settings (roadmap task 4.1).

The API reads and writes them through SettingsService; the YAML layer no
longer knows about them; a saved change reaches the running processor
without a restart.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.container import AppContainer
from app.api.routers import settings as settings_router
from app.api.schemas import GlobalSettingsPayload
from config.settings_service import SettingsService
from tests.test_settings_service import _Clock, _Repo

USER = {"id": 7, "login": "admin", "role": "operator", "permissions": ["tab:settings"]}

NEW_RECONNECT = {
    "signal_loss": {"enabled": False, "frame_timeout_seconds": 9, "retry_interval_seconds": 11},
    "periodic": {"enabled": True, "interval_minutes": 15},
}


def _container(repo=None):
    repo = repo or _Repo()
    container = AppContainer(
        events_db=None, lists_db=None, clients_db=None, user_db=None,
        channel_db=None, controller_db=None, zone_db=None, controller_service=None,
        controller_automation=None, event_bus=None, debug_registry=None, debug_log_bus=None,
        processor=MagicMock(), lifecycle=None, main_loop=None, stream_shutdown=None,
        settings_service=SettingsService(repo, clock=_Clock()),
    )
    container.refresh_storage_clients = MagicMock()
    container.logging_applier = MagicMock()
    return container, repo


def _payload(reconnect=NEW_RECONNECT):
    return GlobalSettingsPayload(
        reconnect=reconnect,
        storage={"auto_cleanup_enabled": True, "cleanup_interval_minutes": 30, "events_retention_days": 30,
                 "media_retention_days": 14, "max_screenshots_mb": 4096},
        logging={"level": "INFO", "retention_days": 30},
        interface={},
        time={"timezone": "UTC+00:00"},
        plates={"enabled_countries": ["RU", "UA", "BY", "KZ"]},
        debug={},
    )


def _put(container, payload):
    return settings_router.put_global_settings(payload, container=container, current_user=USER)


class TestReadPath:
    def test_defaults_come_from_the_registry_when_the_table_is_empty(self):
        container, _ = _container()
        assert container.get_reconnect_settings() == {
            "signal_loss": {"enabled": True, "frame_timeout_seconds": 5, "retry_interval_seconds": 5},
            # Decision 4.10 no. 4: periodic reconnect is off by default.
            "periodic": {"enabled": False, "interval_minutes": 60},
        }

    def test_stored_values_override_defaults(self):
        container, _ = _container(_Repo({"reconnect.periodic.enabled": True, "reconnect.periodic.interval_minutes": 5}))
        assert container.get_reconnect_settings()["periodic"] == {"enabled": True, "interval_minutes": 5}

    def test_get_endpoint_serves_reconnect_from_the_service(self):
        container, _ = _container(_Repo({"reconnect.signal_loss.frame_timeout_seconds": 42}))
        body = settings_router.get_global_settings(container=container, current_user=USER)
        assert body["reconnect"]["signal_loss"]["frame_timeout_seconds"] == 42


class TestWritePath:
    def test_put_writes_flat_registry_keys_with_the_author(self):
        container, repo = _container()
        _put(container, _payload())
        (values, author), = repo.writes
        assert author == 7
        reconnect_only = {k: v for k, v in values.items() if k.startswith("reconnect.")}
        assert reconnect_only == {
            "reconnect.signal_loss.enabled": False,
            "reconnect.signal_loss.frame_timeout_seconds": 9,
            "reconnect.signal_loss.retry_interval_seconds": 11,
            "reconnect.periodic.enabled": True,
            "reconnect.periodic.interval_minutes": 15,
        }

    def test_running_processor_gets_the_new_values_without_restart(self):
        container, _ = _container()
        _put(container, _payload())
        container.processor.update_reconnect_settings.assert_called_once_with(NEW_RECONNECT)
        container.processor.update_reconnect_settings.reset_mock()
        assert container.get_reconnect_settings() == NEW_RECONNECT


    def test_reconnect_change_does_not_restart_the_processor(self):
        container, _ = _container()
        container.restart_processor_for_settings = MagicMock()
        _put(container, _payload())
        container.restart_processor_for_settings.assert_not_called()

    def test_unavailable_database_yields_503_and_leaves_the_processor_alone(self):
        container, repo = _container()
        repo.down = True
        with pytest.raises(HTTPException) as exc:
            _put(container, _payload())
        assert exc.value.status_code == 503
        container.processor.update_reconnect_settings.assert_not_called()

    def test_invalid_value_is_rejected_before_anything_is_saved(self):
        container, repo = _container()
        bad = {**NEW_RECONNECT, "signal_loss": {**NEW_RECONNECT["signal_loss"], "frame_timeout_seconds": 0}}
        with pytest.raises(Exception):
            _put(container, _payload(bad))
        assert repo.writes == []


