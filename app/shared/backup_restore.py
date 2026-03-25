from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import yaml
from psycopg import connect

from common.logging import get_logger
from config.settings_manager import SettingsManager
from database.errors import StorageUnavailableError

logger = get_logger(__name__)
_BACKUP_FORMAT_VERSION = 1
_DB_BACKUP_KIND = "anpr_postgres_backup"


class BackupRestoreService:
    """Сервис резервного копирования PostgreSQL и settings.yaml."""

    def __init__(self, settings: SettingsManager, postgres_dsn: str) -> None:
        self._settings = settings
        self._postgres_dsn = str(postgres_dsn or "").strip()
        self._op_lock = threading.Lock()

    @staticmethod
    def _timestamp_slug() -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_UTC")

    def export_database_backup(self) -> tuple[str, bytes]:
        self._ensure_dsn()
        with self._single_operation("export_database_backup"):
            try:
                with connect(self._postgres_dsn) as conn:
                    with conn.cursor() as cur:
                        cur.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                        cur.execute(
                            "SELECT id, timestamp, channel_id, channel, plate, plate_display, country, confidence, source, frame_path, plate_path, direction FROM events ORDER BY id"
                        )
                        events_rows = cur.fetchall()
                        cur.execute("SELECT id, name, type FROM plate_lists ORDER BY id")
                        lists_rows = cur.fetchall()
                        cur.execute("SELECT id, list_id, plate, plate_normalized, comment FROM plate_list_entries ORDER BY id")
                        entries_rows = cur.fetchall()
                        cur.execute("COMMIT")
            except Exception as exc:  # noqa: BLE001
                raise StorageUnavailableError(f"Не удалось сформировать бэкап PostgreSQL: {exc}") from exc

            payload = {
                "backup_kind": _DB_BACKUP_KIND,
                "format_version": _BACKUP_FORMAT_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "backend": "postgresql",
                "tables": {
                    "events": [
                        {
                            "id": int(row[0]),
                            "timestamp": row[1].isoformat() if hasattr(row[1], "isoformat") else str(row[1]),
                            "channel_id": row[2],
                            "channel": row[3],
                            "plate": row[4],
                            "plate_display": row[5],
                            "country": row[6],
                            "confidence": float(row[7]) if row[7] is not None else None,
                            "source": row[8],
                            "frame_path": row[9],
                            "plate_path": row[10],
                            "direction": row[11],
                        }
                        for row in events_rows
                    ],
                    "plate_lists": [
                        {"id": int(row[0]), "name": row[1], "type": row[2]}
                        for row in lists_rows
                    ],
                    "plate_list_entries": [
                        {
                            "id": int(row[0]),
                            "list_id": int(row[1]),
                            "plate": row[2],
                            "plate_normalized": row[3],
                            "comment": row[4],
                        }
                        for row in entries_rows
                    ],
                },
            }
            logger.info(
                "Экспортирован бэкап PostgreSQL: events=%d, lists=%d, entries=%d",
                len(payload["tables"]["events"]),
                len(payload["tables"]["plate_lists"]),
                len(payload["tables"]["plate_list_entries"]),
            )
            filename = f"anpr_db_backup_{self._timestamp_slug()}.json"
            return filename, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

    def restore_database_backup(self, raw_payload: bytes) -> Dict[str, int]:
        self._ensure_dsn()
        payload = parse_database_backup_payload(raw_payload)
        tables = payload["tables"]
        events_rows = tables["events"]
        lists_rows = tables["plate_lists"]
        entries_rows = tables["plate_list_entries"]

        with self._single_operation("restore_database_backup"):
            try:
                with connect(self._postgres_dsn) as conn:
                    with conn.cursor() as cur:
                        cur.execute("BEGIN")
                        cur.execute(
                            "CREATE TABLE IF NOT EXISTS events ("
                            "id BIGSERIAL PRIMARY KEY, timestamp TIMESTAMPTZ NOT NULL, channel_id INTEGER, channel TEXT NOT NULL, plate TEXT NOT NULL, "
                            "plate_display TEXT, country TEXT, confidence DOUBLE PRECISION, source TEXT, frame_path TEXT, plate_path TEXT, direction TEXT"
                            ")"
                        )
                        cur.execute(
                            "CREATE TABLE IF NOT EXISTS plate_lists (id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL)"
                        )
                        cur.execute(
                            "CREATE TABLE IF NOT EXISTS plate_list_entries ("
                            "id BIGSERIAL PRIMARY KEY, list_id BIGINT NOT NULL REFERENCES plate_lists(id) ON DELETE CASCADE, "
                            "plate TEXT NOT NULL, plate_normalized TEXT NOT NULL, comment TEXT"
                            ")"
                        )
                        cur.execute("TRUNCATE TABLE plate_list_entries, plate_lists, events RESTART IDENTITY CASCADE")

                        for row in events_rows:
                            cur.execute(
                                "INSERT INTO events (id, timestamp, channel_id, channel, plate, plate_display, country, confidence, source, frame_path, plate_path, direction) "
                                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                                (
                                    int(row["id"]),
                                    row["timestamp"],
                                    row.get("channel_id"),
                                    row["channel"],
                                    row["plate"],
                                    row.get("plate_display"),
                                    row.get("country"),
                                    row.get("confidence"),
                                    row.get("source"),
                                    row.get("frame_path"),
                                    row.get("plate_path"),
                                    row.get("direction"),
                                ),
                            )
                        for row in lists_rows:
                            cur.execute(
                                "INSERT INTO plate_lists (id, name, type) VALUES (%s, %s, %s)",
                                (int(row["id"]), row["name"], row["type"]),
                            )
                        for row in entries_rows:
                            cur.execute(
                                "INSERT INTO plate_list_entries (id, list_id, plate, plate_normalized, comment) VALUES (%s, %s, %s, %s, %s)",
                                (
                                    int(row["id"]),
                                    int(row["list_id"]),
                                    row["plate"],
                                    row["plate_normalized"],
                                    row.get("comment"),
                                ),
                            )

                        cur.execute("SELECT setval('events_id_seq', COALESCE((SELECT MAX(id) FROM events), 1), TRUE)")
                        cur.execute("SELECT setval('plate_lists_id_seq', COALESCE((SELECT MAX(id) FROM plate_lists), 1), TRUE)")
                        cur.execute(
                            "SELECT setval('plate_list_entries_id_seq', COALESCE((SELECT MAX(id) FROM plate_list_entries), 1), TRUE)"
                        )
                        cur.execute("COMMIT")
            except Exception as exc:  # noqa: BLE001
                logger.exception("Ошибка восстановления PostgreSQL из бэкапа")
                raise StorageUnavailableError(f"Не удалось восстановить PostgreSQL из бэкапа: {exc}") from exc

            logger.warning(
                "База данных восстановлена из бэкапа: events=%d, lists=%d, entries=%d",
                len(events_rows),
                len(lists_rows),
                len(entries_rows),
            )
            return {
                "events": len(events_rows),
                "plate_lists": len(lists_rows),
                "plate_list_entries": len(entries_rows),
            }

    def export_settings_yaml(self) -> tuple[str, bytes]:
        path = Path(self._settings._repo.path)
        if not path.is_file():
            raise FileNotFoundError(f"Файл настроек не найден: {path}")
        content = path.read_bytes()
        filename = f"settings_backup_{self._timestamp_slug()}.yaml"
        logger.info("Экспортирован settings.yaml (%s)", path)
        return filename, content

    def restore_settings_yaml(self, raw_payload: bytes) -> None:
        try:
            text = raw_payload.decode("utf-8")
            parsed = yaml.safe_load(text)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Файл settings.yaml не является корректным YAML: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Файл settings.yaml должен содержать YAML-объект верхнего уровня")

        normalized, _changed = self._settings._normalizer.normalize_with_meta(parsed)
        self._settings._repo.save(normalized)
        self._settings.reload()
        logger.warning("settings.yaml восстановлен из пользовательского бэкапа")

    def _ensure_dsn(self) -> None:
        if not self._postgres_dsn:
            raise StorageUnavailableError("Не задан postgres_dsn для backup/restore")

    def _single_operation(self, operation_name: str):
        return _SingleOperationLock(self._op_lock, operation_name)


class _SingleOperationLock:
    def __init__(self, lock: threading.Lock, operation_name: str) -> None:
        self._lock = lock
        self._operation_name = operation_name

    def __enter__(self) -> None:
        if not self._lock.acquire(blocking=False):
            raise RuntimeError(f"Операция уже выполняется: {self._operation_name}")

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._lock.release()


def parse_database_backup_payload(raw_payload: bytes) -> Dict[str, Any]:
    """Валидация структуры db-бэкапа перед разрушительными действиями."""
    try:
        payload = json.loads(raw_payload.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Файл бэкапа не является корректным JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Файл бэкапа должен содержать JSON-объект")
    if payload.get("backup_kind") != _DB_BACKUP_KIND:
        raise ValueError("Неверный тип бэкапа: ожидается anpr_postgres_backup")
    if int(payload.get("format_version", 0)) != _BACKUP_FORMAT_VERSION:
        raise ValueError(f"Неподдерживаемая версия формата бэкапа: {payload.get('format_version')}")

    tables = payload.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("В бэкапе отсутствует секция tables")

    for table_name in ("events", "plate_lists", "plate_list_entries"):
        rows = tables.get(table_name)
        if not isinstance(rows, list):
            raise ValueError(f"Секция tables.{table_name} должна быть списком")

    for row in tables["events"]:
        if not isinstance(row, dict):
            raise ValueError("Каждая запись events должна быть объектом")
        for key in ("id", "timestamp", "channel", "plate"):
            if key not in row:
                raise ValueError(f"В записи events отсутствует обязательное поле '{key}'")

    for row in tables["plate_lists"]:
        if not isinstance(row, dict):
            raise ValueError("Каждая запись plate_lists должна быть объектом")
        for key in ("id", "name", "type"):
            if key not in row:
                raise ValueError(f"В записи plate_lists отсутствует обязательное поле '{key}'")

    for row in tables["plate_list_entries"]:
        if not isinstance(row, dict):
            raise ValueError("Каждая запись plate_list_entries должна быть объектом")
        for key in ("id", "list_id", "plate", "plate_normalized"):
            if key not in row:
                raise ValueError(f"В записи plate_list_entries отсутствует обязательное поле '{key}'")

    return payload


__all__ = ["BackupRestoreService", "parse_database_backup_payload"]
