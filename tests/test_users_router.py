"""Tests for app/api/routers/users.py — user CRUD endpoints (Phase 5).

Uses mocks — no live DB or server required.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.auth_utils import hash_password
from app.api.routers.users import (
    list_users,
    create_user,
    get_user,
    update_user,
    change_password,
    deactivate_user,
)
from app.api.schemas import UserCreate, UserUpdate, UserPasswordChange


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(
    user_id=1,
    login="superadmin",
    role="superadmin",
    is_active=True,
    permissions=None,
    password="1234",
):
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


def _make_container(
    users=None,
    find_by_id=None,
    find_by_login=None,
    active_admin_count=2,
):
    container = MagicMock()
    _users = users or []

    container.user_db.list_all.return_value = _users
    container.user_db.find_by_id.side_effect = (
        find_by_id
        if find_by_id is not None
        else lambda uid: next((u for u in _users if u["id"] == uid), None)
    )
    container.user_db.find_by_login.side_effect = (
        find_by_login
        if find_by_login is not None
        else lambda login: next((u for u in _users if u["login"] == login), None)
    )
    container.user_db.count_active_superadmins.return_value = active_admin_count
    container.user_db.create_user.side_effect = (
        lambda login, pw, role, perms: _make_user(user_id=99, login=login, role=role, permissions=perms)
    )
    container.user_db.update_user.return_value = _make_user(user_id=1)
    container.user_db.update_password.return_value = True
    container.user_db.deactivate.return_value = True
    return container


_SUPERADMIN = _make_user(user_id=1, login="superadmin", role="superadmin")
_OPERATOR = _make_user(user_id=2, login="op1", role="operator", permissions=["tab:obs"])


# ---------------------------------------------------------------------------
# GET /api/users
# ---------------------------------------------------------------------------

class TestListUsers:
    def test_superadmin_gets_all_users(self):
        container = _make_container(users=[_SUPERADMIN, _OPERATOR])
        result = list_users(current_user=_SUPERADMIN, container=container)
        assert len(result) == 2
        logins = {u.login for u in result}
        assert logins == {"superadmin", "op1"}

    def test_passwords_not_exposed(self):
        container = _make_container(users=[_SUPERADMIN])
        result = list_users(current_user=_SUPERADMIN, container=container)
        for user_out in result:
            assert not hasattr(user_out, "password") or not getattr(user_out, "password", None)


# ---------------------------------------------------------------------------
# POST /api/users
# ---------------------------------------------------------------------------

class TestCreateUser:
    def test_creates_new_user(self):
        container = _make_container(users=[_SUPERADMIN])
        body = UserCreate(login="newop", password="pass1234", role="operator", permissions=["tab:obs"])
        result = create_user(body=body, current_user=_SUPERADMIN, container=container)
        assert result.login == "newop"
        assert result.role == "operator"

    def test_duplicate_login_returns_409(self):
        container = _make_container(users=[_SUPERADMIN, _OPERATOR])
        body = UserCreate(login="op1", password="pass1234", role="operator")
        with pytest.raises(HTTPException) as exc:
            create_user(body=body, current_user=_SUPERADMIN, container=container)
        assert exc.value.status_code == 409

    def test_short_password_rejected_by_schema(self):
        with pytest.raises(Exception):
            UserCreate(login="x", password="ab")

    def test_invalid_role_rejected_by_schema(self):
        with pytest.raises(Exception):
            UserCreate(login="x", password="1234", role="superuser")


# ---------------------------------------------------------------------------
# GET /api/users/{user_id}
# ---------------------------------------------------------------------------

class TestGetUser:
    def test_returns_user_by_id(self):
        container = _make_container(users=[_SUPERADMIN, _OPERATOR])
        result = get_user(user_id=2, current_user=_SUPERADMIN, container=container)
        assert result.login == "op1"

    def test_not_found_returns_404(self):
        container = _make_container(users=[_SUPERADMIN])
        with pytest.raises(HTTPException) as exc:
            get_user(user_id=999, current_user=_SUPERADMIN, container=container)
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/users/{user_id}
# ---------------------------------------------------------------------------

class TestUpdateUser:
    def test_update_role(self):
        users = [_make_user(user_id=1, role="superadmin"), _make_user(user_id=2, login="op1", role="operator")]
        container = _make_container(users=users)
        container.user_db.update_user.return_value = {**users[1], "role": "superadmin"}
        body = UserUpdate(role="superadmin")
        result = update_user(user_id=2, body=body, current_user=users[0], container=container)
        assert result.role == "superadmin"

    def test_update_permissions(self):
        users = [_SUPERADMIN, _OPERATOR]
        container = _make_container(users=users)
        container.user_db.update_user.return_value = {**_OPERATOR, "permissions": ["tab:obs", "tab:journal"]}
        body = UserUpdate(permissions=["tab:obs", "tab:journal"])
        result = update_user(user_id=2, body=body, current_user=_SUPERADMIN, container=container)
        assert "tab:journal" in result.permissions

    def test_not_found_returns_404(self):
        container = _make_container(users=[_SUPERADMIN])
        body = UserUpdate(role="operator")
        with pytest.raises(HTTPException) as exc:
            update_user(user_id=999, body=body, current_user=_SUPERADMIN, container=container)
        assert exc.value.status_code == 404

    def test_self_deactivation_blocked(self):
        container = _make_container(users=[_SUPERADMIN])
        body = UserUpdate(is_active=False)
        with pytest.raises(HTTPException) as exc:
            update_user(user_id=1, body=body, current_user=_SUPERADMIN, container=container)
        assert exc.value.status_code == 400

    def test_last_superadmin_role_removal_blocked(self):
        """Removing superadmin role from yourself when you're the only active superadmin must fail."""
        container = _make_container(users=[_SUPERADMIN], active_admin_count=1)
        body = UserUpdate(role="operator")
        with pytest.raises(HTTPException) as exc:
            update_user(user_id=1, body=body, current_user=_SUPERADMIN, container=container)
        assert exc.value.status_code == 400

    def test_superadmin_role_removal_allowed_when_multiple_superadmins(self):
        """Can remove superadmin role from self when there are other active superadmins."""
        admin2 = _make_user(user_id=3, login="superadmin2", role="superadmin")
        users = [_SUPERADMIN, admin2]
        container = _make_container(users=users, active_admin_count=2)
        container.user_db.update_user.return_value = {**_SUPERADMIN, "role": "operator"}
        body = UserUpdate(role="operator")
        result = update_user(user_id=1, body=body, current_user=_SUPERADMIN, container=container)
        assert result.role == "operator"


# ---------------------------------------------------------------------------
# PUT /api/users/{user_id}/password
# ---------------------------------------------------------------------------

class TestChangePassword:
    def test_superadmin_can_change_any_password(self):
        container = _make_container(users=[_SUPERADMIN, _OPERATOR])
        body = UserPasswordChange(new_password="newpass1")
        result = change_password(user_id=2, body=body, current_user=_SUPERADMIN, container=container)
        assert result["detail"] == "ok"
        container.user_db.update_password.assert_called_once()

    def test_user_can_change_own_password(self):
        container = _make_container(users=[_SUPERADMIN, _OPERATOR])
        body = UserPasswordChange(new_password="newpass1")
        result = change_password(user_id=2, body=body, current_user=_OPERATOR, container=container)
        assert result["detail"] == "ok"

    def test_operator_cannot_change_others_password(self):
        container = _make_container(users=[_SUPERADMIN, _OPERATOR])
        body = UserPasswordChange(new_password="newpass1")
        with pytest.raises(HTTPException) as exc:
            change_password(user_id=1, body=body, current_user=_OPERATOR, container=container)
        assert exc.value.status_code == 403

    def test_not_found_returns_404(self):
        container = _make_container(users=[_SUPERADMIN])
        body = UserPasswordChange(new_password="newpass1")
        with pytest.raises(HTTPException) as exc:
            change_password(user_id=999, body=body, current_user=_SUPERADMIN, container=container)
        assert exc.value.status_code == 404

    def test_short_password_rejected_by_schema(self):
        with pytest.raises(Exception):
            UserPasswordChange(new_password="ab")


# ---------------------------------------------------------------------------
# DELETE /api/users/{user_id}
# ---------------------------------------------------------------------------

class TestDeactivateUser:
    def test_superadmin_can_deactivate_other(self):
        container = _make_container(users=[_SUPERADMIN, _OPERATOR])
        # Should not raise
        deactivate_user(user_id=2, current_user=_SUPERADMIN, container=container)
        container.user_db.deactivate.assert_called_once_with(2)

    def test_self_deactivation_blocked(self):
        container = _make_container(users=[_SUPERADMIN])
        with pytest.raises(HTTPException) as exc:
            deactivate_user(user_id=1, current_user=_SUPERADMIN, container=container)
        assert exc.value.status_code == 400

    def test_not_found_returns_404(self):
        container = _make_container(users=[_SUPERADMIN])
        with pytest.raises(HTTPException) as exc:
            deactivate_user(user_id=999, current_user=_SUPERADMIN, container=container)
        assert exc.value.status_code == 404
