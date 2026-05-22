from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from app.api.container import AppContainer
from app.api.deps import get_container, require_permission
from app.api.schemas import ControllerPayload, ControllerTestPayload

router = APIRouter()


@router.get("/api/controllers")
def list_controllers(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_permission("controllers:manage"))) -> List[Dict[str, Any]]:
    return container.controller_db.list_controllers()


@router.post("/api/controllers")
def create_controller(payload: ControllerPayload, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_permission("controllers:manage"))) -> Dict[str, Any]:
    existing = container.controller_db.list_controllers()
    new_data = payload.model_dump()
    container.validate_global_hotkeys([*existing, new_data])
    return container.controller_db.create_controller(new_data)


@router.put("/api/controllers/{controller_id}")
def update_controller(controller_id: int, payload: ControllerPayload, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_permission("controllers:manage"))) -> Dict[str, Any]:
    existing = container.controller_db.list_controllers()
    update_data = payload.model_dump()
    others = [c for c in existing if int(c.get("id", 0)) != controller_id]
    container.validate_global_hotkeys([*others, {**update_data, "id": controller_id}])
    updated = container.controller_db.update_controller(controller_id, update_data)
    if updated is None:
        raise HTTPException(status_code=404, detail="Контроллер не найден")
    return updated


@router.delete("/api/controllers/{controller_id}")
def delete_controller(controller_id: int, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_permission("controllers:manage"))) -> Dict[str, str]:
    channels_using = [
        int(ch.get("id", 0))
        for ch in container.channel_db.list_channels()
        if ch.get("controller_id") is not None and int(ch.get("controller_id", 0)) == controller_id
    ]
    if channels_using:
        used_in = ", ".join(str(i) for i in channels_using)
        raise HTTPException(
            status_code=409,
            detail=f"Контроллер используется в каналах: {used_in}. Сначала отвяжите его в настройках каналов.",
        )
    if not container.controller_db.delete_controller(controller_id):
        raise HTTPException(status_code=404, detail="Контроллер не найден")
    return {"status": "deleted"}


@router.post("/api/controllers/{controller_id}/test")
def test_controller(controller_id: int, payload: ControllerTestPayload, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_permission("controllers:manage"))) -> Dict[str, Any]:
    controller = container.controller_db.get_controller(controller_id)
    if not controller:
        raise HTTPException(status_code=404, detail="Контроллер не найден")
    url = container.controller_service.send_command(controller, payload.relay_index, payload.is_on, reason="api-test")
    return {"status": "sent" if url else "skipped", "url": url}
