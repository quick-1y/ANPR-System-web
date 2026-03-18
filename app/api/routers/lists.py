from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from database.errors import StorageUnavailableError
from app.api.container import AppContainer
from app.api.deps import get_container
from app.api.schemas import EntryPayload, ListPayload, UpdateListPayload

router = APIRouter()


@router.get("/api/lists")
def list_plate_lists(container: AppContainer = Depends(get_container)) -> List[Dict[str, Any]]:
    try:
        return container.lists_db.list_lists()
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.post("/api/lists")
def create_plate_list(payload: ListPayload, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    try:
        list_id = container.lists_db.create_list(payload.name, payload.type)
        return {"id": list_id, "name": payload.name, "type": payload.type}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.get("/api/lists/plates")
def all_plates(container: AppContainer = Depends(get_container)) -> List[Dict[str, Any]]:
    try:
        return container.lists_db.all_plates_with_type()
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.delete("/api/lists/{list_id}")
def delete_plate_list(list_id: int, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    try:
        ok = container.lists_db.delete_list(list_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Список не найден")
        return {"ok": True}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.put("/api/lists/{list_id}")
def update_plate_list(list_id: int, payload: UpdateListPayload, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    try:
        ok = container.lists_db.update_list(list_id, payload.name, payload.type)
        if not ok:
            raise HTTPException(status_code=404, detail="Список не найден")
        return {"id": list_id, "name": payload.name, "type": payload.type}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.get("/api/lists/{list_id}/entries")
def list_entries(list_id: int, container: AppContainer = Depends(get_container)) -> List[Dict[str, Any]]:
    try:
        return container.lists_db.list_entries(list_id)
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.post("/api/lists/{list_id}/entries")
def add_entry(list_id: int, payload: EntryPayload, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    try:
        entry_id = container.lists_db.add_entry(list_id=list_id, plate=payload.plate, comment=payload.comment)
        if not entry_id:
            raise HTTPException(status_code=409, detail="Номер уже существует или пуст")
        return {"id": entry_id}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.put("/api/lists/{list_id}/entries/{entry_id}")
def update_entry(list_id: int, entry_id: int, payload: EntryPayload, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    try:
        ok = container.lists_db.update_entry(entry_id, plate=payload.plate, comment=payload.comment)
        if not ok:
            raise HTTPException(status_code=409, detail="Не удалось обновить: номер уже существует или запись не найдена")
        return {"id": entry_id}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.delete("/api/lists/{list_id}/entries/{entry_id}")
def delete_entry(list_id: int, entry_id: int, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    try:
        ok = container.lists_db.delete_entry(entry_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Запись не найдена")
        return {"ok": True}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc
