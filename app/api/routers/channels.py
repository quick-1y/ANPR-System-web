from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request

from database.errors import StorageUnavailableError
from fastapi.responses import Response, StreamingResponse

from app.api.container import AppContainer
from app.api.deps import get_container, get_current_user
from app.api.schemas import ChannelConfigPayload, ChannelFilterPayload, ChannelOCRPayload, ChannelPayload

router = APIRouter()


@router.get("/api/channels")
def list_channels(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> List[Dict[str, Any]]:
    channels = container.channel_db.list_channels()
    metrics = container.processor.list_states()
    debug_states = container.processor.list_debug_states()
    for channel in channels:
        channel_id = int(channel["id"])
        channel_metrics = metrics.get(channel_id)
        if channel_metrics:
            channel["metrics"] = channel_metrics.__dict__
        channel["debug_state"] = debug_states.get(channel_id, {})
    return channels


@router.get("/api/channels/last-plates")
def channels_last_plates(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[int, Dict[str, Any]]:
    channel_ids = [int(item["id"]) for item in container.channel_db.list_channels()]
    try:
        return container.events_db.fetch_last_plates_by_channel_ids(channel_ids)
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.get("/api/channels/{channel_id}/snapshot.jpg")
def channel_snapshot(channel_id: int, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Response:
    if not container.channel_db.get_channel(channel_id):
        raise HTTPException(status_code=404, detail="Канал не найден")

    container.processor.add_preview_consumer(channel_id)
    try:
        frame, _ = container.processor.get_preview_frame(channel_id)
        if not frame:
            metrics = container.processor.list_states().get(channel_id)
            detail = "Preview кадр ещё не готов"
            if metrics and metrics.last_error:
                detail = f"Preview недоступен: {metrics.last_error}"
            raise HTTPException(status_code=503, detail=detail)
        return Response(content=frame, media_type="image/jpeg")
    finally:
        container.processor.remove_preview_consumer(channel_id)


@router.get("/api/channels/{channel_id}/preview/status")
def channel_preview_status(channel_id: int, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if not container.channel_db.get_channel(channel_id):
        raise HTTPException(status_code=404, detail="Канал не найден")

    metrics = container.processor.list_states().get(channel_id)
    frame, frame_ts = container.processor.get_preview_frame(channel_id)
    return {
        "channel_id": channel_id,
        "state": metrics.state if metrics else "unknown",
        "preview_ready": bool(frame),
        "last_frame_unix": frame_ts,
        "last_frame_at": metrics.preview_last_frame_at if metrics else None,
        "last_error": metrics.last_error if metrics else None,
    }


@router.get("/api/channels/{channel_id}/preview.mjpg")
async def channel_preview_stream(channel_id: int, request: Request, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> StreamingResponse:
    if not container.channel_db.get_channel(channel_id):
        raise HTTPException(status_code=404, detail="Канал не найден")

    if container.debug_registry.get_settings().disable_video_output:
        raise HTTPException(status_code=503, detail="Видеовыход отключён")

    async def frame_generator():
        container.processor.add_preview_consumer(channel_id)
        try:
            last_ts = 0.0
            while not container.stream_shutdown.is_set():
                if await request.is_disconnected():
                    break
                if container.debug_registry.get_settings().disable_video_output:
                    break
                frame, frame_ts = container.processor.get_preview_frame(channel_id)
                if frame and frame_ts > last_ts:
                    last_ts = frame_ts
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        + f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii")
                        + frame
                        + b"\r\n"
                    )
                else:
                    await asyncio.sleep(0.08)
        finally:
            container.processor.remove_preview_consumer(channel_id)

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@router.get("/api/channels/{channel_id}/health")
def channel_health(channel_id: int, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    channel = container.channel_db.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Канал не найден")
    metrics = container.processor.list_states().get(channel_id)
    return {
        "channel": channel,
        "metrics": metrics.__dict__ if metrics else {"state": "unknown"},
    }


@router.post("/api/channels")
def create_channel(payload: ChannelPayload, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    channel_data = {
        "name": payload.name,
        "source": payload.source,
        "enabled": payload.enabled,
        "roi_enabled": payload.roi_enabled,
        "region": payload.region or {"unit": "percent", "points": []},
    }
    saved_channel = container.channel_db.create_channel(channel_data)
    container.processor.ensure_channel(saved_channel)
    container.processor.stop(int(saved_channel["id"]))
    return saved_channel


@router.put("/api/channels/{channel_id}")
def update_channel(channel_id: int, payload: Dict[str, Any], container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    updated = container.channel_db.update_channel(channel_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="Канал не найден")
    container.processor.ensure_channel(updated)
    enabled = bool(updated.get("enabled", True))
    threading.Thread(
        target=container.sync_channel_runtime,
        args=(channel_id, enabled),
        daemon=True,
        name=f"channel-sync-{channel_id}",
    ).start()
    return updated


@router.get("/api/channels/{channel_id}/config")
def get_channel_config(channel_id: int, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    channel = container.channel_db.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Канал не найден")
    return channel


@router.put("/api/channels/{channel_id}/config")
def put_channel_config(channel_id: int, payload: ChannelConfigPayload, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    data = payload.model_dump()
    data["min_plate_size"] = payload.min_plate_size.model_dump()
    data["max_plate_size"] = payload.max_plate_size.model_dump()
    data["region"] = payload.region.model_dump()
    data.pop("plate_size_overlay", None)
    if data.get("enabled") is None:
        data.pop("enabled", None)
    container.validate_channel_controller_binding(data)
    return update_channel(channel_id, data, container)


@router.put("/api/channels/{channel_id}/ocr")
def update_channel_ocr(channel_id: int, payload: ChannelOCRPayload, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return update_channel(channel_id, payload.model_dump(), container)


@router.put("/api/channels/{channel_id}/filter")
def update_channel_filter(channel_id: int, payload: ChannelFilterPayload, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return update_channel(channel_id, payload.model_dump(), container)


@router.delete("/api/channels/{channel_id}")
def delete_channel(channel_id: int, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, str]:
    if not container.channel_db.delete_channel(channel_id):
        raise HTTPException(status_code=404, detail="Канал не найден")
    container.processor.remove_channel(channel_id)
    return {"status": "deleted"}


@router.post("/api/channels/{channel_id}/start")
def start_channel(channel_id: int, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, str]:
    container.processor.start(channel_id)
    return {"status": "running"}


@router.post("/api/channels/{channel_id}/stop")
def stop_channel(channel_id: int, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, str]:
    container.processor.stop(channel_id)
    return {"status": "stopped"}


@router.post("/api/channels/{channel_id}/restart")
def restart_channel(channel_id: int, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, str]:
    container.processor.restart(channel_id)
    return {"status": "restarted"}
