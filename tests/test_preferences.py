"""Personal preferences, class U (roadmap phase 6): storage (6.1),
`/api/me/preferences` (6.2) and the split of server/personal debug flags (6.3)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routers import debug as debug_router
from app.api.routers import preferences as prefs_router
from app.api.routers import settings as settings_router
from app.api.routers.system import system_time
from config.preferences import (
    clean_stored,
    effective_timezone,
    known_keys,
    resolve,
    validate_patch,
)
from config.registry import SettingValidationError, get_spec
from database.errors import StorageUnavailableError
from database.user_repository import UserDatabase, _load_preferences, _row_to_dict
from runtime.debug import DebugRegistry, DebugSettings
from tests.test_reconnect_settings import _container, _payload
from tests.test_settings_service import _Repo
from tests.test_user_repository import _make_db, _mock_conn

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "app" / "web"

NO_PERMISSIONS = {"id": 5, "login": "guard", "role": "operator", "permissions": []}
OTHER_USER = {"id": 6, "login": "other", "role": "operator", "permissions": ["tab:obs"]}
SUPERADMIN = {"id": 1, "login": "root", "role": "superadmin", "permissions": []}


# ── 6.1 storage ─────────────────────────────────────────────────────────

class TestRegistryAndValidation:
    def test_known_keys_are_the_class_u_keys_without_reserved(self):
        assert set(known_keys()) == {
            "theme", "style", "sidebar_locked", "debug_panel_enabled", "channel_metrics_visible", "timezone",
        }
        assert "locale" not in known_keys()

    def test_patch_is_validated_per_key_and_stays_partial(self):
        assert validate_patch({"theme": "dark"}) == {"theme": "dark"}
        assert validate_patch({"sidebar_locked": True, "timezone": "Europe/Minsk"}) == {
            "sidebar_locked": True, "timezone": "Europe/Minsk",
        }

    def test_auto_timezone_is_accepted(self):
        assert validate_patch({"timezone": "auto"}) == {"timezone": "auto"}

    @pytest.mark.parametrize(
        "patch_",
        [{"theme": "sepia"}, {"style": "neon"}, {"sidebar_locked": "yes"}, {"timezone": "UTC+03:00"}, {"timezone": 3}],
    )
    def test_values_are_validated_against_the_registry(self, patch_):
        with pytest.raises(SettingValidationError):
            validate_patch(patch_)

    @pytest.mark.parametrize("key", ["role", "permissions", "locale", "password", "id", "nonsense"])
    def test_unknown_and_reserved_keys_are_rejected(self, key):
        with pytest.raises(SettingValidationError):
            validate_patch({key: "x"})

    def test_none_means_reset_and_is_not_type_checked(self):
        assert validate_patch({"theme": None}) == {"theme": None}

    def test_stored_garbage_is_dropped_on_read(self):
        assert clean_stored({"theme": "dark", "role": "superadmin", "style": "neon", "x": 1}) == {"theme": "dark"}
        assert clean_stored(None) == {}


class TestRepository:
    def test_row_carries_preferences_as_dict(self):
        row = (1, "u", "h", "operator", [], True, None, None, None, {"theme": "dark"})
        assert _row_to_dict(row)["preferences"] == {"theme": "dark"}

    @pytest.mark.parametrize("raw, expected", [('{"theme": "dark"}', {"theme": "dark"}), (None, {}), ("garbage", {}), ("[1]", {})])
    def test_preferences_column_is_parsed_defensively(self, raw, expected):
        assert _load_preferences(raw) == expected

    def test_schema_adds_the_column_idempotently(self):
        assert "ADD COLUMN IF NOT EXISTS preferences JSONB NOT NULL DEFAULT '{}'::jsonb" in UserDatabase._SCHEMA
        assert "preferences" in (ROOT / "database" / "postgres" / "schema.sql").read_text(encoding="utf-8")

    def test_get_returns_only_known_keys(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=({"theme": "dark", "role": "superadmin"},))
        with patch.object(db, "_connect", return_value=conn):
            assert db.get_preferences(3) == {"theme": "dark"}

    def test_get_of_missing_user_is_none(self):
        db = _make_db()
        conn, _ = _mock_conn(fetchone=None)
        with patch.object(db, "_connect", return_value=conn):
            assert db.get_preferences(99) is None

    def test_merge_is_one_atomic_jsonb_merge_that_leaves_other_keys_alone(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=({"theme": "dark", "sidebar_locked": True},))
        with patch.object(db, "_connect", return_value=conn):
            result = db.merge_preferences(3, {"theme": "dark"})
        sql, params = cursor.execute.call_args.args
        assert "preferences || %s::jsonb" in sql and "WHERE id = %s" in sql
        assert json.loads(params[0]) == {"theme": "dark"} and params[1] == 3
        assert result == {"theme": "dark", "sidebar_locked": True}
        conn.commit.assert_called_once()

    def test_merge_drops_unknown_keys_before_touching_the_database(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=({},))
        with patch.object(db, "_connect", return_value=conn):
            db.merge_preferences(3, {"theme": "dark", "role": "superadmin", "permissions": ["x"]})
        assert json.loads(cursor.execute.call_args.args[1][0]) == {"theme": "dark"}

    def test_none_removes_the_key(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=({},))
        with patch.object(db, "_connect", return_value=conn):
            db.merge_preferences(3, {"theme": None})
        first_sql, first_params = cursor.execute.call_args_list[-2].args
        assert "preferences - %s::text[]" in first_sql and first_params[0] == ["theme"]
        assert json.loads(cursor.execute.call_args_list[-1].args[1][0]) == {}

    def test_merge_for_a_missing_user_is_none(self):
        db = _make_db()
        conn, _ = _mock_conn(fetchone=None)
        with patch.object(db, "_connect", return_value=conn):
            assert db.merge_preferences(99, {"theme": "dark"}) is None


class TestResolution:
    def _settings(self, stored=None):
        return _container(_Repo(stored))[0].settings_service

    def test_new_user_inherits_registry_defaults(self):
        resolved = resolve({}, self._settings())
        assert resolved["theme"] == {"value": "light", "source": "default"}
        assert resolved["style"] == {"value": "graphite-minimal", "source": "default"}
        assert resolved["sidebar_locked"] == {"value": False, "source": "default"}
        assert resolved["timezone"] == {"value": "auto", "source": "default"}

    def test_explicit_instance_default_is_reported_as_instance(self):
        resolved = resolve({}, self._settings({"interface.default_theme": "dark"}))
        assert resolved["theme"] == {"value": "dark", "source": "instance"}
        assert resolved["style"]["source"] == "default"

    def test_personal_value_wins_over_the_instance_default(self):
        resolved = resolve({"theme": "light"}, self._settings({"interface.default_theme": "dark"}))
        assert resolved["theme"] == {"value": "light", "source": "user"}

    def test_timezone_auto_follows_the_instance_zone_and_a_personal_zone_overrides_it(self):
        settings = self._settings({"interface.display_timezone": "Europe/Minsk"})
        assert effective_timezone({}, settings) == "Europe/Minsk"
        assert effective_timezone({"timezone": "auto"}, settings) == "Europe/Minsk"
        assert effective_timezone({"timezone": "Asia/Almaty"}, settings) == "Asia/Almaty"


# ── 6.2 endpoints ───────────────────────────────────────────────────────

class _FakeUserDb:
    """In-memory `users.preferences`, reusing the real key filtering."""

    def __init__(self, users=(NO_PERMISSIONS, OTHER_USER)):
        self.docs = {u["id"]: {} for u in users}
        self.calls = []
        self.down = False

    def get_preferences(self, user_id):
        if self.down:
            raise StorageUnavailableError("down")
        return clean_stored(self.docs[user_id]) if user_id in self.docs else None

    def merge_preferences(self, user_id, patch):
        if self.down:
            raise StorageUnavailableError("down")
        self.calls.append((user_id, dict(patch)))
        if user_id not in self.docs:
            return None
        doc = self.docs[user_id]
        for key, value in patch.items():
            if value is None:
                doc.pop(key, None)
            else:
                doc[key] = value
        return clean_stored(doc)


def _with_user_db(stored=None, users=(NO_PERMISSIONS, OTHER_USER)):
    container, repo = _container(_Repo(stored))
    container.user_db = _FakeUserDb(users)
    return container


def _patch(container, user, **fields):
    return prefs_router.patch_my_preferences(prefs_router.PreferencesPatch(**fields), container=container, user=user)


class TestEndpoints:
    def test_a_user_without_any_permission_reads_and_writes_their_own_preferences(self):
        container = _with_user_db()
        body = prefs_router.get_my_preferences(container=container, user=NO_PERMISSIONS)
        assert body["preferences"]["theme"]["source"] == "default"
        updated = _patch(container, NO_PERMISSIONS, theme="dark", sidebar_locked=True)
        assert updated["preferences"]["theme"] == {"value": "dark", "source": "user"}
        assert updated["preferences"]["sidebar_locked"] == {"value": True, "source": "user"}

    def test_the_endpoints_require_authentication_only(self):
        import inspect

        from app.api.deps import get_current_user

        for function in (prefs_router.get_my_preferences, prefs_router.patch_my_preferences):
            default = inspect.signature(function).parameters["user"].default
            assert default.dependency is get_current_user
        source = inspect.getsource(prefs_router)
        assert "require_permission" not in source and "require_role" not in source

    def test_a_user_cannot_touch_another_users_preferences(self):
        container = _with_user_db()
        _patch(container, NO_PERMISSIONS, theme="dark")
        assert container.user_db.docs[6] == {}
        assert container.user_db.calls == [(5, {"theme": "dark"})]

    @pytest.mark.parametrize("field", ["user_id", "id", "login", "role", "permissions"])
    def test_the_patch_cannot_name_another_user_or_privileged_fields(self, field):
        with pytest.raises(ValidationError):
            prefs_router.PreferencesPatch(**{field: 6})

    def test_invalid_value_is_422_and_nothing_is_written(self):
        container = _with_user_db()
        with pytest.raises(HTTPException) as exc:
            _patch(container, NO_PERMISSIONS, theme="sepia")
        assert exc.value.status_code == 422
        assert container.user_db.calls == []

    def test_omitted_fields_are_left_alone(self):
        container = _with_user_db()
        _patch(container, NO_PERMISSIONS, theme="dark")
        result = _patch(container, NO_PERMISSIONS, sidebar_locked=True)
        assert result["preferences"]["theme"]["value"] == "dark"

    def test_source_follows_the_layer_and_null_resets_to_it(self):
        container = _with_user_db({"interface.default_theme": "dark"})
        assert prefs_router.get_my_preferences(container=container, user=NO_PERMISSIONS)["preferences"]["theme"] == {
            "value": "dark", "source": "instance",
        }
        assert _patch(container, NO_PERMISSIONS, theme="light")["preferences"]["theme"] == {"value": "light", "source": "user"}
        assert _patch(container, NO_PERMISSIONS, theme=None)["preferences"]["theme"] == {"value": "dark", "source": "instance"}

    def test_response_reports_the_effective_display_timezone(self):
        container = _with_user_db({"interface.display_timezone": "Europe/Minsk"})
        assert prefs_router.get_my_preferences(container=container, user=NO_PERMISSIONS)["display_timezone"] == "Europe/Minsk"
        assert _patch(container, NO_PERMISSIONS, timezone="Asia/Almaty")["display_timezone"] == "Asia/Almaty"

    def test_unknown_user_is_404(self):
        container = _with_user_db(users=())
        with pytest.raises(HTTPException) as exc:
            prefs_router.get_my_preferences(container=container, user=NO_PERMISSIONS)
        assert exc.value.status_code == 404

    def test_database_outage_is_503(self):
        container = _with_user_db()
        container.user_db.down = True
        with pytest.raises(HTTPException) as exc:
            _patch(container, NO_PERMISSIONS, theme="dark")
        assert exc.value.status_code == 503

    def test_system_time_uses_the_personal_zone(self):
        container = _with_user_db({"interface.display_timezone": "Europe/Minsk"})
        assert system_time(container=container, _user=NO_PERMISSIONS)["display_timezone"] == "Europe/Minsk"
        _patch(container, NO_PERMISSIONS, timezone="Asia/Almaty")
        assert system_time(container=container, _user=NO_PERMISSIONS)["display_timezone"] == "Asia/Almaty"
        assert system_time(container=container, _user=OTHER_USER)["display_timezone"] == "Europe/Minsk"

    def test_router_is_registered_in_the_application(self):
        main = (ROOT / "app" / "api" / "main.py").read_text(encoding="utf-8")
        assert "preferences_router" in main and "include_router(preferences_router)" in main


# ── 6.3 server vs personal debug flags ──────────────────────────────────

class TestDebugSplit:
    def test_show_channel_metrics_no_longer_affects_the_server_registry(self):
        registry = DebugRegistry({"video_output_enabled": True})
        registry.update_settings({"show_channel_metrics": True, "log_panel_enabled": True})
        assert registry.get_settings().to_dict() == {"video_output_enabled": True}
        assert not hasattr(DebugSettings(), "show_channel_metrics")

    def test_video_output_flag_does_affect_the_registry(self):
        registry = DebugRegistry({"video_output_enabled": True})
        assert registry.get_settings().video_output_enabled is True
        registry.update_settings({"video_output_enabled": False})
        assert registry.get_settings().video_output_enabled is False

    def test_debug_endpoint_writes_the_server_flag_to_app_settings_and_the_processor(self):
        container, repo = _container()
        debug_router.put_debug_settings(debug_router.DebugPayload(video_output_enabled=False), container=container, user=SUPERADMIN)
        assert repo.stored["debug.video_output_enabled"] is False
        container.processor.update_debug_settings.assert_called_once_with({"video_output_enabled": False})

    def test_settings_put_changes_the_server_flag_only_for_a_superadmin(self):
        payload = _payload()
        payload.debug = debug_router.DebugPayload(video_output_enabled=False)
        container, repo = _container()
        settings_router.put_global_settings(payload, container=container, current_user=SUPERADMIN)
        assert repo.stored["debug.video_output_enabled"] is False
        container2, repo2 = _container()
        settings_router.put_global_settings(payload, container=container2, current_user={**SUPERADMIN, "role": "operator"})
        assert "debug.video_output_enabled" not in repo2.stored

    def test_settings_response_exposes_only_the_server_flag_to_a_superadmin(self):
        container, _ = _container()
        body = settings_router.get_global_settings(container=container, current_user=SUPERADMIN)
        assert body["debug"] == {"video_output_enabled": True}
        body = settings_router.get_global_settings(container=container, current_user={**SUPERADMIN, "role": "operator"})
        assert "debug" not in body

    def test_personal_debug_flags_of_two_users_are_independent(self):
        container = _with_user_db()
        _patch(container, NO_PERMISSIONS, debug_panel_enabled=True, channel_metrics_visible=True)
        mine = prefs_router.get_my_preferences(container=container, user=NO_PERMISSIONS)["preferences"]
        theirs = prefs_router.get_my_preferences(container=container, user=OTHER_USER)["preferences"]
        assert mine["debug_panel_enabled"]["value"] is True and mine["channel_metrics_visible"]["value"] is True
        assert theirs["debug_panel_enabled"]["value"] is False and theirs["channel_metrics_visible"]["value"] is False

    def test_video_output_is_not_a_user_preference(self):
        assert "video_output_enabled" not in known_keys()
        assert get_spec("debug.video_output_enabled").cls.value == "A"
        assert get_spec("debug.video_output_enabled").owner == "admin-debug"


class TestFrontendWiring:
    def _js(self, name):
        return (WEB / "js" / name).read_text(encoding="utf-8")

    def test_removed_server_fields_are_not_used_anywhere(self):
        for path in (WEB / "js").glob("*.js"):
            text = path.read_text(encoding="utf-8")
            for stale in ("disable_video_output", "show_channel_metrics", "log_panel_enabled"):
                assert stale not in text, f"{path.name} still uses {stale}"

    def test_settings_save_no_longer_sends_personal_flags(self):
        text = self._js("settings.js")
        assert not re.search(r"sidebar_locked\s*:", text)
        assert "d_metrics" not in text.split("export async function saveGeneral")[1]

    def test_personal_flags_save_through_the_preferences_endpoint_on_toggle(self):
        text = self._js("preferences.js")
        assert "/api/me/preferences" in text and '"PATCH"' in text
        for pair in ('"p_sidebar_locked", "sidebar_locked"', '"d_metrics", "channel_metrics_visible"', '"d_log", "debug_panel_enabled"'):
            assert pair in text

    def test_bootstrap_loads_preferences_without_a_tab_permission(self):
        app = self._js("app.js")
        before_settings = app.split("hasPermission(\"tab:settings\")")[0]
        assert "appearance.signIn(" in before_settings  # signIn loads the preferences

    def test_ui_reads_personal_flags_from_preferences(self):
        assert 'getPreference("channel_metrics_visible")' in self._js("video-grid.js")
        assert 'getPreference("debug_panel_enabled")' in self._js("debug.js")
