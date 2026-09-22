from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from app.api.container import AppContainer
from app.api.deps import get_container, require_access, require_permission
from app.api.schemas import GlobalSettingsPayload
from app.api.superadmin import audit_user_id
from anpr.postprocessing.country_config import CountryConfigLoader
from common.logging import get_logger
from config.registry import SettingValidationError, schema_document
from database.errors import StorageUnavailableError

logger = get_logger(__name__)
router = APIRouter()


@router.get("/api/countries")
def get_available_countries(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_permission("tab:settings"))) -> List[Dict[str, str]]:
    config_dir = "anpr/countries"
    loader = CountryConfigLoader(os.path.abspath(config_dir))
    return loader.available_configs()


def _flatten(prefix: str, nested: Dict[str, Any]) -> Dict[str, Any]:
    """`{"signal_loss": {"enabled": True}}` -> `{"reconnect.signal_loss.enabled": True}`."""
    flat: Dict[str, Any] = {}
    for key, value in nested.items():
        path = f"{prefix}.{key}"
        if isinstance(value, dict):
            flat.update(_flatten(path, value))
        else:
            flat[path] = value
    return flat


def _interface_view(container: AppContainer) -> Dict[str, Any]:
    """Instance display zone from `app_settings` (appearance is personal, not here)."""
    service = container.settings_service
    return {
        "display_timezone": container.get_display_timezone(),
        "timezone_configured": service.is_configured("interface.display_timezone"),
    }


def _storage_view(container: AppContainer) -> Dict[str, Any]:
    """`storage` section of the response: the retention policy from `app_settings`.
    Directories and the connection string are deployment settings (env) and are
    never exposed here."""
    return container.settings_service.get_section("retention")


@router.get("/api/settings/schema")
def get_settings_schema(_user: Dict[str, Any] = Depends(require_access("authenticated"))) -> Dict[str, Any]:
    """Допустимые значения перечислений и список зон отображения (registry)."""
    return schema_document()


@router.get("/api/settings")
def get_global_settings(container: AppContainer = Depends(get_container), current_user: Dict[str, Any] = Depends(require_permission("tab:settings"))) -> Dict[str, Any]:
    body = {
        "reconnect": container.get_reconnect_settings(),
        "storage": _storage_view(container),
        "logging": container.settings_service.get_section("logging"),
        "interface": _interface_view(container),
        "plates": container.get_plate_settings(),
        "detection": {"confidence_threshold": container.settings_service.get("detection.confidence_threshold")},
        "auth": container.settings_service.get_section("auth"),
    }
    if current_user.get("role") == "superadmin":
        body["debug"] = {"video_output_enabled": container.settings_service.get("debug.video_output_enabled")}
    return body


@router.put("/api/settings")
def put_global_settings(payload: GlobalSettingsPayload, container: AppContainer = Depends(get_container), current_user: Dict[str, Any] = Depends(require_permission("tab:settings"))) -> Dict[str, Any]:
    reconnect_config = payload.reconnect.model_dump()
    retention_config = payload.storage.model_dump()
    settings_mapping = {
        **_flatten("reconnect", reconnect_config),
        **_flatten("retention", retention_config),
        **_flatten("logging", payload.logging.model_dump()),
        "plates.enabled_countries": payload.plates.enabled_countries,
    }
    settings_mapping.update(_flatten("auth", payload.auth.model_dump(exclude_none=True)))
    if payload.detection is not None:
        settings_mapping["detection.confidence_threshold"] = payload.detection.confidence_threshold
    is_superadmin = current_user.get("role") == "superadmin"
    if is_superadmin and payload.debug is not None:
        settings_mapping["debug.video_output_enabled"] = payload.debug.video_output_enabled
    if payload.interface.display_timezone is not None:
        settings_mapping["interface.display_timezone"] = payload.interface.display_timezone
    try:
        requires_restart = container.settings_service.update(settings_mapping, updated_by=audit_user_id(current_user))
    except SettingValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc
    try:
        container.processor.update_reconnect_settings(container.get_reconnect_settings())
    except Exception:
        logger.exception("Не удалось обновить reconnect-настройки активного processor")
    if is_superadmin:
        container.processor.update_debug_settings({"video_output_enabled": container.settings_service.get("debug.video_output_enabled")})
    container.logging_applier.apply()

    container.refresh_storage_clients()

    # A key flagged `requires_restart` that actually changed (plates.enabled_countries)
    # gets exactly one processor restart; other keys never trigger one.
    if requires_restart:
        container.restart_processor_for_settings()

    body = get_global_settings(container=container, current_user=current_user)
    body["requires_restart"] = requires_restart
    return body

