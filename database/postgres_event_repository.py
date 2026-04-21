from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from common.logging import get_logger
from database.base import PooledDatabase
from database.errors import StorageUnavailableError

logger = get_logger(__name__)
_SCHEMA_SQL_PATH = Path(__file__).resolve().parents[1] / "database" / "postgres" / "schema.sql"

_SELECT_COLS = (
    "id, time, channel_id, plate, plate_display, country, confidence, source, "
    "frame_path, plate_path, direction, client_id, zone_id, time_entry, time_exit"
)

class PostgresEventDatabase(PooledDatabase):
    """PostgreSQL-only хранилище событий с ленивым bootstrap схемы."""

    def __init__(self, dsn: str) -> None:
        super().__init__(dsn)
        if not _SCHEMA_SQL_PATH.is_file():
            raise StorageUnavailableError(
                f"SQL-схема не найдена: {_SCHEMA_SQL_PATH}. "
                "Убедитесь, что файл database/postgres/schema.sql существует."
            )

    def _schema_sql(self) -> str:
        try:
            return _SCHEMA_SQL_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            raise StorageUnavailableError(f"Не удалось прочитать SQL-схему {_SCHEMA_SQL_PATH}: {exc}") from exc

    @staticmethod
    def _to_dict(row: Any) -> dict[str, Any]:
        return {
            "id":            row[0],
            "time":          row[1],
            "channel_id":    row[2],
            "plate":         row[3],
            "plate_display": row[4],
            "country":       row[5],
            "confidence":    row[6],
            "source":        row[7],
            "frame_path":    row[8],
            "plate_path":    row[9],
            "direction":     row[10],
            "client_id":     row[11],
            "zone_id":       row[12],
            "time_entry":    row[13],
            "time_exit":     row[14],
        }

    def insert_event(
        self,
        plate: str,
        channel_id: Optional[int] = None,
        plate_display: Optional[str] = None,
        country: Optional[str] = None,
        confidence: float = 0.0,
        source: str = "",
        time: Optional[str] = None,
        frame_path: Optional[str] = None,
        plate_path: Optional[str] = None,
        direction: Optional[str] = None,
        client_id: Optional[int] = None,
        zone_id: Optional[int] = None,
        time_entry: Optional[str] = None,
    ) -> int:
        self._ensure_schema()
        ts = time or datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        (
                            "INSERT INTO events "
                            "(time, channel_id, plate, plate_display, country, confidence, source, "
                            "frame_path, plate_path, direction, client_id, zone_id, time_entry) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"
                        ),
                        (ts, channel_id, plate, plate_display, country, confidence, source,
                         frame_path, plate_path, direction, client_id, zone_id, time_entry),
                    )
                    row = cursor.fetchone()
                conn.commit()
            return int(row[0]) if row else 0
        except StorageUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def find_active_entry_and_write_exit(
        self,
        plate: str,
        zone_before_id: int,
        zone_after_id: int,
        time_exit_iso: str,
    ) -> Optional[int]:
        """
        Find the most recent open entry event for `plate` in `zone_before_id`
        (where time_exit IS NULL), write time_exit and set zone_id = zone_after_id.
        Returns the updated event id, or None if no open entry found.
        """
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE events
                        SET time_exit = %s, zone_id = %s
                        WHERE id = (
                            SELECT id FROM events
                            WHERE plate = %s
                              AND zone_id = %s
                              AND time_exit IS NULL
                            ORDER BY time DESC
                            LIMIT 1
                        )
                        RETURNING id
                        """,
                        (time_exit_iso, zone_after_id, plate, zone_before_id),
                    )
                    row = cursor.fetchone()
                conn.commit()
            return int(row[0]) if row else None
        except StorageUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def fetch_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"SELECT {_SELECT_COLS} FROM events ORDER BY time DESC, id DESC LIMIT %s",
                        (limit,),
                    )
                    return [self._to_dict(row) for row in cursor.fetchall()]
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def fetch_journal_page(
        self,
        *,
        limit: int,
        before_ts: Optional[Any] = None,
        before_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        plate: Optional[str] = None,
        start_ts: Optional[Any] = None,
        end_ts: Optional[Any] = None,
    ) -> list[dict[str, Any]]:
        self._ensure_schema()
        page_limit = max(1, int(limit))
        filters: list[str] = []
        params: list[Any] = []
        if start_ts is not None:
            filters.append("time >= %s")
            params.append(start_ts)
        if end_ts is not None:
            filters.append("time <= %s")
            params.append(end_ts)
        if before_ts is not None and before_id is not None:
            filters.append("(time, id) < (%s, %s)")
            params.extend([before_ts, int(before_id)])
        if channel_id is not None:
            filters.append("channel_id = %s")
            params.append(int(channel_id))
        if plate:
            filters.append("plate ILIKE %s")
            params.append(f"%{plate}%")
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        query = (
            f"SELECT {_SELECT_COLS} "
            f"FROM events {where} ORDER BY time DESC, id DESC LIMIT %s"
        )
        params.append(page_limit)
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, tuple(params))
                    return [self._to_dict(row) for row in cursor.fetchall()]
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def fetch_by_id(self, event_id: int) -> Optional[dict[str, Any]]:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"SELECT {_SELECT_COLS} FROM events WHERE id = %s",
                        (int(event_id),),
                    )
                    row = cursor.fetchone()
                    return self._to_dict(row) if row else None
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def delete_before(self, cutoff_iso: str) -> list[dict[str, Any]]:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM events WHERE time < %s RETURNING id, frame_path, plate_path",
                        (cutoff_iso,),
                    )
                    rows = cursor.fetchall()
                conn.commit()
            return [{"id": row[0], "frame_path": row[1], "plate_path": row[2]} for row in rows]
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def fetch_last_plates_by_channel_ids(self, channel_ids: Sequence[int]) -> dict[int, dict[str, Any]]:
        self._ensure_schema()
        ids = sorted({int(channel_id) for channel_id in channel_ids if channel_id is not None})
        if not ids:
            return {}
        query = (
            "SELECT DISTINCT ON (channel_id) channel_id, plate, plate_display, time, country, confidence, direction "
            "FROM events WHERE channel_id = ANY(%s) AND channel_id IS NOT NULL "
            "ORDER BY channel_id, time DESC"
        )
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (ids,))
                    rows = cursor.fetchall()
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc
        return {
            int(row[0]): {
                "plate":         row[1],
                "plate_display": row[2],
                "time":          row[3],
                "country":       row[4],
                "confidence":    row[5],
                "direction":     row[6],
            }
            for row in rows
        }

    def fetch_for_export(
        self,
        *,
        start: Optional[str] = None,
        end: Optional[str] = None,
        plate: Optional[str] = None,
        channel_id: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        self._ensure_schema()
        filters: list[str] = []
        params: list[Any] = []
        if start:
            filters.append("time >= %s")
            params.append(start)
        if end:
            filters.append("time <= %s")
            params.append(end)
        if channel_id is not None:
            filters.append("channel_id = %s")
            params.append(int(channel_id))
        if plate:
            filters.append("plate ILIKE %s")
            params.append(f"%{plate}%")
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        query = f"SELECT {_SELECT_COLS} FROM events {where} ORDER BY time DESC"
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, tuple(params))
                    return [self._to_dict(row) for row in cursor.fetchall()]
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc


__all__ = ["PostgresEventDatabase"]
