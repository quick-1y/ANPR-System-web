"""Backup / restore helpers for database and settings."""

from __future__ import annotations

import io
import json
import threading
from datetime import datetime, timezone
from typing import Any, Dict
from zipfile import ZIP_DEFLATED, ZipFile

import psycopg
import yaml

from common.logging import get_logger

logger = get_logger(__name__)

# ── Tables included in the database backup ──────────────────────
# Order matters: parents before children for INSERT, reversed for DELETE.
# FK constraints: clients.list_id -> lists.id
# channels.controller_id is an INTEGER with no FK constraint in the schema.
_BACKUP_TABLES = ("controllers", "users", "lists", "channels", "clients", "events")

_BACKUP_MANIFEST_VERSION = 1


# ── Restore lock ────────────────────────────────────────────────

class _RestoreLock:
    """Simple reentrant-safe lock so only one restore runs at a time."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner: str | None = None

    def acquire(self, name: str) -> bool:
        if self._lock.acquire(blocking=False):
            self._owner = name
            return True
        return False

    def release(self) -> None:
        self._owner = None
        try:
            self._lock.release()
        except RuntimeError:
            pass


_restore_lock = _RestoreLock()


def get_restore_lock() -> _RestoreLock:
    return _restore_lock


# ── Database backup ─────────────────────────────────────────────

def export_database_backup(dsn: str) -> tuple[str, bytes]:
    """Export all application tables as a ZIP containing JSON per table."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"db_backup_{ts}.zip"

    tables_data: Dict[str, list[Dict[str, Any]]] = {}

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for table in _BACKUP_TABLES:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = %s ORDER BY ordinal_position",
                    (table,),
                )
                columns = [row[0] for row in cur.fetchall()]
                if not columns:
                    continue
                cur.execute(f"SELECT {', '.join(columns)} FROM {table}")  # noqa: S608
                rows = []
                for row in cur.fetchall():
                    record: Dict[str, Any] = {}
                    for col, val in zip(columns, row):
                        if isinstance(val, datetime):
                            val = val.isoformat()
                        record[col] = val
                    rows.append(record)
                tables_data[table] = rows

    manifest = {
        "version": _BACKUP_MANIFEST_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tables": list(tables_data.keys()),
    }

    buf = io.BytesIO()
    with ZipFile(buf, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for table, rows in tables_data.items():
            zf.writestr(f"{table}.json", json.dumps(rows, ensure_ascii=False, default=str))
    return filename, buf.getvalue()


def validate_database_backup(data: bytes) -> None:
    """Raise ValueError if *data* is not a valid database backup ZIP."""
    try:
        zf = ZipFile(io.BytesIO(data), "r")
    except Exception as exc:
        raise ValueError(f"Файл не является корректным ZIP-архивом: {exc}") from exc

    if "manifest.json" not in zf.namelist():
        raise ValueError("Архив не содержит manifest.json — это не бэкап базы данных")

    try:
        manifest = json.loads(zf.read("manifest.json"))
    except Exception as exc:
        raise ValueError(f"Невозможно прочитать manifest.json: {exc}") from exc

    if manifest.get("version") != _BACKUP_MANIFEST_VERSION:
        raise ValueError(
            f"Неподдерживаемая версия бэкапа: {manifest.get('version')} "
            f"(ожидается {_BACKUP_MANIFEST_VERSION})"
        )


def _fetch_jsonb_columns(cur: Any, table: str) -> frozenset[str]:
    """Return the set of column names whose data type is jsonb for *table*."""
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND udt_name = 'jsonb'",
        (table,),
    )
    return frozenset(row[0] for row in cur.fetchall())


def restore_database_backup(dsn: str, data: bytes) -> Dict[str, Any]:
    """Restore tables from a backup ZIP.  Returns a summary dict."""
    zf = ZipFile(io.BytesIO(data), "r")
    manifest = json.loads(zf.read("manifest.json"))
    tables = manifest.get("tables", [])

    restored: Dict[str, int] = {}

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            # Delete children before parents to respect FK constraints
            for table in reversed(_BACKUP_TABLES):
                if table in tables:
                    cur.execute(f"DELETE FROM {table}")  # noqa: S608

            for table in _BACKUP_TABLES:
                if table not in tables:
                    continue
                raw = zf.read(f"{table}.json")
                rows = json.loads(raw)
                if not rows:
                    restored[table] = 0
                    continue

                jsonb_cols = _fetch_jsonb_columns(cur, table)
                columns = list(rows[0].keys())
                col_names = ", ".join(columns)
                placeholders = ", ".join(
                    f"%s::jsonb" if col in jsonb_cols else "%s"  # noqa: S608
                    for col in columns
                )

                for row in rows:
                    values = []
                    for col in columns:
                        val = row.get(col)
                        if col in jsonb_cols and isinstance(val, (dict, list)):
                            val = json.dumps(val, ensure_ascii=False)
                        values.append(val)
                    cur.execute(
                        f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",  # noqa: S608
                        values,
                    )
                restored[table] = len(rows)

            # Reset sequences so new inserts get correct IDs
            for table in _BACKUP_TABLES:
                if table in tables:
                    cur.execute(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "  # noqa: S608
                        f"COALESCE(MAX(id), 1)) FROM {table}"
                    )
        conn.commit()

    logger.info("База данных восстановлена: %s", restored)
    return {"restored_tables": restored}


# ── Settings backup ─────────────────────────────────────────────

def export_settings(settings_path: str) -> tuple[str, bytes]:
    """Read the settings YAML and return (filename, raw bytes)."""
    import os

    if not os.path.isfile(settings_path):
        raise FileNotFoundError(f"Файл настроек не найден: {settings_path}")

    with open(settings_path, "r", encoding="utf-8") as f:
        body = f.read()

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"settings_{ts}.yaml"
    return filename, body.encode("utf-8")


def validate_settings_yaml(data: bytes) -> None:
    """Raise ValueError if *data* is not valid YAML with a dict root."""
    try:
        parsed = yaml.safe_load(data)
    except yaml.YAMLError as exc:
        raise ValueError(f"Некорректный YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Файл настроек должен содержать YAML-объект (словарь)")


def restore_settings(repo: Any, normalizer_class: type, data: bytes) -> Dict[str, Any]:
    """Write *data* to the settings file, normalizing via *normalizer_class*."""
    parsed = yaml.safe_load(data)
    if not isinstance(parsed, dict):
        raise ValueError("Файл настроек должен содержать YAML-объект (словарь)")

    normalizer = normalizer_class()
    normalized = normalizer.normalize(parsed)
    repo.save(normalized)
    return normalized


__all__ = [
    "export_database_backup",
    "export_settings",
    "get_restore_lock",
    "restore_database_backup",
    "restore_settings",
    "validate_database_backup",
    "validate_settings_yaml",
]
