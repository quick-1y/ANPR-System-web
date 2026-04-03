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
    def test_returns_permission_list(self):
        user = _make_user()
        result = available_permissions(current_user=user)
        assert result == AVAILABLE_PERMISSIONS
        assert "tab:obs" in result
        assert "tab:settings" in result
