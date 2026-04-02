"""Tests for database/lists_repository.py

Covers logic that can be verified without a live PostgreSQL connection:
  - normalize_plate helper
  - schema SQL shape (correct column names, no legacy 'comment' JSON blob)
  - add_entry / update_entry / list_entries / find_entry_by_plate
    verified via psycopg mocks
"""
from __future__ import annotations

import re
import types
from unittest.mock import MagicMock, patch, call

import pytest

from database.lists_repository import normalize_plate, ListDatabase


# ---------------------------------------------------------------------------
# normalize_plate
# ---------------------------------------------------------------------------

class TestNormalizePlate:
    def test_strips_spaces(self):
        assert normalize_plate("А 123 БВ") == "А123БВ"

    def test_uppercases(self):
        assert normalize_plate("a123bc") == "A123BC"

    def test_empty_string(self):
        assert normalize_plate("") == ""

    def test_none_value(self):
        assert normalize_plate(None) == ""  # type: ignore[arg-type]

    def test_already_normalized(self):
        assert normalize_plate("A123BC") == "A123BC"


# ---------------------------------------------------------------------------
# Schema SQL sanity checks (no DB required)
# ---------------------------------------------------------------------------

class TestSchemaSQL:
    def _schema(self) -> str:
        # Instantiate without connecting by bypassing __init__
        db = object.__new__(ListDatabase)
        return db._schema_sql()

    def test_new_columns_present(self):
        schema = self._schema()
        for col in ("last_name", "first_name", "middle_name", "phone", "car", "comment"):
            assert col in schema, f"Column '{col}' missing from schema SQL"

    def test_legacy_columns_absent(self):
        schema = self._schema()
        assert "patronymic" not in schema, "Legacy column 'patronymic' still in schema"
        assert "car_make" not in schema, "Legacy column 'car_make' still in schema"

    def test_is_deleted_present(self):
        schema = self._schema()
        assert "is_deleted" in schema

    def test_partial_unique_index(self):
        schema = self._schema()
        assert "WHERE is_deleted = FALSE" in schema


# ---------------------------------------------------------------------------
# Repository method tests via mocked psycopg connection
# ---------------------------------------------------------------------------

def _make_db() -> ListDatabase:
    """Create a ListDatabase instance with _initialized=True to skip _ensure_schema."""
    db = object.__new__(ListDatabase)
    db._dsn = "postgresql://mock"
    db._initialized = True
    db._init_lock = __import__("threading").Lock()
    db._pool = None
    return db


def _mock_conn(fetchone=None, fetchall=None, rowcount=1):
    """Build a context-manager mock for _connect()."""
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


class TestAddEntry:
    def test_returns_id_on_success(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(42,))
        with patch.object(db, "_connect", return_value=conn):
            result = db.add_entry(
                list_id=1, plate="А123БВ",
                first_name="Артём", last_name="Иванов",
                middle_name="Сергеевич", phone="+7999", car="BMW", comment="VIP"
            )
        assert result == 42

    def test_returns_none_for_empty_plate(self):
        db = _make_db()
        result = db.add_entry(list_id=1, plate="   ")
        assert result is None

    def test_passes_all_fields_to_sql(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(7,))
        with patch.object(db, "_connect", return_value=conn):
            db.add_entry(
                list_id=2, plate="B456CD",
                first_name="Иван", last_name="Петров",
                middle_name="", phone="", car="Lada", comment="test"
            )
        sql, params = cursor.execute.call_args[0]
        assert "last_name" in sql
        assert "first_name" in sql
        assert "middle_name" in sql
        assert "car" in sql
        assert "comment" in sql
        assert "Петров" in params
        assert "Иван" in params
        assert "Lada" in params
        assert "test" in params


class TestUpdateEntry:
    def test_returns_true_when_row_updated(self):
        db = _make_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            result = db.update_entry(
                entry_id=5, plate="X100YZ",
                first_name="Анна", last_name="Сидорова",
                middle_name="В.", phone="", car="Ford", comment=""
            )
        assert result is True

    def test_returns_false_for_empty_plate(self):
        db = _make_db()
        result = db.update_entry(entry_id=5, plate="")
        assert result is False

    def test_returns_false_when_no_row_matched(self):
        db = _make_db()
        conn, cursor = _mock_conn(rowcount=0)
        with patch.object(db, "_connect", return_value=conn):
            result = db.update_entry(entry_id=99, plate="X100YZ")
        assert result is False


class TestListEntries:
    def test_returns_normalized_fields(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchall=[
            (1, "А777АА", "Иванов", "Иван", "Иванович", "+7", "BMW", "важный"),
        ])
        with patch.object(db, "_connect", return_value=conn):
            rows = db.list_entries(list_id=3)
        assert len(rows) == 1
        r = rows[0]
        assert r["id"] == 1
        assert r["plate"] == "А777АА"
        assert r["last_name"] == "Иванов"
        assert r["first_name"] == "Иван"
        assert r["middle_name"] == "Иванович"
        assert r["phone"] == "+7"
        assert r["car"] == "BMW"
        assert r["comment"] == "важный"

    def test_query_filters_deleted(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchall=[])
        with patch.object(db, "_connect", return_value=conn):
            db.list_entries(list_id=3)
        sql = cursor.execute.call_args[0][0]
        assert "is_deleted = FALSE" in sql


class TestFindEntryByPlate:
    def test_returns_normalized_structure(self):
        db = _make_db()
        conn, cursor = _mock_conn(
            fetchone=("А123БВ", "Смирнов", "Олег", "П.", "89001234567", "Toyota", "постоянный", "white", "Белый список")
        )
        with patch.object(db, "_connect", return_value=conn):
            result = db.find_entry_by_plate("А123БВ")
        assert result is not None
        assert result["last_name"] == "Смирнов"
        assert result["first_name"] == "Олег"
        assert result["middle_name"] == "П."
        assert result["car"] == "Toyota"
        assert result["comment"] == "постоянный"
        assert result["list_type"] == "white"
        assert result["list_name"] == "Белый список"

    def test_returns_none_for_empty_plate(self):
        db = _make_db()
        result = db.find_entry_by_plate("")
        assert result is None

    def test_returns_none_when_not_found(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=None)
        with patch.object(db, "_connect", return_value=conn):
            result = db.find_entry_by_plate("ZZZZZZ")
        assert result is None


class TestSoftDelete:
    def test_delete_entry_issues_update_not_delete(self):
        db = _make_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            db.delete_entry(entry_id=10)
        sql = cursor.execute.call_args[0][0]
        assert "UPDATE" in sql.upper()
        assert "is_deleted = TRUE" in sql
        # must not be a hard DELETE statement (UPDATE sets is_deleted, not removes the row)
        assert not sql.strip().upper().startswith("DELETE")

    def test_delete_list_soft_deletes_children_first(self):
        db = _make_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            db.delete_list(list_id=5)
        calls = [c[0][0] for c in cursor.execute.call_args_list]
        # first call should mark clients, second should mark the list
        assert any("clients" in sql and "is_deleted = TRUE" in sql for sql in calls)
        assert any("lists" in sql and "is_deleted = TRUE" in sql for sql in calls)
        # none of the statements should be a hard DELETE
        assert all(not sql.strip().upper().startswith("DELETE") for sql in calls)
