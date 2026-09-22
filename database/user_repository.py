from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from common.logging import get_logger
from database.base import PooledDatabase

logger = get_logger(__name__)

# Same value as app.api.superadmin.SUPERADMIN_LOGIN, kept as a local literal
# rather than imported: database/ must not depend on app/api/ (AGENTS.md
# directory rules). Used only to detect a pre-existing row left over from
# before superadmin became a technical, env-only account (roadmap section 14)
# — never to authenticate one.
_LEGACY_SUPERADMIN_LOGIN = "superadmin"


_USER_COLUMNS = (
    "id, login, password, role, permissions, is_active, created_at, updated_at, "
    "password_changed_at"
)


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
    """

    def _schema_sql(self) -> str:
        return self._SCHEMA

    def _ensure_schema(self) -> None:
        """Create the table; nothing is seeded — superadmin is a technical
        account defined only by SUPERADMIN_PASSWORD (roadmap section 14),
        never a row here."""
        super()._ensure_schema()
        self._warn_if_legacy_superadmin_row_exists()

    def _warn_if_legacy_superadmin_row_exists(self) -> None:
        """A `login='superadmin'` row from before superadmin became an
        env-only account is now permanently unreachable — the login flow
        recognizes that login before ever querying this table. Its data is
        left untouched (no destructive migration, per project policy); this
        only logs so the fact isn't silently invisible to whoever deployed
        this change on an existing database."""
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT count(*) FROM users WHERE login = %s", (_LEGACY_SUPERADMIN_LOGIN,))
                    if cur.fetchone()[0] > 0:
                        logger.warning(
                            "В таблице users осталась строка login='superadmin' из прежней "
                            "версии — вход через неё больше не работает (суперадмин теперь "
                            "только из SUPERADMIN_PASSWORD), данные строки не удалены"
                        )
        except Exception:
            logger.exception("Не удалось проверить устаревшую строку суперадмина")

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
