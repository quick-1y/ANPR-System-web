from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from app.api.container import AppContainer
from app.api.deps import get_container
from app.api.schemas import GlobalSettingsPayload
from common.logging import configure_logging, get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/api/settings")
def get_global_settings(container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    return {
        "grid": container.settings.get_grid(),
        "theme": container.settings.get_theme(),
        "reconnect": container.settings.get_reconnect(),
        "storage": container.settings.get_storage_settings(),
        "logging": container.settings.get_logging_config(),
        "time": container.settings.get_time_settings(),
        "plates": container.settings.get_plate_settings(),
        "debug": container.settings.get_debug_settings(),
    }


@router.put("/api/settings")
def put_global_settings(payload: GlobalSettingsPayload, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    # Detect what changed before saving
    current_dsn = str(container.settings.get_storage_settings().get("postgres_dsn", "") or "").strip()
    new_dsn = str(payload.storage.postgres_dsn or "").strip()
    dsn_changed = current_dsn != new_dsn

    plates_changed = container.settings.get_plate_settings() != payload.plates.model_dump()

    # Save all settings
    container.settings.save_grid(payload.grid)
    container.settings.save_theme(payload.theme)
    reconnect_config = payload.reconnect.model_dump()
    container.settings.save_reconnect(reconnect_config)
    try:
        container.processor.update_reconnect_settings(reconnect_config)
    except Exception:
        logger.exception("Не удалось обновить reconnect-настройки активного processor")
    container.settings.save_storage_settings(payload.storage.model_dump())
    container.settings.save_time_settings(payload.time.model_dump())
    container.settings.save_plate_settings(payload.plates.model_dump())
    debug_payload = payload.debug.model_dump()
    container.settings.save_debug_settings(debug_payload)
    container.processor.update_debug_settings(debug_payload)
    container.settings.save_logging_config(payload.logging.model_dump())
    configure_logging(container.settings.get_logging_config(), service_name="api")

    # Apply only the subsystem updates that are actually needed
    if dsn_changed:
        container.refresh_storage_clients()

    if plates_changed:
        container.restart_processor_for_settings()

    return get_global_settings(container)
