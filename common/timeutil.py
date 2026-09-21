"""Отображаемое время (roadmap, задача 4.5, модель 4.9).

Хранение и внутренняя работа — всегда aware-UTC. Зона отображения
(`interface.display_timezone`, IANA) применяется только на границе: при
форматировании экспорта и в ответе `/api/system/time`.

Модуль зависит только от stdlib (`zoneinfo` требует пакет `tzdata` на
машинах без системной базы зон — он объявлен в `pyproject.toml`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_DISPLAY_TIMEZONE = "UTC"


def utc_now() -> datetime:
    """Текущий момент как aware-UTC — единственный разрешённый источник «сейчас»."""
    return datetime.now(timezone.utc)


def parse_moment(value: Any) -> datetime | None:
    """`datetime` или ISO-8601 строка -> aware datetime; наивное значение считается UTC."""
    if value is None or value == "":
        return None
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def format_in_zone(value: Any, zone_name: str) -> str:
    """Момент времени в зоне отображения: ISO-8601 со смещением, секунды."""
    moment = parse_moment(value)
    if moment is None:
        return ""
    return moment.astimezone(ZoneInfo(zone_name)).isoformat(timespec="seconds")


def zone_slug(zone_name: str) -> str:
    """Имя зоны, пригодное для имени файла: `Europe/Minsk` -> `Europe-Minsk`."""
    return zone_name.replace("/", "-")
