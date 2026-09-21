"""Backup / restore helpers: business database (ZIP) and instance settings (JSON)."""

from __future__ import annotations

import io
import json
import threading
from datetime import datetime, timezone
from typing import Any, Dict
from zipfile import ZIP_DEFLATED, ZipFile

import psycopg
from psycopg import sql

from common.logging import get_logger
from database.errors import StorageUnavailableError

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
                query = sql.SQL("SELECT {fields} FROM {table}").format(
                    fields=sql.SQL(", ").join(sql.Identifier(c) for c in columns),
                    table=sql.Identifier(table),
                )
                cur.execute(query)
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
                    cur.execute(sql.SQL("DELETE FROM {table}").format(table=sql.Identifier(table)))

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
                col_identifiers = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
                placeholders = sql.SQL(", ").join(
                    sql.SQL("%s::jsonb") if col in jsonb_cols else sql.SQL("%s")
                    for col in columns
                )
                insert_query = sql.SQL("INSERT INTO {table} ({cols}) VALUES ({placeholders})").format(
                    table=sql.Identifier(table),
                    cols=col_identifiers,
                    placeholders=placeholders,
                )

                for row in rows:
                    values = []
                    for col in columns:
                        val = row.get(col)
                        if col in jsonb_cols and isinstance(val, (dict, list)):
                            val = json.dumps(val, ensure_ascii=False)
                        values.append(val)
                    cur.execute(insert_query, values)
                restored[table] = len(rows)

            # Reset sequences so new inserts get correct IDs
            for table in _BACKUP_TABLES:
                if table in tables:
                    cur.execute(
                        sql.SQL(
                            "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                            "COALESCE(MAX(id), 1)) FROM {table}"
                        ).format(table=sql.Identifier(table)),
                        (table,),
                    )
        conn.commit()

    logger.info("База данных восстановлена: %s", restored)
    return {"restored_tables": restored}


# ── Settings backup ─────────────────────────────────────────────
#
# The dump is the explicit overrides of app_settings as JSON. It is a different
# thing from the database backup above: `app_settings` is deliberately NOT in
# `_BACKUP_TABLES`, so restoring the database never overwrites instance
# configuration, and restoring settings never touches business data. Nothing
# here reads or writes the file system.

SETTINGS_DUMP_FORMAT = "anpr-app-settings"
SETTINGS_DUMP_VERSION = 1


def export_settings(service: Any) -> tuple[str, bytes]:
    """Return `(filename, JSON bytes)` with every explicitly stored setting."""
    values = service.stored_values()
    if not service.loaded or service.degraded:
        # A dump built from defaults or a stale cache would look valid and be wrong.
        raise StorageUnavailableError("настройки не удалось прочитать из БД — резервная копия не создана")
    now = datetime.now(timezone.utc)
    document = {
        "format": SETTINGS_DUMP_FORMAT,
        "version": SETTINGS_DUMP_VERSION,
        "exported_at": now.isoformat(),
        "settings": values,
    }
    body = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    return f"settings_{now.strftime('%Y%m%d_%H%M%S')}.json", body


def validate_settings_dump(data: bytes) -> Dict[str, Any]:
    """Parse and check a settings dump; return its `settings` mapping.

    Raises `ValueError` on malformed JSON, a foreign format or version, an
    unknown or reserved key, or a value the registry rejects — before anything
    is written. A YAML file (the old format) is not accepted.
    """
    from config.registry import ConfigClass, SettingValidationError, get_spec, specs

    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"Некорректный JSON: {exc}") from exc
    if not isinstance(document, dict) or document.get("format") != SETTINGS_DUMP_FORMAT:
        raise ValueError("Это не дамп настроек ANPR (ожидается формат " + SETTINGS_DUMP_FORMAT + ")")
    if document.get("version") != SETTINGS_DUMP_VERSION:
        raise ValueError(f"Неподдерживаемая версия дампа настроек: {document.get('version')!r}")
    values = document.get("settings")
    if not isinstance(values, dict):
        raise ValueError("В дампе нет объекта settings")

    allowed = {spec.key for spec in specs(ConfigClass.A) if not spec.reserved}
    unknown = sorted(key for key in values if key not in allowed)
    if unknown:
        raise ValueError("Дамп содержит неизвестные ключи настроек: " + ", ".join(unknown))
    checked: Dict[str, Any] = {}
    for key, value in values.items():
        try:
            checked[key] = get_spec(key).validate(value)
        except SettingValidationError as exc:
            raise ValueError(str(exc)) from exc
    return checked


def restore_settings(service: Any, data: bytes, updated_by: int | None = None) -> Dict[str, Any]:
    """Validate the dump, then make app_settings equal to it in one transaction."""
    values = validate_settings_dump(data)
    requires_restart = service.replace(values, updated_by=updated_by)
    return {"restored_keys": len(values), "requires_restart": requires_restart}


__all__ = [
    "export_database_backup",
    "export_settings",
    "get_restore_lock",
    "restore_database_backup",
    "restore_settings",
    "validate_database_backup",
    "validate_settings_dump",
]
