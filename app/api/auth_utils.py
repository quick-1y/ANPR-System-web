from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import bcrypt
import jwt

from common.logging import get_logger
from config.env_settings import load_env_config

logger = get_logger(__name__)

# JWT configuration
_ENV = load_env_config()
JWT_SECRET_KEY = _ENV.jwt_secret_key
JWT_ALGORITHM = "HS256"


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the plain-text password."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Check a plain-text password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: int, role: str, exp_minutes: int) -> str:
    """Create a signed JWT access token.

    The lifetime is the caller's business: the login endpoint passes the current
    `auth.token_ttl_minutes` from app_settings, so a change applies to the next
    sign-in. Tokens already issued keep the `exp` they were signed with.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=exp_minutes)
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT access token.

    Returns the payload dict on success.
    Raises ``jwt.ExpiredSignatureError`` or ``jwt.InvalidTokenError`` on failure.
    """
    return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
