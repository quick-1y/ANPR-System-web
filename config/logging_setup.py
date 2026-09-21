"""Двухслойная настройка логирования (roadmap, задача 4.3).

Единственный случай, когда одно значение имеет два источника (правило 3):

1. `bootstrap_logging()` — с первой секунды процесса уровень берётся из
   `LOG_LEVEL` (env), потому что БД ещё не подключена;
2. `LoggingApplier.apply()` — после первого успешного чтения `app_settings`
   логирование переконфигурируется значениями `logging.level` и
   `logging.retention_days` из БД. С этого момента env-уровень не применяется
   до следующего запуска.

Каталог логов — инфраструктурный параметр (`ANPR_LOGS_DIR`), из БД не берётся.
"""
from __future__ import annotations

import threading
from typing import Any, Mapping, Optional, Tuple

from common.logging import configure_logging, get_logger
from config.env_settings import load_env_config
from config.settings_schema import logging_defaults

logger = get_logger(__name__)


def bootstrap_logging(service_name: str, env: Mapping[str, str] | None = None) -> None:
    """Настроить логирование по env: `LOG_LEVEL` и `ANPR_LOGS_DIR`."""
    cfg = load_env_config(env)
    configure_logging(
        {
            "level": cfg.log_level,
            "retention_days": logging_defaults()["retention_days"],
            "logs_dir": cfg.logs_dir,
        },
        service_name=service_name,
    )


class LoggingApplier:
    """Применяет `logging.*` из `SettingsService`, перенастраивая логирование
    только при изменении значений и только когда БД реально прочитана."""

    def __init__(self, settings: Any, service_name: str, env: Mapping[str, str] | None = None) -> None:
        self._settings = settings
        self._service_name = service_name
        self._logs_dir = load_env_config(env).logs_dir
        self._applied: Optional[Tuple[str, int]] = None
        self._lock = threading.Lock()

    @property
    def applied(self) -> Optional[Tuple[str, int]]:
        return self._applied

    def apply(self) -> bool:
        """Вернуть `True`, если логирование было перенастроено."""
        level = self._settings.get("logging.level")
        retention_days = int(self._settings.get("logging.retention_days"))
        if not self._settings.loaded:
            # Значения — дефолты реестра, а не настройки оператора: пока БД
            # не прочитана, остаётся bootstrap-уровень из env.
            return False
        wanted = (level, retention_days)
        with self._lock:
            if wanted == self._applied:
                return False
            configure_logging(
                {"level": level, "retention_days": retention_days, "logs_dir": self._logs_dir},
                service_name=self._service_name,
            )
            self._applied = wanted
        logger.info("Логирование переключено на настройки из БД (level=%s, retention_days=%s)", level, retention_days)
        return True
