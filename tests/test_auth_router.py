"""Tests for app/api/routers/auth.py — login, logout, me endpoints.

Uses mocks to test auth router logic without a live server or DB.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.auth_utils import hash_password, create_access_token
from app.api.routers.auth import (
    login, logout, me, available_permissions,
    AVAILABLE_PERMISSIONS,
    _check_rate_limit, _record_failed_attempt, _reset_attempts,
    _failed_attempts, _MAX_FAILED_ATTEMPTS, _RATE_WINDOW_SECONDS,
)
from app.api.schemas import LoginRequest, UserOut


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(user_id=1, login="admin", role="admin", is_active=True,
               permissions=None, password="1234", password_changed_at=None):
    return {
        "id": user_id,
        "login": login,
        "password": hash_password(password),
        "role": role,
        "permissions": permissions or [],
        "is_active": is_active,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "password_changed_at": password_changed_at,
    }


def _make_container(user=None):
    container = MagicMock()
    container.user_db.find_by_login.return_value = user
    return container


def _make_request(ip="127.0.0.1"):
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = ip
    return req


# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------

class TestLogin:
    def setup_method(self):
        # Clear rate-limiter state before each test
        _failed_attempts.clear()

    def test_valid_credentials(self):
        user = _make_user(password="1234")
        container = _make_container(user=user)
        body = LoginRequest(login="admin", password="1234")

        result = login(body, _make_request(), container)

        assert result.access_token
        assert result.token_type == "bearer"
        assert result.user.login == "admin"
        assert result.user.role == "admin"
        container.user_db.find_by_login.assert_called_once_with("admin")

    def test_wrong_password(self):
        user = _make_user(password="1234")
        container = _make_container(user=user)
        body = LoginRequest(login="admin", password="wrong")

        with pytest.raises(HTTPException) as exc_info:
            login(body, _make_request(), container)
        assert exc_info.value.status_code == 401

    def test_user_not_found(self):
        container = _make_container(user=None)
        body = LoginRequest(login="nobody", password="1234")

        with pytest.raises(HTTPException) as exc_info:
            login(body, _make_request(), container)
        assert exc_info.value.status_code == 401

    def test_inactive_user(self):
        user = _make_user(is_active=False, password="1234")
        container = _make_container(user=user)
        body = LoginRequest(login="admin", password="1234")

        with pytest.raises(HTTPException) as exc_info:
            login(body, _make_request(), container)
        assert exc_info.value.status_code == 401
        assert "деактивирован" in exc_info.value.detail

    def test_login_response_excludes_password(self):
        user = _make_user(password="1234")
        container = _make_container(user=user)
        body = LoginRequest(login="admin", password="1234")

        result = login(body, _make_request(), container)
        assert not hasattr(result.user, "password")


# ---------------------------------------------------------------------------
# POST /api/auth/logout
# ---------------------------------------------------------------------------

class TestLogout:
    def test_returns_ok(self):
        user = _make_user()
        result = logout(current_user=user)
        assert result == {"detail": "ok"}


# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------

class TestMe:
    def test_returns_current_user(self):
        user = _make_user(user_id=5, login="operator1", role="operator", permissions=["tab:obs"])
        result = me(current_user=user)
        assert isinstance(result, UserOut)
        assert result.login == "operator1"
        assert result.role == "operator"
        assert result.permissions == ["tab:obs"]

    def test_excludes_password(self):
        user = _make_user()
        result = me(current_user=user)
        data = result.model_dump()
        assert "password" not in data


# ---------------------------------------------------------------------------
# GET /api/permissions/available
# ---------------------------------------------------------------------------

class TestAvailablePermissions:
    def test_returns_list_of_objects(self):
        user = _make_user(role="admin")
        result = available_permissions(current_user=user)
        assert isinstance(result, list)
        assert len(result) == len(AVAILABLE_PERMISSIONS)

    def test_each_item_has_required_fields(self):
        user = _make_user(role="admin")
        result = available_permissions(current_user=user)
        for item in result:
            assert "key" in item
            assert "label" in item
            assert "group" in item

    def test_contains_all_tab_keys(self):
        user = _make_user(role="admin")
        result = available_permissions(current_user=user)
        keys = [item["key"] for item in result]
        assert "tab:obs" in keys
        assert "tab:journal" in keys
        assert "tab:lists" in keys
        assert "tab:settings" in keys

    def test_operator_is_blocked(self):
        """available_permissions is admin-only — operators get 403."""
        from app.api.deps import require_role
        user_op = _make_user(role="operator")
        dep = require_role("admin")
        with pytest.raises(Exception) as exc_info:
            dep(current_user=user_op)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Phase 3: Frontend contract validation
# ---------------------------------------------------------------------------

class TestLoginResponseContract:
    def setup_method(self):
        _failed_attempts.clear()

    def test_login_response_has_access_token(self):
        user = _make_user(password="secret")
        result = login(LoginRequest(login="admin", password="secret"), _make_request(), _make_container(user=user))
        assert isinstance(result.access_token, str)
        assert len(result.access_token) > 0

    def test_login_response_user_has_required_frontend_fields(self):
        user = _make_user(user_id=42, login="op1", role="operator",
                          permissions=["tab:obs", "tab:journal"], password="pw")
        result = login(LoginRequest(login="op1", password="pw"), _make_request(), _make_container(user=user))
        u = result.user
        assert u.id == 42
        assert u.login == "op1"
        assert u.role == "operator"
        assert u.permissions == ["tab:obs", "tab:journal"]

    def test_login_response_admin_has_empty_permissions_array(self):
        """Admin permissions array is empty by convention; admin access is implied by role."""
        user = _make_user(role="admin", permissions=[], password="pw")
        result = login(LoginRequest(login="admin", password="pw"), _make_request(), _make_container(user=user))
        assert result.user.permissions == []
        assert result.user.role == "admin"


class TestMeResponseContract:
    def test_me_returns_is_active(self):
        user = _make_user(is_active=True)
        result = me(current_user=user)
        assert result.is_active is True

    def test_me_returns_permissions_list(self):
        user = _make_user(role="operator", permissions=["tab:obs", "tab:lists"])
        result = me(current_user=user)
        assert "tab:obs" in result.permissions
        assert "tab:lists" in result.permissions


# ---------------------------------------------------------------------------
# Phase 6: Brute-force rate limiter
# ---------------------------------------------------------------------------

class TestRateLimiter:
    def setup_method(self):
        _failed_attempts.clear()

    def test_allows_attempts_below_limit(self):
        ip = "10.0.0.1"
        for _ in range(_MAX_FAILED_ATTEMPTS - 1):
            _record_failed_attempt(ip)
        # Should not raise
        _check_rate_limit(ip)

    def test_blocks_after_max_attempts(self):
        ip = "10.0.0.2"
        for _ in range(_MAX_FAILED_ATTEMPTS):
            _record_failed_attempt(ip)
        with pytest.raises(HTTPException) as exc_info:
            _check_rate_limit(ip)
        assert exc_info.value.status_code == 429

    def test_reset_clears_attempts(self):
        ip = "10.0.0.3"
        for _ in range(_MAX_FAILED_ATTEMPTS):
            _record_failed_attempt(ip)
        _reset_attempts(ip)
        # Should not raise after reset
        _check_rate_limit(ip)

    def test_expired_attempts_do_not_count(self):
        ip = "10.0.0.4"
        old_time = time.monotonic() - _RATE_WINDOW_SECONDS - 1
        _failed_attempts[ip] = [old_time] * _MAX_FAILED_ATTEMPTS
        # All attempts are outside the window — should not block
        _check_rate_limit(ip)

    def test_login_records_failed_attempt_on_wrong_password(self):
        ip = "10.0.0.5"
        user = _make_user(password="correct")
        container = _make_container(user=user)
        try:
            login(LoginRequest(login="admin", password="wrong"), _make_request(ip), container)
        except HTTPException:
            pass
        assert len(_failed_attempts[ip]) == 1

    def test_login_resets_attempts_on_success(self):
        ip = "10.0.0.6"
        for _ in range(3):
            _record_failed_attempt(ip)
        user = _make_user(password="1234")
        container = _make_container(user=user)
        login(LoginRequest(login="admin", password="1234"), _make_request(ip), container)
        assert ip not in _failed_attempts

    def test_login_raises_429_when_rate_limited(self):
        ip = "10.0.0.7"
        for _ in range(_MAX_FAILED_ATTEMPTS):
            _record_failed_attempt(ip)
        user = _make_user(password="1234")
        container = _make_container(user=user)
        with pytest.raises(HTTPException) as exc_info:
            login(LoginRequest(login="admin", password="1234"), _make_request(ip), container)
        assert exc_info.value.status_code == 429

    def test_different_ips_are_tracked_independently(self):
        ip1, ip2 = "10.0.1.1", "10.0.1.2"
        for _ in range(_MAX_FAILED_ATTEMPTS):
            _record_failed_attempt(ip1)
        # ip2 should not be affected
        _check_rate_limit(ip2)  # Should not raise
        with pytest.raises(HTTPException):
            _check_rate_limit(ip1)


# ---------------------------------------------------------------------------
# Phase 6: Default password warning
# ---------------------------------------------------------------------------

class TestWarnDefaultPassword:
    def setup_method(self):
        _failed_attempts.clear()

    def test_warn_flag_true_when_password_never_changed(self):
        """Admin who has never changed password → warn_default_password=True."""
        user = _make_user(role="admin", password="1234", password_changed_at=None)
        container = _make_container(user=user)
        result = login(LoginRequest(login="admin", password="1234"), _make_request(), container)
        assert result.warn_default_password is True

    def test_warn_flag_false_after_password_changed(self):
        """Admin whose password was changed → warn_default_password=False."""
        changed_at = datetime.now(timezone.utc)
        user = _make_user(role="admin", password="newpassword", password_changed_at=changed_at)
        container = _make_container(user=user)
        result = login(LoginRequest(login="admin", password="newpassword"), _make_request(), container)
        assert result.warn_default_password is False

    def test_warn_flag_false_for_operator(self):
        """Operators never trigger the default-password warning."""
        user = _make_user(role="operator", password="1234", password_changed_at=None)
        container = _make_container(user=user)
        result = login(LoginRequest(login="op1", password="1234"), _make_request(), container)
        assert result.warn_default_password is False

    def test_login_response_has_warn_default_password_field(self):
        """LoginResponse always contains the warn_default_password field."""
        user = _make_user(password="pw")
        container = _make_container(user=user)
        result = login(LoginRequest(login="admin", password="pw"), _make_request(), container)
        assert hasattr(result, "warn_default_password")
        assert isinstance(result.warn_default_password, bool)
