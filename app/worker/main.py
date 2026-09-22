from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict

from fastapi import FastAPI, Request

from config.env_settings import enforce_secret_policy, load_env_config
from config.settings_service import SettingsService
from database.errors import StorageUnavailableError
from database.settings_repository import AppSettingsRepository
from app.shared.data_lifecycle import DataLifecycleService, RetentionPolicy
from common.logging import get_logger
from config.logging_setup import LoggingApplier, bootstrap_logging

logger = get_logger(__name__)

# Fail-fast on weak infrastructure secrets before the worker starts: with
# APP_ENV=production a default JWT_SECRET_KEY or a missing
# SUPERADMIN_PASSWORD aborts the process (roadmap task 0.4).
enforce_secret_policy()


class RetentionScheduler:
    #: How often the policy is re-read. Deliberately shorter than any sensible
    #: cleanup interval, so a changed interval takes effect within one poll
    #: instead of after the previous (possibly very long) sleep has run out.
    POLICY_POLL_SECONDS = 30.0
    MIN_INTERVAL_SECONDS = 60.0

    def __init__(
        self,
        lifecycle: DataLifecycleService,
        settings: SettingsService,
        *,
        clock: Callable[[], float] = time.monotonic,
        logging_applier: LoggingApplier | None = None,
    ) -> None:
        self._logging_applier = logging_applier
        self._lifecycle = lifecycle
        self._settings = settings
        self._clock = clock
        self._task: asyncio.Task[Any] | None = None
        self._last_run: Dict[str, int] | None = None
        self._last_run_at: float | None = None

    def tick(self) -> float:
        """One scheduler iteration; returns how many seconds to sleep before the next.

        The policy is re-read from `SettingsService` on every tick (P9), so an
        administrator's change reaches the worker without a restart, and the
        next run time is recomputed from the *current* interval.
        """
        if self._logging_applier is not None:
            self._logging_applier.apply()
        policy = RetentionPolicy.from_settings(self._settings)
        if not self._settings.loaded:
            # No successful read of the settings yet (DB down at startup): the
            # registry defaults are not the operator's policy, and retention
            # deletes data, so wait rather than clean up by the wrong rules.
            logger.warning("Настройки retention ещё не прочитаны из БД — цикл очистки отложен")
            return self.POLICY_POLL_SECONDS
        self._lifecycle.update_policy(policy)
        interval = max(self.MIN_INTERVAL_SECONDS, policy.cleanup_interval_minutes * 60.0)
        now = self._clock()
        due = self._last_run_at is None or now - self._last_run_at >= interval
        if policy.auto_cleanup_enabled and due:
            logger.info("Запуск retention cycle (interval_minutes=%s)", policy.cleanup_interval_minutes)
            try:
                self._last_run = self._lifecycle.run_retention_cycle()
            except StorageUnavailableError:
                logger.exception("Ошибка retention cycle")
                self._last_run = {"status": "error"}
            self._last_run_at = self._clock()
        if not policy.auto_cleanup_enabled or self._last_run_at is None:
            return self.POLICY_POLL_SECONDS
        remaining = interval - (self._clock() - self._last_run_at)
        return max(1.0, min(self.POLICY_POLL_SECONDS, remaining))

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.tick())

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    @property
    def last_run(self) -> Dict[str, int] | None:
        return self._last_run


@dataclass
class WorkerContainer:
    settings_service: SettingsService
    lifecycle: DataLifecycleService
    scheduler: RetentionScheduler

    @classmethod
    def build(cls) -> "WorkerContainer":
        bootstrap_logging("worker")
        env = load_env_config()
        dsn = env.postgres_dsn
        settings_service = SettingsService(AppSettingsRepository(dsn))
        logging_applier = LoggingApplier(settings_service, "worker")
        logging_applier.apply()
        lifecycle = DataLifecycleService(
            screenshots_dir=env.media_dir,
            policy=RetentionPolicy.from_settings(settings_service),
            postgres_dsn=dsn,
        )
        scheduler = RetentionScheduler(lifecycle, settings_service, logging_applier=logging_applier)
        return cls(settings_service=settings_service, lifecycle=lifecycle, scheduler=scheduler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = WorkerContainer.build()
    app.state.container = container
    logger.info("Retention worker startup")
    container.scheduler.start()
    yield
    logger.info("Retention worker shutdown")
    container.scheduler.stop()


app = FastAPI(title="ANPR Retention Worker", version="0.8-stage8", lifespan=lifespan)


def _get_container(request: Request) -> WorkerContainer:
    return request.app.state.container


@app.get("/worker/health")
def health(request: Request) -> Dict[str, Any]:
    container = _get_container(request)
    return {
        "status": "ok",
        "policy": container.lifecycle.policy.to_storage(),
        "last_run": container.scheduler.last_run,
    }


@app.post("/worker/retention/run")
def run_retention(request: Request) -> Dict[str, Any]:
    container = _get_container(request)
    logger.info("Ручной запуск retention endpoint")
    try:
        result = container.lifecycle.run_retention_cycle()
        return {"status": "ok", **result}
    except StorageUnavailableError as exc:
        logger.exception("Ошибка retention cycle при ручном запуске")
        return {"status": "error", "detail": str(exc)}


@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "service": "retention-worker",
        "status": "ok",
        "health": "/worker/health",
        "run_retention": "/worker/retention/run",
    }
