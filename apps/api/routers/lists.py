from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from database.errors import StorageUnavailableError
from apps.api.container import AppContainer
from apps.api.deps import get_container, get_current_user
from apps.api.schemas import BulkImportPayload, ListPayload, UpdateListPayload

router = APIRouter()


@router.get("/api/lists")
def list_lists(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> List[Dict[str, Any]]:
    try:
        return container.lists_db.list_lists()
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.post("/api/lists")
def create_list(payload: ListPayload, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    try:
        list_id = container.lists_db.create_list(payload.name, payload.type)
        return {"id": list_id, "name": payload.name, "type": payload.type}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.get("/api/lists/plates")
def plates_by_type(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> List[Dict[str, Any]]:
    try:
        return container.lists_db.all_plates_with_type()
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.delete("/api/lists/{list_id}")
def delete_list(list_id: int, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    try:
        ok = container.lists_db.delete_list(list_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Список не найден")
        return {"ok": True}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.put("/api/lists/{list_id}")
def update_list(list_id: int, payload: UpdateListPayload, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
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


@router.post("/api/lists/{list_id}/import")
def import_clients(list_id: int, payload: BulkImportPayload, container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    try:
        return container.clients_db.bulk_create_and_attach(list_id, [c.model_dump() for c in payload.clients])
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc
