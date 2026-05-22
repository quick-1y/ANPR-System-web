from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.container import AppContainer
from app.api.deps import get_container, require_permission
from app.api.schemas import DebugPayload

router = APIRouter()


@router.get("/api/debug/settings")
def get_debug_settings(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_permission("debug:read"))) -> Dict[str, Any]:
    return container.processor.get_debug_settings()


@router.put("/api/debug/settings")
def put_debug_settings(payload: DebugPayload, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_permission("debug:write"))) -> Dict[str, Any]:
    body = payload.model_dump()
    container.settings.save_debug_settings(body)
    return container.processor.update_debug_settings(body)


@router.get("/api/debug/channels")
def debug_channels(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_permission("debug:read"))) -> Dict[str, Any]:
    metrics = container.processor.list_states()
    states = container.processor.list_debug_states()
    return {
        "settings": container.processor.get_debug_settings(),
        "channels": [
            {
                "channel_id": channel_id,
                "metrics": metric.__dict__,
                "debug_state": states.get(channel_id, {}),
            }
            for channel_id, metric in metrics.items()
        ],
    }


@router.get("/api/debug/state")
def debug_state(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_permission("debug:read"))) -> Dict[str, Any]:
    return {
        "settings": container.processor.get_debug_settings(),
        "channel_states": container.processor.list_debug_states(),
    }


@router.get("/api/debug/logs")
def debug_logs(limit: int = 200, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_permission("debug:read"))) -> Dict[str, Any]:
    return {"items": container.debug_log_bus.snapshot(limit=limit)}


@router.get("/api/debug/logs/stream")
async def stream_debug_logs(request: Request, last_id: int = 0, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_permission("debug:read"))) -> StreamingResponse:
    async def generator():
        loop = asyncio.get_running_loop()
        queue = container.debug_log_bus.subscribe(loop)
        cursor = max(0, int(last_id))
        try:
            yield "retry: 2000\n\n"
            # Flush backlog: entries that arrived before this subscriber was registered
            for entry in container.debug_log_bus.snapshot_after(cursor):
                cursor = entry.id
                yield f"data: {json.dumps(entry.to_dict(), ensure_ascii=False)}\n\n"
            # Stream live entries
            while not container.stream_shutdown.is_set():
                if await request.is_disconnected():
                    break
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=15.0)
                    if entry.id > cursor:
                        cursor = entry.id
                        yield f"data: {json.dumps(entry.to_dict(), ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            container.debug_log_bus.unsubscribe(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
