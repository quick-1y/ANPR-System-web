"""Tests for database/lists_repository.py and database/clients_repository.py

Covers logic verifiable without a live PostgreSQL connection:
  - normalize_plate helper (including Cyrillic → Latin mapping)
  - ListDatabase: schema SQL shape, list CRUD, plate-matching methods,
    find_client_by_plate, list_clients_in_list
  - ClientDatabase: create_client, update_client, delete_client,
    get_client, list_all_clients, search_clients, attach_to_list,
    detach_from_list — all verified via psycopg mocks
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from database.lists_repository import normalize_plate, ListDatabase
from database.clients_repository import ClientDatabase


# ---------------------------------------------------------------------------
# normalize_plate — basic behaviour
# ---------------------------------------------------------------------------

class TestNormalizePlate:
    def test_strips_spaces(self):
        assert normalize_plate("А 123 БВ") == "A123БB"

    def test_uppercases_latin(self):
        assert normalize_plate("a123bc") == "A123BC"

    def test_empty_string(self):
        assert normalize_plate("") == ""

    def test_none_value(self):
        assert normalize_plate(None) == ""  # type: ignore[arg-type]

    def test_already_normalized_latin(self):
        assert normalize_plate("A123BC") == "A123BC"

    def test_full_cyrillic_plate_maps_to_latin(self):
        assert normalize_plate("А123ВС77") == "A123BC77"

    def test_latin_plate_unchanged(self):
        assert normalize_plate("A123BC77") == "A123BC77"

    def test_lowercase_cyrillic_with_spaces(self):
        assert normalize_plate(" а123 вс77 ") == "A123BC77"

    def test_cyrillic_yo_maps_to_latin_e(self):
        assert normalize_plate("ЁЁЁЁ") == "EEEE"

    def test_all_mapped_cyrillic_chars(self):
        assert normalize_plate("АВЕКМНОРСТУХЁ") == "ABEKMHOPCTYXE"

    def test_unmapped_cyrillic_preserved(self):
        assert normalize_plate("БГДЖ") == "БГДЖ"

    def test_cyrillic_and_latin_same_result(self):
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
        db = object.__new__(ListDatabase)
        return db._schema_sql()

    def test_new_columns_present(self):
        schema = self._schema()
        for col in ("last_name", "first_name", "middle_name", "phone", "car", "comment"):
            assert col in schema, f"Column '{col}' missing from schema SQL"

    def test_legacy_columns_absent(self):
        schema = self._schema()
        assert "patronymic" not in schema
        assert "car_make" not in schema

    def test_is_deleted_present(self):
        assert "is_deleted" in self._schema()

    def test_partial_unique_index(self):
        assert "WHERE is_deleted = FALSE" in self._schema()

    def test_list_id_is_nullable(self):
        schema = self._schema()
        # list_id must NOT have NOT NULL — it is now nullable
        assert "NOT NULL REFERENCES lists" not in schema
        # it should still reference lists
        assert "REFERENCES lists" in schema

    def test_on_delete_set_null(self):
        assert "ON DELETE SET NULL" in self._schema()


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------

def _make_list_db() -> ListDatabase:
    db = object.__new__(ListDatabase)
    db._dsn = "postgresql://mock"
    db._initialized = True
    db._init_lock = threading.Lock()
    db._pool = None
    return db


def _make_client_db() -> ClientDatabase:
    db = object.__new__(ClientDatabase)
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
# ListDatabase — list_clients_in_list
# ---------------------------------------------------------------------------

class TestListClientsInList:
    def test_returns_normalized_fields(self):
        db = _make_list_db()
        conn, cursor = _mock_conn(fetchall=[
            (1, "А777АА", "Иванов", "Иван", "Иванович", "+7", "BMW", "важный"),
        ])
        with patch.object(db, "_connect", return_value=conn):
            rows = db.list_clients_in_list(list_id=3)
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
        db = _make_list_db()
        conn, cursor = _mock_conn(fetchall=[])
        with patch.object(db, "_connect", return_value=conn):
            db.list_clients_in_list(list_id=3)
        sql = cursor.execute.call_args[0][0]
        assert "is_deleted = FALSE" in sql


# ---------------------------------------------------------------------------
# ListDatabase — find_client_by_plate
# ---------------------------------------------------------------------------

class TestFindClientByPlate:
    def test_returns_normalized_structure(self):
        db = _make_list_db()
        conn, cursor = _mock_conn(
            fetchone=(42, "А123БВ", "Смирнов", "Олег", "П.", "89001234567", "Toyota", "постоянный", "white", "Белый список")
        )
        with patch.object(db, "_connect", return_value=conn):
            result = db.find_client_by_plate("А123БВ")
        assert result is not None
        assert result["id"] == 42
        assert result["last_name"] == "Смирнов"
        assert result["first_name"] == "Олег"
        assert result["middle_name"] == "П."
        assert result["car"] == "Toyota"
        assert result["comment"] == "постоянный"
        assert result["list_type"] == "white"
        assert result["list_name"] == "Белый список"

    def test_returns_none_for_empty_plate(self):
        db = _make_list_db()
        assert db.find_client_by_plate("") is None

    def test_returns_none_when_not_found(self):
        db = _make_list_db()
        conn, cursor = _mock_conn(fetchone=None)
        with patch.object(db, "_connect", return_value=conn):
            result = db.find_client_by_plate("ZZZZZZ")
        assert result is None

    def test_uses_latin_normalized_for_query(self):
        db = _make_list_db()
        conn, cursor = _mock_conn(fetchone=(1, "А777КН77", "", "", "", "", "", "", "white", "Test"))
        with patch.object(db, "_connect", return_value=conn):
            db.find_client_by_plate("A777KH77")
        _, params = cursor.execute.call_args[0]
        assert params[0] == "A777KH77"

    def test_cyrillic_input_normalizes_before_query(self):
        db = _make_list_db()
        conn, cursor = _mock_conn(fetchone=None)
        with patch.object(db, "_connect", return_value=conn):
            db.find_client_by_plate("А777КН77")
        _, params = cursor.execute.call_args[0]
        assert params[0] == "A777KH77"


# ---------------------------------------------------------------------------
# ListDatabase — soft-delete behaviour
# ---------------------------------------------------------------------------

class TestListSoftDelete:
    def test_delete_list_detaches_clients_first(self):
        """Deleting a list must set list_id = NULL on members, not mark them deleted."""
        db = _make_list_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            db.delete_list(list_id=5)
        calls = [c[0][0] for c in cursor.execute.call_args_list]
        # First statement must detach clients (list_id = NULL), not soft-delete them
        assert any("clients" in sql and "list_id = NULL" in sql for sql in calls)
        # Second statement must soft-delete the list itself
        assert any("lists" in sql and "is_deleted = TRUE" in sql for sql in calls)
        # No hard DELETE statements allowed
        assert all(not sql.strip().upper().startswith("DELETE") for sql in calls)


# ---------------------------------------------------------------------------
# ListDatabase — plate matching (channel automation — must not change)
# ---------------------------------------------------------------------------

class TestPlateMatching:
    def test_plate_in_list_type_cyrillic_uses_latin(self):
        db = _make_list_db()
        conn, cursor = _mock_conn(fetchone=(1,))
        with patch.object(db, "_connect", return_value=conn):
            db.plate_in_list_type("А123ВС77", "white")
        _, params = cursor.execute.call_args[0]
        assert params[0] == "A123BC77"

    def test_plate_in_lists_cyrillic_uses_latin(self):
        db = _make_list_db()
        conn, cursor = _mock_conn(fetchone=(1,))
        with patch.object(db, "_connect", return_value=conn):
            db.plate_in_lists("А123ВС77", [1, 2])
        query_params = cursor.execute.call_args[0][1]
        assert query_params[0] == "A123BC77"

    def test_plate_in_list_type_empty_plate_returns_false(self):
        db = _make_list_db()
        assert db.plate_in_list_type("", "white") is False

    def test_plate_in_lists_empty_ids_returns_false(self):
        db = _make_list_db()
        assert db.plate_in_lists("A123BC", []) is False


# ---------------------------------------------------------------------------
# ClientDatabase — create_client
# ---------------------------------------------------------------------------

class TestCreateClient:
    def test_returns_id_on_success(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(fetchone=(42,))
        with patch.object(db, "_connect", return_value=conn):
            result = db.create_client(
                plate="А123ВС77",
                first_name="Артём", last_name="Иванов",
                middle_name="Сергеевич", phone="+7999", car="BMW", comment="VIP"
            )
        assert result == 42

    def test_returns_none_for_empty_plate(self):
        db = _make_client_db()
        assert db.create_client(plate="   ") is None

    def test_stores_original_and_normalized_plate(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(fetchone=(7,))
        with patch.object(db, "_connect", return_value=conn):
            db.create_client(plate="А123ВС77")
        _, params = cursor.execute.call_args[0]
        assert "А123ВС77" in params   # original preserved
        assert "A123BC77" in params   # canonical Latin stored

    def test_list_id_defaults_to_none(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(fetchone=(1,))
        with patch.object(db, "_connect", return_value=conn):
            db.create_client(plate="A100BC")
        _, params = cursor.execute.call_args[0]
        assert params[0] is None   # list_id is first param

    def test_optional_list_id_passed_through(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(fetchone=(1,))
        with patch.object(db, "_connect", return_value=conn):
            db.create_client(plate="A100BC", list_id=5)
        _, params = cursor.execute.call_args[0]
        assert params[0] == 5


# ---------------------------------------------------------------------------
# ClientDatabase — update_client
# ---------------------------------------------------------------------------

class TestUpdateClient:
    def test_returns_true_when_row_updated(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            result = db.update_client(
                client_id=5, plate="X100YZ",
                first_name="Анна", last_name="Сидорова",
                middle_name="В.", phone="", car="Ford", comment=""
            )
        assert result is True

    def test_returns_false_for_empty_plate(self):
        db = _make_client_db()
        assert db.update_client(client_id=5, plate="") is False

    def test_returns_false_when_no_row_matched(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(rowcount=0)
        with patch.object(db, "_connect", return_value=conn):
            assert db.update_client(client_id=99, plate="X100YZ") is False

    def test_recalculates_normalized_plate(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            db.update_client(client_id=5, plate="Е777КН77")
        _, params = cursor.execute.call_args[0]
        assert params[0] == "Е777КН77"   # original preserved
        assert params[1] == "E777KH77"   # Latin canonical


# ---------------------------------------------------------------------------
# ClientDatabase — delete_client (soft delete)
# ---------------------------------------------------------------------------

class TestDeleteClient:
    def test_issues_update_not_hard_delete(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            result = db.delete_client(client_id=10)
        sql = cursor.execute.call_args[0][0]
        assert result is True
        assert "UPDATE" in sql.upper()
        assert "is_deleted = TRUE" in sql
        assert not sql.strip().upper().startswith("DELETE")

    def test_returns_false_when_not_found(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(rowcount=0)
        with patch.object(db, "_connect", return_value=conn):
            assert db.delete_client(client_id=999) is False


# ---------------------------------------------------------------------------
# ClientDatabase — get_client
# ---------------------------------------------------------------------------

class TestGetClient:
    def test_returns_full_record(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(
            fetchone=(1, 3, "A123BC", "Иванов", "Иван", "П.", "+7", "BMW", "VIP", "Белый список", "white")
        )
        with patch.object(db, "_connect", return_value=conn):
            result = db.get_client(1)
        assert result is not None
        assert result["id"] == 1
        assert result["list_id"] == 3
        assert result["plate"] == "A123BC"
        assert result["last_name"] == "Иванов"
        assert result["list_name"] == "Белый список"
        assert result["list_type"] == "white"

    def test_returns_none_when_not_found(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(fetchone=None)
        with patch.object(db, "_connect", return_value=conn):
            assert db.get_client(999) is None

    def test_query_filters_deleted(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(fetchone=None)
        with patch.object(db, "_connect", return_value=conn):
            db.get_client(1)
        sql = cursor.execute.call_args[0][0]
        assert "is_deleted = FALSE" in sql


# ---------------------------------------------------------------------------
# ClientDatabase — list_all_clients
# ---------------------------------------------------------------------------

class TestListAllClients:
    def test_returns_all_rows(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(fetchall=[
            (1, None, "A001", "Иванов", "Иван", "", "+7", "BMW", ""),
            (2, 5,    "A002", "Петров", "Петр", "", "",   "Lada", "важный"),
        ])
        with patch.object(db, "_connect", return_value=conn):
            rows = db.list_all_clients()
        assert len(rows) == 2
        assert rows[0]["plate"] == "A001"
        assert rows[0]["list_id"] is None
        assert rows[1]["list_id"] == 5

    def test_query_filters_deleted(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(fetchall=[])
        with patch.object(db, "_connect", return_value=conn):
            db.list_all_clients()
        sql = cursor.execute.call_args[0][0]
        assert "is_deleted = FALSE" in sql


# ---------------------------------------------------------------------------
# ClientDatabase — search_clients
# ---------------------------------------------------------------------------

class TestSearchClients:
    def test_returns_matching_rows(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(fetchall=[
            (1, None, "A001", "Иванов", "Иван", "", "+7", "BMW", ""),
        ])
        with patch.object(db, "_connect", return_value=conn):
            rows = db.search_clients("Иванов")
        assert len(rows) == 1
        assert rows[0]["last_name"] == "Иванов"

    def test_query_uses_ilike(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(fetchall=[])
        with patch.object(db, "_connect", return_value=conn):
            db.search_clients("test")
        sql = cursor.execute.call_args[0][0]
        assert "ILIKE" in sql.upper()

    def test_query_filters_deleted(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(fetchall=[])
        with patch.object(db, "_connect", return_value=conn):
            db.search_clients("x")
        sql = cursor.execute.call_args[0][0]
        assert "is_deleted = FALSE" in sql


# ---------------------------------------------------------------------------
# ClientDatabase — attach_to_list / detach_from_list
# ---------------------------------------------------------------------------

class TestListAttachment:
    def test_attach_sets_list_id(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            result = db.attach_to_list(client_id=1, list_id=7)
        assert result is True
        sql, params = cursor.execute.call_args[0]
        assert "list_id" in sql
        assert params[0] == 7
        assert params[1] == 1

    def test_attach_returns_false_when_not_found(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(rowcount=0)
        with patch.object(db, "_connect", return_value=conn):
            assert db.attach_to_list(client_id=999, list_id=1) is False

    def test_detach_sets_list_id_to_null(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            result = db.detach_from_list(client_id=1)
        assert result is True
        sql = cursor.execute.call_args[0][0]
        assert "list_id = NULL" in sql

    def test_detach_returns_false_when_not_found(self):
        db = _make_client_db()
        conn, cursor = _mock_conn(rowcount=0)
        with patch.object(db, "_connect", return_value=conn):
            assert db.detach_from_list(client_id=999) is False
