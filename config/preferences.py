"""Личные предпочтения пользователя, класс U (roadmap, фаза 6, модель 4.3).

Хранилище — `users.preferences` (JSONB). Здесь — чистая логика без БД:
какие ключи допустимы, как валидируется патч и как значение разрешается по
порядку `users.preferences` -> константа реестра (дефолта инстанса нет).

Ключи и их дефолты объявлены в реестре (`config/registry.py`, класс U);
зарезервированные ключи (`locale`) в предпочтения не попадают.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from config.registry import ConfigClass, SettingValidationError, get_spec, specs


def known_keys() -> tuple[str, ...]:
    """Ключи, которые пользователь может хранить (без зарезервированных)."""
    return tuple(spec.key for spec in specs(ConfigClass.U) if not spec.reserved)


def validate_patch(patch: Mapping[str, Any]) -> Dict[str, Any]:
    """Проверить частичный патч по реестру.

    Неизвестный или зарезервированный ключ — ошибка (а не молчаливое
    игнорирование: клиент должен узнать об опечатке). `None` означает «сбросить
    личное значение и снова получить код-дефолт» и проходит без проверки типа.
    """
    allowed = set(known_keys())
    checked: Dict[str, Any] = {}
    for key, value in patch.items():
        if key not in allowed:
            raise SettingValidationError(f"{key}: неизвестное или недоступное предпочтение")
        checked[key] = None if value is None else get_spec(key).validate(value)
    return checked


def clean_stored(stored: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Оставить в сохранённом документе только известные ключи с допустимыми значениями."""
    allowed = set(known_keys())
    result: Dict[str, Any] = {}
    for key, value in (stored or {}).items():
        if key not in allowed:
            continue
        try:
            result[key] = get_spec(key).validate(value)
        except SettingValidationError:
            continue
    return result


def resolve(stored: Optional[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Разрешить все предпочтения: `{ключ: {"value", "source"}}`.

    Порядок: личное значение → константа реестра. `source`: `user` либо
    `default`. Дефолта инстанса больше нет — у внешнего вида один владелец.
    """
    personal = clean_stored(stored)
    return {
        key: {"value": personal[key], "source": "user"} if key in personal else {"value": get_spec(key).default, "source": "default"}
        for key in known_keys()
    }
