"""Tests for database/zones_repository.py

Covers ZoneDatabase logic without a live PostgreSQL connection:
  - list_zones, get_zone, create_zone, update_zone
  - delete_zone: cascade clears channels, then deletes zone
  - get_channels_for_zone
  - get_zone_occupancy: counts only open entries (time_exit IS NULL)
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, call, patch

import pytest

from database.zones_repository import ZoneDatabase


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_db() -> ZoneDatabase:
    db = object.__new__(ZoneDatabase)
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


# ---------------------------------------------------------------------------
# list_zones
# ---------------------------------------------------------------------------

class TestListZones:
    def test_returns_all_rows(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchall=[(1, "Парковка А", 50), (2, "Парковка Б", 20)])
        with patch.object(db, "_connect", return_value=conn):
            result = db.list_zones()
        assert len(result) == 2
        assert result[0] == {"id": 1, "name": "Парковка А", "capacity": 50}
        assert result[1] == {"id": 2, "name": "Парковка Б", "capacity": 20}

    def test_returns_empty_list_when_no_zones(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchall=[])
        with patch.object(db, "_connect", return_value=conn):
            result = db.list_zones()
        assert result == []

    def test_query_orders_by_id(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchall=[])
        with patch.object(db, "_connect", return_value=conn):
            db.list_zones()
        sql = cursor.execute.call_args[0][0]
        assert "ORDER BY id" in sql


# ---------------------------------------------------------------------------
# get_zone
# ---------------------------------------------------------------------------

class TestGetZone:
    def test_returns_zone_dict_when_found(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(3, "Внутренняя", 10))
        with patch.object(db, "_connect", return_value=conn):
            result = db.get_zone(3)
        assert result == {"id": 3, "name": "Внутренняя", "capacity": 10}

    def test_returns_none_when_not_found(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=None)
        with patch.object(db, "_connect", return_value=conn):
            result = db.get_zone(999)
        assert result is None

    def test_query_filters_by_id(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=None)
        with patch.object(db, "_connect", return_value=conn):
            db.get_zone(7)
        sql, params = cursor.execute.call_args[0]
        assert "WHERE id = %s" in sql
        assert params == (7,)


# ---------------------------------------------------------------------------
# create_zone
# ---------------------------------------------------------------------------

class TestCreateZone:
    def test_returns_new_id(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(42,))
        with patch.object(db, "_connect", return_value=conn):
            result = db.create_zone("Парковка В", 30)
        assert result == 42

    def test_commits_transaction(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(1,))
        with patch.object(db, "_connect", return_value=conn):
            db.create_zone("Тест", 0)
        conn.commit.assert_called_once()

    def test_insert_uses_name_and_capacity(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(5,))
        with patch.object(db, "_connect", return_value=conn):
            db.create_zone("Северная", 100)
        sql, params = cursor.execute.call_args[0]
        assert "INSERT INTO zones" in sql
        assert params == ("Северная", 100)

    def test_returns_zero_when_no_row_returned(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=None)
        with patch.object(db, "_connect", return_value=conn):
            result = db.create_zone("Пустая", 0)
        assert result == 0


# ---------------------------------------------------------------------------
# update_zone
# ---------------------------------------------------------------------------

class TestUpdateZone:
    def test_returns_true_when_updated(self):
        db = _make_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            result = db.update_zone(1, "Новое имя", 60)
        assert result is True

    def test_returns_false_when_not_found(self):
        db = _make_db()
        conn, cursor = _mock_conn(rowcount=0)
        with patch.object(db, "_connect", return_value=conn):
            result = db.update_zone(999, "X", 0)
        assert result is False

    def test_update_sql_sets_name_and_capacity(self):
        db = _make_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            db.update_zone(2, "Изменённая", 75)
        sql, params = cursor.execute.call_args[0]
        assert "UPDATE zones" in sql
        assert "name = %s" in sql
        assert "capacity = %s" in sql
        assert params == ("Изменённая", 75, 2)

    def test_commits_transaction(self):
        db = _make_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            db.update_zone(1, "Имя", 10)
        conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# delete_zone
# ---------------------------------------------------------------------------

class TestDeleteZone:
    def test_returns_true_when_deleted(self):
        db = _make_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            result = db.delete_zone(1)
        assert result is True

    def test_returns_false_when_not_found(self):
        db = _make_db()
        conn, cursor = _mock_conn(rowcount=0)
        with patch.object(db, "_connect", return_value=conn):
            result = db.delete_zone(999)
        assert result is False

    def test_cascade_clears_channels_before_delete(self):
        db = _make_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            db.delete_zone(3)
        calls = [c[0][0] for c in cursor.execute.call_args_list]
        assert len(calls) == 2
        # First call: clear channels
        assert "UPDATE channels" in calls[0]
        assert "zone_before_id" in calls[0]
        assert "zone_after_id" in calls[0]
        assert "channel_type" in calls[0]
        # Second call: delete zone
        assert "DELETE FROM zones" in calls[1]

    def test_cascade_filters_channels_by_zone_refs(self):
        db = _make_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            db.delete_zone(5)
        first_call_params = cursor.execute.call_args_list[0][0][1]
        assert first_call_params == (5, 5, 5, 5, 5, 5)

    def test_commits_single_transaction(self):
        db = _make_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            db.delete_zone(1)
        conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# get_channels_for_zone
# ---------------------------------------------------------------------------

class TestGetChannelsForZone:
    def test_returns_channel_list(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchall=[(3, "Въезд 1"), (4, "Выезд 1")])
        with patch.object(db, "_connect", return_value=conn):
            result = db.get_channels_for_zone(2)
        assert result == [{"id": 3, "name": "Въезд 1"}, {"id": 4, "name": "Выезд 1"}]

    def test_returns_empty_when_no_channels(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchall=[])
        with patch.object(db, "_connect", return_value=conn):
            result = db.get_channels_for_zone(99)
        assert result == []

    def test_query_filters_by_zone_id(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchall=[])
        with patch.object(db, "_connect", return_value=conn):
            db.get_channels_for_zone(7)
        sql, params = cursor.execute.call_args[0]
        assert "zone_before_id = %s OR zone_after_id = %s" in sql
        assert params == (7, 7)


# ---------------------------------------------------------------------------
# get_zone_occupancy
# ---------------------------------------------------------------------------

class TestGetZoneOccupancy:
    def test_returns_count_of_open_entries(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(12,))
        with patch.object(db, "_connect", return_value=conn):
            result = db.get_zone_occupancy(1)
        assert result == 12

    def test_returns_zero_for_empty_zone(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(0,))
        with patch.object(db, "_connect", return_value=conn):
            result = db.get_zone_occupancy(5)
        assert result == 0

    def test_returns_zero_when_no_row(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=None)
        with patch.object(db, "_connect", return_value=conn):
            result = db.get_zone_occupancy(5)
        assert result == 0

    def test_query_filters_open_entries_only(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(3,))
        with patch.object(db, "_connect", return_value=conn):
            db.get_zone_occupancy(2)
        sql, params = cursor.execute.call_args[0]
        assert "time_exit IS NULL" in sql
        assert "zone_id = %s" in sql
        assert params == (2,)
