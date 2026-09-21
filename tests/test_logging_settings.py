"""Logging settings: env is the bootstrap layer, app_settings takes over
(roadmap task 4.3 — the single documented two-layer case, rule 3)."""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

import common.logging as clog
from app.worker.main import RetentionScheduler
from config.env_settings import EnvConfigError, load_env_config
from config.logging_setup import LoggingApplier, bootstrap_logging
from config.settings_service import SettingsService
from tests.test_reconnect_settings import USER, _container, _payload
from tests.test_settings_service import _Clock, _Repo

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture
def logdir(tmp_path):
    yield tmp_path
    with clog._STATE_LOCK:
        clog._stop_runtime_threads()
    logging.getLogger().handlers.clear()
    logging.getLogger().setLevel(logging.WARNING)


def _env(tmp_path, **extra):
    return {"ANPR_LOGS_DIR": str(tmp_path), **extra}


def _service(stored=None):
    repo = _Repo(stored)
    return SettingsService(repo, clock=_Clock()), repo


def _flush_and_read(tmp_path) -> str:
    with clog._STATE_LOCK:
        clog._stop_runtime_threads()
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(tmp_path.glob("*.log")))


class TestEnvLayer:
    def test_defaults(self):
        cfg = load_env_config({})
        assert (cfg.log_level, cfg.logs_dir) == ("INFO", "logs")

    def test_level_is_normalised_and_dir_read(self):
        cfg = load_env_config({"LOG_LEVEL": " warning ", "ANPR_LOGS_DIR": "/app/logs"})
        assert (cfg.log_level, cfg.logs_dir) == ("WARNING", "/app/logs")

    def test_invalid_level_fails_fast(self):
        with pytest.raises(EnvConfigError) as exc:
            load_env_config({"LOG_LEVEL": "LOUD"})
        assert "LOG_LEVEL" in str(exc.value)


class TestPriorityEnvThenDatabase:
    def test_bootstrap_uses_the_env_level(self, logdir):
        bootstrap_logging("t", _env(logdir, LOG_LEVEL="WARNING"))
        assert logging.getLogger().level == logging.WARNING

    def test_early_messages_follow_env_later_messages_follow_the_database(self, logdir):
        env = _env(logdir, LOG_LEVEL="WARNING")
        bootstrap_logging("t", env)
        log = logging.getLogger("order.test")
        log.info("early-info")
        log.warning("early-warning")

        service, _ = _service({"logging.level": "DEBUG"})
        assert LoggingApplier(service, "t", env).apply() is True
        log.debug("late-debug")

        text = _flush_and_read(logdir)
        assert "early-info" not in text
        assert "early-warning" in text
        assert "late-debug" in text

    def test_database_level_wins_over_env_once_loaded(self, logdir):
        env = _env(logdir, LOG_LEVEL="DEBUG")
        bootstrap_logging("t", env)
        service, _ = _service({"logging.level": "ERROR"})
        LoggingApplier(service, "t", env).apply()
        assert logging.getLogger().level == logging.ERROR

    def test_env_level_stays_while_the_database_was_never_read(self, logdir):
        env = _env(logdir, LOG_LEVEL="WARNING")
        bootstrap_logging("t", env)
        service, repo = _service()
        repo.down = True  # registry default is ALL — must NOT replace the env level
        applier = LoggingApplier(service, "t", env)
        assert applier.apply() is False
        assert applier.applied is None
        assert logging.getLogger().level == logging.WARNING

    def test_change_in_the_database_is_applied_without_restart(self, logdir):
        env = _env(logdir)
        bootstrap_logging("t", env)
        service, repo = _service({"logging.level": "INFO"})
        applier = LoggingApplier(service, "t", env)
        assert applier.apply() is True
        assert applier.apply() is False  # unchanged -> no reconfiguration
        repo.external_write({"logging.level": "ERROR"})
        service._checked_at = None
        assert applier.apply() is True
        assert logging.getLogger().level == logging.ERROR

    def test_logs_dir_always_comes_from_env(self, logdir):
        env = _env(logdir)
        service, _ = _service({"logging.retention_days": 5})
        LoggingApplier(service, "t", env).apply()
        logging.getLogger("dir.test").warning("hello")
        assert list(logdir.glob("t_*.log"))


class TestApiAndWorkerWiring:
    def test_put_saves_logging_keys_in_the_same_transaction_and_reapplies(self):
        from app.api.routers import settings as settings_router

        container, repo = _container()
        payload = _payload()
        payload.logging = type(payload.logging)(level="ERROR", retention_days=9)
        settings_router.put_global_settings(payload, container=container, current_user=USER)
        (values, _author), = repo.writes
        assert values["logging.level"] == "ERROR"
        assert values["logging.retention_days"] == 9
        container.logging_applier.apply.assert_called_once()

    def test_get_settings_serves_logging_from_the_database(self):
        from app.api.routers import settings as settings_router

        container, _ = _container(_Repo({"logging.level": "WARNING"}))
        body = settings_router.get_global_settings(container=container, current_user=USER)
        assert body["logging"] == {"level": "WARNING", "retention_days": 30}


    def test_worker_scheduler_reapplies_logging_every_tick(self):
        service, _ = _service()
        applier = MagicMock()
        scheduler = RetentionScheduler(MagicMock(), service, clock=_Clock(), logging_applier=applier)
        scheduler.tick()
        applier.apply.assert_called_once()

