from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.auth_utils import create_access_token, verify_password
from app.api.container import AppContainer
from app.api.deps import get_container, get_current_user, require_permission
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

# ---------------------------------------------------------------------------
# Brute-force rate limiter (in-memory, per-IP, Phase 6)
# ---------------------------------------------------------------------------

_MAX_FAILED_ATTEMPTS = 5   # per window
_RATE_WINDOW_SECONDS = 60  # rolling window

_failed_attempts: dict[str, list[float]] = defaultdict(list)
_attempts_lock = Lock()


def _check_rate_limit(ip: str) -> None:
    """Raise HTTP 429 if the IP has exceeded the failed-login limit."""
    now = time.monotonic()
    with _attempts_lock:
        attempts = [t for t in _failed_attempts[ip] if now - t < _RATE_WINDOW_SECONDS]
        _failed_attempts[ip] = attempts
        if len(attempts) >= _MAX_FAILED_ATTEMPTS:
            raise HTTPException(
                status_code=429,
                detail="Слишком много попыток входа. Повторите через минуту.",
            )


def _record_failed_attempt(ip: str) -> None:
    now = time.monotonic()
    with _attempts_lock:
        _failed_attempts[ip].append(now)


def _reset_attempts(ip: str) -> None:
    with _attempts_lock:
        _failed_attempts.pop(ip, None)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/api/auth/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    request: Request,
    container: AppContainer = Depends(get_container),
):
    """Authenticate with login + password, receive a JWT."""
    ip = (request.client.host if request.client else "unknown") or "unknown"

    _check_rate_limit(ip)

    user = container.user_db.find_by_login(body.login)
    if not user:
        _record_failed_attempt(ip)
        logger.warning(
            "login_failed login='%s' ip='%s' reason='user_not_found'",
            body.login, ip,
        )
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    if not user.get("is_active"):
        _record_failed_attempt(ip)
        logger.warning(
            "login_failed login='%s' ip='%s' reason='inactive'",
            body.login, ip,
        )
        raise HTTPException(status_code=401, detail="Учётная запись деактивирована")

    if not verify_password(body.password, user["password"]):
        _record_failed_attempt(ip)
        logger.warning(
            "login_failed login='%s' ip='%s' reason='wrong_password'",
            body.login, ip,
        )
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    _reset_attempts(ip)
    token = create_access_token(user_id=user["id"], role=user["role"])
    logger.info("login login='%s' id=%s ip='%s'", user["login"], user["id"], ip)

    # Warn if superadmin still uses the default password (never changed).
    warn_default_password = (
        user.get("role") == "superadmin"
        and user.get("password_changed_at") is None
    )

    return LoginResponse(
        access_token=token,
        user=UserOut(**{k: v for k, v in user.items() if k != "password"}),
        warn_default_password=warn_default_password,
    )


@router.post("/api/auth/logout")
def logout(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Logout — server acknowledgement and audit log.  Client clears the token."""
    logger.info("logout login='%s' id=%s", current_user["login"], current_user["id"])
    return {"detail": "ok"}


@router.get("/api/auth/me", response_model=UserOut)
def me(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Return the currently authenticated user."""
    return UserOut(**{k: v for k, v in current_user.items() if k != "password"})


@router.get("/api/permissions/available")
def available_permissions(current_user: Dict[str, Any] = Depends(require_permission("tab:settings"))):
    """Return known permission keys with labels (superadmin-only, for user management UI)."""
    return AVAILABLE_PERMISSIONS
