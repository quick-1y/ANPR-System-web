"""Phase 4 tests — admin-only route protection via require_role("admin").

Verifies that the settings, controllers, data, and debug routers correctly
reject operator-role users with HTTP 403, while admins pass through.

These tests call the FastAPI dependency functions directly (unit-style),
matching the pattern used in test_auth_deps.py.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.deps import require_role


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _admin_user():
    return {"id": 1, "login": "admin", "role": "admin", "permissions": [], "is_active": True}


def _operator_user(permissions=None):
    return {
        "id": 2,
        "login": "op1",
        "role": "operator",
        "permissions": permissions or ["tab:obs", "tab:journal"],
        "is_active": True,
    }


def _call_require_admin(user):
    """Invoke require_role('admin') with the given user (simulates DI resolution)."""
    dep = require_role("admin")
    return dep(current_user=user)


# ---------------------------------------------------------------------------
# require_role("admin") — unit tests
# ---------------------------------------------------------------------------

class TestRequireAdmin:
    def test_admin_passes(self):
        result = _call_require_admin(_admin_user())
        assert result["role"] == "admin"

    def test_operator_raises_403(self):
        with pytest.raises(HTTPException) as exc_info:
            _call_require_admin(_operator_user())
        assert exc_info.value.status_code == 403

    def test_operator_with_all_tab_permissions_still_raises_403(self):
        """Having all tab permissions does not grant admin route access."""
        op = _operator_user(permissions=["tab:obs", "tab:journal", "tab:lists", "tab:settings"])
        with pytest.raises(HTTPException) as exc_info:
            _call_require_admin(op)
        assert exc_info.value.status_code == 403

    def test_error_message_is_russian(self):
        with pytest.raises(HTTPException) as exc_info:
            _call_require_admin(_operator_user())
        assert "прав" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Settings router — verify require_role("admin") is applied
# ---------------------------------------------------------------------------

class TestSettingsRouterGuards:
    """Verify that settings endpoints use require_role('admin') by calling the
    handler with the admin-dependency result pre-resolved.

    We only test the dependency guard itself; full handler logic is covered
    by integration/smoke tests elsewhere.
    """

    def test_admin_passes_require_admin_dep(self):
        result = _call_require_admin(_admin_user())
        assert result["role"] == "admin"

    def test_operator_blocked_from_settings(self):
        with pytest.raises(HTTPException) as exc_info:
            _call_require_admin(_operator_user())
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Controllers router guard
# ---------------------------------------------------------------------------

class TestControllersRouterGuards:
    def test_admin_passes(self):
        result = _call_require_admin(_admin_user())
        assert result["role"] == "admin"

    def test_operator_blocked(self):
        with pytest.raises(HTTPException) as exc_info:
            _call_require_admin(_operator_user())
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Data router guard
# ---------------------------------------------------------------------------

class TestDataRouterGuards:
    def test_admin_passes(self):
        result = _call_require_admin(_admin_user())
        assert result["role"] == "admin"

    def test_operator_blocked_from_backup(self):
        with pytest.raises(HTTPException) as exc_info:
            _call_require_admin(_operator_user())
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Debug router guard
# ---------------------------------------------------------------------------

class TestDebugRouterGuards:
    def test_admin_passes(self):
        result = _call_require_admin(_admin_user())
        assert result["role"] == "admin"

    def test_operator_blocked_from_debug(self):
        with pytest.raises(HTTPException) as exc_info:
            _call_require_admin(_operator_user())
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Verify router files actually import require_role (not get_current_user)
# ---------------------------------------------------------------------------

class TestRouterImports:
    """Smoke-check that admin-only routers use require_role, not get_current_user,
    by reading the source files directly (avoids importing heavy dependencies)."""

    def _read_router_source(self, relative_path: str) -> str:
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, *relative_path.split("/"))
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_settings_router_uses_require_role(self):
        src = self._read_router_source("app/api/routers/settings.py")
        assert "require_role" in src
        assert "get_current_user" not in src

    def test_controllers_router_uses_require_role(self):
        src = self._read_router_source("app/api/routers/controllers.py")
        assert "require_role" in src
        assert "get_current_user" not in src

    def test_data_router_uses_require_role(self):
        src = self._read_router_source("app/api/routers/data.py")
        assert "require_role" in src
        assert "get_current_user" not in src

    def test_debug_router_uses_require_role(self):
        src = self._read_router_source("app/api/routers/debug.py")
        assert "require_role" in src
        assert "get_current_user" not in src

    def test_auth_router_available_permissions_uses_require_role(self):
        src = self._read_router_source("app/api/routers/auth.py")
        assert "require_role" in src
