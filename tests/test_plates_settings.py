"""plates.enabled_countries lives in app_settings and is flagged
`requires_restart` (roadmap task 4.4)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api.routers import settings as settings_router
from config.registry import get_spec
from tests.test_reconnect_settings import USER, _container, _payload
from tests.test_settings_service import _Repo

DEFAULT = ["RU", "UA", "BY", "KZ"]


def _put(container, countries):
    payload = _payload()
    payload.plates = type(payload.plates)(enabled_countries=countries)
    container.restart_processor_for_settings = MagicMock()
    body = settings_router.put_global_settings(payload, container=container, current_user=USER)
    return body, container.restart_processor_for_settings


def test_key_is_flagged_as_requiring_restart():
    assert get_spec("plates.enabled_countries").requires_restart is True


def test_default_list_comes_from_the_registry_decision_4_10():
    container, _ = _container()
    assert container.get_plate_settings() == {"enabled_countries": DEFAULT}


def test_changing_the_list_restarts_the_processor_exactly_once_and_reports_it():
    container, repo = _container()
    body, restart = _put(container, ["RU", "BY"])
    restart.assert_called_once()
    assert body["requires_restart"] == ["plates.enabled_countries"]
    assert body["plates"] == {"enabled_countries": ["RU", "BY"]}
    assert repo.stored["plates.enabled_countries"] == ["RU", "BY"]


def test_unchanged_list_does_not_restart():
    container, _ = _container()
    body, restart = _put(container, DEFAULT)
    restart.assert_not_called()
    assert body["requires_restart"] == []


def test_same_change_saved_twice_restarts_only_the_first_time():
    container, _ = _container()
    _put(container, ["RU"])
    _, restart = _put(container, ["RU"])
    restart.assert_not_called()


def test_only_non_restart_keys_changed_does_not_restart():
    container, _ = _container()
    payload = _payload()
    payload.logging = type(payload.logging)(level="ERROR", retention_days=9)
    container.restart_processor_for_settings = MagicMock()
    body = settings_router.put_global_settings(payload, container=container, current_user=USER)
    container.restart_processor_for_settings.assert_not_called()
    assert body["requires_restart"] == []


def test_unknown_country_is_rejected_with_422_and_nothing_is_stored():
    container, repo = _container()
    with pytest.raises(HTTPException) as exc:
        _put(container, ["RU", "XX"])
    assert exc.value.status_code == 422
    assert repo.writes == []


def test_get_serves_plates_from_the_database():
    container, _ = _container(_Repo({"plates.enabled_countries": ["KZ"]}))
    body = settings_router.get_global_settings(container=container, current_user=USER)
    assert body["plates"] == {"enabled_countries": ["KZ"]}


