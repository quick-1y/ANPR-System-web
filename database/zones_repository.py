from __future__ import annotations

from typing import Any, Optional

from database.base import PooledDatabase
from database.errors import StorageUnavailableError


class ZoneDatabase(PooledDatabase):
    """CRUD for zones table; occupancy queries; cascade on delete."""

    def _schema_sql(self) -> str:
        # Schema (zones table) is owned by PostgresEventDatabase via schema.sql.
        # This no-op satisfies the abstract requirement and marks the instance initialised.
        return "SELECT 1"

    def list_zones(self) -> list[dict[str, Any]]:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, name, capacity FROM zones ORDER BY id")
                    return [
                        {"id": row[0], "name": row[1], "capacity": row[2]}
                        for row in cur.fetchall()
                    ]
        except StorageUnavailableError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def get_zone(self, zone_id: int) -> Optional[dict[str, Any]]:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, name, capacity FROM zones WHERE id = %s",
                        (int(zone_id),),
                    )
                    row = cur.fetchone()
                    return {"id": row[0], "name": row[1], "capacity": row[2]} if row else None
        except StorageUnavailableError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def create_zone(self, name: str, capacity: int) -> int:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO zones (name, capacity) VALUES (%s, %s) RETURNING id",
                        (name, int(capacity)),
                    )
                    row = cur.fetchone()
                conn.commit()
            return int(row[0]) if row else 0
        except StorageUnavailableError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def update_zone(self, zone_id: int, name: str, capacity: int) -> bool:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE zones SET name = %s, capacity = %s WHERE id = %s",
                        (name, int(capacity), int(zone_id)),
                    )
                    updated = cur.rowcount > 0
                conn.commit()
            return updated
        except StorageUnavailableError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def delete_zone(self, zone_id: int) -> bool:
        """Delete zone and cascade: clear zone movement bindings on affected channels."""
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        (
                            "UPDATE channels "
                            "SET zone_before_id = CASE WHEN zone_before_id = %s THEN NULL ELSE zone_before_id END, "
                            "zone_after_id = CASE WHEN zone_after_id = %s THEN NULL ELSE zone_after_id END, "
                            "channel_type = CASE "
                            "  WHEN (CASE WHEN zone_before_id = %s THEN NULL ELSE zone_before_id END) IS NULL "
                            "    OR (CASE WHEN zone_after_id = %s THEN NULL ELSE zone_after_id END) IS NULL "
                            "  THEN NULL ELSE channel_type END "
                            "WHERE zone_before_id = %s OR zone_after_id = %s"
                        ),
                        (int(zone_id), int(zone_id), int(zone_id), int(zone_id), int(zone_id), int(zone_id)),
                    )
                    cur.execute(
                        "DELETE FROM zones WHERE id = %s",
                        (int(zone_id),),
                    )
                    deleted = cur.rowcount > 0
                conn.commit()
            return deleted
        except StorageUnavailableError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def get_channels_for_zone(self, zone_id: int) -> list[dict[str, Any]]:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, name FROM channels WHERE zone_before_id = %s OR zone_after_id = %s ORDER BY id",
                        (int(zone_id), int(zone_id)),
                    )
                    return [{"id": row[0], "name": row[1]} for row in cur.fetchall()]
        except StorageUnavailableError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def get_zone_occupancy(self, zone_id: int) -> int:
        """Count active (un-exited) entries for the zone."""
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) FROM events WHERE zone_id = %s AND time_exit IS NULL",
                        (int(zone_id),),
                    )
                    row = cur.fetchone()
                    return int(row[0]) if row else 0
        except StorageUnavailableError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc


__all__ = ["ZoneDatabase"]
