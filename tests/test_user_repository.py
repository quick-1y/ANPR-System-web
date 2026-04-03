"""Tests for database/user_repository.py

Covers logic that can be verified without a live PostgreSQL connection:
  - password hashing helper
  - schema SQL shape
  - _row_to_dict conversion
  - repository methods via psycopg mocks
  - default admin seeding logic
"""
from __future__ import annotations

import json
import threading
from unittest.mock import MagicMock, patch, call

import pytest

from database.user_repository import UserDatabase, _hash_password, _row_to_dict


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

class TestHashPassword:
    def test_returns_bcrypt_hash(self):
        hashed = _hash_password("1234")
        assert hashed.startswith("$2")  # bcrypt prefix
        assert len(hashed) == 60

    def test_different_calls_produce_different_hashes(self):
        h1 = _hash_password("test")
        h2 = _hash_password("test")
        assert h1 != h2  # different salts

    def test_hash_verifiable_with_bcrypt(self):
        import bcrypt
        plain = "securePassword123"
        hashed = _hash_password(plain)
        assert bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ---------------------------------------------------------------------------
# Row to dict conversion
# ---------------------------------------------------------------------------

class TestRowToDict:
    def test_converts_tuple_to_dict(self):
        row = (1, "admin", "$2b$hash", "admin", ["tab:obs"], True, "2024-01-01", "2024-01-01")
        result = _row_to_dict(row)
        assert result["id"] == 1
        assert result["login"] == "admin"
        assert result["password"] == "$2b$hash"
        assert result["role"] == "admin"
        assert result["permissions"] == ["tab:obs"]
        assert result["is_active"] is True

    def test_parses_json_string_permissions(self):
        row = (1, "op", "hash", "operator", '["tab:obs"]', True, "2024-01-01", "2024-01-01")
        result = _row_to_dict(row)
        assert result["permissions"] == ["tab:obs"]

    def test_handles_none_permissions(self):
        row = (1, "op", "hash", "operator", None, True, "2024-01-01", "2024-01-01")
        result = _row_to_dict(row)
        assert result["permissions"] == []


# ---------------------------------------------------------------------------
# Schema SQL sanity checks
# ---------------------------------------------------------------------------

class TestSchemaSQL:
    def _schema(self) -> str:
        db = object.__new__(UserDatabase)
        return db._schema_sql()

    def test_creates_users_table(self):
        schema = self._schema()
        assert "CREATE TABLE IF NOT EXISTS users" in schema

    def test_required_columns_present(self):
        schema = self._schema()
        for col in ("id", "login", "password", "role", "permissions", "is_active", "created_at", "updated_at"):
            assert col in schema, f"Column '{col}' missing from schema SQL"

    def test_permissions_is_jsonb(self):
        schema = self._schema()
        assert "JSONB" in schema

    def test_unique_index_on_login(self):
        schema = self._schema()
        assert "idx_users_login" in schema


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _make_db() -> UserDatabase:
    """Create a UserDatabase instance with _initialized=True to skip _ensure_schema."""
    db = object.__new__(UserDatabase)
    db._dsn = "postgresql://mock"
    db._initialized = True
    db._init_lock = threading.Lock()
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
    conn.rollback = MagicMock()
    return conn, cursor


# ---------------------------------------------------------------------------
# find_by_login
# ---------------------------------------------------------------------------

class TestFindByLogin:
    def test_returns_user_dict_when_found(self):
        db = _make_db()
        row = (1, "admin", "$2b$hash", "admin", [], True, "2024-01-01", "2024-01-01")
        conn, cursor = _mock_conn(fetchone=row)
        with patch.object(db, "_connect", return_value=conn):
            result = db.find_by_login("admin")
        assert result is not None
        assert result["login"] == "admin"
        assert result["role"] == "admin"

    def test_returns_none_when_not_found(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=None)
        with patch.object(db, "_connect", return_value=conn):
            result = db.find_by_login("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# find_by_id
# ---------------------------------------------------------------------------

class TestFindById:
    def test_returns_user_dict_when_found(self):
        db = _make_db()
        row = (5, "operator1", "$2b$hash", "operator", ["tab:obs"], True, "2024-01-01", "2024-01-01")
        conn, cursor = _mock_conn(fetchone=row)
        with patch.object(db, "_connect", return_value=conn):
            result = db.find_by_id(5)
        assert result is not None
        assert result["id"] == 5
        assert result["permissions"] == ["tab:obs"]

    def test_returns_none_when_not_found(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=None)
        with patch.object(db, "_connect", return_value=conn):
            result = db.find_by_id(999)
        assert result is None


# ---------------------------------------------------------------------------
# list_all
# ---------------------------------------------------------------------------

class TestListAll:
    def test_returns_list_of_users(self):
        db = _make_db()
        rows = [
            (1, "admin", "$2b$h1", "admin", [], True, "2024-01-01", "2024-01-01"),
            (2, "op1", "$2b$h2", "operator", ["tab:obs"], True, "2024-01-01", "2024-01-01"),
        ]
        conn, cursor = _mock_conn(fetchall=rows)
        with patch.object(db, "_connect", return_value=conn):
            result = db.list_all()
        assert len(result) == 2
        assert result[0]["login"] == "admin"
        assert result[1]["login"] == "op1"

    def test_returns_empty_list_when_no_users(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchall=[])
        with patch.object(db, "_connect", return_value=conn):
            result = db.list_all()
        assert result == []


# ---------------------------------------------------------------------------
# create_user
# ---------------------------------------------------------------------------

class TestCreateUser:
    def test_returns_created_user(self):
        db = _make_db()
        row = (3, "newuser", "$2b$hash", "operator", ["tab:obs", "tab:journal"], True, "2024-01-01", "2024-01-01")
        conn, cursor = _mock_conn(fetchone=row)
        with patch.object(db, "_connect", return_value=conn):
            result = db.create_user("newuser", "$2b$hash", "operator", ["tab:obs", "tab:journal"])
        assert result["login"] == "newuser"
        assert result["permissions"] == ["tab:obs", "tab:journal"]

    def test_sql_contains_insert(self):
        db = _make_db()
        row = (3, "u", "h", "operator", [], True, "2024-01-01", "2024-01-01")
        conn, cursor = _mock_conn(fetchone=row)
        with patch.object(db, "_connect", return_value=conn):
            db.create_user("u", "h")
        sql = cursor.execute.call_args[0][0]
        assert "INSERT INTO users" in sql


# ---------------------------------------------------------------------------
# update_user
# ---------------------------------------------------------------------------

class TestUpdateUser:
    def test_updates_role(self):
        db = _make_db()
        row = (1, "admin", "h", "operator", [], True, "2024-01-01", "2024-01-01")
        conn, cursor = _mock_conn(fetchone=row)
        with patch.object(db, "_connect", return_value=conn):
            result = db.update_user(1, role="operator")
        sql = cursor.execute.call_args[0][0]
        assert "role = %s" in sql
        assert "updated_at = now()" in sql

    def test_updates_permissions(self):
        db = _make_db()
        row = (1, "op", "h", "operator", ["tab:obs"], True, "2024-01-01", "2024-01-01")
        conn, cursor = _mock_conn(fetchone=row)
        with patch.object(db, "_connect", return_value=conn):
            result = db.update_user(1, permissions=["tab:obs"])
        sql = cursor.execute.call_args[0][0]
        assert "permissions = %s::jsonb" in sql

    def test_noop_when_no_fields(self):
        db = _make_db()
        row = (1, "op", "h", "operator", [], True, "2024-01-01", "2024-01-01")
        conn, cursor = _mock_conn(fetchone=row)
        with patch.object(db, "_connect", return_value=conn):
            with patch.object(db, "find_by_id", return_value=_row_to_dict(row)):
                result = db.update_user(1)
        assert result["id"] == 1


# ---------------------------------------------------------------------------
# update_password
# ---------------------------------------------------------------------------

class TestUpdatePassword:
    def test_returns_true_on_success(self):
        db = _make_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            assert db.update_password(1, "$2b$newhash") is True

    def test_returns_false_when_user_not_found(self):
        db = _make_db()
        conn, cursor = _mock_conn(rowcount=0)
        with patch.object(db, "_connect", return_value=conn):
            assert db.update_password(999, "$2b$newhash") is False


# ---------------------------------------------------------------------------
# deactivate
# ---------------------------------------------------------------------------

class TestDeactivate:
    def test_returns_true_on_success(self):
        db = _make_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            assert db.deactivate(1) is True

    def test_sql_sets_is_active_false(self):
        db = _make_db()
        conn, cursor = _mock_conn(rowcount=1)
        with patch.object(db, "_connect", return_value=conn):
            db.deactivate(1)
        sql = cursor.execute.call_args[0][0]
        assert "is_active = false" in sql


# ---------------------------------------------------------------------------
# count_active_admins
# ---------------------------------------------------------------------------

class TestCountActiveAdmins:
    def test_returns_count(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(2,))
        with patch.object(db, "_connect", return_value=conn):
            assert db.count_active_admins() == 2


# ---------------------------------------------------------------------------
# Default admin seeding
# ---------------------------------------------------------------------------

class TestSeedDefaultAdmin:
    def test_seeds_admin_when_table_empty(self):
        db = _make_db()
        # First query: count(*) returns 0
        conn, cursor = _mock_conn(fetchone=(0,))
        with patch.object(db, "_connect", return_value=conn):
            db._seed_default_admin()
        calls = cursor.execute.call_args_list
        # Should have 2 calls: SELECT count(*) and INSERT
        assert len(calls) == 2
        insert_sql = calls[1][0][0]
        assert "INSERT INTO users" in insert_sql
        insert_params = calls[1][0][1]
        assert insert_params[0] == "admin"  # login
        assert insert_params[1].startswith("$2")  # bcrypt hash

    def test_skips_seed_when_table_not_empty(self):
        db = _make_db()
        conn, cursor = _mock_conn(fetchone=(3,))
        with patch.object(db, "_connect", return_value=conn):
            db._seed_default_admin()
        calls = cursor.execute.call_args_list
        # Only the count query, no INSERT
        assert len(calls) == 1
        assert "count" in calls[0][0][0].lower()
