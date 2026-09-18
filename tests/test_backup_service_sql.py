"""Tests for app/shared/backup_service.py's SQL composition (finding #3).

The database backup/restore functions build table/column names into SQL
dynamically. `table` only ever comes from the hardcoded _BACKUP_TABLES tuple
(never request input), so this was never a live injection path — but it had
the shape of one (f-string interpolation of identifiers), which the fix
replaces with psycopg.sql.Identifier()/sql.SQL() composition.

These tests drive export_database_backup() and restore_database_backup()
end-to-end against a hand-written fake psycopg connection (no live Postgres
needed — psycopg.sql.Composable.as_string() renders without a real
connection for plain-ASCII identifiers), verifying both that the composed
SQL always double-quotes identifiers and that the round trip still works.
"""
from __future__ import annotations

import json

from app.shared import backup_service


# ---------------------------------------------------------------------------
# Fake psycopg connection/cursor
# ---------------------------------------------------------------------------
# Keyed by substrings of the *rendered* SQL text so both export and restore
# (which issue different queries in a different order) can share one fake.

class _FakeCursor:
    def __init__(self, table_columns, table_rows, jsonb_columns):
        self.executed: list[tuple[str, object]] = []
        self._table_columns = table_columns
        self._table_rows = table_rows
        self._jsonb_columns = jsonb_columns
        self._last_result: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params=None):
        rendered = query.as_string(None) if hasattr(query, "as_string") else str(query)
        self.executed.append((rendered, params))

        if "udt_name = 'jsonb'" in rendered:
            table = params[0]
            self._last_result = [(c,) for c in self._jsonb_columns.get(table, [])]
        elif "information_schema.columns" in rendered:
            table = params[0]
            self._last_result = [(c,) for c in self._table_columns.get(table, [])]
        elif rendered.startswith("SELECT ") and " FROM " in rendered:
            # export's per-table data SELECT
            table = rendered.split(" FROM ")[-1].strip('"')
            self._last_result = self._table_rows.get(table, [])
        else:
            self._last_result = []

    def fetchall(self):
        return self._last_result


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True


def _install_fake_connect(monkeypatch, cursor):
    monkeypatch.setattr(backup_service.psycopg, "connect", lambda dsn: _FakeConnection(cursor))


# ---------------------------------------------------------------------------
# Identifier quoting
# ---------------------------------------------------------------------------

class TestIdentifierQuoting:
    def test_all_executed_identifiers_are_double_quoted(self, monkeypatch):
        """Every table/column reference in the queries this module issues
        must be a properly quoted identifier, not a bare interpolated name —
        that's the whole point of the fix."""
        cursor = _FakeCursor(
            table_columns={"users": ["id", "login"]},
            table_rows={"users": [(1, "admin")]},
            jsonb_columns={"users": []},
        )
        _install_fake_connect(monkeypatch, cursor)

        backup_service.export_database_backup("postgresql://fake/db")

        sql_queries = [rendered for rendered, _params in cursor.executed if rendered.startswith("SELECT ") and " FROM " in rendered and "information_schema" not in rendered]
        assert sql_queries, "expected the per-table data SELECT to have run"
        for rendered in sql_queries:
            assert '"users"' in rendered
            assert '"id"' in rendered and '"login"' in rendered
            # No bare, unquoted table/column name directly after FROM/SELECT.
            assert "FROM users" not in rendered
            assert "SELECT id, login" not in rendered

    def test_malicious_looking_table_name_is_safely_quoted_not_interpreted(self):
        """Defense-in-depth check on the composition mechanism itself: even
        though `table` only ever comes from the hardcoded _BACKUP_TABLES
        tuple today, prove that IF a hostile string ever reached
        sql.Identifier(), it would render as a single quoted identifier
        (with embedded quotes doubled) rather than breaking out of the
        identifier position."""
        from psycopg import sql

        hostile = 'evil"; DROP TABLE users; --'
        rendered = sql.SQL("DELETE FROM {table}").format(table=sql.Identifier(hostile)).as_string(None)

        # The whole hostile string ends up inside one quoted identifier
        # (embedded `"` doubled to `""`), with the query ending exactly at
        # its closing quote — no bare DROP TABLE statement escapes into it.
        assert rendered == 'DELETE FROM "evil""; DROP TABLE users; --"'


# ---------------------------------------------------------------------------
# Round trip still works
# ---------------------------------------------------------------------------

class TestBackupRestoreRoundTrip:
    def test_export_then_restore_round_trips_a_table(self, monkeypatch):
        cursor = _FakeCursor(
            table_columns={"users": ["id", "login"]},
            table_rows={"users": [(1, "admin")]},
            jsonb_columns={"users": []},
        )
        _install_fake_connect(monkeypatch, cursor)

        filename, backup_bytes = backup_service.export_database_backup("postgresql://fake/db")
        assert filename.startswith("db_backup_")

        backup_service.validate_database_backup(backup_bytes)  # must not raise

        cursor.executed.clear()
        result = backup_service.restore_database_backup("postgresql://fake/db", backup_bytes)

        assert result == {"restored_tables": {"users": 1}}

        rendered_queries = [r for r, _p in cursor.executed]
        assert any(r.startswith('DELETE FROM "users"') for r in rendered_queries)
        assert any(r.startswith('INSERT INTO "users"') for r in rendered_queries)
        assert any("setval(pg_get_serial_sequence(%s, 'id')" in r for r in rendered_queries)
        assert cursor.executed[-1][0].count('"users"') >= 1  # the setval FROM clause is quoted too
