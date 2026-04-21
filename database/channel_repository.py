from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from config.settings_schema import channel_defaults, direction_defaults, normalize_region_config
from database.base import PooledDatabase
from database.errors import StorageUnavailableError

_SELECT_COLS = (
    "id, name, source, enabled, roi_enabled, region, "
    "best_shots, cooldown_seconds, ocr_min_confidence, max_ocr_attempts, max_consecutive_empty_ocr, "
    "direction, detection_mode, detector_frame_stride, adaptive_stride_enabled, preview_fps_limit, "
    "motion_threshold, motion_frame_stride, motion_activation_frames, motion_release_frames, "
    "size_filter_enabled, min_plate_size, max_plate_size, "
    "controller_id, controller_relay, controller_direction_filter, list_filter_mode, list_filter_list_ids, "
    "zone_before_id, zone_after_id, channel_type"
)


def _load_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _row_to_dict(row: Any) -> Dict[str, Any]:
    return {
        "id": row[0],
        "name": row[1],
        "source": row[2],
        "enabled": row[3],
        "roi_enabled": row[4],
        "region": _load_json(row[5], {"unit": "px", "points": []}),
        "best_shots": row[6],
        "cooldown_seconds": row[7],
        "ocr_min_confidence": row[8],
        "max_ocr_attempts": row[9],
        "max_consecutive_empty_ocr": row[10],
        "direction": _load_json(row[11], {}),
        "detection_mode": row[12],
        "detector_frame_stride": row[13],
        "adaptive_stride_enabled": row[14],
        "preview_fps_limit": row[15],
        "motion_threshold": row[16],
        "motion_frame_stride": row[17],
        "motion_activation_frames": row[18],
        "motion_release_frames": row[19],
        "size_filter_enabled": row[20],
        "min_plate_size": _load_json(row[21], {"width": 80, "height": 20}),
        "max_plate_size": _load_json(row[22], {"width": 600, "height": 240}),
        "controller_id": row[23],
        "controller_relay": row[24],
        "controller_direction_filter": row[25],
        "list_filter_mode": row[26],
        "list_filter_list_ids": _load_json(row[27], []),
        "zone_before_id": row[28],
        "zone_after_id": row[29],
        "channel_type": row[30],
    }


def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    """Apply defaults and normalize all channel fields before storing."""
    defaults = channel_defaults({})
    result = dict(defaults)
    result.update(data)

    result["region"] = normalize_region_config(result.get("region"))

    dir_defaults = direction_defaults()
    direction = result.get("direction")
    if not isinstance(direction, dict):
        direction = {}
    for key, val in dir_defaults.items():
        if key not in direction:
            direction[key] = val
    result["direction"] = direction

    cid = result.get("controller_id")
    if cid in ("", 0, "0", None):
        cid = None
    else:
        try:
            cid = int(cid)
            if cid <= 0:
                cid = None
        except (TypeError, ValueError):
            cid = None
    result["controller_id"] = cid

    if cid is None:
        result["controller_relay"] = 0
    else:
        try:
            relay = int(result.get("controller_relay", 0) or 0)
        except (TypeError, ValueError):
            relay = 0
        result["controller_relay"] = relay if relay in (0, 1) else 0

    direction_filter = str(result.get("controller_direction_filter") or "both").strip().lower()
    if direction_filter not in {"approaching", "receding", "both"}:
        direction_filter = "both"
    result["controller_direction_filter"] = direction_filter

    mode = str(result.get("list_filter_mode") or "all").strip().lower()
    if mode not in {"all", "whitelist", "custom"}:
        mode = "all"
    result["list_filter_mode"] = mode

    raw_ids = result.get("list_filter_list_ids")
    if not isinstance(raw_ids, list):
        raw_ids = []
    ids: List[int] = []
    for item in raw_ids:
        try:
            v = int(item)
        except (TypeError, ValueError):
            continue
        if v > 0 and v not in ids:
            ids.append(v)
    result["list_filter_list_ids"] = ids

    def _normalize_zone_ref(value: Any) -> Optional[int]:
        if value in (None, "", "none"):
            return None
        try:
            zone_ref = int(value)
        except (TypeError, ValueError):
            return None
        if zone_ref < 0:
            return None
        return zone_ref

    result["zone_before_id"] = _normalize_zone_ref(result.get("zone_before_id"))
    result["zone_after_id"] = _normalize_zone_ref(result.get("zone_after_id"))

    channel_type = str(result.get("channel_type") or "").strip().lower()
    if channel_type not in ("entry", "exit"):
        channel_type = None
    if channel_type is None:
        result["zone_before_id"] = None
        result["zone_after_id"] = None
    result["channel_type"] = channel_type

    return result


class ChannelDatabase(PooledDatabase):
    """PostgreSQL repository for channels."""

    _SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    roi_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    region JSONB NOT NULL DEFAULT '{"unit":"px","points":[]}'::jsonb,
    best_shots INTEGER NOT NULL DEFAULT 3,
    cooldown_seconds INTEGER NOT NULL DEFAULT 5,
    ocr_min_confidence DOUBLE PRECISION NOT NULL DEFAULT 0.6,
    max_ocr_attempts INTEGER NOT NULL DEFAULT 15,
    max_consecutive_empty_ocr INTEGER NOT NULL DEFAULT 5,
    direction JSONB NOT NULL DEFAULT '{}'::jsonb,
    detection_mode TEXT NOT NULL DEFAULT 'motion',
    detector_frame_stride INTEGER NOT NULL DEFAULT 2,
    adaptive_stride_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    preview_fps_limit INTEGER NOT NULL DEFAULT 5,
    motion_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.01,
    motion_frame_stride INTEGER NOT NULL DEFAULT 1,
    motion_activation_frames INTEGER NOT NULL DEFAULT 3,
    motion_release_frames INTEGER NOT NULL DEFAULT 100,
    size_filter_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    min_plate_size JSONB NOT NULL DEFAULT '{"width":80,"height":20}'::jsonb,
    max_plate_size JSONB NOT NULL DEFAULT '{"width":600,"height":240}'::jsonb,
    controller_id INTEGER,
    controller_relay INTEGER NOT NULL DEFAULT 0,
    controller_direction_filter TEXT NOT NULL DEFAULT 'both',
    list_filter_mode TEXT NOT NULL DEFAULT 'all',
    list_filter_list_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    zone_before_id INTEGER,
    zone_after_id INTEGER,
    channel_type TEXT
);
"""

    def _schema_sql(self) -> str:
        return self._SCHEMA

    def list_channels(self) -> List[Dict[str, Any]]:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT {_SELECT_COLS} FROM channels ORDER BY id")
                    return [_row_to_dict(row) for row in cur.fetchall()]
        except StorageUnavailableError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def get_channel(self, channel_id: int) -> Optional[Dict[str, Any]]:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT {_SELECT_COLS} FROM channels WHERE id = %s", (int(channel_id),))
                    row = cur.fetchone()
                    return _row_to_dict(row) if row else None
        except StorageUnavailableError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def create_channel(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_schema()
        d = _normalize(data)
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO channels (
                            name, source, enabled, roi_enabled, region,
                            best_shots, cooldown_seconds, ocr_min_confidence, max_ocr_attempts,
                            max_consecutive_empty_ocr, direction, detection_mode,
                            detector_frame_stride, adaptive_stride_enabled, preview_fps_limit,
                            motion_threshold, motion_frame_stride, motion_activation_frames,
                            motion_release_frames, size_filter_enabled, min_plate_size, max_plate_size,
                            controller_id, controller_relay, controller_direction_filter,
                            list_filter_mode, list_filter_list_ids,
                            zone_before_id, zone_after_id, channel_type
                        ) VALUES (
                            %s, %s, %s, %s, %s::jsonb,
                            %s, %s, %s, %s,
                            %s, %s::jsonb, %s,
                            %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s::jsonb, %s::jsonb,
                            %s, %s, %s,
                            %s, %s::jsonb,
                            %s, %s
                        ) RETURNING {_SELECT_COLS}
                        """,
                        (
                            d["name"], d["source"], d["enabled"], d["roi_enabled"],
                            json.dumps(d["region"]),
                            d["best_shots"], d["cooldown_seconds"], d["ocr_min_confidence"],
                            d["max_ocr_attempts"],
                            d["max_consecutive_empty_ocr"], json.dumps(d["direction"]),
                            d["detection_mode"],
                            d["detector_frame_stride"], d["adaptive_stride_enabled"],
                            d["preview_fps_limit"],
                            d["motion_threshold"], d["motion_frame_stride"],
                            d["motion_activation_frames"],
                            d["motion_release_frames"], d["size_filter_enabled"],
                            json.dumps(d["min_plate_size"]), json.dumps(d["max_plate_size"]),
                            d["controller_id"], d["controller_relay"],
                            d["controller_direction_filter"],
                            d["list_filter_mode"], json.dumps(d["list_filter_list_ids"]),
                            d["zone_before_id"], d["zone_after_id"], d["channel_type"],
                        ),
                    )
                    row = cur.fetchone()
                conn.commit()
            return _row_to_dict(row)
        except StorageUnavailableError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def update_channel(self, channel_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Merge *data* into the existing channel and persist. Returns None if not found."""
        existing = self.get_channel(channel_id)
        if existing is None:
            return None
        merged = dict(existing)
        merged.update(data)
        d = _normalize(merged)
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        UPDATE channels SET
                            name=%s, source=%s, enabled=%s, roi_enabled=%s, region=%s::jsonb,
                            best_shots=%s, cooldown_seconds=%s, ocr_min_confidence=%s,
                            max_ocr_attempts=%s, max_consecutive_empty_ocr=%s,
                            direction=%s::jsonb, detection_mode=%s,
                            detector_frame_stride=%s, adaptive_stride_enabled=%s, preview_fps_limit=%s,
                            motion_threshold=%s, motion_frame_stride=%s, motion_activation_frames=%s,
                            motion_release_frames=%s, size_filter_enabled=%s,
                            min_plate_size=%s::jsonb, max_plate_size=%s::jsonb,
                            controller_id=%s, controller_relay=%s, controller_direction_filter=%s,
                            list_filter_mode=%s, list_filter_list_ids=%s::jsonb,
                            zone_before_id=%s, zone_after_id=%s, channel_type=%s
                        WHERE id=%s
                        RETURNING {_SELECT_COLS}
                        """,
                        (
                            d["name"], d["source"], d["enabled"], d["roi_enabled"],
                            json.dumps(d["region"]),
                            d["best_shots"], d["cooldown_seconds"], d["ocr_min_confidence"],
                            d["max_ocr_attempts"], d["max_consecutive_empty_ocr"],
                            json.dumps(d["direction"]), d["detection_mode"],
                            d["detector_frame_stride"], d["adaptive_stride_enabled"],
                            d["preview_fps_limit"],
                            d["motion_threshold"], d["motion_frame_stride"],
                            d["motion_activation_frames"],
                            d["motion_release_frames"], d["size_filter_enabled"],
                            json.dumps(d["min_plate_size"]), json.dumps(d["max_plate_size"]),
                            d["controller_id"], d["controller_relay"],
                            d["controller_direction_filter"],
                            d["list_filter_mode"], json.dumps(d["list_filter_list_ids"]),
                            d["zone_before_id"], d["zone_after_id"], d["channel_type"],
                            int(channel_id),
                        ),
                    )
                    row = cur.fetchone()
                conn.commit()
            return _row_to_dict(row) if row else None
        except StorageUnavailableError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def delete_channel(self, channel_id: int) -> bool:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM channels WHERE id = %s", (int(channel_id),))
                    deleted = cur.rowcount > 0
                conn.commit()
            return deleted
        except StorageUnavailableError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc


__all__ = ["ChannelDatabase"]
