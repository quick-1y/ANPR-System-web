from __future__ import annotations

import signal
import threading
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import JSONResponse, Response

from database.errors import StorageUnavailableError
from app.api.container import AppContainer
from app.api.deps import get_container, require_permission
from app.api.schemas import ExportBundlePayload
from app.api.superadmin import audit_user_id
from app.shared.data_lifecycle import RetentionPolicy
from app.shared.backup_service import (
    export_database_backup,
    export_settings,
    get_restore_lock,
    restore_database_backup,
    restore_settings,
    validate_database_backup,
    validate_settings_dump,
)
from common.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()

# ── Upload size limits ───────────────────────────────────
# Database backups only contain table rows as JSON (no media), settings
# backups are a single small YAML file — caps are generous but bounded so
# an authenticated upload can't exhaust server memory.
_UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MiB
MAX_DATABASE_BACKUP_SIZE = 200 * 1024 * 1024  # 200 MiB
MAX_SETTINGS_BACKUP_SIZE = 5 * 1024 * 1024  # 5 MiB


class _PayloadTooLargeError(Exception):
    """Raised when an uploaded file exceeds its configured size cap."""


async def _read_upload_capped(file: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise _PayloadTooLargeError(
                f"Файл превышает допустимый размер {max_bytes // (1024 * 1024)} МБ"
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.get("/api/data/policy")
def get_data_policy(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_permission("tab:settings"))) -> Dict[str, Any]:
    """Read-only: the policy is changed only through `PUT /api/settings` (retention.*)."""
    return RetentionPolicy.from_settings(container.settings_service).to_storage()


@router.post("/api/data/retention/run")
def run_retention(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_permission("tab:settings"))) -> Dict[str, Any]:
    try:
        container.lifecycle.update_policy(RetentionPolicy.from_settings(container.settings_service))
        result = container.lifecycle.run_retention_cycle()
        return {"status": "ok", **result}
    except StorageUnavailableError as exc:
        return {"status": "error", "detail": str(exc)}


@router.get("/api/data/export/events.csv")
def export_events_csv(
    start: Optional[str] = None,
    end: Optional[str] = None,
    plate: Optional[str] = None,
    channel_id: Optional[int] = None,
    container: AppContainer = Depends(get_container),
    _user: Dict[str, Any] = Depends(require_permission("tab:settings")),
) -> Response:
    try:
        filename, payload = container.lifecycle.export_events_csv(start=start, end=end, plate=plate, channel_id=channel_id, display_timezone=container.get_display_timezone())
        return Response(
            content=payload,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.post("/api/data/export/bundle")
def export_events_bundle(payload: ExportBundlePayload, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_permission("tab:settings"))) -> Response:
    try:
        filename, body = container.lifecycle.export_events_bundle(
            start=payload.start,
            end=payload.end,
            channel_id=payload.channel_id,
            include_media=payload.include_media,
            display_timezone=container.get_display_timezone(),
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
def backup_database(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_permission("tab:settings"))) -> Response:
    dsn = container._resolve_dsn()
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
    _user: Dict[str, Any] = Depends(require_permission("tab:settings")),
) -> JSONResponse:
    lock = get_restore_lock()
    if not lock.acquire("database_restore"):
        return JSONResponse(
            status_code=409,
            content={"status": "error", "detail": "Операция восстановления уже выполняется"},
        )
    try:
        try:
            data = await _read_upload_capped(file, MAX_DATABASE_BACKUP_SIZE)
        except _PayloadTooLargeError as exc:
            return JSONResponse(status_code=413, content={"status": "error", "detail": str(exc)})

        try:
            validate_database_backup(data)
        except ValueError as exc:
            return JSONResponse(status_code=422, content={"status": "error", "detail": str(exc)})

        dsn = container._resolve_dsn()
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

        # Schedule a graceful restart (Docker will restart the container).
        # SIGTERM lets uvicorn stop accepting connections, finish in-flight
        # requests, and run the FastAPI lifespan shutdown before exiting —
        # unlike os._exit(0), which killed the process mid-request.
        def _delayed_exit():
            time.sleep(2)
            logger.info("Перезапуск приложения после восстановления БД")
            signal.raise_signal(signal.SIGTERM)

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
def backup_settings(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_permission("tab:settings"))) -> Response:
    """JSON dump of the explicit `app_settings` overrides (no file system involved)."""
    try:
        filename, body = export_settings(container.settings_service)
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/data/backup/settings/restore")
async def restore_settings_endpoint(
    file: UploadFile = File(...),
    container: AppContainer = Depends(get_container),
    _user: Dict[str, Any] = Depends(require_permission("tab:settings")),
) -> JSONResponse:
    lock = get_restore_lock()
    if not lock.acquire("settings_restore"):
        return JSONResponse(
            status_code=409,
            content={"status": "error", "detail": "Операция восстановления уже выполняется"},
        )
    try:
        try:
            data = await _read_upload_capped(file, MAX_SETTINGS_BACKUP_SIZE)
        except _PayloadTooLargeError as exc:
            return JSONResponse(status_code=413, content={"status": "error", "detail": str(exc)})

        try:
            validate_settings_dump(data)
        except ValueError as exc:
            return JSONResponse(status_code=422, content={"status": "error", "detail": str(exc)})

        try:
            result = restore_settings(container.settings_service, data, updated_by=audit_user_id(_user))
        except ValueError as exc:
            return JSONResponse(status_code=422, content={"status": "error", "detail": str(exc)})
        except StorageUnavailableError as exc:
            return JSONResponse(status_code=503, content={"status": "error", "detail": f"PostgreSQL недоступен: {exc}"})
        except Exception as exc:
            logger.exception("Ошибка восстановления настроек")
            return JSONResponse(status_code=500, content={"status": "error", "detail": f"Ошибка восстановления: {exc}"})

        # Apply what can change at runtime, then restart the processor only if a
        # restart-requiring key actually changed.
        try:
            container.processor.update_reconnect_settings(container.get_reconnect_settings())
            container.processor.update_debug_settings({"video_output_enabled": container.settings_service.get("debug.video_output_enabled")})
            container.logging_applier.apply()
            container.refresh_storage_clients()
            if result["requires_restart"]:
                container.restart_processor_for_settings()
        except Exception:
            logger.exception("Ошибка применения настроек после восстановления")

        return JSONResponse(content={
            "status": "ok",
            "detail": "Настройки успешно восстановлены и применены",
            **result,
        })
    finally:
        lock.release()
