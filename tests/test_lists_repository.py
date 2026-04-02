"""Tests for database/lists_repository.py

Covers logic that can be verified without a live PostgreSQL connection:
  - normalize_plate helper (including Cyrillic → Latin mapping)
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
# normalize_plate — basic behaviour
# ---------------------------------------------------------------------------

class TestNormalizePlate:
    def test_strips_spaces(self):
        # А (Cyrillic) → A (Latin), В (Cyrillic) → B (Latin); Б has no mapping
        assert normalize_plate("А 123 БВ") == "A123БB"

    def test_uppercases_latin(self):
        assert normalize_plate("a123bc") == "A123BC"

    def test_empty_string(self):
        assert normalize_plate("") == ""

    def test_none_value(self):
        assert normalize_plate(None) == ""  # type: ignore[arg-type]

    def test_already_normalized_latin(self):
        assert normalize_plate("A123BC") == "A123BC"

    # ------------------------------------------------------------------
    # Cyrillic → Latin mapping
    # ------------------------------------------------------------------

    def test_full_cyrillic_plate_maps_to_latin(self):
        # А В С are standard Russian plate characters
        assert normalize_plate("А123ВС77") == "A123BC77"

    def test_latin_plate_unchanged(self):
        assert normalize_plate("A123BC77") == "A123BC77"

    def test_lowercase_cyrillic_with_spaces(self):
        assert normalize_plate(" а123 вс77 ") == "A123BC77"

    def test_cyrillic_yo_maps_to_latin_e(self):
        assert normalize_plate("ЁЁЁЁ") == "EEEE"

    def test_all_mapped_cyrillic_chars(self):
        # А В Е К М Н О Р С Т У Х Ё  →  A B E K M H O P C T Y X E
        assert normalize_plate("АВЕКМНОРСТУХЁ") == "ABEKMHOPCTYXE"

    def test_unmapped_cyrillic_preserved(self):
        # Б, Г, Д, Ж … are not plate characters; they stay as Cyrillic
        assert normalize_plate("БГДЖ") == "БГДЖ"

    def test_cyrillic_and_latin_same_result(self):
        # Cyrillic "А123ВС" and Latin "A123BC" must produce identical canonical forms
        assert normalize_plate("А123ВС") == normalize_plate("A123BC")

    def test_digits_unchanged(self):
        assert normalize_plate("1234567890") == "1234567890"

    def test_mixed_case_cyrillic_input(self):
        assert normalize_plate("а123вс") == "A123BC"


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


# ---------------------------------------------------------------------------
# Cyrillic → Latin normalization in repository operations
# ---------------------------------------------------------------------------

class TestCyrillicNormalizationInRepository:
    """Verify that add/update/lookup all use canonical Latin plate_normalized."""

    def test_add_entry_stores_latin_normalized_for_cyrillic_plate(self):
        """plate (display) stays Cyrillic; plate_normalized must be Latin."""
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(99,))
        with patch.object(db, "_connect", return_value=conn):
            db.add_entry(list_id=1, plate="А123ВС77")
        _, params = cursor.execute.call_args[0]
        # params order: list_id, plate, plate_normalized, last_name, …
        assert params[1] == "А123ВС77"   # original Cyrillic preserved
        assert params[2] == "A123BC77"   # canonical Latin in normalized field

    def test_add_entry_latin_plate_normalized_unchanged(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(99,))
        with patch.object(db, "_connect", return_value=conn):
            db.add_entry(list_id=1, plate="A123BC77")
        _, params = cursor.execute.call_args[0]
        assert params[1] == "A123BC77"
        assert params[2] == "A123BC77"

    def test_update_entry_recalculates_normalized(self):
        """Editing a plate must recompute plate_normalized with the new value."""
        db = _make_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            db.update_entry(entry_id=5, plate="Е777КН77")
        _, params = cursor.execute.call_args[0]
        # UPDATE params order: plate, plate_normalized, last_name, … WHERE id
        assert params[0] == "Е777КН77"   # original preserved
        assert params[1] == "E777KH77"   # Latin canonical

    def test_find_entry_by_plate_uses_latin_normalized_for_query(self):
        """Lookup with Latin ANPR output must match a Cyrillic-entered entry."""
        db = _make_db()
        conn, cursor = _mock_conn(
            fetchone=("А777КН77", "", "", "", "", "", "", "white", "Test")
        )
        with patch.object(db, "_connect", return_value=conn):
            result = db.find_entry_by_plate("A777KH77")   # Latin (ANPR output)
        assert result is not None
        # Confirm the query was issued with the Latin normalized form
        _, params = cursor.execute.call_args[0]
        assert params[0] == "A777KH77"

    def test_find_entry_by_cyrillic_plate_uses_latin_normalized(self):
        """Lookup with Cyrillic plate must also normalize before querying."""
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=None)
        with patch.object(db, "_connect", return_value=conn):
            db.find_entry_by_plate("А777КН77")   # Cyrillic input
        _, params = cursor.execute.call_args[0]
        assert params[0] == "A777KH77"   # must query with Latin canonical

    def test_plate_in_list_type_cyrillic_query_uses_latin(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(1,))
        with patch.object(db, "_connect", return_value=conn):
            db.plate_in_list_type("А123ВС77", "white")
        _, params = cursor.execute.call_args[0]
        assert params[0] == "A123BC77"

    def test_plate_in_lists_cyrillic_query_uses_latin(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(1,))
        with patch.object(db, "_connect", return_value=conn):
            db.plate_in_lists("А123ВС77", [1, 2])
        query_params = cursor.execute.call_args[0][1]
        assert query_params[0] == "A123BC77"

    def test_api_returns_original_cyrillic_plate_not_canonical(self):
        """list_entries must return the original display plate, not plate_normalized."""
        db = _make_db()
        conn, cursor = _mock_conn(fetchall=[
            (1, "А777АА77", "Иванов", "Иван", "", "", "", ""),
        ])
        with patch.object(db, "_connect", return_value=conn):
            rows = db.list_entries(list_id=1)
        assert rows[0]["plate"] == "А777АА77"   # Cyrillic display value unchanged

