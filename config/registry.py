"""Реестр конфигурации: классы, типы, дефолты и правила валидации.

Единый машинночитаемый источник для всей инвентаризации roadmap'а
(`docs/roadmap/configuration-architecture.md`, задача 1.1): для каждого
значения — класс (D/A/U/C/L), тип, дефолт, домен, требование перезапуска,
владелец и описание.

Дефолты берутся из `config/settings_schema.py` с применением решений 4.10;
значения каналов (`CHANNEL_SPECS`) реестр дополняет типами и границами, по
которым строятся pydantic-схемы. Класс C (константы кода) в реестр
записями не входит — он владеет лишь доменами перечислений (`THEMES`, `STYLES`,
`COUNTRIES`, `LOG_LEVELS`) и дефолтами ключей классов A и U, которые заданы
ниже.

Модуль не имеет побочных эффектов при импорте и не обращается к БД.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config.env_settings import (
    DEFAULT_DEVICE,
    DEFAULT_IO_POOL_WORKERS,
    DEFAULT_JWT_SECRET_KEY,
    DEFAULT_LOGS_DIR,
    DEFAULT_MEDIA_DIR,
    DEFAULT_OCR_MODEL_PATH,
    DEFAULT_POOL_MAX,
    DEFAULT_POOL_MIN,
    DEFAULT_YOLO_MODEL_PATH,
)
from config.settings_schema import (
    LOG_LEVELS,
    SUPPORTED_CONTROLLER_TYPES,
    channel_defaults,
    logging_defaults,
    plate_defaults,
    plate_size_defaults,
    reconnect_defaults,
    retention_defaults,
)

THEMES = ("light", "dark")
STYLES = ("graphite-minimal", "aurora")
#: Коды стран, для которых есть конфигурации в `anpr/countries/`.
COUNTRIES = ("RU", "UA", "BY", "KZ")

# Домены перечислений (задача 3.2): каждый объявлен один раз здесь. Схемы
# pydantic, нормализаторы, репозитории и `GET /api/settings/schema` берут
# допустимые значения отсюда; список <option> в UI строится по ответу API.
DETECTION_MODES = ("always", "motion")
DIRECTION_FILTERS = ("approaching", "receding", "both")
LIST_FILTER_MODES = ("all", "whitelist", "custom")
ZONE_CHANNEL_TYPES = ("entry", "exit")
RELAY_MODES = ("pulse", "pulse_timer")
ROI_UNITS = ("px", "percent")

#: Зоны отображения, предлагаемые в UI (IANA). Проверка значения остаётся за
#: `_valid_zone` — принимается любой корректный идентификатор, список нужен
#: только для выбора; расширяется правкой этой строки.
TIMEZONES = (
    "UTC", "Europe/Kaliningrad", "Europe/Minsk", "Europe/Moscow", "Europe/Kyiv",
    "Europe/Samara", "Asia/Yekaterinburg", "Asia/Almaty", "Asia/Omsk",
    "Asia/Novosibirsk", "Asia/Krasnoyarsk", "Asia/Irkutsk", "Asia/Yakutsk",
    "Asia/Vladivostok", "Asia/Magadan", "Asia/Kamchatka", "Asia/Tashkent",
    "Asia/Tbilisi", "Asia/Yerevan", "Asia/Baku",
)

#: Все домены для `GET /api/settings/schema` и генерации паттернов.
ENUMS: Dict[str, Tuple[str, ...]] = {
    "theme": THEMES,
    "style": STYLES,
    "log_level": tuple(LOG_LEVELS),
    "country": COUNTRIES,
    "detection_mode": DETECTION_MODES,
    "controller_direction_filter": DIRECTION_FILTERS,
    "list_filter_mode": LIST_FILTER_MODES,
    "zone_channel_type": ZONE_CHANNEL_TYPES,
    "relay_mode": RELAY_MODES,
    "roi_unit": ROI_UNITS,
    "controller_type": tuple(SUPPORTED_CONTROLLER_TYPES),
}


def choices_pattern(choices: Tuple[str, ...]) -> str:
    """Регулярное выражение pydantic, принимающее ровно значения `choices`."""
    return "^(" + "|".join(choices) + ")$"


def schema_document() -> Dict[str, Any]:
    """Тело `GET /api/settings/schema`: домены перечислений и список зон."""
    return {
        "enums": {name: list(values) for name, values in ENUMS.items()},
        "timezones": list(TIMEZONES),
    }

#: Уровни доступа из 4.11 плюс два не-API владельца: развёртывание (класс D)
#: и устройство пользователя (класс L).
OWNERS = (
    "public",
    "self",
    "admin-config",
    "admin-data",
    "admin-users",
    "admin-debug",
    "admin-devices",
    "deploy",
    "device",
)

_TYPES = ("bool", "int", "float", "str", "str_list")


class ConfigClass(str, Enum):
    D = "D"  # .env — развёртывание и инфраструктура
    A = "A"  # app_settings — операционные настройки инстанса
    U = "U"  # users.preferences — личные предпочтения
    C = "C"  # константы кода
    L = "L"  # localStorage — состояние устройства и кэш


class SettingValidationError(ValueError):
    """Значение не соответствует спецификации ключа в реестре."""


@dataclass(frozen=True)
class SettingSpec:
    key: str
    cls: ConfigClass
    type: str
    default: Any
    owner: str
    description: str
    choices: Optional[Tuple[Any, ...]] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    validator: Optional[Callable[[Any], Any]] = None
    requires_restart: bool = False
    reserved: bool = False

    def __post_init__(self) -> None:
        if self.type not in _TYPES:
            raise ValueError(f"{self.key}: неизвестный тип {self.type!r}")
        if self.owner not in OWNERS:
            raise ValueError(f"{self.key}: неизвестный владелец {self.owner!r}")
        if not self.description.strip():
            raise ValueError(f"{self.key}: описание обязательно")
        if self.reserved and not self.description.startswith("Зарезервирован:"):
            raise ValueError(f"{self.key}: reserved требует причины в описании (\"Зарезервирован: ...\")")
        if self.default is not None:
            object.__setattr__(self, "default", self.validate(self.default))

    def validate(self, value: Any) -> Any:
        """Проверить значение и вернуть его в нормализованном виде."""
        checked = self._check_type(value)
        if self.type == "str_list":
            if self.choices is not None:
                unknown = [item for item in checked if item not in self.choices]
                if unknown:
                    raise SettingValidationError(f"{self.key}: недопустимые значения {unknown}, допустимо {list(self.choices)}")
        elif self.choices is not None and checked not in self.choices:
            raise SettingValidationError(f"{self.key}: значение {checked!r} вне допустимых {list(self.choices)}")
        if self.type in ("int", "float"):
            if self.minimum is not None and checked < self.minimum:
                raise SettingValidationError(f"{self.key}: значение {checked} меньше минимума {self.minimum}")
            if self.maximum is not None and checked > self.maximum:
                raise SettingValidationError(f"{self.key}: значение {checked} больше максимума {self.maximum}")
        if self.validator is not None:
            try:
                checked = self.validator(checked)
            except SettingValidationError:
                raise
            except ValueError as exc:
                raise SettingValidationError(f"{self.key}: {exc}") from exc
        return checked

    def _check_type(self, value: Any) -> Any:
        # bool — подкласс int, поэтому его нужно исключать явно: `True` не
        # должен молча становиться числом `1` в целочисленной настройке.
        if self.type == "bool":
            if isinstance(value, bool):
                return value
        elif self.type == "int":
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        elif self.type == "float":
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        elif self.type == "str":
            if isinstance(value, str):
                return value
        elif self.type == "str_list":
            if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
                # Дубликаты убираются с сохранением порядка: список стран — множество.
                return list(dict.fromkeys(value))
        raise SettingValidationError(f"{self.key}: ожидается тип {self.type}, получено {type(value).__name__}")


def _valid_zone(value: str) -> str:
    """Принять `UTC` (и `auto` для личной зоны) либо идентификатор IANA.

    `zoneinfo` на Windows не имеет системной базы зон, пока не установлен
    `tzdata`; зависимость добавляется задачей 4.5. До этого значения, кроме
    `UTC`, на такой машине будут отклонены с понятной причиной.
    """
    if value in ("UTC", "auto"):
        return value
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise SettingValidationError(f"неизвестная временная зона {value!r} (нужен идентификатор IANA, например Europe/Minsk)") from exc
    return value


_RECONNECT = reconnect_defaults()
_RETENTION = retention_defaults()
_LOGGING = logging_defaults()
#: Код-дефолты личного внешнего вида: глобального дефолта инстанса нет, действуют они.
DEFAULT_THEME = "light"
DEFAULT_STYLE = "graphite-minimal"
_PLATES = plate_defaults()


def _a(key: str, type_: str, default: Any, description: str, *, owner: str = "admin-config", **kwargs: Any) -> SettingSpec:
    return SettingSpec(key=key, cls=ConfigClass.A, type=type_, default=default, owner=owner, description=description, **kwargs)


def _u(key: str, type_: str, default: Any, description: str, **kwargs: Any) -> SettingSpec:
    return SettingSpec(key=key, cls=ConfigClass.U, type=type_, default=default, owner="self", description=description, **kwargs)


def _d(key: str, type_: str, default: Any, description: str, **kwargs: Any) -> SettingSpec:
    return SettingSpec(key=key, cls=ConfigClass.D, type=type_, default=default, owner="deploy", description=description, requires_restart=True, **kwargs)


def _l(key: str, description: str) -> SettingSpec:
    return SettingSpec(key=key, cls=ConfigClass.L, type="str", default=None, owner="device", description=description)


_SPECS: Tuple[SettingSpec, ...] = (
    # ── Класс A — app_settings ───────────────────────────────────────────
    _a("reconnect.signal_loss.enabled", "bool", _RECONNECT["signal_loss"]["enabled"], "Переподключение канала при потере сигнала"),
    _a("reconnect.signal_loss.frame_timeout_seconds", "int", _RECONNECT["signal_loss"]["frame_timeout_seconds"], "Сколько секунд без кадров считать потерей сигнала", minimum=1),
    _a("reconnect.signal_loss.retry_interval_seconds", "int", _RECONNECT["signal_loss"]["retry_interval_seconds"], "Пауза между попытками переподключения, секунд", minimum=1),
    # Решение 4.10 №4: дефолт False (в прежнем файле настроек было true).
    _a("reconnect.periodic.enabled", "bool", _RECONNECT["periodic"]["enabled"], "Периодическое переподключение каналов"),
    _a("reconnect.periodic.interval_minutes", "int", _RECONNECT["periodic"]["interval_minutes"], "Интервал периодического переподключения, минут", minimum=1),
    _a("retention.auto_cleanup_enabled", "bool", _RETENTION["auto_cleanup_enabled"], "Автоматическая очистка старых событий и медиа"),
    _a("retention.cleanup_interval_minutes", "int", _RETENTION["cleanup_interval_minutes"], "Интервал между циклами очистки, минут", minimum=1),
    _a("retention.events_retention_days", "int", _RETENTION["events_retention_days"], "Срок хранения событий, дней", minimum=1),
    _a("retention.media_retention_days", "int", _RETENTION["media_retention_days"], "Срок хранения скриншотов без события, дней", minimum=1),
    _a("retention.max_screenshots_mb", "int", _RETENTION["max_screenshots_mb"], "Предел объёма скриншотов, МБ; при превышении удаляются самые старые", minimum=256),
    _a("logging.level", "str", _LOGGING["level"], "Уровень логирования (после старта процесса значение из БД перекрывает LOG_LEVEL)", choices=LOG_LEVELS),
    _a("logging.retention_days", "int", _LOGGING["retention_days"], "Срок хранения файлов логов, дней", minimum=1),
    # Решение 4.10 №5: список из schema, а не из прежнего файла настроек.
    _a(
        "plates.enabled_countries", "str_list", _PLATES["enabled_countries"],
        "Страны, форматы номеров которых распознаются", choices=COUNTRIES, requires_restart=True,
    ),
    # Решение 4.10 №8: статический дефолт UTC вместо зоны ОС хоста.
    _a("interface.display_timezone", "str", "UTC", "Зона отображения времени инстанса (IANA); хранение остаётся в UTC", validator=_valid_zone),
    _a(
        "interface.default_locale", "str", "ru",
        "Зарезервирован: в системе нет слоя локализации (P15), поэтому настройка не имеет потребителя и не показывается в UI",
        choices=("ru",), reserved=True,
    ),
    # Решение 4.10 №3 относится к debug.show_channel_metrics (класс U ниже); здесь
    # инверсия debug.disable_video_output: вывод видео включён по умолчанию.
    _a("debug.video_output_enabled", "bool", True, "Выводить видео каналов; отключение — серверный debug-эффект", owner="admin-debug"),
    _a(
        "auth.token_ttl_minutes", "int", 480,
        "Срок жизни токена доступа, минут (действует для новых токенов; выданные не меняются). "
        "Нижняя граница — 5 минут: меньшее значение выбросило бы оператора из системы посреди работы; верхняя — 30 суток",
        minimum=5, maximum=43200,
    ),
    _a("auth.login_rate_limit_attempts", "int", 5, "Число неудачных попыток входа с одного адреса за окно; верхняя граница не даёт фактически отключить защиту", minimum=1, maximum=100),
    _a("auth.login_rate_limit_window_seconds", "int", 60, "Окно ограничения неудачных попыток входа, секунд", minimum=1, maximum=86400),
    _a(
        "detection.confidence_threshold", "float", 0.5,
        "Порог уверенности детектора номеров; совпадает с DETECTION_CONFIDENCE_THRESHOLD в anpr/model_config.py",
        minimum=0.0, maximum=1.0, requires_restart=True,
    ),
    # ── Класс U — users.preferences ──────────────────────────────────────
    _u("theme", "str", DEFAULT_THEME, "Личная тема; единственный источник — предпочтение пользователя, без дефолта инстанса", choices=THEMES),
    _u("style", "str", DEFAULT_STYLE, "Личный стиль; единственный источник — предпочтение пользователя, без дефолта инстанса", choices=STYLES),
    _u("sidebar_locked", "bool", False, "Фиксация левой панели в свёрнутом виде"),
    _u("debug_panel_enabled", "bool", False, "Показывать панель debug-логов"),
    # Решение 4.10 №3: дефолт False (debug-функция выключена, пока её не включили).
    _u("channel_metrics_visible", "bool", False, "Показывать метрики каналов"),
    _u(
        "locale", "str", "ru",
        "Зарезервирован: нет слоя локализации (P15); место выбора языка — рядом с переключателем темы, а не в настройках",
        choices=("ru",), reserved=True,
    ),
    # ── Класс D — .env ───────────────────────────────────────────────────
    _d("JWT_SECRET_KEY", "str", DEFAULT_JWT_SECRET_KEY, "Секрет подписи JWT; дефолт пригоден только для разработки, в production запуск с ним запрещён"),
    _d("POSTGRES_DSN", "str", "postgresql://anpr:anpr@postgres:5432/anpr", "DSN подключения приложения к PostgreSQL"),
    _d("POSTGRES_DB", "str", "anpr", "Имя базы данных (потребитель — контейнер postgres)"),
    _d("POSTGRES_USER", "str", "anpr", "Пользователь PostgreSQL (потребитель — контейнер postgres)"),
    _d("POSTGRES_PASSWORD", "str", "anpr", "Пароль PostgreSQL (потребитель — контейнер postgres)"),
    _d("POSTGRES_PORT", "int", 5432, "Порт PostgreSQL, публикуемый на хосте", minimum=1, maximum=65535),
    _d("HTTP_PORT", "int", 8080, "Порт nginx, публикуемый на хосте", minimum=1, maximum=65535),
    _d("CORS_ALLOWED_ORIGINS", "str", "", "Origin'ы через запятую, которым разрешён кросс-origin доступ из браузера; пусто — никому"),
    _d("OMP_NUM_THREADS", "int", 2, "Лимит потоков PyTorch/OpenMP", minimum=1),
    _d("MKL_NUM_THREADS", "int", 2, "Лимит потоков MKL (читается нативной библиотекой)", minimum=1),
    _d("OPENBLAS_NUM_THREADS", "int", 2, "Лимит потоков OpenBLAS (читается нативной библиотекой)", minimum=1),
    _d("ANPR_MEDIA_DIR", "str", DEFAULT_MEDIA_DIR, "Каталог скриншотов и экспорта — точка монтирования volume"),
    _d("ANPR_LOGS_DIR", "str", DEFAULT_LOGS_DIR, "Каталог логов — точка монтирования volume"),
    _d("ANPR_YOLO_MODEL_PATH", "str", DEFAULT_YOLO_MODEL_PATH, "Путь к весам YOLO внутри образа"),
    _d("ANPR_OCR_MODEL_PATH", "str", DEFAULT_OCR_MODEL_PATH, "Путь к весам OCR внутри образа"),
    _d("ANPR_DEVICE", "str", DEFAULT_DEVICE, "Устройство инференса"),
    _d("BOOTSTRAP_SUPERADMIN_PASSWORD", "str", None, "Пароль первичного суперадмина; используется при пустой таблице users, обязателен в production"),
    _d("LOG_LEVEL", "str", "INFO", "Bootstrap-уровень логирования до первого чтения app_settings; далее владелец logging.level", choices=LOG_LEVELS),
    _d("POSTGRES_POOL_MIN", "int", DEFAULT_POOL_MIN, "Нижняя граница пула соединений PostgreSQL", minimum=1),
    _d("POSTGRES_POOL_MAX", "int", DEFAULT_POOL_MAX, "Верхняя граница пула соединений PostgreSQL", minimum=1),
    _d("ANPR_IO_POOL_WORKERS", "int", DEFAULT_IO_POOL_WORKERS, "Размер пула исполнителей ввода-вывода канала", minimum=1),
    _d("APP_ENV", "str", "", "Режим окружения; production включает строгие проверки секретов при старте"),
    _d("TZ", "str", "UTC", "Системная зона контейнера; фиксируется в Dockerfile, чтобы логи не зависели от хоста"),
    # ── Класс L — localStorage ───────────────────────────────────────────
    _l("anpr_token", "JWT сессии"),
    _l("anpr_channel_order", "Порядок плиток видеосетки на конкретном экране — серверного владельца нет"),
    _l("anpr_grid_size", "Размер видеосетки на конкретном экране — серверного владельца нет"),
    _l("anpr_appearance_user:<user_id>", "Кэш личного внешнего вида пользователя; источник — users.preferences; удаляется при выходе"),
)

REGISTRY: Dict[str, SettingSpec] = {spec.key: spec for spec in _SPECS}
if len(REGISTRY) != len(_SPECS):
    raise RuntimeError("В реестре конфигурации есть повторяющиеся ключи")

#: Значения прежних слоёв, которые перестают быть самостоятельными настройками:
#: ключ -> куда переезжает (ключ реестра или пояснение). Нужен тесту полноты и
#: читателю инвентаризации; переноса значений (миграции) он не выполняет.
REMOVED: Dict[str, str] = {
    "models.yolo_model_path": "ANPR_YOLO_MODEL_PATH",
    "models.ocr_model_path": "ANPR_OCR_MODEL_PATH",
    "models.device": "ANPR_DEVICE",
    "storage.screenshots_dir": "ANPR_MEDIA_DIR",
    "storage.logs_dir": "ANPR_LOGS_DIR",
    "storage.postgres_dsn": "POSTGRES_DSN",
    "storage.auto_cleanup_enabled": "retention.auto_cleanup_enabled",
    "storage.cleanup_interval_minutes": "retention.cleanup_interval_minutes",
    "storage.events_retention_days": "retention.events_retention_days",
    "storage.media_retention_days": "retention.media_retention_days",
    "storage.max_screenshots_mb": "retention.max_screenshots_mb",
    "debug.show_channel_metrics": "channel_metrics_visible",
    "debug.log_panel_enabled": "debug_panel_enabled",
    "debug.disable_video_output": "debug.video_output_enabled (инвертируется)",
    "interface.style": "style (только личное предпочтение)",
    "interface.theme": "theme (только личное предпочтение)",
    "interface.default_style": "удалён: дефолта инстанса нет, действует код-дефолт",
    "interface.default_theme": "удалён: дефолта инстанса нет, действует код-дефолт",
    "interface.sidebar_locked": "sidebar_locked",
    "timezone (личная)": "удалена: остаётся только interface.display_timezone",
    "time.timezone": "interface.display_timezone (домен меняется на IANA)",
    "JWT_EXPIRATION_MINUTES": "auth.token_ttl_minutes",
    "SETTINGS_PATH": "удаляется вместе с settings.yaml (фаза 9)",
    "DEBUG": "удаляется: дублирует класс A (фаза 9)",
    "anpr_theme": "users.preferences.theme (ключ localStorage удаляется в фазе 7)",
    "anpr_style": "users.preferences.style (ключ localStorage удаляется в фазе 7)",
}


#: Дефолты и границы полей настроек канала (таблица `channels`, задача 3.1).
#: Значения берутся из `channel_defaults()`; здесь к ним добавляются типы и
#: границы, по которым pydantic-схемы строят свои поля, а тест сверяет DDL.
#: Отдельно от `REGISTRY`: эти поля живут в собственной таблице, а не в
#: `app_settings`, и `SettingsService` про них знать не должен.
_CHANNEL_DEFAULTS = channel_defaults({})


def _c(name: str, type_: str, description: str, **kwargs: Any) -> Tuple[str, SettingSpec]:
    spec = SettingSpec(
        key=f"channel.{name}", cls=ConfigClass.A, type=type_,
        default=_CHANNEL_DEFAULTS[name], owner="admin-config", description=description, **kwargs,
    )
    return name, spec


CHANNEL_SPECS: Dict[str, SettingSpec] = dict((
    _c("best_shots", "int", "Число лучших кадров для распознавания", minimum=1, maximum=20),
    _c("cooldown_seconds", "int", "Пауза после распознавания номера, секунд", minimum=0, maximum=300),
    _c("ocr_min_confidence", "float", "Минимальная уверенность OCR", minimum=0.0, maximum=1.0),
    _c("max_ocr_attempts", "int", "Максимум попыток OCR на один трек", minimum=1, maximum=200),
    _c("max_consecutive_empty_ocr", "int", "Сколько пустых результатов OCR подряд допустимо", minimum=0, maximum=200),
    _c("roi_enabled", "bool", "Ограничивать детекцию областью интереса"),
    _c("detection_mode", "str", "Режим запуска детектора", choices=DETECTION_MODES),
    _c("detector_frame_stride", "int", "Шаг кадров детектора", minimum=1, maximum=30),
    _c("adaptive_stride_enabled", "bool", "Адаптивный шаг кадров"),
    _c("preview_fps_limit", "int", "Предел FPS превью", minimum=1, maximum=30),
    _c("motion_threshold", "float", "Порог детектора движения", minimum=0.0, maximum=1.0),
    _c("motion_frame_stride", "int", "Шаг кадров детектора движения", minimum=1, maximum=30),
    _c("motion_activation_frames", "int", "Кадров движения для активации", minimum=1, maximum=120),
    # Решение 4.10 №1: 100 (schema, DDL); прежние 6 в pydantic были ошибкой.
    _c("motion_release_frames", "int", "Кадров без движения для отпускания", minimum=1, maximum=120),
    _c("size_filter_enabled", "bool", "Отбраковывать номера по размеру рамки"),
    _c("controller_relay", "int", "Номер реле контроллера", minimum=0, maximum=1),
    _c(
        "controller_direction_filter", "str", "Направление, при котором срабатывает реле",
        choices=DIRECTION_FILTERS,
    ),
    _c("list_filter_mode", "str", "Режим фильтрации по спискам", choices=LIST_FILTER_MODES),
))

#: Дефолтные размеры рамки номера в пикселях кадра (решение 4.10 №2).
#: Проверка порога 400×100 при включённом фильтре размера: рамка меряется в
#: пикселях исходного кадра, номер РФ имеет пропорции ≈4,6:1, поэтому
#: ограничивающим оказывается порог по ширине. В кадре 1920×1080 ширина
#: 400 px — это ≈21 % кадра: корректно распознаваемые номера при обычной
#: установке камеры (несколько метров до полосы) заведомо уже. Только
#: вплотную стоящий автомобиль даёт рамку шире 400 px — такие срабатывания
#: отбраковываются намеренно; для камеры с близким расположением порог
#: поднимается в настройках канала.
CHANNEL_PLATE_SIZES: Dict[str, Dict[str, int]] = plate_size_defaults()


def get_spec(key: str) -> SettingSpec:
    try:
        return REGISTRY[key]
    except KeyError:
        raise KeyError(f"Ключ {key!r} отсутствует в реестре конфигурации") from None


def specs(cls: Optional[ConfigClass] = None) -> Tuple[SettingSpec, ...]:
    return tuple(spec for spec in _SPECS if cls is None or spec.cls is cls)


def defaults(cls: ConfigClass) -> Dict[str, Any]:
    """Дефолты всех ключей класса (для класса A — то, что действует при пустой таблице)."""
    return {spec.key: spec.default for spec in specs(cls)}


__all__ = [
    "DETECTION_MODES",
    "DIRECTION_FILTERS",
    "ENUMS",
    "LIST_FILTER_MODES",
    "RELAY_MODES",
    "ROI_UNITS",
    "TIMEZONES",
    "ZONE_CHANNEL_TYPES",
    "choices_pattern",
    "schema_document",
    "CHANNEL_PLATE_SIZES",
    "CHANNEL_SPECS",
    "COUNTRIES",
    "ConfigClass",
    "OWNERS",
    "REGISTRY",
    "REMOVED",
    "STYLES",
    "SettingSpec",
    "SettingValidationError",
    "THEMES",
    "defaults",
    "get_spec",
    "specs",
]
