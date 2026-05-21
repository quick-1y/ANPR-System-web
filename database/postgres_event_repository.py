from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from common.logging import get_logger
from database.base import PooledDatabase
from database.errors import StorageUnavailableError

logger = get_logger(__name__)
_SCHEMA_SQL_PATH = Path(__file__).resolve().parents[1] / "database" / "postgres" / "schema.sql"

_SELECT_COLS = (
    "id, time, channel_id_entry, channel_id_exit, plate, plate_display, country, confidence, source, "
    "frame_path_entry, plate_path_entry, frame_path_exit, plate_path_exit, direction, client_id, "
    "zone_id, time_entry, time_exit"
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
        event = {
            "id": row[0],
            "time": row[1],
            "channel_id_entry": row[2],
            "channel_id_exit": row[3],
            "plate": row[4],
            "plate_display": row[5],
            "country": row[6],
            "confidence": row[7],
            "source": row[8],
            "frame_path_entry": row[9],
            "plate_path_entry": row[10],
            "frame_path_exit": row[11],
            "plate_path_exit": row[12],
            "direction": row[13],
            "client_id": row[14],
            "zone_id": row[15],
            "time_entry": row[16],
            "time_exit": row[17],
        }
        # Совместимый вычисляемый идентификатор последнего физического канала
        # нужен runtime/UI-фильтрам и автоматике контроллеров, но в БД больше не хранится.
        event["channel_id"] = event["channel_id_exit"] or event["channel_id_entry"]
        event["frame_path"] = event["frame_path_exit"] or event["frame_path_entry"]
        event["plate_path"] = event["plate_path_exit"] or event["plate_path_entry"]
        return event

    def insert_event(
        self,
        plate: str,
        channel_id_entry: Optional[int] = None,
        plate_display: Optional[str] = None,
        country: Optional[str] = None,
        confidence: float = 0.0,
        source: str = "",
        time: Optional[str] = None,
        frame_path_entry: Optional[str] = None,
        plate_path_entry: Optional[str] = None,
        direction: Optional[str] = None,
        client_id: Optional[int] = None,
        zone_id: Optional[int] = None,
        time_entry: Optional[str] = None,
        channel_id_exit: Optional[int] = None,
        frame_path_exit: Optional[str] = None,
        plate_path_exit: Optional[str] = None,
        time_exit: Optional[str] = None,
        channel_id: Optional[int] = None,
        frame_path: Optional[str] = None,
        plate_path: Optional[str] = None,
    ) -> int:
        self._ensure_schema()
        ts = time or datetime.now(timezone.utc).isoformat()
        if channel_id_entry is None and channel_id is not None:
            channel_id_entry = channel_id
        if frame_path_entry is None and frame_path is not None:
            frame_path_entry = frame_path
        if plate_path_entry is None and plate_path is not None:
            plate_path_entry = plate_path
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        (
                            "INSERT INTO events "
                            "(time, channel_id_entry, channel_id_exit, plate, plate_display, country, confidence, source, "
                            "frame_path_entry, plate_path_entry, frame_path_exit, plate_path_exit, direction, client_id, "
                            "zone_id, time_entry, time_exit) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"
                        ),
                        (
                            ts,
                            channel_id_entry,
                            channel_id_exit,
                            plate,
                            plate_display,
                            country,
                            confidence,
                            source,
                            frame_path_entry,
                            plate_path_entry,
                            frame_path_exit,
                            plate_path_exit,
                            direction,
                            client_id,
                            zone_id,
                            time_entry,
                            time_exit,
                        ),
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
        *,
        channel_id_exit: Optional[int] = None,
        frame_path_exit: Optional[str] = None,
        plate_path_exit: Optional[str] = None,
        direction: Optional[str] = None,
        confidence: Optional[float] = None,
        country: Optional[str] = None,
        plate_display: Optional[str] = None,
        source: Optional[str] = None,
        client_id: Optional[int] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Найти последнюю открытую запись въезда по номеру и зоне, записать выезд
        и вернуть обновленное событие. Поле time также сдвигается на время выезда,
        чтобы запись поднялась вверх в live-ленте и журнале.
        """
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE events
                        SET time = %s,
                            time_exit = %s,
                            zone_id = %s,
                            channel_id_exit = %s,
                            frame_path_exit = %s,
                            plate_path_exit = %s,
                            direction = COALESCE(%s, direction),
                            confidence = COALESCE(%s, confidence),
                            country = COALESCE(%s, country),
                            plate_display = COALESCE(%s, plate_display),
                            source = COALESCE(%s, source),
                            client_id = COALESCE(%s, client_id)
                        WHERE id = (
                            SELECT id FROM events
                            WHERE plate = %s
                              AND zone_id = %s
                              AND time_exit IS NULL
                            ORDER BY time DESC, id DESC
                            LIMIT 1
                        )
                        RETURNING {_SELECT_COLS}
                        """,
                        (
                            time_exit_iso,
                            time_exit_iso,
                            zone_after_id,
                            channel_id_exit,
                            frame_path_exit,
                            plate_path_exit,
                            direction,
                            confidence,
                            country,
                            plate_display,
                            source,
                            client_id,
                            plate,
                            zone_before_id,
                        ),
                    )
                    row = cursor.fetchone()
                conn.commit()
            return self._to_dict(row) if row else None
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
            filters.append("(channel_id_entry = %s OR channel_id_exit = %s)")
            params.extend([int(channel_id), int(channel_id)])
        if plate:
            filters.append("plate ILIKE %s")
            params.append(f"%{plate}%")
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        query = f"SELECT {_SELECT_COLS} FROM events {where} ORDER BY time DESC, id DESC LIMIT %s"
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
                    cursor.execute(f"SELECT {_SELECT_COLS} FROM events WHERE id = %s", (int(event_id),))
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
                        """
                        DELETE FROM events
                        WHERE time < %s
                        RETURNING id, frame_path_entry, plate_path_entry, frame_path_exit, plate_path_exit
                        """,
                        (cutoff_iso,),
                    )
                    rows = cursor.fetchall()
                conn.commit()
            return [
                {
                    "id": row[0],
                    "frame_path_entry": row[1],
                    "plate_path_entry": row[2],
                    "frame_path_exit": row[3],
                    "plate_path_exit": row[4],
                    "frame_path": row[3] or row[1],
                    "plate_path": row[4] or row[2],
                }
                for row in rows
            ]
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def fetch_last_plates_by_channel_ids(self, channel_ids: Sequence[int]) -> dict[int, dict[str, Any]]:
        self._ensure_schema()
        ids = sorted({int(channel_id) for channel_id in channel_ids if channel_id is not None})
        if not ids:
            return {}
        query = """
            SELECT DISTINCT ON (channel_id) channel_id, plate, plate_display, time, country, confidence, direction
            FROM (
                SELECT channel_id_entry AS channel_id, plate, plate_display, time, country, confidence, direction
                FROM events WHERE channel_id_entry = ANY(%s)
                UNION ALL
                SELECT channel_id_exit AS channel_id, plate, plate_display, time, country, confidence, direction
                FROM events WHERE channel_id_exit = ANY(%s)
            ) AS channel_events
            WHERE channel_id IS NOT NULL
            ORDER BY channel_id, time DESC
        """
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (ids, ids))
                    rows = cursor.fetchall()
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc
        return {
            int(row[0]): {
                "plate": row[1],
                "plate_display": row[2],
                "time": row[3],
                "country": row[4],
                "confidence": row[5],
                "direction": row[6],
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
            filters.append("(channel_id_entry = %s OR channel_id_exit = %s)")
            params.extend([int(channel_id), int(channel_id)])
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
