"""Tests for zone-related fields in database/channel_repository.py

Covers:
  - _normalize: zone_id coercion and validation
  - _normalize: zone_channel_type validation (entry/exit only)
  - _normalize: zone_channel_type cleared when zone_id is None
  - Schema SQL contains zone_id and zone_channel_type columns
  - create_channel and update_channel include zone fields in SQL
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from database.channel_repository import ChannelDatabase, _normalize


# ---------------------------------------------------------------------------
# _normalize — zone_id
# ---------------------------------------------------------------------------

class TestNormalizeZoneId:
    def _base(self, **overrides):
        data = {
            "name": "Тест",
            "source": "0",
            "enabled": True,
            "roi_enabled": False,
            "region": {"unit": "percent", "points": []},
            "detection_mode": "motion",
            "motion_threshold": 0.01,
            "motion_frame_stride": 1,
            "motion_activation_frames": 3,
            "motion_release_frames": 6,
            "detector_frame_stride": 2,
            "adaptive_stride_enabled": True,
            "size_filter_enabled": False,
            "min_plate_size": {"width": 80, "height": 20},
            "max_plate_size": {"width": 600, "height": 240},
            "best_shots": 3,
            "cooldown_seconds": 5,
            "ocr_min_confidence": 0.6,
            "max_ocr_attempts": 15,
            "max_consecutive_empty_ocr": 5,
            "preview_fps_limit": 5,
            "controller_id": None,
            "controller_relay": 0,
            "controller_direction_filter": "both",
            "list_filter_mode": "all",
            "list_filter_list_ids": [],
            "zone_id": None,
            "zone_channel_type": None,
        }
        data.update(overrides)
        return data

    def test_none_zone_id_stays_none(self):
        result = _normalize(self._base(zone_id=None))
        assert result["zone_id"] is None

    def test_zero_zone_id_becomes_none(self):
        result = _normalize(self._base(zone_id=0))
        assert result["zone_id"] is None

    def test_empty_string_zone_id_becomes_none(self):
        result = _normalize(self._base(zone_id=""))
        assert result["zone_id"] is None

    def test_string_zero_zone_id_becomes_none(self):
        result = _normalize(self._base(zone_id="0"))
        assert result["zone_id"] is None

    def test_negative_zone_id_becomes_none(self):
        result = _normalize(self._base(zone_id=-1))
        assert result["zone_id"] is None

    def test_valid_positive_zone_id_preserved(self):
        result = _normalize(self._base(zone_id=3))
        assert result["zone_id"] == 3

    def test_string_positive_zone_id_cast_to_int(self):
        result = _normalize(self._base(zone_id="5"))
        assert result["zone_id"] == 5

    def test_non_numeric_zone_id_becomes_none(self):
        result = _normalize(self._base(zone_id="abc"))
        assert result["zone_id"] is None


# ---------------------------------------------------------------------------
# _normalize — zone_channel_type
# ---------------------------------------------------------------------------

class TestNormalizeZoneChannelType:
    def _base(self, zone_id=1, zone_channel_type=None):
        return {
            "name": "Тест", "source": "0", "enabled": True,
            "roi_enabled": False, "region": {"unit": "percent", "points": []},
            "detection_mode": "motion", "motion_threshold": 0.01,
            "motion_frame_stride": 1, "motion_activation_frames": 3,
            "motion_release_frames": 6, "detector_frame_stride": 2,
            "adaptive_stride_enabled": True, "size_filter_enabled": False,
            "min_plate_size": {"width": 80, "height": 20},
            "max_plate_size": {"width": 600, "height": 240},
            "best_shots": 3, "cooldown_seconds": 5,
            "ocr_min_confidence": 0.6, "max_ocr_attempts": 15,
            "max_consecutive_empty_ocr": 5, "preview_fps_limit": 5,
            "controller_id": None, "controller_relay": 0,
            "controller_direction_filter": "both",
            "list_filter_mode": "all", "list_filter_list_ids": [],
            "zone_id": zone_id, "zone_channel_type": zone_channel_type,
        }

    def test_entry_is_valid(self):
        result = _normalize(self._base(zone_id=1, zone_channel_type="entry"))
        assert result["zone_channel_type"] == "entry"

    def test_exit_is_valid(self):
        result = _normalize(self._base(zone_id=1, zone_channel_type="exit"))
        assert result["zone_channel_type"] == "exit"

    def test_invalid_type_becomes_none(self):
        result = _normalize(self._base(zone_id=1, zone_channel_type="both"))
        assert result["zone_channel_type"] is None

    def test_empty_string_becomes_none(self):
        result = _normalize(self._base(zone_id=1, zone_channel_type=""))
        assert result["zone_channel_type"] is None

    def test_uppercase_entry_normalised(self):
        result = _normalize(self._base(zone_id=1, zone_channel_type="ENTRY"))
        assert result["zone_channel_type"] == "entry"

    def test_type_cleared_when_zone_id_is_none(self):
        result = _normalize(self._base(zone_id=None, zone_channel_type="entry"))
        assert result["zone_channel_type"] is None

    def test_type_cleared_when_zone_id_is_zero(self):
        result = _normalize(self._base(zone_id=0, zone_channel_type="exit"))
        assert result["zone_channel_type"] is None


# ---------------------------------------------------------------------------
# Schema SQL contains zone columns
# ---------------------------------------------------------------------------

class TestSchemaContainsZoneColumns:
    def _schema(self) -> str:
        db = object.__new__(ChannelDatabase)
        return db._schema_sql()

    def test_zone_id_column_present(self):
        assert "zone_id" in self._schema()

    def test_zone_channel_type_column_present(self):
        assert "zone_channel_type" in self._schema()


# ---------------------------------------------------------------------------
# create_channel and update_channel include zone fields
# ---------------------------------------------------------------------------

def _make_db() -> ChannelDatabase:
    db = object.__new__(ChannelDatabase)
    db._dsn = "postgresql://mock"
    db._initialized = True
    db._init_lock = threading.Lock()
    db._pool = None
    return db


def _mock_conn(fetchone=None, fetchall=None, rowcount=1):
    cursor = MagicMock()
    cursor.__enter__ = lambda s: s
    cursor.__exit__ = MagicMock(return_value=False)
    cursor.fetchone.return_value = fetchone
    cursor.fetchall.return_value = fetchall or []
    cursor.rowcount = rowcount

    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cursor
    conn.commit = MagicMock()
    return conn, cursor


def _channel_row(
    id=1, name="Cam", source="0", enabled=True, roi_enabled=False,
    region=None, best_shots=3, cooldown_seconds=5,
    ocr_min_confidence=0.6, max_ocr_attempts=15, max_consecutive_empty_ocr=5,
    direction=None, detection_mode="motion", detector_frame_stride=2,
    adaptive_stride_enabled=True, preview_fps_limit=5,
    motion_threshold=0.01, motion_frame_stride=1,
    motion_activation_frames=3, motion_release_frames=6,
    size_filter_enabled=False, min_plate_size=None, max_plate_size=None,
    controller_id=None, controller_relay=0, controller_direction_filter="both",
    list_filter_mode="all", list_filter_list_ids="[]",
    zone_id=None, zone_channel_type=None,
):
    """Build a mock DB row matching the channel_repository _SELECT_COLS column order."""
    import json
    return (
        id, name, source, enabled, roi_enabled,
        json.dumps(region or {"unit": "percent", "points": []}),
        best_shots, cooldown_seconds, ocr_min_confidence,
        max_ocr_attempts, max_consecutive_empty_ocr,
        json.dumps(direction or {}),
        detection_mode, detector_frame_stride, adaptive_stride_enabled, preview_fps_limit,
        motion_threshold, motion_frame_stride, motion_activation_frames, motion_release_frames,
        size_filter_enabled,
        json.dumps(min_plate_size or {"width": 80, "height": 20}),
        json.dumps(max_plate_size or {"width": 600, "height": 240}),
        controller_id, controller_relay, controller_direction_filter,
        list_filter_mode, list_filter_list_ids,
        zone_id, zone_channel_type,
    )


def _full_channel_data(**overrides):
    """Minimal complete data dict accepted by create_channel / update_channel."""
    data = {"name": "Тест", "source": "0", "enabled": True}
    data.update(overrides)
    return data


class TestCreateChannelZoneFields:
    def test_create_channel_with_zone(self):
        db = _make_db()
        row = _channel_row(zone_id=2, zone_channel_type="entry")
        conn, cursor = _mock_conn(fetchone=row)
        with patch.object(db, "_connect", return_value=conn):
            result = db.create_channel(_full_channel_data(zone_id=2, zone_channel_type="entry"))
        assert result["zone_id"] == 2
        assert result["zone_channel_type"] == "entry"

    def test_create_sql_includes_zone_columns(self):
        db = _make_db()
        row = _channel_row()
        conn, cursor = _mock_conn(fetchone=row)
        with patch.object(db, "_connect", return_value=conn):
            db.create_channel(_full_channel_data())
        sql = cursor.execute.call_args[0][0]
        assert "zone_id" in sql
        assert "zone_channel_type" in sql


class TestUpdateChannelZoneFields:
    def test_update_sql_includes_zone_columns(self):
        db = _make_db()
        existing_row = _channel_row(zone_id=None, zone_channel_type=None)
        updated_row = _channel_row(zone_id=3, zone_channel_type="exit")
        conn, cursor = _mock_conn(fetchone=existing_row)
        # get_channel (called internally) and update both use _connect;
        # supply two sequential fetchone returns
        cursor.fetchone.side_effect = [existing_row, updated_row]
        with patch.object(db, "_connect", return_value=conn):
            db.update_channel(1, {"name": "Выезд", "source": "0", "zone_id": 3, "zone_channel_type": "exit"})
        calls = [c[0][0] for c in cursor.execute.call_args_list]
        update_sql = next((s for s in calls if "UPDATE" in s.upper()), "")
        assert "zone_id" in update_sql
        assert "zone_channel_type" in update_sql

    def test_update_returns_none_when_not_found(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=None)
        with patch.object(db, "_connect", return_value=conn):
            result = db.update_channel(999, {"name": "X", "source": "0"})
        assert result is None
