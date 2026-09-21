"""Tests for database/settings_repository.py (roadmap task 1.3).

No live PostgreSQL: a stub connection records every statement, which is enough
to pin down the properties the roadmap requires — partial writes touch only
their own keys, every write bumps the revision in the same transaction, and
database failures surface as StorageUnavailableError.
"""
from __future__ import annotations

import json
import pathlib
import threading

import pytest

from database.errors import StorageUnavailableError
from database.settings_repository import AppSettingsRepository


class _Cursor:
    def __init__(self, conn):
        self._conn = conn
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        if self._conn.fail:
            raise RuntimeError("connection refused")
        self._conn.statements.append((" ".join(sql.split()), params))
        self.rowcount = self._conn.rowcounts.pop(0) if self._conn.rowcounts else 1

    def fetchall(self):
        return self._conn.rows

    def fetchone(self):
        return self._conn.one


class _Conn:
    def __init__(self, rows=(), one=None, rowcounts=(), fail=False):
        self.rows = list(rows)
        self.one = one
        self.rowcounts = list(rowcounts)
        self.fail = fail
        self.statements = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1


def _repo(conn: _Conn) -> AppSettingsRepository:
    repo = object.__new__(AppSettingsRepository)
    repo._dsn = "postgresql://stub"
    repo._initialized = True
    repo._init_lock = threading.Lock()
    repo._connect = lambda: conn
    return repo


class TestRead:
    def test_get_all_returns_key_value_mapping(self):
        conn = _Conn(rows=[("retention.events_retention_days", 90), ("logging.level", "INFO")])
        assert _repo(conn).get_all() == {"retention.events_retention_days": 90, "logging.level": "INFO"}

    def test_get_all_on_an_empty_table_is_empty(self):
        assert _repo(_Conn()).get_all() == {}

    def test_get_many_selects_the_subtree_by_dotted_prefix(self):
        conn = _Conn(rows=[("retention.events_retention_days", 90)])
        result = _repo(conn).get_many("retention")
        assert result == {"retention.events_retention_days": 90}
        sql, params = conn.statements[0]
        assert "starts_with(key, %s)" in sql
        assert params == ("retention.",)

    def test_get_many_does_not_double_the_trailing_dot(self):
        conn = _Conn()
        _repo(conn).get_many("retention.")
        assert conn.statements[0][1] == ("retention.",)

    def test_revision_reads_the_counter(self):
        assert _repo(_Conn(one=(7,))).revision() == 7

    def test_revision_of_a_missing_row_is_zero(self):
        assert _repo(_Conn(one=None)).revision() == 0


class TestWrite:
    def test_set_many_upserts_each_key_then_bumps_revision_in_one_transaction(self):
        conn = _Conn(one=(5,))
        revision = _repo(conn).set_many({"a.b": 1, "c.d": [1, 2]}, updated_by=42)

        assert revision == 5
        assert conn.commits == 1
        kinds = [sql.split()[0] for sql, _ in conn.statements]
        assert kinds == ["INSERT", "INSERT", "UPDATE"]
        assert "app_settings_revision" in conn.statements[-1][0]
        assert "revision = revision + 1" in conn.statements[-1][0]
        assert conn.statements[0][1] == ("a.b", "1", 42)
        assert conn.statements[1][1] == ("c.d", json.dumps([1, 2]), 42)

    def test_partial_write_never_reads_or_touches_other_keys(self):
        """No SELECT and no statement naming a key that was not passed: a
        write is a set of per-key upserts, not a read-modify-write of the
        whole document, so two writers of different keys cannot lose each
        other's changes."""
        conn = _Conn(one=(1,))
        _repo(conn).set_many({"only.this": True})
        assert not [sql for sql, _ in conn.statements if sql.startswith("SELECT")]
        touched = [params[0] for sql, params in conn.statements if sql.startswith("INSERT")]
        assert touched == ["only.this"]

    def test_bool_and_string_values_are_stored_as_json(self):
        conn = _Conn(one=(1,))
        _repo(conn).set_many({"x": True, "y": "aurora"})
        assert conn.statements[0][1][1] == "true"
        assert conn.statements[1][1][1] == json.dumps("aurora")

    def test_empty_write_does_not_bump_the_revision(self):
        conn = _Conn(one=(3,))
        assert _repo(conn).set_many({}) == 3
        assert not [sql for sql, _ in conn.statements if sql.startswith(("INSERT", "UPDATE"))]
        assert conn.commits == 0

    def test_delete_of_an_existing_key_bumps_the_revision(self):
        conn = _Conn(one=(9,), rowcounts=[1])
        assert _repo(conn).delete("a.b") is True
        assert [sql.split()[0] for sql, _ in conn.statements] == ["DELETE", "UPDATE"]
        assert conn.commits == 1

    def test_delete_of_a_missing_key_leaves_the_revision_alone(self):
        conn = _Conn(rowcounts=[0])
        assert _repo(conn).delete("a.b") is False
        assert [sql.split()[0] for sql, _ in conn.statements] == ["DELETE"]


class TestFailures:
    @pytest.mark.parametrize("call", [
        lambda r: r.get_all(),
        lambda r: r.get_many("retention"),
        lambda r: r.revision(),
        lambda r: r.set_many({"a": 1}),
        lambda r: r.delete("a"),
    ])
    def test_database_errors_surface_as_storage_unavailable(self, call):
        with pytest.raises(StorageUnavailableError):
            call(_repo(_Conn(fail=True)))


class TestSchema:
    def test_lazy_schema_creates_users_before_app_settings(self):
        sql = _repo(_Conn())._schema_sql()
        assert sql.index("CREATE TABLE IF NOT EXISTS users") < sql.index("CREATE TABLE IF NOT EXISTS app_settings")
        assert "INSERT INTO app_settings_revision (id) VALUES (1) ON CONFLICT DO NOTHING" in sql

    def test_init_script_defines_the_same_tables(self):
        script = (pathlib.Path(__file__).resolve().parent.parent / "database" / "postgres" / "schema.sql").read_text(encoding="utf-8")
        for fragment in (
            "CREATE TABLE IF NOT EXISTS app_settings (",
            "CREATE TABLE IF NOT EXISTS app_settings_revision (",
            "updated_by BIGINT      REFERENCES users(id) ON DELETE SET NULL",
            "CHECK (id = 1)",
            "INSERT INTO app_settings_revision (id) VALUES (1) ON CONFLICT DO NOTHING",
        ):
            assert fragment in script, fragment
