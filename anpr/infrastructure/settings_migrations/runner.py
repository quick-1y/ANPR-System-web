"""Единый upgrade flow совместимости settings до актуальной схемы."""

from __future__ import annotations

import copy
from typing import Any, Dict, Tuple

from anpr.infrastructure.settings_schema import (
    SETTINGS_LINEAGE,
    SETTINGS_LINEAGE_KEY,
    SETTINGS_VERSION,
    direction_defaults,
    normalize_region_config,
)


def _apply_legacy_compat(data: Dict[str, Any]) -> Dict[str, Any]:
    """Подтягивает legacy-конфиг (исторические форматы ROI/direction) к текущему виду полей."""

    upgraded = dict(data)
    tracking = dict(upgraded.get("tracking") or {})
    current_direction = dict(tracking.get("direction") or {})
    for key, value in direction_defaults().items():
        current_direction.setdefault(key, value)
    tracking["direction"] = current_direction
    upgraded["tracking"] = tracking

    channels = list(upgraded.get("channels") or [])
    for channel in channels:
        if not isinstance(channel, dict):
            continue
        channel["region"] = normalize_region_config(channel.get("region"))
    upgraded["channels"] = channels
    return upgraded


def _parse_version(data: Dict[str, Any]) -> int:
    value = data.get("settings_version")
    if isinstance(value, int) and value > 0:
        return value
    return 0


def _validate_current_lineage_version(data: Dict[str, Any], target_version: int) -> None:
    current_version = _parse_version(data)
    if current_version > target_version:
        raise ValueError(
            "Неподдерживаемая будущая версия схемы настроек для текущей линии "
            f"'{SETTINGS_LINEAGE}': {current_version}. "
            f"Максимально поддерживаемая версия: {target_version}."
        )


def run_settings_migrations(data: Dict[str, Any], target_version: int = SETTINGS_VERSION) -> Tuple[Dict[str, Any], bool]:
    """Совместимость старых settings + фиксация текущей канонической версии схемы."""

    migrated = copy.deepcopy(data)
    changed = False
    lineage = migrated.get(SETTINGS_LINEAGE_KEY)

    # Legacy path: marker линии отсутствует.
    if lineage is None:
        upgraded = _apply_legacy_compat(migrated)
        if upgraded != migrated:
            migrated = upgraded
            changed = True
        migrated[SETTINGS_LINEAGE_KEY] = SETTINGS_LINEAGE
        changed = True
    elif lineage == SETTINGS_LINEAGE:
        _validate_current_lineage_version(migrated, target_version)
    else:
        raise ValueError(
            "Неподдерживаемая линия схемы настроек: "
            f"'{lineage}'. Поддерживаемая линия: '{SETTINGS_LINEAGE}'."
        )

    if migrated.get("settings_version") != target_version:
        migrated["settings_version"] = target_version
        changed = True

    return migrated, changed
