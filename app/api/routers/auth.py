from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth_utils import create_access_token, verify_password
from app.api.container import AppContainer
from app.api.deps import get_container, get_current_user, require_role
from app.api.schemas import LoginRequest, LoginResponse, UserOut

from common.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Available permission keys with metadata (for admin UI — Phase 5 user management).
AVAILABLE_PERMISSIONS = [
    {"key": "tab:obs", "label": "Наблюдение", "group": "tabs"},
    {"key": "tab:journal", "label": "Журнал", "group": "tabs"},
    {"key": "tab:lists", "label": "Списки", "group": "tabs"},
    {"key": "tab:settings", "label": "Настройки", "group": "tabs"},
]


@router.post("/api/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, container: AppContainer = Depends(get_container)):
    """Authenticate with login + password, receive a JWT."""
    user = container.user_db.find_by_login(body.login)
    if not user:
        logger.info("Неудачная попытка входа: пользователь '%s' не найден", body.login)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    if not user.get("is_active"):
        logger.info("Неудачная попытка входа: пользователь '%s' деактивирован", body.login)
        raise HTTPException(status_code=401, detail="Учётная запись деактивирована")

    if not verify_password(body.password, user["password"]):
        logger.info("Неудачная попытка входа: неверный пароль для '%s'", body.login)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    token = create_access_token(user_id=user["id"], role=user["role"])
    logger.info("Успешный вход: '%s' (id=%s)", user["login"], user["id"])

    return LoginResponse(
        access_token=token,
        user=UserOut(**{k: v for k, v in user.items() if k != "password"}),
    )


@router.post("/api/auth/logout")
def logout():
    """Logout (client-side token removal). Server acknowledges."""
    return {"detail": "ok"}


@router.get("/api/auth/me", response_model=UserOut)
def me(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Return the currently authenticated user."""
    return UserOut(**{k: v for k, v in current_user.items() if k != "password"})


@router.get("/api/permissions/available")
def available_permissions(current_user: Dict[str, Any] = Depends(require_role("admin"))):
    """Return known permission keys with labels (admin-only, for user management UI)."""
    return AVAILABLE_PERMISSIONS
