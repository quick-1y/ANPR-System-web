"""Authentication policy in app_settings (roadmap phase 8): token lifetime (8.1)
and brute-force limits (8.2) are operational settings, changeable at runtime."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import app.api.auth_utils as auth_utils
from app.api.auth_utils import create_access_token, hash_password
from app.api.routers import auth as auth_router
from app.api.routers import settings as settings_router
from app.api.schemas import AuthPayload, LoginRequest
from config.registry import SettingValidationError, get_spec
from config.settings_service import SettingsService
from tests.test_reconnect_settings import USER, _container, _payload
from tests.test_settings_service import _Clock, _Repo

ROOT = Path(__file__).resolve().parent.parent


def _user():
    return {
        "id": 1, "login": "root", "password": hash_password("1234"), "role": "superadmin", "permissions": [],
        "is_active": True, "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
        "password_changed_at": None,
    }


def _login_container(stored=None):
    container = MagicMock()
    container.user_db.find_by_login.return_value = _user()
    repo = _Repo(stored)
    container.settings_service = SettingsService(repo, clock=_Clock())
    return container, repo


def _request(ip="10.1.1.1"):
    request = MagicMock()
    request.client.host = ip
    return request


def _login(container, password="1234", ip="10.1.1.1"):
    return auth_router.login(LoginRequest(login="root", password=password), _request(ip), container)


def _lifetime_minutes(token: str) -> float:
    claims = pyjwt.decode(token, auth_utils.JWT_SECRET_KEY, algorithms=[auth_utils.JWT_ALGORITHM])
    return round((claims["exp"] - claims["iat"]) / 60)


@pytest.fixture(autouse=True)
def _clean_limiter():
    auth_router._failed_attempts.clear()
    yield
    auth_router._failed_attempts.clear()


def _save(container, **auth):
    payload = _payload()
    payload.auth = AuthPayload(**auth)
    return settings_router.put_global_settings(payload, container=container, current_user=USER)


# ── 8.1 token lifetime ──────────────────────────────────────────────────

class TestTokenTtl:
    def test_default_is_eight_hours(self):
        container, _ = _login_container()
        assert _lifetime_minutes(_login(container).access_token) == 480

    def test_the_module_constant_and_the_env_variable_are_gone(self):
        assert not hasattr(auth_utils, "JWT_EXPIRATION_MINUTES")
        from config.env_settings import load_env_config

        assert not hasattr(load_env_config({}), "jwt_expiration_minutes")
        assert "JWT_EXPIRATION_MINUTES" not in (ROOT / ".env.example").read_text(encoding="utf-8")

    def test_the_lifetime_is_a_required_argument_not_a_hidden_default(self):
        with pytest.raises(TypeError):
            create_access_token(user_id=1, role="x")  # type: ignore[call-arg]

    def test_the_stored_value_is_used_for_the_next_sign_in(self):
        container, _ = _login_container({"auth.token_ttl_minutes": 60})
        assert _lifetime_minutes(_login(container).access_token) == 60

    def test_a_change_affects_only_new_tokens(self):
        container, _ = _login_container()
        before = _login(container).access_token
        container.settings_service.update({"auth.token_ttl_minutes": 30})
        after = _login(container).access_token
        assert _lifetime_minutes(before) == 480, "an already issued token must keep its exp"
        assert _lifetime_minutes(after) == 30

    def test_it_changes_through_the_settings_endpoint_and_applies_from_the_next_login(self):
        container, repo = _container()
        container.user_db = MagicMock()
        container.user_db.find_by_login.return_value = _user()
        body = _save(container, token_ttl_minutes=120)
        assert body["auth"]["token_ttl_minutes"] == 120 and repo.stored["auth.token_ttl_minutes"] == 120
        assert _lifetime_minutes(_login(container).access_token) == 120

    @pytest.mark.parametrize("value", [0, 1, 4, 43201])
    def test_values_outside_the_bounds_are_refused(self, value):
        with pytest.raises(SettingValidationError):
            get_spec("auth.token_ttl_minutes").validate(value)
        with pytest.raises(ValidationError):
            AuthPayload(token_ttl_minutes=value)

    def test_the_lower_bound_protects_against_accidental_degradation(self):
        spec = get_spec("auth.token_ttl_minutes")
        assert spec.minimum == 5 and spec.default == 480
        assert spec.validate(5) == 5

    def test_an_out_of_range_value_never_reaches_the_database(self):
        container, repo = _container()
        with pytest.raises(SettingValidationError):
            container.settings_service.update({"auth.token_ttl_minutes": 2})
        assert repo.writes == []

    def test_saving_without_the_auth_section_leaves_the_stored_policy_alone(self):
        container, repo = _container(_Repo({"auth.token_ttl_minutes": 45}))
        settings_router.put_global_settings(_payload(), container=container, current_user=USER)
        assert repo.stored["auth.token_ttl_minutes"] == 45


# ── 8.2 brute-force limits ──────────────────────────────────────────────

def _fail(container, times, ip="10.1.1.1"):
    for _ in range(times):
        with pytest.raises(HTTPException) as exc:
            _login(container, password="wrong", ip=ip)
        assert exc.value.status_code == 401


class TestRateLimitPolicy:
    def test_defaults_are_unchanged_five_failures_per_sixty_seconds(self):
        assert get_spec("auth.login_rate_limit_attempts").default == 5
        assert get_spec("auth.login_rate_limit_window_seconds").default == 60
        container, _ = _login_container()
        _fail(container, 5)
        with pytest.raises(HTTPException) as exc:
            _login(container, password="wrong")
        assert exc.value.status_code == 429

    def test_a_stricter_stored_policy_applies(self):
        container, _ = _login_container({"auth.login_rate_limit_attempts": 2})
        _fail(container, 2)
        with pytest.raises(HTTPException) as exc:
            _login(container)  # even the right password is refused while locked out
        assert exc.value.status_code == 429

    def test_a_change_applies_to_the_next_request_without_a_restart(self):
        container, _ = _login_container({"auth.login_rate_limit_attempts": 2})
        _fail(container, 2)
        with pytest.raises(HTTPException) as locked:
            _login(container)
        assert locked.value.status_code == 429
        # the administrator relaxes the limit through the settings endpoint
        container.settings_service.update({"auth.login_rate_limit_attempts": 10})
        container.settings_service._checked_at = None
        assert _login(container).access_token  # same process, same recorded failures, now allowed

    def test_the_window_is_read_on_every_check(self, monkeypatch):
        container, _ = _login_container({"auth.login_rate_limit_attempts": 2, "auth.login_rate_limit_window_seconds": 10})
        now = {"t": 1000.0}
        monkeypatch.setattr(auth_router.time, "monotonic", lambda: now["t"])
        _fail(container, 2)
        now["t"] += 11  # window elapsed
        assert _login(container).access_token

    def test_a_longer_window_keeps_the_lockout_longer(self, monkeypatch):
        container, _ = _login_container({"auth.login_rate_limit_attempts": 2, "auth.login_rate_limit_window_seconds": 600})
        now = {"t": 1000.0}
        monkeypatch.setattr(auth_router.time, "monotonic", lambda: now["t"])
        _fail(container, 2)
        now["t"] += 120  # the default window would have expired by now
        with pytest.raises(HTTPException) as exc:
            _login(container)
        assert exc.value.status_code == 429

    def test_the_policy_is_per_ip(self):
        container, _ = _login_container({"auth.login_rate_limit_attempts": 1})
        _fail(container, 1, ip="10.9.9.1")
        assert _login(container, ip="10.9.9.2").access_token

    def test_the_message_reflects_the_window(self):
        assert auth_router._wait_text(60) == "минуту"
        assert auth_router._wait_text(20) == "20 с"
        assert auth_router._wait_text(600) == "10 мин"

    def test_the_module_constants_are_gone(self):
        assert not hasattr(auth_router, "_MAX_FAILED_ATTEMPTS")
        assert not hasattr(auth_router, "_RATE_WINDOW_SECONDS")

    @pytest.mark.parametrize("key, bad", [
        ("auth.login_rate_limit_attempts", 0),
        ("auth.login_rate_limit_attempts", 101),
        ("auth.login_rate_limit_window_seconds", 0),
        ("auth.login_rate_limit_window_seconds", 86401),
    ])
    def test_bounds_keep_the_protection_from_being_switched_off(self, key, bad):
        with pytest.raises(SettingValidationError):
            get_spec(key).validate(bad)

    def test_the_limits_are_editable_through_the_settings_endpoint(self):
        container, repo = _container()
        body = _save(container, login_rate_limit_attempts=3, login_rate_limit_window_seconds=120)
        assert body["auth"] == {"token_ttl_minutes": 480, "login_rate_limit_attempts": 3, "login_rate_limit_window_seconds": 120}
        assert repo.stored["auth.login_rate_limit_attempts"] == 3

    def test_partial_auth_payload_changes_only_the_given_keys(self):
        container, repo = _container()
        _save(container, login_rate_limit_attempts=7)
        assert "auth.token_ttl_minutes" not in repo.stored and repo.stored["auth.login_rate_limit_attempts"] == 7

    def test_saving_the_policy_needs_the_settings_permission(self):
        guard = __import__("inspect").signature(settings_router.put_global_settings).parameters["current_user"].default.dependency
        with pytest.raises(HTTPException) as exc:
            guard(current_user={"id": 9, "role": "operator", "permissions": ["tab:obs"]})
        assert exc.value.status_code == 403


class TestSettingsUi:
    def _js(self, name):
        return (ROOT / "app" / "web" / "js" / name).read_text(encoding="utf-8")

    def test_the_security_card_is_wired_to_the_auth_section(self):
        html = (ROOT / "app" / "web" / "index.html").read_text(encoding="utf-8")
        for control in ("g_token_ttl", "g_rl_attempts", "g_rl_window"):
            assert f'id="{control}"' in html
        assert 'data-general-tab="security"' in html and 'data-general-group="security"' in html
        settings = self._js("settings.js")
        for name in ("token_ttl_minutes", "login_rate_limit_attempts", "login_rate_limit_window_seconds"):
            assert settings.count(name) >= 2, f"{name} must be both loaded and saved"
