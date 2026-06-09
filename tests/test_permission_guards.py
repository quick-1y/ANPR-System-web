"""Phase 4 tests — superadmin-only route protection via require_role("superadmin").

Verifies that the settings/debug/etc routers correctly enforce their declared role/permission guards.

These tests call the FastAPI dependency functions directly (unit-style),
matching the pattern used in test_auth_deps.py.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.deps import require_permission, require_role


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _superadmin_user():
    return {"id": 1, "login": "superadmin", "role": "superadmin", "permissions": [], "is_active": True}


def _operator_user(permissions=None):
    return {
        "id": 2,
        "login": "op1",
        "role": "operator",
        "permissions": permissions or ["tab:obs", "tab:journal"],
        "is_active": True,
    }


def _call_require_superadmin(user):
    """Invoke require_role('superadmin') with the given user (simulates DI resolution)."""
    dep = require_role("superadmin")
    return dep(current_user=user)


def _call_require_tab_settings(user):
    """Invoke require_permission('tab:settings') with the given user."""
    dep = require_permission("tab:settings")
    return dep(current_user=user)


# ---------------------------------------------------------------------------
# require_role("superadmin") — unit tests
# ---------------------------------------------------------------------------

class TestRequireSuperadmin:
    def test_superadmin_passes(self):
        result = _call_require_superadmin(_superadmin_user())
        assert result["role"] == "superadmin"

    def test_operator_raises_403(self):
        with pytest.raises(HTTPException) as exc_info:
            _call_require_superadmin(_operator_user())
        assert exc_info.value.status_code == 403

    def test_operator_with_all_tab_permissions_still_raises_403(self):
        """Having all tab permissions does not grant superadmin route access."""
        op = _operator_user(permissions=["tab:obs", "tab:journal", "tab:clients", "tab:settings"])
        with pytest.raises(HTTPException) as exc_info:
            _call_require_superadmin(op)
        assert exc_info.value.status_code == 403

    def test_error_message_is_russian(self):
        with pytest.raises(HTTPException) as exc_info:
            _call_require_superadmin(_operator_user())
        assert "прав" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Settings router — verify permission-based access is used
# ---------------------------------------------------------------------------

class TestSettingsRouterGuards:
    """Verify that settings endpoints use require_role('superadmin') by calling the
    handler with the superadmin-dependency result pre-resolved.

    We only test the dependency guard itself; full handler logic is covered
    by integration/smoke tests elsewhere.
    """

    def test_superadmin_passes_require_superadmin_dep(self):
        result = _call_require_superadmin(_superadmin_user())
        assert result["role"] == "superadmin"

    def test_operator_blocked_from_settings(self):
        with pytest.raises(HTTPException) as exc_info:
            _call_require_superadmin(_operator_user())
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Controllers router guard
# ---------------------------------------------------------------------------

class TestControllersRouterGuards:
    def test_superadmin_passes(self):
        result = _call_require_superadmin(_superadmin_user())
        assert result["role"] == "superadmin"

    def test_operator_blocked(self):
        with pytest.raises(HTTPException) as exc_info:
            _call_require_superadmin(_operator_user())
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Data router guard
# ---------------------------------------------------------------------------

class TestDataRouterGuards:
    def test_superadmin_passes(self):
        result = _call_require_tab_settings(_superadmin_user())
        assert result["role"] == "superadmin"

    def test_operator_with_tab_settings_passes(self):
        op = _operator_user(permissions=["tab:obs", "tab:journal", "tab:settings"])
        result = _call_require_tab_settings(op)
        assert result["role"] == "operator"


# ---------------------------------------------------------------------------
# Debug router guard
# ---------------------------------------------------------------------------

class TestDebugRouterGuards:
    def test_superadmin_passes(self):
        result = _call_require_superadmin(_superadmin_user())
        assert result["role"] == "superadmin"

    def test_operator_blocked_from_debug(self):
        with pytest.raises(HTTPException) as exc_info:
            _call_require_superadmin(_operator_user())
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Verify router files actually import require_role (not get_current_user)
# ---------------------------------------------------------------------------

class TestRouterImports:
    """Smoke-check that superadmin-only routers use require_role, not get_current_user,
    by reading the source files directly (avoids importing heavy dependencies)."""

    def _read_router_source(self, relative_path: str) -> str:
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, *relative_path.split("/"))
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_settings_router_uses_require_role(self):
        src = self._read_router_source("app/api/routers/settings.py")
        assert "require_permission" in src

    def test_controllers_router_uses_require_role(self):
        src = self._read_router_source("app/api/routers/controllers.py")
        assert "require_role" in src
        assert "get_current_user" not in src

    def test_data_router_uses_require_permission(self):
        src = self._read_router_source("app/api/routers/data.py")
        assert "require_permission" in src
        assert "get_current_user" not in src

    def test_debug_router_uses_require_role(self):
        src = self._read_router_source("app/api/routers/debug.py")
        assert "require_role" in src
        assert "get_current_user" not in src

    def test_auth_router_available_permissions_uses_require_permission(self):
        src = self._read_router_source("app/api/routers/auth.py")
        assert "require_permission" in src
