"""Backup & restore service for PostgreSQL database and settings.yaml."""

from __future__ import annotations

import copy
import io
import json
import os
import threading
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import yaml

from common.logging import get_logger
from config.settings_normalizer import SettingsNormalizer
from database.errors import StorageUnavailableError

logger = get_logger(__name__)

BACKUP_FORMAT_VERSION = 1
BACKUP_TYPE_DATABASE = "database"
BACKUP_TYPE_SETTINGS = "settings"


class BackupLock:
    """Single-flight lock for restore operations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: Optional[str] = None

    def acquire(self, operation: str) -> bool:
        with self._lock:
            if self._active is not None:
                return False
            self._active = operation
            return True

    def release(self) -> None:
        with self._lock:
            self._active = None

    @property
    def active_operation(self) -> Optional[str]:
        with self._lock:
            return self._active


_restore_lock = BackupLock()


def get_restore_lock() -> BackupLock:
    return _restore_lock


def _build_manifest(backup_type: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    manifest: Dict[str, Any] = {
        "format_version": BACKUP_FORMAT_VERSION,
        "backup_type": backup_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "app_version": os.getenv("APP_VERSION", "0.8"),
    }
    if extra:
        manifest.update(extra)
    return manifest


def export_database_backup(dsn: str) -> Tuple[str, bytes]:
    """Export full PostgreSQL database as a ZIP with SQL dump + manifest."""
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(dsn, min_size=1, max_size=2, open=True)
    try:
        tables_data: Dict[str, Any] = {}
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                )
                tables = [row[0] for row in cur.fetchall()]

            for table in tables:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = %s "
                        "ORDER BY ordinal_position",
                        (table,),
                    )
                    columns = [(row[0], row[1]) for row in cur.fetchall()]

                with conn.cursor() as cur:
                    col_names = [c[0] for c in columns]
                    cur.execute(f'SELECT {", ".join(col_names)} FROM "{table}"')  # noqa: S608
                    rows = cur.fetchall()

                serialized_rows = []
                for row in rows:
                    serialized_row = []
                    for val in row:
                        if isinstance(val, datetime):
                            serialized_row.append(val.isoformat())
                        elif val is None:
                            serialized_row.append(None)
                        else:
                            serialized_row.append(val)
                    serialized_rows.append(serialized_row)

                tables_data[table] = {
                    "columns": [{"name": c[0], "type": c[1]} for c in columns],
                    "rows": serialized_rows,
                    "row_count": len(serialized_rows),
                }

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT sequencename FROM pg_sequences WHERE schemaname = 'public'"
                )
                sequences = [row[0] for row in cur.fetchall()]

            sequence_values: Dict[str, int] = {}
            for seq in sequences:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT last_value FROM \"{seq}\"")  # noqa: S608
                    row = cur.fetchone()
                    if row:
                        sequence_values[seq] = row[0]

        dump_data = {
            "tables": tables_data,
            "sequences": sequence_values,
        }

        manifest = _build_manifest(
            BACKUP_TYPE_DATABASE,
            {"table_count": len(tables), "total_rows": sum(t["row_count"] for t in tables_data.values())},
        )

        buf = io.BytesIO()
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            zf.writestr("dump.json", json.dumps(dump_data, indent=2, ensure_ascii=False, default=str))

        filename = f"anpr_db_backup_{ts}.zip"
        return filename, buf.getvalue()
    finally:
        pool.close()


def validate_database_backup(data: bytes) -> Dict[str, Any]:
    """Validate uploaded DB backup file. Returns manifest on success, raises on failure."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("Загруженный файл не является корректным ZIP-архивом")

    names = zf.namelist()
    if "manifest.json" not in names:
        raise ValueError("Архив не содержит manifest.json — это не бэкап ANPR")
    if "dump.json" not in names:
        raise ValueError("Архив не содержит dump.json — данные бэкапа отсутствуют")

    try:
        manifest = json.loads(zf.read("manifest.json"))
    except (json.JSONDecodeError, KeyError):
        raise ValueError("manifest.json повреждён или имеет неверный формат")

    if not isinstance(manifest, dict):
        raise ValueError("manifest.json должен содержать JSON-объект")

    if manifest.get("backup_type") != BACKUP_TYPE_DATABASE:
        raise ValueError(
            f"Тип бэкапа '{manifest.get('backup_type')}' не является бэкапом базы данных"
        )

    fmt_ver = manifest.get("format_version")
    if not isinstance(fmt_ver, int) or fmt_ver > BACKUP_FORMAT_VERSION:
        raise ValueError(
            f"Неподдерживаемая версия формата бэкапа: {fmt_ver}. "
            f"Максимально поддерживаемая: {BACKUP_FORMAT_VERSION}"
        )

    try:
        dump = json.loads(zf.read("dump.json"))
    except (json.JSONDecodeError, KeyError):
        raise ValueError("dump.json повреждён или имеет неверный формат")

    if not isinstance(dump, dict) or "tables" not in dump:
        raise ValueError("dump.json не содержит данных таблиц")

    return manifest


def restore_database_backup(dsn: str, data: bytes) -> Dict[str, Any]:
    """Restore database from backup ZIP. Returns summary dict."""
    manifest = validate_database_backup(data)

    zf = zipfile.ZipFile(io.BytesIO(data))
    dump = json.loads(zf.read("dump.json"))
    tables_data = dump.get("tables", {})
    sequence_values = dump.get("sequences", {})

    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                )
                existing_tables = [row[0] for row in cur.fetchall()]

            with conn.cursor() as cur:
                for table in existing_tables:
                    cur.execute(f'TRUNCATE TABLE "{table}" CASCADE')  # noqa: S608
            conn.commit()

            for table_name, table_info in tables_data.items():
                columns = table_info.get("columns", [])
                rows = table_info.get("rows", [])
                if not columns or not rows:
                    continue

                col_names = [c["name"] for c in columns]
                placeholders = ", ".join(["%s"] * len(col_names))
                col_list = ", ".join(f'"{c}"' for c in col_names)

                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename = %s",
                        (table_name,),
                    )
                    if not cur.fetchone():
                        logger.warning("Таблица '%s' из бэкапа не существует в текущей схеме, пропускаем", table_name)
                        continue

                insert_sql = f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})'  # noqa: S608
                with conn.cursor() as cur:
                    for row in rows:
                        try:
                            cur.execute(insert_sql, tuple(row))
                        except Exception as exc:
                            logger.warning("Ошибка вставки строки в %s: %s", table_name, exc)
                            conn.rollback()
                            raise ValueError(f"Ошибка восстановления таблицы {table_name}: {exc}") from exc

            for seq_name, last_val in sequence_values.items():
                with conn.cursor() as cur:
                    try:
                        cur.execute(f"SELECT setval('\"{seq_name}\"', %s, true)", (last_val,))  # noqa: S608
                    except Exception:
                        try:
                            cur.execute(f"SELECT setval('{seq_name}', %s, true)", (last_val,))  # noqa: S608
                        except Exception as exc:
                            logger.warning("Не удалось восстановить sequence %s: %s", seq_name, exc)

            conn.commit()

        return {
            "tables_restored": len(tables_data),
            "backup_created_at": manifest.get("created_at"),
        }
    finally:
        pool.close()


def export_settings(settings_path: str) -> Tuple[str, bytes]:
    """Export current settings.yaml as raw bytes."""
    if not os.path.exists(settings_path):
        raise FileNotFoundError("Файл настроек не найден")

    with open(settings_path, "r", encoding="utf-8") as f:
        content = f.read()

    return "settings.yaml", content.encode("utf-8")


def validate_settings_yaml(data: bytes) -> Dict[str, Any]:
    """Parse and validate uploaded settings YAML. Returns parsed dict."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("Файл настроек должен быть в кодировке UTF-8")

    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Некорректный YAML: {exc}")

    if parsed is None:
        raise ValueError("Файл настроек пуст")

    if not isinstance(parsed, dict):
        raise ValueError("Файл настроек должен содержать YAML-объект (словарь) на верхнем уровне")

    normalizer = SettingsNormalizer()
    try:
        normalized, _ = normalizer.normalize_with_meta(parsed)
    except Exception as exc:
        raise ValueError(f"Ошибка валидации настроек: {exc}")

    return normalized


def restore_settings(repo: Any, normalizer_cls: type, raw_data: bytes) -> Dict[str, Any]:
    """Validate and atomically save uploaded settings using existing repository."""
    normalized = validate_settings_yaml(raw_data)
    repo.save(normalized)
    return normalized
