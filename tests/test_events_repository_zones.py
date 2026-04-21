"""Tests for zone-related functionality in database/postgres_event_repository.py

Covers:
  - _to_dict: field mapping, no 'channel' text field, 'time' key present
  - insert_event: zone_id and time_entry round-trip; defaults to NULL
  - find_active_entry_and_write_exit: found / not-found / targets most recent
  - fetch_journal_page: cursor uses (time, id) composite tuple
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from database.postgres_event_repository import PostgresEventDatabase


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_db() -> PostgresEventDatabase:
    db = object.__new__(PostgresEventDatabase)
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


def _make_row(
    id=1, time="2024-01-01T12:00:00Z", channel_id=2, plate="A123BC",
    plate_display="A123BC", country="RU", confidence=0.95, source="cam",
    frame_path=None, plate_path=None, direction="in", client_id=None,
    zone_id=None, time_entry=None, time_exit=None,
):
    return (
        id, time, channel_id, plate, plate_display, country, confidence, source,
        frame_path, plate_path, direction, client_id, zone_id, time_entry, time_exit,
    )


# ---------------------------------------------------------------------------
# _to_dict — field mapping
# ---------------------------------------------------------------------------

class TestToDict:
    def test_has_time_key(self):
        row = _make_row(time="2024-06-01T10:00:00Z")
        result = PostgresEventDatabase._to_dict(row)
        assert "time" in result
        assert result["time"] == "2024-06-01T10:00:00Z"

    def test_no_channel_text_field(self):
        row = _make_row()
        result = PostgresEventDatabase._to_dict(row)
        assert "channel" not in result

    def test_zone_id_mapped(self):
        row = _make_row(zone_id=3)
        result = PostgresEventDatabase._to_dict(row)
        assert result["zone_id"] == 3

    def test_time_entry_mapped(self):
        row = _make_row(time_entry="2024-06-01T09:00:00Z")
        result = PostgresEventDatabase._to_dict(row)
        assert result["time_entry"] == "2024-06-01T09:00:00Z"

    def test_time_exit_mapped(self):
        row = _make_row(time_exit="2024-06-01T11:00:00Z")
        result = PostgresEventDatabase._to_dict(row)
        assert result["time_exit"] == "2024-06-01T11:00:00Z"

    def test_zone_fields_default_none(self):
        row = _make_row()
        result = PostgresEventDatabase._to_dict(row)
        assert result["zone_id"] is None
        assert result["time_entry"] is None
        assert result["time_exit"] is None

    def test_all_expected_keys_present(self):
        row = _make_row()
        result = PostgresEventDatabase._to_dict(row)
        expected = {
            "id", "time", "channel_id", "plate", "plate_display", "country",
            "confidence", "source", "frame_path", "plate_path", "direction",
            "client_id", "zone_id", "time_entry", "time_exit",
        }
        assert set(result.keys()) == expected


# ---------------------------------------------------------------------------
# insert_event — zone fields
# ---------------------------------------------------------------------------

class TestInsertEventZoneFields:
    def test_insert_with_zone_id_and_time_entry(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(10,))
        with patch.object(db, "_connect", return_value=conn):
            result = db.insert_event(
                plate="A123BC",
                channel_id=1,
                zone_id=2,
                time_entry="2024-06-01T09:00:00Z",
            )
        assert result == 10
        _, params = cursor.execute.call_args[0]
        # zone_id and time_entry should be in params
        assert 2 in params
        assert "2024-06-01T09:00:00Z" in params

    def test_zone_fields_default_to_none(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(5,))
        with patch.object(db, "_connect", return_value=conn):
            db.insert_event(plate="X100YZ", channel_id=1)
        _, params = cursor.execute.call_args[0]
        # Last two params are zone_id and time_entry — both should be None
        assert params[-2] is None  # zone_id
        assert params[-1] is None  # time_entry

    def test_insert_sql_includes_zone_columns(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(1,))
        with patch.object(db, "_connect", return_value=conn):
            db.insert_event(plate="Z999ZZ")
        sql = cursor.execute.call_args[0][0]
        assert "zone_id" in sql
        assert "time_entry" in sql

    def test_no_channel_text_column_in_insert(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(1,))
        with patch.object(db, "_connect", return_value=conn):
            db.insert_event(plate="Z999ZZ")
        sql = cursor.execute.call_args[0][0]
        # 'channel' text column was removed; only channel_id remains
        assert "channel_id" in sql
        # should not have a bare 'channel,' entry (only channel_id)
        import re
        assert not re.search(r'\bINSERT INTO events\b.*\bchannel\b(?!_id)', sql)

    def test_commits_after_insert(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(1,))
        with patch.object(db, "_connect", return_value=conn):
            db.insert_event(plate="A1B2C3")
        conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# find_active_entry_and_write_exit
# ---------------------------------------------------------------------------

class TestFindActiveEntryAndWriteExit:
    def test_returns_updated_id_when_found(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(77,))
        with patch.object(db, "_connect", return_value=conn):
            result = db.find_active_entry_and_write_exit("A123BC", 2, 0, "2024-06-01T11:00:00Z")
        assert result == 77

    def test_returns_none_when_no_open_entry(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=None)
        with patch.object(db, "_connect", return_value=conn):
            result = db.find_active_entry_and_write_exit("ZZZZZZ", 1, 0, "2024-06-01T11:00:00Z")
        assert result is None

    def test_sql_sets_time_exit_and_zone_id_from_channel_movement(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(5,))
        with patch.object(db, "_connect", return_value=conn):
            db.find_active_entry_and_write_exit("A123BC", 3, 0, "2024-06-01T15:00:00Z")
        sql = cursor.execute.call_args[0][0]
        assert "time_exit = %s" in sql
        assert "zone_id = %s" in sql

    def test_sql_subquery_filters_plate_zone_and_open(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(5,))
        with patch.object(db, "_connect", return_value=conn):
            db.find_active_entry_and_write_exit("B456DE", 4, 0, "2024-06-01T15:00:00Z")
        sql = cursor.execute.call_args[0][0]
        assert "plate = %s" in sql
        assert "zone_id = %s" in sql
        assert "time_exit IS NULL" in sql
        assert "ORDER BY time DESC" in sql
        assert "LIMIT 1" in sql

    def test_params_order_time_exit_zone_after_plate_zone_before(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(1,))
        with patch.object(db, "_connect", return_value=conn):
            db.find_active_entry_and_write_exit("C789FG", 7, 9, "2024-06-02T08:00:00Z")
        _, params = cursor.execute.call_args[0]
        assert params == ("2024-06-02T08:00:00Z", 9, "C789FG", 7)

    def test_commits_after_update(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(3,))
        with patch.object(db, "_connect", return_value=conn):
            db.find_active_entry_and_write_exit("A1", 1, 0, "2024-01-01T00:00:00Z")
        conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# fetch_journal_page — cursor uses (time, id) composite
# ---------------------------------------------------------------------------

class TestFetchJournalPageCursor:
    def test_cursor_uses_time_column(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchall=[])
        with patch.object(db, "_connect", return_value=conn):
            db.fetch_journal_page(
                limit=10,
                before_ts="2024-06-01T12:00:00Z",
                before_id=100,
            )
        sql = cursor.execute.call_args[0][0]
        assert "(time, id) < (%s, %s)" in sql

    def test_cursor_not_using_timestamp(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchall=[])
        with patch.object(db, "_connect", return_value=conn):
            db.fetch_journal_page(limit=10, before_ts="2024-01-01T00:00:00Z", before_id=1)
        sql = cursor.execute.call_args[0][0]
        assert "timestamp" not in sql

    def test_no_cursor_when_not_provided(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchall=[])
        with patch.object(db, "_connect", return_value=conn):
            db.fetch_journal_page(limit=10)
        sql = cursor.execute.call_args[0][0]
        assert "(time, id)" not in sql

    def test_results_use_to_dict(self):
        db = _make_db()
        row = _make_row(id=1, zone_id=2, time_entry="2024-06-01T09:00:00Z")
        conn, cursor = _mock_conn(fetchall=[row])
        with patch.object(db, "_connect", return_value=conn):
            results = db.fetch_journal_page(limit=10)
        assert len(results) == 1
        assert results[0]["zone_id"] == 2
        assert results[0]["time_entry"] == "2024-06-01T09:00:00Z"
        assert "channel" not in results[0]
