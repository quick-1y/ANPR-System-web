from __future__ import annotations

from typing import Any, Dict

import jwt
from fastapi import Depends, HTTPException, Request

from app.api.auth_utils import decode_access_token
from app.api.container import AppContainer

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

    user_id = int(payload.get("sub", 0))
    if not user_id:
        raise HTTPException(status_code=401, detail="Недействительный токен авторизации")

    user = container.user_db.find_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    if not user.get("is_active"):
        raise HTTPException(status_code=401, detail="Учётная запись деактивирована")

    return user



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


def require_any_permission(*permissions: str):
    """Return a dependency that checks user has at least one permission.

    Superadmins implicitly pass all checks.
    """

    required = tuple(p for p in permissions if p)

    def _check(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        if current_user.get("role") == "superadmin":
            return current_user
        user_permissions = set(current_user.get("permissions", []))
        if not any(permission in user_permissions for permission in required):
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return current_user

    return _check
