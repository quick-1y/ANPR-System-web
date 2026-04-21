"""Tests for zone movement fields in database/channel_repository.py."""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from database.channel_repository import ChannelDatabase, _normalize


class TestNormalizeZoneRefs:
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
            "zone_before_id": None,
            "zone_after_id": None,
            "channel_type": None,
        }
        data.update(overrides)
        return data

    def test_zero_is_valid_outside_zone(self):
        result = _normalize(self._base(zone_before_id=0, zone_after_id=3, channel_type="entry"))
        assert result["zone_before_id"] == 0
        assert result["zone_after_id"] == 3

    def test_negative_becomes_none(self):
        result = _normalize(self._base(zone_before_id=-1, zone_after_id=2, channel_type="entry"))
        assert result["zone_before_id"] is None

    def test_non_numeric_becomes_none(self):
        result = _normalize(self._base(zone_before_id="abc", zone_after_id=2, channel_type="entry"))
        assert result["zone_before_id"] is None


class TestNormalizeChannelType:
    def _base(self, channel_type=None):
        return {
            "name": "Тест", "source": "0", "enabled": True,
            "zone_before_id": 0, "zone_after_id": 1, "channel_type": channel_type,
        }

    def test_entry_is_valid(self):
        result = _normalize(self._base(channel_type="entry"))
        assert result["channel_type"] == "entry"

    def test_exit_is_valid(self):
        result = _normalize(self._base(channel_type="exit"))
        assert result["channel_type"] == "exit"

    def test_invalid_type_becomes_none_and_clears_zones(self):
        result = _normalize(self._base(channel_type="both"))
        assert result["channel_type"] is None
        assert result["zone_before_id"] is None
        assert result["zone_after_id"] is None


class TestSchemaContainsZoneColumns:
    def _schema(self) -> str:
        db = object.__new__(ChannelDatabase)
        return db._schema_sql()

    def test_zone_before_id_column_present(self):
        assert "zone_before_id" in self._schema()

    def test_zone_after_id_column_present(self):
        assert "zone_after_id" in self._schema()

    def test_channel_type_column_present(self):
        assert "channel_type" in self._schema()


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
    zone_before_id=None, zone_after_id=None, channel_type=None,
):
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
        zone_before_id, zone_after_id, channel_type,
    )


def _full_channel_data(**overrides):
    data = {"name": "Тест", "source": "0", "enabled": True}
    data.update(overrides)
    return data


class TestCreateChannelZoneFields:
    def test_create_channel_with_zone_movement(self):
        db = _make_db()
        row = _channel_row(zone_before_id=0, zone_after_id=2, channel_type="entry")
        conn, _ = _mock_conn(fetchone=row)
        with patch.object(db, "_connect", return_value=conn):
            result = db.create_channel(_full_channel_data(zone_before_id=0, zone_after_id=2, channel_type="entry"))
        assert result["zone_before_id"] == 0
        assert result["zone_after_id"] == 2
        assert result["channel_type"] == "entry"


class TestUpdateChannelZoneFields:
    def test_update_sql_includes_zone_movement_columns(self):
        db = _make_db()
        existing_row = _channel_row(zone_before_id=None, zone_after_id=None, channel_type=None)
        updated_row = _channel_row(zone_before_id=3, zone_after_id=0, channel_type="exit")
        conn, cursor = _mock_conn(fetchone=existing_row)
        cursor.fetchone.side_effect = [existing_row, updated_row]
        with patch.object(db, "_connect", return_value=conn):
            db.update_channel(1, {"name": "Выезд", "source": "0", "zone_before_id": 3, "zone_after_id": 0, "channel_type": "exit"})
        calls = [c[0][0] for c in cursor.execute.call_args_list]
        update_sql = next((s for s in calls if "UPDATE" in s.upper()), "")
        assert "zone_before_id" in update_sql
        assert "zone_after_id" in update_sql
        assert "channel_type" in update_sql
