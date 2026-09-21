"""Инфраструктурный слой окружения (класс D): проверки секретов на старте.

Единственное место, где приложение читает окружение
(`docs/roadmap/configuration-architecture.md`, задачи 0.4 и 1.2): `EnvConfig`
с приведением типов и fail-fast проверка секретов, без которых процесс не
должен подниматься в production.

Модуль намеренно не имеет побочных эффектов при импорте: проверки
вызываются явно на старте процесса (`app/api/main.py`, `app/worker/main.py`).
Зависимостей тяжелее stdlib у него нет — как и у `common/cors.py`, его можно
импортировать и тестировать без FastAPI, torch и БД.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from common.cors import parse_cors_allowed_origins
from common.logging import get_logger
from config.settings_schema import LOG_LEVELS

logger = get_logger(__name__)

#: Значение `APP_ENV`, включающее строгие проверки.
PRODUCTION_ENV = "production"

#: Дефолт `JWT_SECRET_KEY` из `.env.example` — пригоден только для разработки.
DEFAULT_JWT_SECRET_KEY = "anpr-default-secret-change-me"

#: Минимальная длина секрета подписи JWT в байтах.
MIN_JWT_SECRET_BYTES = 32

#: Пароль суперадмина для dev-установок, когда `BOOTSTRAP_SUPERADMIN_PASSWORD`
#: не задан. В production незаданный пароль прерывает запуск.
DEV_BOOTSTRAP_SUPERADMIN_PASSWORD = "1234"


#: DSN по умолчанию — совпадает с `.env.example` и docker-compose.
DEFAULT_POSTGRES_DSN = "postgresql://anpr:anpr@postgres:5432/anpr"

DEFAULT_OMP_NUM_THREADS = 2
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOGS_DIR = "logs"
DEFAULT_MEDIA_DIR = "data/screenshots"
DEFAULT_YOLO_MODEL_PATH = "anpr/models/yolo/best.pt"
DEFAULT_OCR_MODEL_PATH = "anpr/models/ocr_crnn/crnn_ocr_model_int8_fx.pth"
DEFAULT_DEVICE = "cpu"
DEFAULT_POOL_MIN = 2
DEFAULT_POOL_MAX = 10
DEFAULT_IO_POOL_WORKERS = 2


class EnvConfigError(ValueError):
    """Переменная окружения задана, но не проходит проверку типа или диапазона."""


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def _int_var(name: str, raw: str | None, default: int, minimum: int = 1) -> int:
    """Целое из значения переменной; пустое значение = не задано = дефолт."""
    raw = (raw or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise EnvConfigError(f"{name}={raw!r}: ожидается целое число") from None
    if value < minimum:
        raise EnvConfigError(f"{name}={value}: значение должно быть не меньше {minimum}")
    return value


def _log_level(raw: str | None) -> str:
    value = (raw or "").strip().upper()
    if not value:
        return DEFAULT_LOG_LEVEL
    if value not in LOG_LEVELS:
        raise EnvConfigError(f"LOG_LEVEL={raw!r}: допустимо {', '.join(LOG_LEVELS)}")
    return value


@dataclass(frozen=True)
class EnvConfig:
    """Типизированный снимок переменных класса D, которые читает приложение.

    Единственная точка чтения окружения (roadmap, задача 1.2): остальной код
    получает значения отсюда, а не через `os.getenv`. Переменные, которые
    читают только контейнеры или нативные библиотеки (`POSTGRES_USER`,
    `MKL_NUM_THREADS`, …), сюда не входят; переменные фазы 5 (`ANPR_*`) и
    границы пула появятся вместе с задачами, которые начнут их читать.
    """

    app_env: str
    jwt_secret_key: str
    postgres_dsn: str
    cors_allowed_origins: tuple[str, ...]
    omp_num_threads: int
    bootstrap_superadmin_password: str | None
    #: Bootstrap log level: valid from process start until the first read of
    #: `logging.level` from app_settings (the one documented env -> DB case).
    log_level: str
    logs_dir: str
    #: Screenshots and export files: a volume mount point, not a UI setting.
    media_dir: str
    #: Model artifacts inside the image and the inference device.
    yolo_model_path: str
    ocr_model_path: str
    device: str
    postgres_pool_min: int
    postgres_pool_max: int
    io_pool_workers: int

    @property
    def is_production(self) -> bool:
        return self.app_env == PRODUCTION_ENV


def load_env_config(env: Mapping[str, str] | None = None) -> EnvConfig:
    """Прочитать и провалидировать окружение; при ошибке — `EnvConfigError`.

    Без побочных эффектов: секреты здесь не проверяются (для этого
    `enforce_secret_policy`), а лишь приводятся типы.
    """
    source = _env(env)
    password = source.get("BOOTSTRAP_SUPERADMIN_PASSWORD") or ""
    pool_min = _int_var("POSTGRES_POOL_MIN", source.get("POSTGRES_POOL_MIN"), DEFAULT_POOL_MIN)
    pool_max = _int_var("POSTGRES_POOL_MAX", source.get("POSTGRES_POOL_MAX"), DEFAULT_POOL_MAX)
    if pool_max < pool_min:
        raise EnvConfigError(f"POSTGRES_POOL_MAX={pool_max} меньше POSTGRES_POOL_MIN={pool_min}")
    return EnvConfig(
        app_env=app_env(source),
        jwt_secret_key=jwt_secret_key(source),
        postgres_dsn=(source.get("POSTGRES_DSN") or "").strip() or DEFAULT_POSTGRES_DSN,
        cors_allowed_origins=tuple(
            parse_cors_allowed_origins(source.get("CORS_ALLOWED_ORIGINS"))
        ),
        omp_num_threads=_int_var(
            "OMP_NUM_THREADS", source.get("OMP_NUM_THREADS"), DEFAULT_OMP_NUM_THREADS
        ),
        bootstrap_superadmin_password=password if password.strip() else None,
        log_level=_log_level(source.get("LOG_LEVEL")),
        logs_dir=(source.get("ANPR_LOGS_DIR") or "").strip() or DEFAULT_LOGS_DIR,
        media_dir=(source.get("ANPR_MEDIA_DIR") or "").strip() or DEFAULT_MEDIA_DIR,
        yolo_model_path=(source.get("ANPR_YOLO_MODEL_PATH") or "").strip() or DEFAULT_YOLO_MODEL_PATH,
        ocr_model_path=(source.get("ANPR_OCR_MODEL_PATH") or "").strip() or DEFAULT_OCR_MODEL_PATH,
        device=(source.get("ANPR_DEVICE") or "").strip().lower() or DEFAULT_DEVICE,
        postgres_pool_min=pool_min,
        postgres_pool_max=pool_max,
        io_pool_workers=_int_var("ANPR_IO_POOL_WORKERS", source.get("ANPR_IO_POOL_WORKERS"), DEFAULT_IO_POOL_WORKERS),
    )


def verify_model_files(cfg: EnvConfig) -> None:
    """Fail at startup, with the variable name, when a weights file is missing.

    Without this the API would start and every channel would fail later with a
    bare file error from the inference library.
    """
    missing = [
        f"{name}={path!r} — файл не найден"
        for name, path in (("ANPR_YOLO_MODEL_PATH", cfg.yolo_model_path), ("ANPR_OCR_MODEL_PATH", cfg.ocr_model_path))
        if not os.path.isfile(path)
    ]
    if missing:
        raise EnvConfigError("Файлы весов моделей недоступны: " + "; ".join(missing))


def app_env(env: Mapping[str, str] | None = None) -> str:
    """Режим окружения из `APP_ENV` (в нижнем регистре, без пробелов)."""
    return (_env(env).get("APP_ENV") or "").strip().lower()


def is_production(env: Mapping[str, str] | None = None) -> bool:
    """`True`, если окружение объявлено production и проверки строгие."""
    return app_env(env) == PRODUCTION_ENV


def jwt_secret_key(env: Mapping[str, str] | None = None) -> str:
    """Секрет подписи JWT; при отсутствии — заведомо слабый дефолт."""
    return _env(env).get("JWT_SECRET_KEY") or DEFAULT_JWT_SECRET_KEY


def bootstrap_superadmin_password(env: Mapping[str, str] | None = None) -> str:
    """Пароль первичного суперадмина из `BOOTSTRAP_SUPERADMIN_PASSWORD`.

    Значение не обрезается: пробелы могут быть частью пароля. Пустое или
    состоящее только из пробелов значение считается незаданным — в dev
    возвращается `DEV_BOOTSTRAP_SUPERADMIN_PASSWORD`, в production такой
    запуск уже прерван `enforce_secret_policy()`.
    """
    raw = _env(env).get("BOOTSTRAP_SUPERADMIN_PASSWORD") or ""
    if not raw.strip():
        logger.warning(
            "BOOTSTRAP_SUPERADMIN_PASSWORD не задан: суперадмин будет создан "
            "с паролем по умолчанию — смените его сразу после первого входа"
        )
        return DEV_BOOTSTRAP_SUPERADMIN_PASSWORD
    return raw


def secret_problems(env: Mapping[str, str] | None = None) -> list[str]:
    """Перечислить нарушения политики секретов, не принимая решения о старте."""
    source = _env(env)
    problems: list[str] = []

    secret = jwt_secret_key(source)
    if secret == DEFAULT_JWT_SECRET_KEY:
        problems.append(
            "JWT_SECRET_KEY равен дефолту из .env.example — токены может "
            "подделать любой, кто знает этот общеизвестный секрет"
        )
    elif len(secret.encode("utf-8")) < MIN_JWT_SECRET_BYTES:
        problems.append(
            f"JWT_SECRET_KEY короче {MIN_JWT_SECRET_BYTES} байт "
            f"({len(secret.encode('utf-8'))}) — секрет подписи слишком слаб"
        )

    if not (source.get("BOOTSTRAP_SUPERADMIN_PASSWORD") or "").strip():
        problems.append(
            "BOOTSTRAP_SUPERADMIN_PASSWORD не задан — первичный суперадмин "
            f"будет создан с паролем {DEV_BOOTSTRAP_SUPERADMIN_PASSWORD!r}, "
            "одинаковым во всех установках"
        )

    return problems


def enforce_secret_policy(env: Mapping[str, str] | None = None) -> list[str]:
    """Проверить секреты на старте: в production — fail-fast, иначе warning.

    Возвращает список найденных нарушений (пустой, если их нет), чтобы
    вызывающая сторона могла их залогировать или показать. При
    `APP_ENV=production` и непустом списке поднимает `SystemExit`: запуск с
    дефолтным секретом не должен проходить незамеченным.
    """
    problems = secret_problems(env)
    if not problems:
        return []

    if is_production(env):
        for problem in problems:
            logger.critical("Запуск в production невозможен: %s", problem)
        raise SystemExit(
            "APP_ENV=production: проверка секретов не пройдена ("
            + "; ".join(problems)
            + ")"
        )

    for problem in problems:
        logger.warning("Небезопасная конфигурация секретов: %s", problem)
    return problems
