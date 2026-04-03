"""Tests for app/api/routers/auth.py — login, logout, me endpoints.

Uses mocks to test auth router logic without a live server or DB.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.auth_utils import hash_password, create_access_token
from app.api.routers.auth import login, logout, me, available_permissions, AVAILABLE_PERMISSIONS
from app.api.schemas import LoginRequest, UserOut


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(user_id=1, login="admin", role="admin", is_active=True, permissions=None, password="1234"):
    return {
        "id": user_id,
        "login": login,
        "password": hash_password(password),
        "role": role,
        "permissions": permissions or [],
        "is_active": is_active,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def _make_container(user=None):
    container = MagicMock()
    container.user_db.find_by_login.return_value = user
    return container


# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------

class TestLogin:
    def test_valid_credentials(self):
        user = _make_user(password="1234")
        container = _make_container(user=user)
        body = LoginRequest(login="admin", password="1234")

        result = login(body, container)

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
            login(body, container)
        assert exc_info.value.status_code == 401

    def test_user_not_found(self):
        container = _make_container(user=None)
        body = LoginRequest(login="nobody", password="1234")

        with pytest.raises(HTTPException) as exc_info:
            login(body, container)
        assert exc_info.value.status_code == 401

    def test_inactive_user(self):
        user = _make_user(is_active=False, password="1234")
        container = _make_container(user=user)
        body = LoginRequest(login="admin", password="1234")

        with pytest.raises(HTTPException) as exc_info:
            login(body, container)
        assert exc_info.value.status_code == 401
        assert "деактивирован" in exc_info.value.detail

    def test_login_response_excludes_password(self):
        user = _make_user(password="1234")
        container = _make_container(user=user)
        body = LoginRequest(login="admin", password="1234")

        result = login(body, container)
        # UserOut should not have a password field
        assert not hasattr(result.user, "password")


# ---------------------------------------------------------------------------
# POST /api/auth/logout
# ---------------------------------------------------------------------------

class TestLogout:
    def test_returns_ok(self):
        result = logout()
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
        # Pydantic model should not expose password
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
# These tests verify the exact response structure the JS frontend relies on.
# ---------------------------------------------------------------------------

class TestLoginResponseContract:
    """Verify that POST /api/auth/login returns the shape the frontend requires.

    The frontend (api.js) destructures: { access_token, user }
    and stores user in state.currentUser = { id, login, role, permissions }.
    """

    def test_login_response_has_access_token(self):
        user = _make_user(password="secret")
        result = login(LoginRequest(login="admin", password="secret"), _make_container(user=user))
        assert isinstance(result.access_token, str)
        assert len(result.access_token) > 0

    def test_login_response_user_has_required_frontend_fields(self):
        user = _make_user(user_id=42, login="op1", role="operator",
                          permissions=["tab:obs", "tab:journal"], password="pw")
        result = login(LoginRequest(login="op1", password="pw"), _make_container(user=user))
        u = result.user
        assert u.id == 42
        assert u.login == "op1"
        assert u.role == "operator"
        assert u.permissions == ["tab:obs", "tab:journal"]

    def test_login_response_admin_has_empty_permissions_array(self):
        """Admin permissions array is empty by convention; admin access is implied by role."""
        user = _make_user(role="admin", permissions=[], password="pw")
        result = login(LoginRequest(login="admin", password="pw"), _make_container(user=user))
        assert result.user.permissions == []
        assert result.user.role == "admin"


class TestMeResponseContract:
    """Verify that GET /api/auth/me returns the shape the frontend requires on startup."""

    def test_me_returns_is_active(self):
        user = _make_user(is_active=True)
        result = me(current_user=user)
        assert result.is_active is True

    def test_me_returns_permissions_list(self):
        user = _make_user(role="operator", permissions=["tab:obs", "tab:lists"])
        result = me(current_user=user)
        assert "tab:obs" in result.permissions
        assert "tab:lists" in result.permissions
