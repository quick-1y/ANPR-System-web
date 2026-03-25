from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from database.errors import StorageUnavailableError
from app.api.container import AppContainer
from app.api.deps import get_container
from app.api.schemas import ExportBundlePayload, RetentionPolicyPayload
from app.shared.data_lifecycle import RetentionPolicy

router = APIRouter()


@router.get("/api/data/policy")
def get_data_policy(container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    return container.lifecycle.policy.to_storage()


@router.put("/api/data/policy")
def update_data_policy(payload: RetentionPolicyPayload, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    policy = RetentionPolicy(**payload.model_dump())
    container.lifecycle.update_policy(policy)
    container.settings.save_storage_settings(policy.to_storage())
    return {"status": "updated", "policy": policy.to_storage()}


@router.post("/api/data/retention/run")
def run_retention(container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
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
def export_events_bundle(payload: ExportBundlePayload, container: AppContainer = Depends(get_container)) -> Response:
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
