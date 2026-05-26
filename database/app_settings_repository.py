from __future__ import annotations

import copy
import json
from typing import Any, Dict, Optional

from database.base import PooledDatabase
from database.errors import StorageUnavailableError


class AppSettingsDatabase(PooledDatabase):
    """PostgreSQL repository for global app settings payload."""

    _SCHEMA = """
CREATE TABLE IF NOT EXISTS app_settings (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

    def _schema_sql(self) -> str:
        return self._SCHEMA

    def load(self) -> Optional[Dict[str, Any]]:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT payload FROM app_settings WHERE id = 1")
                    row = cur.fetchone()
                    if not row:
                        return None
                    raw = row[0]
                    if isinstance(raw, dict):
                        return copy.deepcopy(raw)
                    if isinstance(raw, str):
                        return json.loads(raw)
                    return None
        except StorageUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def save(self, payload: Dict[str, Any]) -> None:
        self._ensure_schema()
        data = copy.deepcopy(payload)
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO app_settings (id, payload, updated_at)
                        VALUES (1, %s::jsonb, now())
                        ON CONFLICT (id) DO UPDATE
                        SET payload = EXCLUDED.payload,
                            updated_at = now()
                        """,
                        (json.dumps(data),),
                    )
                conn.commit()
        except StorageUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

