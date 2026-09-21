from __future__ import annotations

import json
from typing import Any, Dict, Optional

from database.base import PooledDatabase
from database.errors import StorageUnavailableError
from database.user_repository import UserDatabase


class AppSettingsRepository(PooledDatabase):
    """PostgreSQL repository for class A settings (`app_settings`).

    One row per leaf key; a missing key is not an error — the registry default
    applies (`config/registry.py`). Every write bumps `app_settings_revision`
    in the same transaction, which is what lets other processes notice the
    change (`SettingsService`). Values are stored as-is: validation belongs to
    the service, which knows the registry.
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS app_settings (
        key        TEXT        PRIMARY KEY,
        value      JSONB       NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_by BIGINT      REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS app_settings_revision (
        id         SMALLINT    PRIMARY KEY DEFAULT 1 CHECK (id = 1),
        revision   BIGINT      NOT NULL DEFAULT 0,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    INSERT INTO app_settings_revision (id) VALUES (1) ON CONFLICT DO NOTHING;
    """

    _UPSERT = """
    INSERT INTO app_settings (key, value, updated_at, updated_by)
    VALUES (%s, %s::jsonb, now(), %s)
    ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value, updated_at = now(), updated_by = EXCLUDED.updated_by
    """

    _BUMP_REVISION = """
    UPDATE app_settings_revision SET revision = revision + 1, updated_at = now()
    WHERE id = 1 RETURNING revision
    """

    def _schema_sql(self) -> str:
        # app_settings.updated_by references users(id), so the lazy bootstrap
        # has to create `users` first; the DDL is reused, not duplicated.
        return UserDatabase._SCHEMA + self._SCHEMA

    # ── Read ──────────────────────────────────────────────────────────

    def get_all(self) -> Dict[str, Any]:
        return self._read_rows("SELECT key, value FROM app_settings", ())

    def get_many(self, prefix: str) -> Dict[str, Any]:
        """Return the subtree under *prefix* (`retention` -> every `retention.*` key)."""
        return self._read_rows(
            "SELECT key, value FROM app_settings WHERE starts_with(key, %s)",
            (prefix.rstrip(".") + ".",),
        )

    def revision(self) -> int:
        try:
            self._ensure_schema()
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT revision FROM app_settings_revision WHERE id = 1")
                    row = cur.fetchone()
        except StorageUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc
        return int(row[0]) if row else 0

    # ── Write ─────────────────────────────────────────────────────────

    def set_many(self, values: Dict[str, Any], updated_by: Optional[int] = None) -> int:
        """Upsert *values* and bump the revision in one transaction.

        Rows are written key by key, never as a read-modify-write of a whole
        document, so concurrent writers to different keys cannot lose each
        other's changes. Returns the new revision (unchanged for empty input).
        """
        if not values:
            return self.revision()
        rows = [(key, json.dumps(value), updated_by) for key, value in values.items()]
        return self._write(rows, [])

    def replace_all(self, values: Dict[str, Any], updated_by: Optional[int] = None) -> Optional[int]:
        """Make the table hold exactly *values*: upsert them, delete every other row.

        One transaction, one revision bump — used by the settings restore, where
        "restore" must mean "the instance now looks like the dump", including
        keys the dump does not contain returning to their registry default.
        Returns the new revision, or `None` if nothing changed.
        """
        try:
            self._ensure_schema()
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT key, value FROM app_settings")
                    existing = {row[0]: row[1] for row in cur.fetchall()}
                    stale = [key for key in existing if key not in values]
                    changed = bool(stale)
                    for key in stale:
                        cur.execute("DELETE FROM app_settings WHERE key = %s", (key,))
                    for key, value in values.items():
                        if key in existing and existing[key] == value:
                            continue  # identical row: do not touch updated_at/updated_by
                        cur.execute(self._UPSERT, (key, json.dumps(value), updated_by))
                        changed = True
                    revision = None
                    if changed:
                        cur.execute(self._BUMP_REVISION)
                        revision = int(cur.fetchone()[0])
                conn.commit()
        except StorageUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc
        return revision

    def delete(self, key: str) -> bool:
        """Remove an override so the registry default applies again; True if a row existed."""
        return self._write([], [key]) is not None

    # ── Internals ─────────────────────────────────────────────────────

    def _read_rows(self, query: str, params: tuple) -> Dict[str, Any]:
        try:
            self._ensure_schema()
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    rows = cur.fetchall()
        except StorageUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc
        return {row[0]: row[1] for row in rows}

    def _write(self, upserts: list, deletes: list) -> Optional[int]:
        try:
            self._ensure_schema()
            with self._connect() as conn:
                with conn.cursor() as cur:
                    for row in upserts:
                        cur.execute(self._UPSERT, row)
                    changed = bool(upserts)
                    for key in deletes:
                        cur.execute("DELETE FROM app_settings WHERE key = %s", (key,))
                        changed = changed or cur.rowcount > 0
                    revision = None
                    if changed:
                        cur.execute(self._BUMP_REVISION)
                        revision = int(cur.fetchone()[0])
                conn.commit()
        except StorageUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc
        return revision


__all__ = ["AppSettingsRepository"]
