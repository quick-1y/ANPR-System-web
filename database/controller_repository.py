from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from config.settings_schema import SUPPORTED_CONTROLLER_TYPES, normalize_hotkey, relay_defaults
from database.base import PooledDatabase
from database.errors import StorageUnavailableError


def _load_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _normalize_relay(relay: Dict[str, Any]) -> Dict[str, Any]:
    defaults = relay_defaults()
    normalized = dict(defaults)
    normalized.update(relay or {})
    mode = str(normalized.get("mode", "pulse") or "pulse")
    if mode not in ("pulse", "pulse_timer"):
        mode = "pulse"
    normalized["mode"] = mode
    try:
        timer = int(normalized.get("timer_seconds", 1) or 1)
    except (TypeError, ValueError):
        timer = 1
    if mode == "pulse":
        timer = 1
    normalized["timer_seconds"] = max(1, timer)
    normalized["hotkey"] = normalize_hotkey(normalized.get("hotkey", ""), strict=False)
    return normalized


def _normalize_controller(data: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(data)

    controller_type = str(result.get("type") or "").strip()
    if not controller_type or controller_type not in SUPPORTED_CONTROLLER_TYPES:
        result["type"] = "DTWONDER2CH"

    if not result.get("name"):
        result["name"] = "Контроллер"
    result.setdefault("address", "")
    result.setdefault("password", "0")

    relays = result.get("relays")
    if not isinstance(relays, list) or len(relays) != 2:
        result["relays"] = [relay_defaults(), relay_defaults()]
    else:
        result["relays"] = [_normalize_relay(relay) for relay in relays[:2]]

    return result


def _row_to_dict(row: Any) -> Dict[str, Any]:
    return {
        "id": row[0],
        "name": row[1],
        "type": row[2],
        "address": row[3],
        "password": row[4],
        "relays": _load_json(row[5], [relay_defaults(), relay_defaults()]),
    }


class ControllerDatabase(PooledDatabase):
    """PostgreSQL repository for relay controllers."""

    _SCHEMA = """
CREATE TABLE IF NOT EXISTS controllers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'DTWONDER2CH',
    address TEXT NOT NULL DEFAULT '',
    password TEXT NOT NULL DEFAULT '0',
    relays JSONB NOT NULL DEFAULT '[{"mode":"pulse","timer_seconds":1,"hotkey":""},{"mode":"pulse","timer_seconds":1,"hotkey":""}]'::jsonb
);
"""

    def _schema_sql(self) -> str:
        return self._SCHEMA

    def list_controllers(self) -> List[Dict[str, Any]]:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, name, type, address, password, relays FROM controllers ORDER BY id"
                    )
                    return [_row_to_dict(row) for row in cur.fetchall()]
        except StorageUnavailableError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def get_controller(self, controller_id: int) -> Optional[Dict[str, Any]]:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, name, type, address, password, relays FROM controllers WHERE id = %s",
                        (int(controller_id),),
                    )
                    row = cur.fetchone()
                    return _row_to_dict(row) if row else None
        except StorageUnavailableError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def create_controller(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_schema()
        d = _normalize_controller(data)
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO controllers (name, type, address, password, relays) "
                        "VALUES (%s, %s, %s, %s, %s::jsonb) "
                        "RETURNING id, name, type, address, password, relays",
                        (d["name"], d["type"], d["address"], d["password"], json.dumps(d["relays"])),
                    )
                    row = cur.fetchone()
                conn.commit()
            return _row_to_dict(row)
        except StorageUnavailableError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def update_controller(self, controller_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Merge *data* into the existing controller and persist. Returns None if not found."""
        existing = self.get_controller(controller_id)
        if existing is None:
            return None
        merged = dict(existing)
        merged.update(data)
        d = _normalize_controller(merged)
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE controllers SET name=%s, type=%s, address=%s, password=%s, relays=%s::jsonb "
                        "WHERE id=%s "
                        "RETURNING id, name, type, address, password, relays",
                        (
                            d["name"], d["type"], d["address"], d["password"],
                            json.dumps(d["relays"]), int(controller_id),
                        ),
                    )
                    row = cur.fetchone()
                conn.commit()
            return _row_to_dict(row) if row else None
        except StorageUnavailableError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def delete_controller(self, controller_id: int) -> bool:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM controllers WHERE id = %s", (int(controller_id),))
                    deleted = cur.rowcount > 0
                conn.commit()
            return deleted
        except StorageUnavailableError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc


__all__ = ["ControllerDatabase"]
