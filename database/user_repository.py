from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import bcrypt

from common.logging import get_logger
from database.base import PooledDatabase

logger = get_logger(__name__)

# Default admin credentials created on first startup.
_DEFAULT_ADMIN_LOGIN = "admin"
_DEFAULT_ADMIN_PASSWORD = "1234"


def _hash_password(plain: str) -> str:
    """Return a bcrypt hash of the plain-text password."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Convert a DB row tuple to a user dict."""
    return {
        "id": row[0],
        "login": row[1],
        "password": row[2],
        "role": row[3],
        "permissions": row[4] if isinstance(row[4], list) else json.loads(row[4] or "[]"),
        "is_active": row[5],
        "created_at": row[6],
        "updated_at": row[7],
    }


class UserDatabase(PooledDatabase):
    """PostgreSQL repository for users (auth)."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS users (
        id          BIGSERIAL PRIMARY KEY,
        login       TEXT NOT NULL UNIQUE,
        password    TEXT NOT NULL,
        role        TEXT NOT NULL DEFAULT 'operator',
        permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
        is_active   BOOLEAN NOT NULL DEFAULT TRUE,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_users_login ON users(login);
    """

    _SEED_ADMIN = """
    INSERT INTO users (login, password, role, permissions, is_active)
    VALUES (%s, %s, 'admin', '[]'::jsonb, true)
    ON CONFLICT (login) DO NOTHING;
    """

    def _schema_sql(self) -> str:
        return self._SCHEMA

    def _ensure_schema(self) -> None:
        """Create table and seed default admin if the table is empty."""
        super()._ensure_schema()
        self._seed_default_admin()

    def _seed_default_admin(self) -> None:
        """Insert the default admin user when the users table is empty."""
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT count(*) FROM users")
                    count = cur.fetchone()[0]
                    if count == 0:
                        hashed = _hash_password(_DEFAULT_ADMIN_PASSWORD)
                        cur.execute(self._SEED_ADMIN, (_DEFAULT_ADMIN_LOGIN, hashed))
                        conn.commit()
                        logger.info("Создан пользователь по умолчанию: admin")
                    else:
                        conn.rollback()
        except Exception:
            logger.exception("Ошибка при создании пользователя по умолчанию")

    # ── Read ──────────────────────────────────────────────────────────

    def find_by_login(self, login: str) -> Optional[Dict[str, Any]]:
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, login, password, role, permissions, is_active, created_at, updated_at "
                    "FROM users WHERE login = %s",
                    (login,),
                )
                row = cur.fetchone()
                return _row_to_dict(row) if row else None

    def find_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, login, password, role, permissions, is_active, created_at, updated_at "
                    "FROM users WHERE id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
                return _row_to_dict(row) if row else None

    def list_all(self) -> List[Dict[str, Any]]:
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, login, password, role, permissions, is_active, created_at, updated_at "
                    "FROM users ORDER BY id"
                )
                return [_row_to_dict(row) for row in cur.fetchall()]

    # ── Write ─────────────────────────────────────────────────────────

    def create_user(
        self,
        login: str,
        password_hash: str,
        role: str = "operator",
        permissions: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        self._ensure_schema()
        perms_json = json.dumps(permissions or [])
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (login, password, role, permissions) "
                    "VALUES (%s, %s, %s, %s::jsonb) "
                    "RETURNING id, login, password, role, permissions, is_active, created_at, updated_at",
                    (login, password_hash, role, perms_json),
                )
                row = cur.fetchone()
                conn.commit()
                return _row_to_dict(row)

    def update_user(
        self,
        user_id: int,
        *,
        role: Optional[str] = None,
        permissions: Optional[List[str]] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        self._ensure_schema()
        sets: list[str] = []
        params: list[Any] = []
        if role is not None:
            sets.append("role = %s")
            params.append(role)
        if permissions is not None:
            sets.append("permissions = %s::jsonb")
            params.append(json.dumps(permissions))
        if is_active is not None:
            sets.append("is_active = %s")
            params.append(is_active)
        if not sets:
            return self.find_by_id(user_id)
        sets.append("updated_at = now()")
        params.append(user_id)
        query = (
            f"UPDATE users SET {', '.join(sets)} WHERE id = %s "
            "RETURNING id, login, password, role, permissions, is_active, created_at, updated_at"
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                conn.commit()
                return _row_to_dict(row) if row else None

    def update_password(self, user_id: int, password_hash: str) -> bool:
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET password = %s, updated_at = now() WHERE id = %s",
                    (password_hash, user_id),
                )
                conn.commit()
                return cur.rowcount > 0

    def deactivate(self, user_id: int) -> bool:
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET is_active = false, updated_at = now() WHERE id = %s",
                    (user_id,),
                )
                conn.commit()
                return cur.rowcount > 0

    def count_active_admins(self) -> int:
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM users WHERE role = 'admin' AND is_active = true")
                return cur.fetchone()[0]
