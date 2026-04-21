from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from database.errors import StorageUnavailableError
from app.api.container import AppContainer
from app.api.deps import get_container, get_current_user

router = APIRouter()


@router.get("/api/events")
def list_events(
    limit: int = 100,
    before_ts: Optional[datetime] = None,
    before_id: Optional[int] = None,
    channel_id: Optional[int] = None,
    plate: Optional[str] = None,
    start_ts: Optional[datetime] = None,
    end_ts: Optional[datetime] = None,
    container: AppContainer = Depends(get_container),
    _user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    safe_limit = max(1, min(int(limit), 200))
    fetch_limit = safe_limit + 1
    if (before_ts is None) ^ (before_id is None):
        raise HTTPException(status_code=400, detail="before_ts и before_id должны передаваться вместе")
    use_cursor = before_ts is not None and before_id is not None
    use_filtered = use_cursor or channel_id is not None or plate or start_ts is not None or end_ts is not None
    try:
        if use_filtered:
            rows = container.events_db.fetch_journal_page(
                limit=fetch_limit,
                before_ts=before_ts,
                before_id=before_id,
                channel_id=channel_id,
                plate=plate,
                start_ts=start_ts,
                end_ts=end_ts,
            )
        else:
            rows = container.events_db.fetch_recent(limit=fetch_limit)
        has_more = len(rows) > safe_limit
        items = [dict(row) for row in rows[:safe_limit]]
        return {"items": items, "has_more": has_more}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc



def _fetch_event_by_id(container: AppContainer, event_id: int) -> Dict[str, Any] | None:
    try:
        row = container.events_db.fetch_by_id(event_id)
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    return dict(row)


@router.get("/api/events/item/{event_id}")
def get_event(event_id: int, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    event = _fetch_event_by_id(container, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Событие не найдено")
    return event


@router.get("/api/events/item/{event_id}/media/{kind}")
def get_event_media(event_id: int, kind: str, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> FileResponse:
    event = _fetch_event_by_id(container, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Событие не найдено")
    if kind not in {"frame", "plate"}:
        raise HTTPException(status_code=400, detail="kind должен быть frame или plate")
    media_path = str(event.get("frame_path" if kind == "frame" else "plate_path") or "").strip()
    if not media_path:
        raise HTTPException(status_code=404, detail="Изображение для события отсутствует")
    path_obj = Path(media_path)
    if not path_obj.is_file():
        raise HTTPException(status_code=404, detail="Файл изображения не найден")
    return FileResponse(path=path_obj, media_type="image/jpeg")


@router.get("/api/events/stream")
async def stream_events(request: Request, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> StreamingResponse:
    queue = await container.event_bus.subscribe()

    async def generator():
        try:
            yield "retry: 3000\n\n"
            while not container.stream_shutdown.is_set():
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            await container.event_bus.unsubscribe(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
