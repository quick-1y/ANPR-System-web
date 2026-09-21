"""Keep `database/postgres/schema.sql` and the repositories' lazy-bootstrap DDL
identical (roadmap task 1.4, problem P11).

`schema.sql` is mounted as the Docker init script; the repositories bootstrap
their own tables lazily. Both must describe the same schema. Without a live
PostgreSQL the comparison is done on the DDL statements themselves: every
`CREATE TABLE` / `CREATE INDEX` a repository runs must appear, token for
token, in `schema.sql`, and every table or index in `schema.sql` must be owned
by some repository.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from database.channel_repository import ChannelDatabase
from database.controller_repository import ControllerDatabase
from database.lists_repository import ListDatabase
from database.settings_repository import AppSettingsRepository
from database.user_repository import UserDatabase

SCHEMA_SQL = Path(__file__).resolve().parent.parent / "database" / "postgres" / "schema.sql"
DSN = "postgresql://unused/unused"

_DDL_RE = re.compile(r"^(?:CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX)|ALTER\s+TABLE)\b", re.IGNORECASE)


def _statements(sql: str) -> list[str]:
    sql = re.sub(r"--[^\n]*", "", sql)
    return [part.strip() for part in sql.split(";") if part.strip()]


def _normalise(statement: str) -> str:
    text = re.sub(r"\s+", " ", statement.strip())
    text = re.sub(r"\s*([(),])\s*", r"\1", text)
    return text.lower()


def _ddl(sql: str) -> dict[str, str]:
    """Normalised CREATE TABLE / CREATE INDEX statements, keyed by object name."""
    result: dict[str, str] = {}
    for statement in _statements(sql):
        if not _DDL_RE.match(statement):
            continue
        alter = re.match(r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+(\w+)", statement, re.IGNORECASE)
        name = f"{alter.group(1)}.{alter.group(2)}".lower() if alter else re.search(r"IF NOT EXISTS\s+(\w+)", statement, re.IGNORECASE).group(1).lower()
        assert name not in result, f"{name} is defined twice"
        result[name] = _normalise(statement)
    return result


REPOSITORIES = [
    ChannelDatabase,
    ControllerDatabase,
    ListDatabase,
    UserDatabase,
    AppSettingsRepository,
]


def _repository_ddl() -> dict[str, tuple[str, str]]:
    owned: dict[str, tuple[str, str]] = {}
    for cls in REPOSITORIES:
        for name, statement in _ddl(cls(DSN)._schema_sql()).items():
            # AppSettingsRepository re-runs the users DDL (FK dependency): the
            # same statement owned twice is fine, a different one is drift.
            if name in owned:
                assert owned[name][1] == statement, f"{name} differs between repositories"
                continue
            owned[name] = (cls.__name__, statement)
    return owned


SCHEMA_DDL = _ddl(SCHEMA_SQL.read_text(encoding="utf-8"))
REPO_DDL = _repository_ddl()


@pytest.mark.parametrize("name", sorted(REPO_DDL))
def test_repository_ddl_matches_schema_sql(name):
    owner, statement = REPO_DDL[name]
    assert name in SCHEMA_DDL, f"{owner} creates {name!r} but schema.sql does not"
    assert SCHEMA_DDL[name] == statement, f"{name!r}: schema.sql differs from {owner}"


def test_schema_sql_has_no_orphan_objects():
    """Everything in schema.sql is owned by a repository, except `events`
    and `zones`, whose repository reads schema.sql itself and so cannot drift."""
    self_owned = {n for n in SCHEMA_DDL if n in ("events", "zones") or n.startswith("idx_events_")}
    orphans = set(SCHEMA_DDL) - set(REPO_DDL) - self_owned
    assert not orphans, f"In schema.sql but not created by any repository: {sorted(orphans)}"


def test_schema_sql_covers_every_table():
    tables = {n for n in SCHEMA_DDL if not n.startswith(("idx_", "uq_")) and "." not in n}
    assert {
        "zones", "events", "channels", "controllers", "lists", "clients",
        "users", "app_settings", "app_settings_revision",
    } <= tables


def test_foreign_key_targets_are_created_first():
    """Init scripts run top to bottom: a referenced table must come earlier."""
    text = re.sub(r"--[^\n]*", "", SCHEMA_SQL.read_text(encoding="utf-8")).lower()
    position = {m.group(1): m.start() for m in re.finditer(r"create table if not exists (\w+)", text)}
    for m in re.finditer(r"create table if not exists (\w+)(.*?)\n\);", text, re.DOTALL):
        table = m.group(1)
        for target in re.findall(r"references (\w+)\(", m.group(2)):
            assert position[target] < position[table], f"{table} references {target} defined later"
