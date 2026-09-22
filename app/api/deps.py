from __future__ import annotations

from typing import Any, Dict

import jwt
from fastapi import Depends, HTTPException, Request

from app.api.auth_utils import decode_access_token
from app.api.container import AppContainer
from app.api.superadmin import is_superadmin_id, synthetic_superadmin

from common.logging import get_logger

logger = get_logger(__name__)


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


def get_current_user(request: Request, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    """Extract and validate JWT from the request, return user dict.

    Token is read from:
      1. ``Authorization: Bearer <token>`` header
      2. ``?token=<jwt>`` query parameter (for SSE / MJPEG streams)
    """
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Не предоставлен токен авторизации")

    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Токен авторизации истёк")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Недействительный токен авторизации")

    user_id = int(payload.get("sub", -1))
    if user_id < 0:
        raise HTTPException(status_code=401, detail="Недействительный токен авторизации")

    if is_superadmin_id(user_id):
        return synthetic_superadmin()

    user = container.user_db.find_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    if not user.get("is_active"):
        raise HTTPException(status_code=401, detail="Учётная запись деактивирована")

    return user


def require_role(role: str):
    """Return a dependency that checks the current user has the given role."""

    def _check(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        if current_user.get("role") != role:
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return current_user

    return _check


def require_permission(permission: str):
    """Return a dependency that checks the current user has a specific permission key.

    Superadmins implicitly have all permissions.
    """

    def _check(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        if current_user.get("role") == "superadmin":
            return current_user
        user_permissions = current_user.get("permissions", [])
        if permission not in user_permissions:
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return current_user

    return _check


# ── Access levels (roadmap 4.11) ─────────────────────────────────────────
#
# Endpoints declare the level of protection the DATA needs, not a tab or a
# permission key. `require_access` is the single adapter from a level to the
# mechanism that enforces it today; the access model itself is redesigned in
# roadmap phase 11, and only this mapping will change then.
#
#   public         no authentication (login screen material only)
#   authenticated  any signed-in user
#   self           any signed-in user, restricted to their own record by the handler
#   admin-config   instance configuration      (transitional: `tab:settings`)
#   admin-data     export, backup, retention   (transitional: `tab:settings`)
#   admin-users    user management             (transitional: `tab:settings`)
#   admin-debug    developer tooling           (superadmin)
#   admin-devices  controllers                 (superadmin)

ACCESS_LEVELS = (
    "public", "authenticated", "self",
    "admin-config", "admin-data", "admin-users", "admin-debug", "admin-devices",
)


def _no_authentication() -> None:
    return None


def require_access(level: str):
    """Return the FastAPI dependency that enforces access *level*."""
    if level == "public":
        return _no_authentication
    if level in ("authenticated", "self"):
        return get_current_user
    if level in ("admin-config", "admin-data", "admin-users"):
        return require_permission("tab:settings")
    if level in ("admin-debug", "admin-devices"):
        return require_role("superadmin")
    raise ValueError(f"Неизвестный уровень доступа {level!r}; допустимо: {', '.join(ACCESS_LEVELS)}")


def _extract_token(request: Request) -> str | None:
    """Extract JWT from Authorization header or query parameter."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        bearer_value = auth_header[7:].strip()
        if bearer_value:
            return bearer_value

    token = request.query_params.get("token", "").strip()
    if token:
        return token

    return None
