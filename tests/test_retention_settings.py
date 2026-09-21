"""Retention policy lives in app_settings and has a single write path
(roadmap task 4.2, problem P8)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.container import AppContainer
from app.api.routers import settings as settings_router
from app.shared.data_lifecycle import RetentionPolicy
from config.settings_service import SettingsService
from tests.test_reconnect_settings import USER, _container, _payload
from tests.test_settings_service import _Clock, _Repo

STORAGE = {"auto_cleanup_enabled": False, "cleanup_interval_minutes": 10, "events_retention_days": 90,
           "media_retention_days": 7, "max_screenshots_mb": 2048}


def _put(container, storage=STORAGE):
    payload = _payload()
    payload.storage = type(payload.storage)(**storage)
    return settings_router.put_global_settings(payload, container=container, current_user=USER)


def test_put_settings_writes_retention_keys_to_app_settings():
    container, repo = _container()
    _put(container)
    (values, author), = repo.writes
    assert author == 7
    assert {k: v for k, v in values.items() if k.startswith("retention.")} == {
        f"retention.{name}": value for name, value in STORAGE.items()
    }


def test_reconnect_and_retention_are_saved_in_one_transaction():
    container, repo = _container()
    _put(container)
    assert len(repo.writes) == 1


def test_policy_is_rebuilt_from_the_database_after_a_save():
    container, _ = _container()
    _put(container)
    assert RetentionPolicy.from_settings(container.settings_service).events_retention_days == 90


def test_get_settings_shows_retention_from_the_database():
    container, _ = _container(_Repo({"retention.events_retention_days": 5}))
    body = settings_router.get_global_settings(container=container, current_user=USER)
    assert body["storage"]["events_retention_days"] == 5
    assert body["storage"]["cleanup_interval_minutes"] == 30




def test_out_of_range_retention_is_rejected_and_nothing_is_written():
    container, repo = _container()
    with pytest.raises(Exception):
        _put(container, {**STORAGE, "max_screenshots_mb": 200})  # registry minimum is 256 (payload allows 128)
    assert repo.writes == []


def test_database_outage_gives_503():
    container, repo = _container()
    repo.down = True
    with pytest.raises(HTTPException) as exc:
        _put(container)
    assert exc.value.status_code == 503


def test_lifecycle_is_built_from_the_service():
    container, _ = _container(_Repo({"retention.media_retention_days": 3}))
    with patch("app.api.container.DataLifecycleService") as lifecycle:
        container._resolve_dsn = lambda: "postgresql://x/x"
        container._build_lifecycle()
    assert lifecycle.call_args.kwargs["policy"].media_retention_days == 3


