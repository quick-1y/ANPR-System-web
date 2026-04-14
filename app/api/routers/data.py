from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import JSONResponse, Response

from database.errors import StorageUnavailableError
from app.api.container import AppContainer
from app.api.deps import get_container, require_role
from app.api.schemas import ExportBundlePayload, RetentionPolicyPayload
from app.shared.data_lifecycle import RetentionPolicy
from app.shared.backup_service import (
    export_database_backup,
    export_settings,
    get_restore_lock,
    restore_database_backup,
    restore_settings,
    validate_database_backup,
    validate_settings_yaml,
)
from common.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/api/data/policy")
def get_data_policy(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_role("superadmin"))) -> Dict[str, Any]:
    return container.lifecycle.policy.to_storage()


@router.put("/api/data/policy")
def update_data_policy(payload: RetentionPolicyPayload, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_role("superadmin"))) -> Dict[str, Any]:
    policy = RetentionPolicy(**payload.model_dump())
    container.lifecycle.update_policy(policy)
    container.settings.save_storage_settings(policy.to_storage())
    return {"status": "updated", "policy": policy.to_storage()}


@router.post("/api/data/retention/run")
def run_retention(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_role("superadmin"))) -> Dict[str, Any]:
    try:
        result = container.lifecycle.run_retention_cycle()
        return {"status": "ok", **result}
    except StorageUnavailableError as exc:
        return {"status": "error", "detail": str(exc)}


@router.get("/api/data/export/events.csv")
def export_events_csv(
    start: Optional[str] = None,
    end: Optional[str] = None,
    channel: Optional[str] = None,
    plate: Optional[str] = None,
    channel_id: Optional[int] = None,
    container: AppContainer = Depends(get_container),
    _user: Dict[str, Any] = Depends(require_role("superadmin")),
) -> Response:
    try:
        filename, payload = container.lifecycle.export_events_csv(start=start, end=end, channel=channel, plate=plate, channel_id=channel_id)
        return Response(
            content=payload,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.post("/api/data/export/bundle")
def export_events_bundle(payload: ExportBundlePayload, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_role("superadmin"))) -> Response:
    try:
        filename, body = container.lifecycle.export_events_bundle(
            start=payload.start,
            end=payload.end,
            channel=payload.channel,
            include_media=payload.include_media,
        )
        return Response(
            content=body,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


# ── Database backup / restore ────────────────────────────

@router.get("/api/data/backup/database")
def backup_database(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_role("superadmin"))) -> Response:
    dsn = str(container.settings.get_storage_settings().get("postgres_dsn", "")).strip()
    if not dsn:
        return JSONResponse(status_code=500, content={"status": "error", "detail": "PostgreSQL DSN не настроен"})
    try:
        filename, body = export_database_backup(dsn)
        return Response(
            content=body,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc
    except Exception as exc:
        logger.exception("Ошибка создания бэкапа БД")
        return JSONResponse(status_code=500, content={"status": "error", "detail": f"Ошибка создания бэкапа: {exc}"})


@router.post("/api/data/backup/database/restore")
async def restore_database(
    file: UploadFile = File(...),
    container: AppContainer = Depends(get_container),
    _user: Dict[str, Any] = Depends(require_role("superadmin")),
) -> JSONResponse:
    lock = get_restore_lock()
    if not lock.acquire("database_restore"):
        return JSONResponse(
            status_code=409,
            content={"status": "error", "detail": "Операция восстановления уже выполняется"},
        )
    try:
        data = await file.read()

        try:
            validate_database_backup(data)
        except ValueError as exc:
            return JSONResponse(status_code=422, content={"status": "error", "detail": str(exc)})

        dsn = str(container.settings.get_storage_settings().get("postgres_dsn", "")).strip()
        if not dsn:
            return JSONResponse(status_code=500, content={"status": "error", "detail": "PostgreSQL DSN не настроен"})

        # Stop processor before restoring
        try:
            container.shutdown()
        except Exception:
            logger.warning("Не удалось корректно остановить процессор перед восстановлением БД")

        try:
            result = restore_database_backup(dsn, data)
        except ValueError as exc:
            return JSONResponse(status_code=422, content={"status": "error", "detail": str(exc)})
        except Exception as exc:
            logger.exception("Ошибка восстановления БД")
            return JSONResponse(status_code=500, content={"status": "error", "detail": f"Ошибка восстановления: {exc}"})

        # Reinitialize all DB clients and restart processor
        try:
            container.refresh_storage_clients()
            container.processor = container._create_processor()
            for channel in container.channel_db.list_channels():
                container.processor.ensure_channel(channel)
                if channel.get("enabled", True):
                    container.processor.start(int(channel["id"]))
        except Exception:
            logger.exception("Ошибка перезапуска после восстановления БД")

        # Schedule process exit for a true restart (Docker will restart the container)
        def _delayed_exit():
            time.sleep(2)
            logger.info("Перезапуск приложения после восстановления БД")
            os._exit(0)

        exit_thread = threading.Thread(target=_delayed_exit, daemon=True)
        exit_thread.start()

        return JSONResponse(content={
            "status": "ok",
            "detail": "База данных успешно восстановлена. Приложение перезапускается...",
            **result,
        })
    finally:
        lock.release()


# ── Settings backup / restore ────────────────────────────

@router.get("/api/data/backup/settings")
def backup_settings(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_role("superadmin"))) -> Response:
    try:
        settings_path = container.settings._repo.path
        filename, body = export_settings(settings_path)
        return Response(
            content=body,
            media_type="application/x-yaml",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except FileNotFoundError as exc:
        return JSONResponse(status_code=404, content={"status": "error", "detail": str(exc)})
    except Exception as exc:
        logger.exception("Ошибка экспорта настроек")
        return JSONResponse(status_code=500, content={"status": "error", "detail": f"Ошибка экспорта: {exc}"})


@router.post("/api/data/backup/settings/restore")
async def restore_settings_endpoint(
    file: UploadFile = File(...),
    container: AppContainer = Depends(get_container),
    _user: Dict[str, Any] = Depends(require_role("superadmin")),
) -> JSONResponse:
    lock = get_restore_lock()
    if not lock.acquire("settings_restore"):
        return JSONResponse(
            status_code=409,
            content={"status": "error", "detail": "Операция восстановления уже выполняется"},
        )
    try:
        data = await file.read()

        try:
            validate_settings_yaml(data)
        except ValueError as exc:
            return JSONResponse(status_code=422, content={"status": "error", "detail": str(exc)})

        try:
            from config.settings_normalizer import SettingsNormalizer
            normalized = restore_settings(container.settings._repo, SettingsNormalizer, data)
        except ValueError as exc:
            return JSONResponse(status_code=422, content={"status": "error", "detail": str(exc)})
        except Exception as exc:
            logger.exception("Ошибка восстановления настроек")
            return JSONResponse(status_code=500, content={"status": "error", "detail": f"Ошибка восстановления: {exc}"})

        # Reload settings in-memory
        try:
            container.settings.refresh()
        except Exception:
            logger.exception("Ошибка перезагрузки настроек в памяти")

        # Refresh storage clients and restart processor
        try:
            container.refresh_storage_clients()
            container.restart_processor_for_settings()
        except Exception:
            logger.exception("Ошибка перезапуска после восстановления настроек")

        return JSONResponse(content={
            "status": "ok",
            "detail": "Настройки успешно восстановлены и применены",
        })
    finally:
        lock.release()
