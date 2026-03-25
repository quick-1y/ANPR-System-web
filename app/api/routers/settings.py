from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.api.container import AppContainer
from app.api.deps import get_container
from app.api.schemas import GlobalSettingsPayload
from app.shared.backup_restore import BackupRestoreService
from common.logging import configure_logging, get_logger
from database.errors import StorageUnavailableError

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
    import copy

    old_plates = container.settings.get_plate_settings()
    old_storage = container.settings.get_storage_settings()

    reconnect_config = payload.reconnect.model_dump()
    debug_payload = payload.debug.model_dump()
    logging_payload = payload.logging.model_dump()

    with container.settings._file_lock:
        container.settings.settings["grid"] = payload.grid
        container.settings.settings["theme"] = payload.theme
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
    pipeline_changed = old_plates != new_plates or old_storage.get("postgres_dsn") != new_storage.get("postgres_dsn")
    if pipeline_changed:
        container.restart_processor_for_settings()

    return get_global_settings(container)


def _backup_service(container: AppContainer) -> BackupRestoreService:
    storage = container.settings.get_storage_settings()
    return BackupRestoreService(container.settings, str(storage.get("postgres_dsn", "")).strip())


@router.get("/api/settings/backup/database")
def export_database_backup(container: AppContainer = Depends(get_container)) -> Response:
    service = _backup_service(container)
    try:
        filename, payload = service.export_database_backup()
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/settings/restore/database")
async def restore_database_backup(
    backup_file: UploadFile = File(...), container: AppContainer = Depends(get_container)
) -> Dict[str, Any]:
    filename = str(backup_file.filename or "")
    if filename and not filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Ожидается JSON-файл бэкапа базы данных (*.json)")

    raw_payload = await backup_file.read()
    if not raw_payload:
        raise HTTPException(status_code=400, detail="Файл бэкапа пустой")

    service = _backup_service(container)
    try:
        stats = service.restore_database_backup(raw_payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Некорректный файл бэкапа: {exc}") from exc
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    container.request_process_restart(reason="Восстановление PostgreSQL из бэкапа", delay_seconds=1.5)
    return {
        "status": "ok",
        "message": "База данных успешно восстановлена. Запущен перезапуск приложения.",
        "stats": stats,
        "restart_scheduled": True,
    }


@router.get("/api/settings/backup/settings")
def export_settings_backup(container: AppContainer = Depends(get_container)) -> Response:
    service = _backup_service(container)
    try:
        filename, payload = service.export_settings_yaml()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return Response(
        content=payload,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/settings/restore/settings")
async def restore_settings_backup(
    settings_file: UploadFile = File(...), container: AppContainer = Depends(get_container)
) -> Dict[str, Any]:
    filename = str(settings_file.filename or "")
    if filename and not filename.lower().endswith((".yaml", ".yml")):
        raise HTTPException(status_code=400, detail="Ожидается YAML-файл настроек (*.yaml, *.yml)")

    raw_payload = await settings_file.read()
    if not raw_payload:
        raise HTTPException(status_code=400, detail="Файл settings.yaml пустой")

    service = _backup_service(container)
    try:
        service.restore_settings_yaml(raw_payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Некорректный settings.yaml: {exc}") from exc

    container.refresh_storage_clients()
    container.processor.update_reconnect_settings(container.settings.get_reconnect())
    container.processor.update_debug_settings(container.settings.get_debug_settings())
    configure_logging(container.settings.get_logging_config(), service_name="api")
    container.restart_processor_for_settings()

    return {
        "status": "ok",
        "message": "settings.yaml успешно восстановлен и применён.",
    }
