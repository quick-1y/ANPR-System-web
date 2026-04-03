from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth_utils import hash_password
from app.api.container import AppContainer
from app.api.deps import get_container, get_current_user, require_role
from app.api.schemas import UserCreate, UserOut, UserPasswordChange, UserUpdate

from common.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/api/users", response_model=List[UserOut])
def list_users(
    current_user: Dict[str, Any] = Depends(require_role("admin")),
    container: AppContainer = Depends(get_container),
):
    """Return all users (admin only)."""
    users = container.user_db.list_all()
    return [UserOut(**{k: v for k, v in u.items() if k != "password"}) for u in users]


@router.post("/api/users", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate,
    current_user: Dict[str, Any] = Depends(require_role("admin")),
    container: AppContainer = Depends(get_container),
):
    """Create a new user (admin only)."""
    if container.user_db.find_by_login(body.login):
        raise HTTPException(
            status_code=409,
            detail="Пользователь с таким логином уже существует",
        )
    pw_hash = hash_password(body.password)
    user = container.user_db.create_user(body.login, pw_hash, body.role, body.permissions)
    logger.info(
        "Создан пользователь: '%s' (role=%s, admin: %s)",
        body.login,
        body.role,
        current_user["login"],
    )
    return UserOut(**{k: v for k, v in user.items() if k != "password"})


@router.get("/api/users/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    current_user: Dict[str, Any] = Depends(require_role("admin")),
    container: AppContainer = Depends(get_container),
):
    """Get a single user by ID (admin only)."""
    user = container.user_db.find_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return UserOut(**{k: v for k, v in user.items() if k != "password"})


@router.put("/api/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    current_user: Dict[str, Any] = Depends(require_role("admin")),
    container: AppContainer = Depends(get_container),
):
    """Update user role, permissions, or active state (admin only).

    Admin self-lock rules:
    - Cannot remove admin role from yourself if you are the last active admin.
    - Cannot deactivate yourself.
    """
    user = container.user_db.find_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user_id == current_user["id"]:
        if body.is_active is False:
            raise HTTPException(
                status_code=400,
                detail="Невозможно деактивировать собственную учётную запись",
            )
        if body.role is not None and body.role != "admin" and current_user["role"] == "admin":
            if container.user_db.count_active_admins() <= 1:
                raise HTTPException(
                    status_code=400,
                    detail="Невозможно снять роль администратора: вы единственный активный администратор",
                )

    updated = container.user_db.update_user(
        user_id,
        role=body.role,
        permissions=body.permissions,
        is_active=body.is_active,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    logger.info(
        "Обновлён пользователь id=%s (admin: %s)",
        user_id,
        current_user["login"],
    )
    return UserOut(**{k: v for k, v in updated.items() if k != "password"})


@router.put("/api/users/{user_id}/password")
def change_password(
    user_id: int,
    body: UserPasswordChange,
    current_user: Dict[str, Any] = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
):
    """Change user password.

    Admins can change any user's password.
    Regular users can only change their own password.
    """
    if current_user["role"] != "admin" and user_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    user = container.user_db.find_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    pw_hash = hash_password(body.new_password)
    success = container.user_db.update_password(user_id, pw_hash)
    if not success:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    logger.info(
        "Сменён пароль для пользователя id=%s (исполнитель: %s)",
        user_id,
        current_user["login"],
    )
    return {"detail": "ok"}


@router.delete("/api/users/{user_id}", status_code=204)
def deactivate_user(
    user_id: int,
    current_user: Dict[str, Any] = Depends(require_role("admin")),
    container: AppContainer = Depends(get_container),
):
    """Deactivate a user (soft-delete). Admin cannot deactivate themselves."""
    if user_id == current_user["id"]:
        raise HTTPException(
            status_code=400,
            detail="Невозможно деактивировать собственную учётную запись",
        )

    user = container.user_db.find_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    container.user_db.deactivate(user_id)
    logger.info(
        "Деактивирован пользователь id=%s (admin: %s)",
        user_id,
        current_user["login"],
    )
