from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from app.api.container import AppContainer
from app.api.deps import get_container, require_role
from app.api.schemas import GlobalSettingsPayload
from anpr.postprocessing.country_config import CountryConfigLoader
from common.logging import configure_logging, get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/api/countries")
def get_available_countries(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_role("admin"))) -> List[Dict[str, str]]:
    plates = container.settings.get_plate_settings()
    config_dir = str(plates.get("config_dir") or "anpr/countries")
    loader = CountryConfigLoader(os.path.abspath(config_dir))
    return loader.available_configs()


@router.get("/api/settings")
def get_global_settings(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_role("admin"))) -> Dict[str, Any]:
    return {
        "grid": container.settings.get_grid(),
        "theme": container.settings.get_theme(),
        "sidebar_locked": container.settings.settings.get("sidebar_locked", False),
        "reconnect": container.settings.get_reconnect(),
        "storage": container.settings.get_storage_settings(),
        "logging": container.settings.get_logging_config(),
        "time": container.settings.get_time_settings(),
        "plates": container.settings.get_plate_settings(),
        "debug": container.settings.get_debug_settings(),
    }


@router.put("/api/settings")
def put_global_settings(payload: GlobalSettingsPayload, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_role("admin"))) -> Dict[str, Any]:
    import copy

    old_plates = container.settings.get_plate_settings()
    old_storage = container.settings.get_storage_settings()

    reconnect_config = payload.reconnect.model_dump()
    debug_payload = payload.debug.model_dump()
    logging_payload = payload.logging.model_dump()

    with container.settings._file_lock:
        container.settings.settings["grid"] = payload.grid
        container.settings.settings["theme"] = payload.theme
        container.settings.settings["sidebar_locked"] = payload.sidebar_locked
        container.settings.settings["reconnect"] = reconnect_config

        current_storage = container.settings.settings.get("storage", {})
        sanitized_storage = copy.deepcopy(payload.storage.model_dump())
        sanitized_storage.pop("postgres_dsn", None)
        current_storage.update(sanitized_storage)
        container.settings.settings["storage"] = current_storage

        container.settings.settings["time"] = payload.time.model_dump()
        current_plates = container.settings.settings.get("plates", {})
        current_plates.update(payload.plates.model_dump())
        container.settings.settings["plates"] = current_plates
        container.settings.settings["debug"] = debug_payload

        current_logging = container.settings.settings.get("logging", {})
        current_logging.update(logging_payload)
        from config.settings_schema import normalize_log_level
        current_logging["level"] = normalize_log_level(current_logging.get("level"))
        container.settings.settings["logging"] = current_logging

        settings_snapshot = copy.deepcopy(container.settings.settings)

    container.settings._repo.save(settings_snapshot)

    try:
        container.processor.update_reconnect_settings(reconnect_config)
    except Exception:
        logger.exception("Не удалось обновить reconnect-настройки активного processor")
    container.processor.update_debug_settings(debug_payload)
    configure_logging(container.settings.get_logging_config(), service_name="api")

    container.refresh_storage_clients()

    new_plates = container.settings.get_plate_settings()
    new_storage = payload.storage.model_dump()
    pipeline_changed = (
        old_plates != new_plates
        or old_storage.get("postgres_dsn") != new_storage.get("postgres_dsn")
    )
    if pipeline_changed:
        container.restart_processor_for_settings()

    return get_global_settings(container)
