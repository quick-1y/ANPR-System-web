"""Tests keeping `.env.example` in sync with the environment the code reads
(roadmap task 0.2).

The audit found drift in both directions: `CORS_ALLOWED_ORIGINS` lived only in
the template, `POSTGRES_PORT` in neither, and `APP_ENV` / `DEBUG` / `LOG_LEVEL`
were documented as if they were read while nothing read them. These tests fix
the template as the description of the real environment: every variable the
Python code reads must be listed, and every listed variable must either be
read by the code or be justified in the allow-list below.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = REPO_ROOT / ".env.example"
ENV_FILE = REPO_ROOT / ".env"

ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")

#: Directories scanned for environment reads (production code only).
SOURCE_DIRS = ("anpr", "app", "common", "config", "controllers", "database", "runtime")

#: Variables that belong in `.env.example` although no Python code reads them.
#: Every entry states its consumer — an unexplained entry is drift.
INFRASTRUCTURE_ONLY = {
    "POSTGRES_DB": "consumed by the postgres container (docker-compose.yml)",
    "POSTGRES_USER": "consumed by the postgres container (docker-compose.yml)",
    "POSTGRES_PASSWORD": "consumed by the postgres container (docker-compose.yml)",
    "POSTGRES_PORT": "host port published by the postgres container (docker-compose.yml)",
    "HTTP_PORT": "host port published by the nginx container (docker-compose.yml)",
    "MKL_NUM_THREADS": "consumed by the native MKL library, not by Python",
    "OPENBLAS_NUM_THREADS": "consumed by the native OpenBLAS library, not by Python",
}

#: Variables whose lifecycle is not the obvious one and which must therefore
#: carry an explicit roadmap-phase annotation in `.env.example`.
PHASE_ANNOTATED = ("APP_ENV", "LOG_LEVEL")

PHASE_COMMENT_RE = re.compile(r"roadmap phase \d+", re.IGNORECASE)


def _parse_env_file(path: Path) -> dict[str, list[str]]:
    """Map each variable in an env file to the comment lines above it."""
    entries: dict[str, list[str]] = {}
    comments: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            comments = []
            continue
        if line.startswith("#"):
            comments.append(line.lstrip("#").strip())
            continue
        name = line.split("=", 1)[0].strip()
        entries[name] = comments
        comments = []
    return entries


def _python_sources() -> list[Path]:
    files: list[Path] = []
    for directory in SOURCE_DIRS:
        files.extend((REPO_ROOT / directory).rglob("*.py"))
    return files


def _env_names_read_by(path: Path) -> set[str]:
    """Environment variable names read in one module.

    Recognises `os.getenv("X")`, `os.environ["X"]` and any `.get("X")` whose
    literal key looks like an environment variable name — the latter covers
    `config/env_settings.py`, which reads from an injected mapping rather than
    from `os.environ` directly.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args:
            first = node.args[0]
            func = node.func
            is_get = isinstance(func, ast.Attribute) and func.attr in ("get", "getenv")
            if is_get and isinstance(first, ast.Constant) and isinstance(first.value, str):
                if ENV_NAME_RE.match(first.value):
                    names.add(first.value)
        elif isinstance(node, ast.Subscript):
            value, key = node.value, node.slice
            is_environ = isinstance(value, ast.Attribute) and value.attr == "environ"
            if is_environ and isinstance(key, ast.Constant) and isinstance(key.value, str):
                names.add(key.value)
    return names


def _env_names_read_by_code() -> dict[str, list[str]]:
    """Every environment variable read by the code, with the modules reading it."""
    found: dict[str, list[str]] = {}
    for path in _python_sources():
        for name in _env_names_read_by(path):
            found.setdefault(name, []).append(str(path.relative_to(REPO_ROOT)))
    return found


class TestEnvExampleSync:
    def test_every_variable_read_by_code_is_in_the_template(self):
        template = set(_parse_env_file(ENV_EXAMPLE))
        missing = {
            name: readers
            for name, readers in _env_names_read_by_code().items()
            if name not in template
        }
        assert not missing, f"Read by code but absent from .env.example: {missing}"

    def test_every_template_variable_is_read_or_allow_listed(self):
        read_by_code = set(_env_names_read_by_code())
        unexplained = [
            name
            for name in _parse_env_file(ENV_EXAMPLE)
            if name not in read_by_code and name not in INFRASTRUCTURE_ONLY
        ]
        assert not unexplained, (
            "In .env.example but neither read by code nor allow-listed as "
            f"infrastructure-only: {unexplained}"
        )

    def test_allow_list_has_no_stale_entries(self):
        template = set(_parse_env_file(ENV_EXAMPLE))
        stale = [name for name in INFRASTRUCTURE_ONLY if name not in template]
        assert not stale, f"Allow-listed but missing from .env.example: {stale}"

    def test_dead_and_pending_variables_are_annotated_with_their_phase(self):
        entries = _parse_env_file(ENV_EXAMPLE)
        unannotated = [
            name
            for name in PHASE_ANNOTATED
            if not PHASE_COMMENT_RE.search(" ".join(entries.get(name, [])))
        ]
        assert not unannotated, (
            "These variables must say in a comment which roadmap phase removes "
            f"them or starts reading them: {unannotated}"
        )


class TestLocalEnvFile:
    def test_local_env_matches_the_template(self):
        """A developer's `.env` and the template must describe the same set of
        variables. Skipped on a fresh clone, where `.env` does not exist yet."""
        if not ENV_FILE.exists():
            pytest.skip(".env is absent (fresh clone) — nothing to compare")
        template = set(_parse_env_file(ENV_EXAMPLE))
        local = set(_parse_env_file(ENV_FILE))
        assert local == template, (
            f"Only in .env: {sorted(local - template)}; "
            f"only in .env.example: {sorted(template - local)}"
        )
