"""Tests for apps/api/deps.py — get_current_user, require_role, require_permission.

Uses mocks to avoid a live FastAPI/PostgreSQL instance.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from apps.api.auth_utils import create_access_token
from apps.api.deps import get_current_user, require_role, require_permission, _extract_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(*, auth_header: str = "", query_params: dict | None = None, headers: dict | None = None):
    """Build a mock Request object."""
    req = MagicMock()
    _headers = {}
    if auth_header:
        _headers["Authorization"] = auth_header
    if headers:
        _headers.update(headers)
    req.headers = _headers
    req.query_params = query_params or {}
    return req


def _make_user(user_id=1, login="superadmin", role="superadmin", is_active=True, permissions=None):
    return {
        "id": user_id,
        "login": login,
        "password": "$2b$12$fakehash",
        "role": role,
        "permissions": permissions or [],
        "is_active": is_active,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "password_changed_at": None,
    }


def _make_container(user=None):
    container = MagicMock()
    container.user_db.find_by_id.return_value = user
    container.user_db.find_by_login.return_value = user
    return container


# ---------------------------------------------------------------------------
# _extract_token
# ---------------------------------------------------------------------------

class TestExtractToken:
    def test_bearer_header(self):
        req = _make_request(auth_header="Bearer abc123")
        assert _extract_token(req) == "abc123"

    def test_query_param(self):
        req = _make_request(query_params={"token": "tok123"})
        assert _extract_token(req) == "tok123"

    def test_bearer_takes_precedence(self):
        req = _make_request(auth_header="Bearer header_tok", query_params={"token": "query_tok"})
        assert _extract_token(req) == "header_tok"

    def test_no_token_returns_none(self):
        req = _make_request()
        assert _extract_token(req) is None

    def test_empty_bearer(self):
        req = _make_request(auth_header="Bearer ")
        assert _extract_token(req) is None


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------

class TestGetCurrentUser:
    def test_valid_jwt_returns_user(self):
        user = _make_user(user_id=5)
        token = create_access_token(user_id=5, role="superadmin")
        request = _make_request(auth_header=f"Bearer {token}")
        container = _make_container(user=user)

        result = get_current_user(request, container)
        assert result["id"] == 5
        container.user_db.find_by_id.assert_called_once_with(5)

    def test_no_token_raises_401(self):
        request = _make_request()
        container = _make_container()

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(request, container)
        assert exc_info.value.status_code == 401

    def test_expired_token_raises_401(self):
        token = create_access_token(user_id=1, role="superadmin", exp_minutes=-1)
        request = _make_request(auth_header=f"Bearer {token}")
        container = _make_container()

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(request, container)
        assert exc_info.value.status_code == 401
        assert "истёк" in exc_info.value.detail

    def test_invalid_token_raises_401(self):
        request = _make_request(auth_header="Bearer garbage")
        container = _make_container()

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(request, container)
        assert exc_info.value.status_code == 401

    def test_user_not_found_raises_401(self):
        token = create_access_token(user_id=999, role="superadmin")
        request = _make_request(auth_header=f"Bearer {token}")
        container = _make_container(user=None)

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(request, container)
        assert exc_info.value.status_code == 401

    def test_inactive_user_raises_401(self):
        user = _make_user(user_id=3, is_active=False)
        token = create_access_token(user_id=3, role="superadmin")
        request = _make_request(auth_header=f"Bearer {token}")
        container = _make_container(user=user)

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(request, container)
        assert exc_info.value.status_code == 401
        assert "деактивирована" in exc_info.value.detail

    def test_query_param_token(self):
        user = _make_user(user_id=10)
        token = create_access_token(user_id=10, role="operator")
        request = _make_request(query_params={"token": token})
        container = _make_container(user=user)

        result = get_current_user(request, container)
        assert result["id"] == 10


# ---------------------------------------------------------------------------
# require_role
# ---------------------------------------------------------------------------

class TestRequireRole:
    def test_matching_role_passes(self):
        user = _make_user(role="superadmin")
        dep = require_role("superadmin")
        result = dep(current_user=user)
        assert result["role"] == "superadmin"

    def test_wrong_role_raises_403(self):
        user = _make_user(role="operator")
        dep = require_role("superadmin")
        with pytest.raises(HTTPException) as exc_info:
            dep(current_user=user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# require_permission
# ---------------------------------------------------------------------------

class TestRequirePermission:
    def test_superadmin_bypasses_permission_check(self):
        user = _make_user(role="superadmin", permissions=[])
        dep = require_permission("tab:settings")
        result = dep(current_user=user)
        assert result["role"] == "superadmin"

    def test_operator_with_permission_passes(self):
        user = _make_user(role="operator", permissions=["tab:obs", "tab:journal"])
        dep = require_permission("tab:obs")
        result = dep(current_user=user)
        assert result["id"] == 1

    def test_operator_without_permission_raises_403(self):
        user = _make_user(role="operator", permissions=["tab:obs"])
        dep = require_permission("tab:settings")
        with pytest.raises(HTTPException) as exc_info:
            dep(current_user=user)
        assert exc_info.value.status_code == 403
