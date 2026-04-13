from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

from database.errors import StorageUnavailableError
from app.api.container import AppContainer
from app.api.deps import get_container, get_current_user
from app.api.schemas import ListPayload, UpdateListPayload

router = APIRouter()


@router.get("/api/lists")
def list_plate_lists(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> List[Dict[str, Any]]:
    try:
        return container.lists_db.list_lists()
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.post("/api/lists")
def create_plate_list(payload: ListPayload, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    try:
        list_id = container.lists_db.create_list(payload.name, payload.type)
        return {"id": list_id, "name": payload.name, "type": payload.type}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.get("/api/lists/entry-by-plate")
def entry_by_plate(plate: str = Query(..., min_length=1), container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    try:
        result = container.lists_db.find_client_by_plate(plate)
        if result is None:
            raise HTTPException(status_code=404, detail="Запись не найдена")
        return result
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.get("/api/lists/plates")
def all_plates(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> List[Dict[str, Any]]:
    try:
        return container.lists_db.all_plates_with_type()
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.delete("/api/lists/{list_id}")
def delete_plate_list(list_id: int, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    try:
        ok = container.lists_db.delete_list(list_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Список не найден")
        return {"ok": True}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.put("/api/lists/{list_id}")
def update_plate_list(list_id: int, payload: UpdateListPayload, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    try:
        ok = container.lists_db.update_list(list_id, payload.name, payload.type)
        if not ok:
            raise HTTPException(status_code=404, detail="Список не найден")
        return {"id": list_id, "name": payload.name, "type": payload.type}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.get("/api/lists/{list_id}/clients")
def list_clients_in_list(list_id: int, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> List[Dict[str, Any]]:
    try:
        return container.lists_db.list_clients_in_list(list_id)
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc
