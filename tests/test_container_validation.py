"""Tests for AppContainer's cross-entity validation methods (app/api/container.py).

Covers validate_channel_controller_binding, validate_channel_zone_binding, and
validate_global_hotkeys — the checks that gate PUT /api/channels/{id}/config
(app/api/routers/channels.py) and controller create/update
(app/api/routers/controllers.py). These need a live-DB existence check
(controller_db.get_controller / zone_db.get_zone), which is why they live on
the container rather than as Pydantic schema validators (see audit finding #8).

Exercised via lightweight stub objects (per project convention: no mocking
library) rather than a real AppContainer, since these methods only touch
`controller_exists()` and `zone_db.get_zone()`.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.container import AppContainer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeZoneDb:
    def __init__(self, zone_ids=()):
        self._zones = {zid: {"id": zid} for zid in zone_ids}

    def get_zone(self, zone_id):
        return self._zones.get(zone_id)


class _ValidationContainer:
    """Duck-types just enough of AppContainer for the validate_* methods
    under test — they only read `controller_exists()` and `zone_db`."""

    def __init__(self, controller_ids=(), zone_ids=()):
        self._controller_ids = set(controller_ids)
        self.zone_db = _FakeZoneDb(zone_ids)

    def controller_exists(self, controller_id: int) -> bool:
        return controller_id in self._controller_ids


def _validate_controller_binding(payload, controller_ids=()):
    container = _ValidationContainer(controller_ids=controller_ids)
    AppContainer.validate_channel_controller_binding(container, payload)
    return payload


def _validate_zone_binding(payload, zone_ids=()):
    container = _ValidationContainer(zone_ids=zone_ids)
    AppContainer.validate_channel_zone_binding(container, payload)
    return payload


# ---------------------------------------------------------------------------
# validate_channel_controller_binding
# ---------------------------------------------------------------------------

class TestValidateChannelControllerBinding:
    def test_no_controller_id_clears_relay(self):
        payload = {"controller_relay": 3}
        result = _validate_controller_binding(payload, controller_ids=[1, 2])
        assert result["controller_relay"] == 0

    def test_existing_controller_id_is_accepted(self):
        payload = {"controller_id": 1, "controller_relay": 2}
        result = _validate_controller_binding(payload, controller_ids=[1, 2])
        assert result["controller_id"] == 1
        assert result["controller_relay"] == 2

    def test_unknown_controller_id_raises_400(self):
        payload = {"controller_id": 99}
        with pytest.raises(HTTPException) as exc:
            _validate_controller_binding(payload, controller_ids=[1, 2])
        assert exc.value.status_code == 400
        assert "99" in exc.value.detail


# ---------------------------------------------------------------------------
# validate_channel_zone_binding
# ---------------------------------------------------------------------------

class TestValidateChannelZoneBinding:
    def test_no_zones_clears_channel_type(self):
        payload = {"zone_channel_type": "entry"}
        result = _validate_zone_binding(payload, zone_ids=[10])
        assert result["zone_channel_type"] is None

    def test_existing_zone_before_id_is_accepted(self):
        payload = {"zone_before_id": 10, "zone_after_id": None}
        result = _validate_zone_binding(payload, zone_ids=[10])
        assert result["zone_before_id"] == 10

    def test_existing_zone_after_id_is_accepted(self):
        payload = {"zone_before_id": None, "zone_after_id": 20}
        result = _validate_zone_binding(payload, zone_ids=[20])
        assert result["zone_after_id"] == 20

    def test_zero_zone_id_is_treated_as_unset(self):
        # 0 is the "no zone" sentinel — must not trigger a DB existence check.
        payload = {"zone_before_id": 0, "zone_after_id": None}
        result = _validate_zone_binding(payload, zone_ids=[])
        assert result["zone_before_id"] == 0

    def test_unknown_zone_before_id_raises_400(self):
        payload = {"zone_before_id": 999, "zone_after_id": None}
        with pytest.raises(HTTPException) as exc:
            _validate_zone_binding(payload, zone_ids=[10])
        assert exc.value.status_code == 400
        assert "999" in exc.value.detail

    def test_unknown_zone_after_id_raises_400(self):
        payload = {"zone_before_id": None, "zone_after_id": 999}
        with pytest.raises(HTTPException) as exc:
            _validate_zone_binding(payload, zone_ids=[10])
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# validate_global_hotkeys
# ---------------------------------------------------------------------------

class TestValidateGlobalHotkeys:
    def test_no_hotkeys_passes(self):
        controllers = [{"id": 1, "name": "gate", "relays": [{"hotkey": ""}]}]
        AppContainer.validate_global_hotkeys(controllers)  # should not raise

    def test_unique_hotkeys_across_controllers_pass(self):
        controllers = [
            {"id": 1, "name": "gate", "relays": [{"hotkey": "A"}]},
            {"id": 2, "name": "barrier", "relays": [{"hotkey": "B"}]},
        ]
        AppContainer.validate_global_hotkeys(controllers)  # should not raise

    def test_duplicate_hotkey_within_one_controller_raises_422(self):
        controllers = [
            {"id": 1, "name": "gate", "relays": [{"hotkey": "A"}, {"hotkey": "A"}]},
        ]
        with pytest.raises(HTTPException) as exc:
            AppContainer.validate_global_hotkeys(controllers)
        assert exc.value.status_code == 422
        assert "A" in exc.value.detail

    def test_duplicate_hotkey_across_controllers_raises_422(self):
        controllers = [
            {"id": 1, "name": "gate", "relays": [{"hotkey": "A"}]},
            {"id": 2, "name": "barrier", "relays": [{"hotkey": "A"}]},
        ]
        with pytest.raises(HTTPException) as exc:
            AppContainer.validate_global_hotkeys(controllers)
        assert exc.value.status_code == 422

    def test_hotkey_comparison_is_case_insensitive(self):
        controllers = [
            {"id": 1, "name": "gate", "relays": [{"hotkey": "a"}]},
            {"id": 2, "name": "barrier", "relays": [{"hotkey": "A"}]},
        ]
        with pytest.raises(HTTPException) as exc:
            AppContainer.validate_global_hotkeys(controllers)
        assert exc.value.status_code == 422
