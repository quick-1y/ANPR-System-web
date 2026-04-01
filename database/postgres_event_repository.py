from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from common.logging import get_logger
from database.base import PooledDatabase
from database.errors import StorageUnavailableError

logger = get_logger(__name__)
_SCHEMA_SQL_PATH = Path(__file__).resolve().parents[1] / "database" / "postgres" / "schema.sql"

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
            "id": row[0],
            "timestamp": row[1],
            "channel_id": row[2],
            "channel": row[3],
            "plate": row[4],
            "plate_display": row[5],
            "country": row[6],
            "confidence": row[7],
            "source": row[8],
            "frame_path": row[9],
            "plate_path": row[10],
            "direction": row[11],
        }

    def insert_event(
        self,
        channel: str,
        plate: str,
        channel_id: Optional[int] = None,
        plate_display: Optional[str] = None,
        country: Optional[str] = None,
        confidence: float = 0.0,
        source: str = "",
        timestamp: Optional[str] = None,
        frame_path: Optional[str] = None,
        plate_path: Optional[str] = None,
        direction: Optional[str] = None,
    ) -> int:
        self._ensure_schema()
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        (
                            "INSERT INTO events (timestamp, channel_id, channel, plate, plate_display, country, confidence, source, frame_path, plate_path, direction) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"
                        ),
                        (ts, channel_id, channel, plate, plate_display, country, confidence, source, frame_path, plate_path, direction),
                    )
                    row = cursor.fetchone()
                conn.commit()
            return int(row[0]) if row else 0
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
                        "SELECT id, timestamp, channel_id, channel, plate, plate_display, country, confidence, source, frame_path, plate_path, direction "
                        "FROM events ORDER BY timestamp DESC, id DESC LIMIT %s",
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
            filters.append("timestamp >= %s")
            params.append(start_ts)
        if end_ts is not None:
            filters.append("timestamp <= %s")
            params.append(end_ts)
        if before_ts is not None and before_id is not None:
            filters.append("(timestamp, id) < (%s, %s)")
            params.extend([before_ts, int(before_id)])
        if channel_id is not None:
            filters.append("channel_id = %s")
            params.append(int(channel_id))
        if plate:
            filters.append("plate ILIKE %s")
            params.append(f"%{plate}%")
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        query = (
            "SELECT id, timestamp, channel_id, channel, plate, plate_display, country, confidence, source, frame_path, plate_path, direction "
            f"FROM events {where} ORDER BY timestamp DESC, id DESC LIMIT %s"
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
                        "SELECT id, timestamp, channel_id, channel, plate, plate_display, country, confidence, source, frame_path, plate_path, direction FROM events WHERE id = %s",
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
                        "DELETE FROM events WHERE timestamp < %s RETURNING id, frame_path, plate_path",
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
            "SELECT DISTINCT ON (channel_id) channel_id, plate, plate_display, timestamp, country, confidence, direction "
            "FROM events WHERE channel_id = ANY(%s) AND channel_id IS NOT NULL "
            "ORDER BY channel_id, timestamp DESC"
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
                "plate": row[1],
                "plate_display": row[2],
                "timestamp": row[3],
                "country": row[4],
                "confidence": row[5],
                "direction": row[6],
            }
            for row in rows
        }

    def fetch_for_export(self, *, start: Optional[str] = None, end: Optional[str] = None, channel: Optional[str] = None, plate: Optional[str] = None, channel_id: Optional[int] = None) -> list[dict[str, Any]]:
        self._ensure_schema()
        filters: list[str] = []
        params: list[Any] = []
        if start:
            filters.append("timestamp >= %s")
            params.append(start)
        if end:
            filters.append("timestamp <= %s")
            params.append(end)
        if channel_id is not None:
            filters.append("channel_id = %s")
            params.append(int(channel_id))
        elif channel:
            filters.append("channel = %s")
            params.append(channel)
        if plate:
            filters.append("plate ILIKE %s")
            params.append(f"%{plate}%")
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        query = (
            "SELECT id, timestamp, channel_id, channel, plate, plate_display, country, confidence, source, frame_path, plate_path, direction "
            f"FROM events {where} ORDER BY timestamp DESC"
        )
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, tuple(params))
                    return [self._to_dict(row) for row in cursor.fetchall()]
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc


__all__ = ["PostgresEventDatabase"]
