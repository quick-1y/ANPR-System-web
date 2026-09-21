"""Tests for config/env_settings.py — startup secret policy (roadmap task 0.4).

Covers the two regimes the roadmap requires: APP_ENV=production aborts the
process on a weak secret, any other environment only warns and keeps running.
The module under test is dependency-free, so nothing here needs FastAPI,
torch or a database.
"""
from __future__ import annotations

import pytest

from config.env_settings import (
    DEFAULT_JWT_SECRET_KEY,
    DEV_BOOTSTRAP_SUPERADMIN_PASSWORD,
    MIN_JWT_SECRET_BYTES,
    app_env,
    bootstrap_superadmin_password,
    enforce_secret_policy,
    is_production,
    jwt_secret_key,
    secret_problems,
)

STRONG_SECRET = "s" * MIN_JWT_SECRET_BYTES


def _env(**overrides: str) -> dict[str, str]:
    """A valid production environment, with per-test overrides applied."""
    base = {
        "APP_ENV": "production",
        "JWT_SECRET_KEY": STRONG_SECRET,
        "BOOTSTRAP_SUPERADMIN_PASSWORD": "a-real-password",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Environment mode
# ---------------------------------------------------------------------------

class TestAppEnv:
    def test_missing_app_env_is_not_production(self):
        assert app_env({}) == ""
        assert is_production({}) is False

    def test_production_is_recognised_case_insensitively(self):
        assert is_production({"APP_ENV": "  Production "}) is True

    def test_docker_is_not_production(self):
        assert is_production({"APP_ENV": "docker"}) is False


# ---------------------------------------------------------------------------
# Individual values
# ---------------------------------------------------------------------------

class TestJwtSecretKey:
    def test_falls_back_to_the_weak_default(self):
        assert jwt_secret_key({}) == DEFAULT_JWT_SECRET_KEY

    def test_reads_the_configured_value(self):
        assert jwt_secret_key({"JWT_SECRET_KEY": STRONG_SECRET}) == STRONG_SECRET


class TestBootstrapSuperadminPassword:
    def test_reads_the_configured_value(self):
        env = {"BOOTSTRAP_SUPERADMIN_PASSWORD": "from-env"}
        assert bootstrap_superadmin_password(env) == "from-env"

    def test_whitespace_inside_the_password_is_preserved(self):
        env = {"BOOTSTRAP_SUPERADMIN_PASSWORD": "two words"}
        assert bootstrap_superadmin_password(env) == "two words"

    def test_unset_falls_back_to_the_dev_password(self):
        assert bootstrap_superadmin_password({}) == DEV_BOOTSTRAP_SUPERADMIN_PASSWORD

    def test_blank_counts_as_unset(self):
        env = {"BOOTSTRAP_SUPERADMIN_PASSWORD": "   "}
        assert bootstrap_superadmin_password(env) == DEV_BOOTSTRAP_SUPERADMIN_PASSWORD


# ---------------------------------------------------------------------------
# Policy evaluation
# ---------------------------------------------------------------------------

class TestSecretProblems:
    def test_fully_configured_environment_has_no_problems(self):
        assert secret_problems(_env()) == []

    def test_default_secret_is_reported(self):
        problems = secret_problems(_env(JWT_SECRET_KEY=DEFAULT_JWT_SECRET_KEY))
        assert len(problems) == 1
        assert "JWT_SECRET_KEY" in problems[0]

    def test_unset_secret_is_reported_as_the_default(self):
        env = _env()
        del env["JWT_SECRET_KEY"]
        problems = secret_problems(env)
        assert len(problems) == 1
        assert "JWT_SECRET_KEY" in problems[0]

    def test_short_secret_is_reported(self):
        problems = secret_problems(_env(JWT_SECRET_KEY="s" * (MIN_JWT_SECRET_BYTES - 1)))
        assert len(problems) == 1
        assert str(MIN_JWT_SECRET_BYTES) in problems[0]

    def test_secret_length_is_measured_in_bytes_not_characters(self):
        """32 Cyrillic characters are 64 UTF-8 bytes — and still fine; 16 of
        them are 32 bytes, which is the boundary."""
        assert secret_problems(_env(JWT_SECRET_KEY="я" * 16)) == []
        problems = secret_problems(_env(JWT_SECRET_KEY="я" * 15))
        assert len(problems) == 1

    def test_missing_bootstrap_password_is_reported(self):
        env = _env()
        del env["BOOTSTRAP_SUPERADMIN_PASSWORD"]
        problems = secret_problems(env)
        assert len(problems) == 1
        assert "BOOTSTRAP_SUPERADMIN_PASSWORD" in problems[0]

    def test_blank_bootstrap_password_is_reported(self):
        problems = secret_problems(_env(BOOTSTRAP_SUPERADMIN_PASSWORD="  "))
        assert len(problems) == 1
        assert "BOOTSTRAP_SUPERADMIN_PASSWORD" in problems[0]

    def test_several_problems_are_all_reported(self):
        problems = secret_problems(
            {"APP_ENV": "production", "JWT_SECRET_KEY": DEFAULT_JWT_SECRET_KEY}
        )
        assert len(problems) == 2


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------

class TestEnforceSecretPolicy:
    def test_production_with_default_secret_aborts_startup(self):
        with pytest.raises(SystemExit) as exc:
            enforce_secret_policy(_env(JWT_SECRET_KEY=DEFAULT_JWT_SECRET_KEY))
        assert "JWT_SECRET_KEY" in str(exc.value)

    def test_production_with_short_secret_aborts_startup(self):
        with pytest.raises(SystemExit):
            enforce_secret_policy(_env(JWT_SECRET_KEY="short"))

    def test_production_without_bootstrap_password_aborts_startup(self):
        env = _env()
        del env["BOOTSTRAP_SUPERADMIN_PASSWORD"]
        with pytest.raises(SystemExit) as exc:
            enforce_secret_policy(env)
        assert "BOOTSTRAP_SUPERADMIN_PASSWORD" in str(exc.value)

    def test_production_with_strong_secrets_starts(self):
        assert enforce_secret_policy(_env()) == []

    def test_development_with_default_secret_warns_and_continues(self, caplog):
        env = _env(APP_ENV="docker", JWT_SECRET_KEY=DEFAULT_JWT_SECRET_KEY)
        with caplog.at_level("WARNING"):
            problems = enforce_secret_policy(env)
        assert len(problems) == 1
        assert any(record.levelname == "WARNING" for record in caplog.records)

    def test_development_without_app_env_warns_and_continues(self):
        assert len(enforce_secret_policy({})) == 2


class TestEnvConfig:
    def test_defaults_on_empty_environment(self):
        from config.env_settings import (
            DEFAULT_OMP_NUM_THREADS,
            DEFAULT_POSTGRES_DSN,
            load_env_config,
        )

        cfg = load_env_config({})
        assert cfg.app_env == ""
        assert cfg.jwt_secret_key == DEFAULT_JWT_SECRET_KEY
        assert cfg.postgres_dsn == DEFAULT_POSTGRES_DSN
        assert cfg.cors_allowed_origins == ()
        assert cfg.omp_num_threads == DEFAULT_OMP_NUM_THREADS
        assert cfg.bootstrap_superadmin_password is None
        assert cfg.is_production is False

    def test_values_are_read_and_typed(self):
        from config.env_settings import load_env_config

        cfg = load_env_config(
            {
                "APP_ENV": " Production ",
                "POSTGRES_DSN": " postgresql://u:p@h:5432/d ",
                "CORS_ALLOWED_ORIGINS": "https://a.example, https://b.example,",
                "OMP_NUM_THREADS": "4",
                "BOOTSTRAP_SUPERADMIN_PASSWORD": "  pw ",
            }
        )
        assert cfg.is_production is True
        assert cfg.postgres_dsn == "postgresql://u:p@h:5432/d"
        assert cfg.cors_allowed_origins == ("https://a.example", "https://b.example")
        assert cfg.omp_num_threads == 4
        assert cfg.bootstrap_superadmin_password == "  pw "

    def test_blank_values_fall_back_to_defaults(self):
        from config.env_settings import DEFAULT_OMP_NUM_THREADS, load_env_config

        cfg = load_env_config({"OMP_NUM_THREADS": "  ", "POSTGRES_DSN": ""})
        assert cfg.omp_num_threads == DEFAULT_OMP_NUM_THREADS

    @pytest.mark.parametrize(
        "name, value",
        [
            ("OMP_NUM_THREADS", "-1"),
            ("OMP_NUM_THREADS", "2.5"),
        ],
    )
    def test_invalid_integers_raise(self, name, value):
        from config.env_settings import EnvConfigError, load_env_config

        with pytest.raises(EnvConfigError) as exc:
            load_env_config({name: value})
        assert name in str(exc.value)

    def test_reads_process_environment_by_default(self):
        from unittest.mock import patch

        from config.env_settings import load_env_config

        with patch.dict("os.environ", {"OMP_NUM_THREADS": "3"}):
            assert load_env_config().omp_num_threads == 3

    def test_registry_defaults_agree_with_env_layer(self):
        from config.env_settings import DEFAULT_OMP_NUM_THREADS, DEFAULT_POSTGRES_DSN
        from config.registry import get_spec

        assert get_spec("OMP_NUM_THREADS").default == DEFAULT_OMP_NUM_THREADS
        assert get_spec("POSTGRES_DSN").default == DEFAULT_POSTGRES_DSN


class TestNoDirectEnvironmentReads:
    """Roadmap 1.2: only config/env_settings.py may read the environment."""

    def test_no_os_getenv_or_environ_outside_env_settings(self):
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        offenders = []
        for directory in ("anpr", "app", "common", "config", "controllers", "database", "runtime"):
            for path in (root / directory).rglob("*.py"):
                if path.relative_to(root).as_posix() == "config/env_settings.py":
                    continue
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    if (
                        isinstance(node, ast.Attribute)
                        and node.attr in ("getenv", "environ")
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "os"
                    ):
                        offenders.append(f"{path.relative_to(root)}:{node.lineno}")
        assert not offenders, f"Direct environment reads: {offenders}"
