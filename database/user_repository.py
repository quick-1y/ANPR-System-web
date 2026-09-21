from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.api.auth_utils import hash_password

from common.logging import get_logger
from config.env_settings import bootstrap_superadmin_password
from config.preferences import clean_stored, known_keys
from database.base import PooledDatabase

logger = get_logger(__name__)

# Login of the superadmin created on first startup. The password comes from
# BOOTSTRAP_SUPERADMIN_PASSWORD (config/env_settings.py) — it is an
# infrastructure secret and must not live as a constant here.
_DEFAULT_SUPERADMIN_LOGIN = "superadmin"


_USER_COLUMNS = (
    "id, login, password, role, permissions, is_active, created_at, updated_at, "
    "password_changed_at, preferences"
)


def _load_preferences(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        loaded = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


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
        "password_changed_at": row[8],
        "preferences": _load_preferences(row[9]),
    }


class UserDatabase(PooledDatabase):
    """PostgreSQL repository for users (auth)."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS users (
        id                  BIGSERIAL PRIMARY KEY,
        login               TEXT NOT NULL UNIQUE,
        password            TEXT NOT NULL,
        role                TEXT NOT NULL DEFAULT 'operator',
        permissions         JSONB NOT NULL DEFAULT '[]'::jsonb,
        is_active           BOOLEAN NOT NULL DEFAULT TRUE,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
        password_changed_at TIMESTAMPTZ DEFAULT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_users_login ON users(login);
    ALTER TABLE users ADD COLUMN IF NOT EXISTS preferences JSONB NOT NULL DEFAULT '{}'::jsonb;
    """


    _SEED_SUPERADMIN = """
    INSERT INTO users (login, password, role, permissions, is_active)
    VALUES (%s, %s, 'superadmin', '[]'::jsonb, true)
    ON CONFLICT (login) DO NOTHING;
    """

    def _schema_sql(self) -> str:
        return self._SCHEMA

    def _ensure_schema(self) -> None:
        """Create table and seed default superadmin if the table is empty."""
        super()._ensure_schema()
        self._seed_default_superadmin()

    def _seed_default_superadmin(self) -> None:
        """Insert the default superadmin user when the users table is empty."""
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT count(*) FROM users")
                    count = cur.fetchone()[0]
                    if count == 0:
                        hashed = hash_password(bootstrap_superadmin_password())
                        cur.execute(self._SEED_SUPERADMIN, (_DEFAULT_SUPERADMIN_LOGIN, hashed))
                        conn.commit()
                        logger.info("Создан пользователь по умолчанию: superadmin")
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
                    f"SELECT {_USER_COLUMNS} FROM users WHERE login = %s",
                    (login,),
                )
                row = cur.fetchone()
                return _row_to_dict(row) if row else None

    def find_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {_USER_COLUMNS} FROM users WHERE id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
                return _row_to_dict(row) if row else None

    def list_all(self) -> List[Dict[str, Any]]:
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {_USER_COLUMNS} FROM users ORDER BY id"
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
                    f"RETURNING {_USER_COLUMNS}",
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
            f"RETURNING {_USER_COLUMNS}"
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
                    "UPDATE users SET password = %s, updated_at = now(), "
                    "password_changed_at = now() WHERE id = %s",
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

    # ── Preferences (class U) ─────────────────────────────────────────

    _MERGE_PREFERENCES = (
        "UPDATE users SET preferences = jsonb_strip_nulls(preferences || %s::jsonb) "
        "WHERE id = %s RETURNING preferences"
    )

    def get_preferences(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Personal preferences of one user (known keys only), or `None` if no such user."""
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT preferences FROM users WHERE id = %s", (user_id,))
                row = cur.fetchone()
                return clean_stored(_load_preferences(row[0])) if row else None

    def merge_preferences(self, user_id: int, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Merge *patch* into the user's preferences in one atomic statement.

        Keys outside the registry are dropped; a `None` value removes the key
        (the user inherits the instance default again). Other keys are left
        untouched. Value validation is the caller's job (`config.preferences`).
        Returns the stored preferences, or `None` if no such user.
        """
        self._ensure_schema()
        allowed = set(known_keys())
        cleaned = {key: value for key, value in patch.items() if key in allowed}
        with self._connect() as conn:
            with conn.cursor() as cur:
                # A single `||` cannot delete keys, so nulls are applied as
                # explicit removals first: the merge itself stays one statement.
                removals = [key for key, value in cleaned.items() if value is None]
                document = json.dumps({key: value for key, value in cleaned.items() if value is not None})
                if removals:
                    cur.execute(
                        "UPDATE users SET preferences = preferences - %s::text[] WHERE id = %s",
                        (removals, user_id),
                    )
                cur.execute(self._MERGE_PREFERENCES, (document, user_id))
                row = cur.fetchone()
                conn.commit()
                return clean_stored(_load_preferences(row[0])) if row else None

    def count_active_superadmins(self) -> int:
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM users WHERE role = 'superadmin' AND is_active = true")
                return cur.fetchone()[0]
