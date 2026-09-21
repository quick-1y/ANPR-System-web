"""Личные предпочтения пользователя, класс U (roadmap, фаза 6, модель 4.3).

Хранилище — `users.preferences` (JSONB). Здесь — чистая логика без БД:
какие ключи допустимы, как валидируется патч и как значение разрешается по
порядку `users.preferences` -> `app_settings` -> константа.

Ключи и их дефолты объявлены в реестре (`config/registry.py`, класс U);
зарезервированные ключи (`locale`) в предпочтения не попадают.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from config.registry import ConfigClass, SettingValidationError, get_spec, specs

#: Ключ предпочтения -> ключ `app_settings`, чьё значение — дефолт инстанса.
INSTANCE_DEFAULT_KEYS: Dict[str, str] = {
    "theme": "interface.default_theme",
    "style": "interface.default_style",
}

#: Значение `timezone`, означающее «использовать зону инстанса».
TIMEZONE_AUTO = "auto"


def known_keys() -> tuple[str, ...]:
    """Ключи, которые пользователь может хранить (без зарезервированных)."""
    return tuple(spec.key for spec in specs(ConfigClass.U) if not spec.reserved)


def validate_patch(patch: Mapping[str, Any]) -> Dict[str, Any]:
    """Проверить частичный патч по реестру.

    Неизвестный или зарезервированный ключ — ошибка (а не молчаливое
    игнорирование: клиент должен узнать об опечатке). `None` означает «сбросить
    личное значение и снова наследовать дефолт» и проходит без проверки типа.
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


def resolve(stored: Optional[Mapping[str, Any]], settings: Any) -> Dict[str, Dict[str, Any]]:
    """Разрешить все предпочтения: `{ключ: {"value", "source"}}`.

    `source`: `user` — личное значение; `instance` — администратор явно задал
    дефолт инстанса в `app_settings`; `default` — действует константа реестра.
    """
    personal = clean_stored(stored)
    resolved: Dict[str, Dict[str, Any]] = {}
    for key in known_keys():
        if key in personal:
            resolved[key] = {"value": personal[key], "source": "user"}
            continue
        instance_key = INSTANCE_DEFAULT_KEYS.get(key)
        if instance_key is not None:
            source = "instance" if settings.is_configured(instance_key) else "default"
            resolved[key] = {"value": settings.get(instance_key), "source": source}
        else:
            resolved[key] = {"value": get_spec(key).default, "source": "default"}
    return resolved


def effective_timezone(stored: Optional[Mapping[str, Any]], settings: Any) -> str:
    """Зона отображения для пользователя: личная, если не `auto`, иначе зона инстанса."""
    personal = clean_stored(stored).get("timezone", TIMEZONE_AUTO)
    if personal and personal != TIMEZONE_AUTO:
        return personal
    return str(settings.get("interface.display_timezone"))
