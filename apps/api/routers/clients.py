from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

from database.errors import StorageUnavailableError
from apps.api.container import AppContainer
from apps.api.deps import get_container, get_current_user
from apps.api.schemas import AttachClientPayload, ClientPayload

router = APIRouter()


@router.get("/api/clients")
def list_all_clients(
    container: AppContainer = Depends(get_container),
    _user: Dict[str, Any] = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    try:
        return container.clients_db.list_all_clients()
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


# NOTE: /api/clients/search must be declared before /api/clients/{client_id}
# so FastAPI does not treat "search" as a path parameter.
@router.get("/api/clients/search")
def search_clients(
    q: str = Query(..., min_length=1),
    container: AppContainer = Depends(get_container),
    _user: Dict[str, Any] = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    try:
        return container.clients_db.search_clients(q)
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.get("/api/clients/{client_id}")
def get_client(
    client_id: int,
    container: AppContainer = Depends(get_container),
    _user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        client = container.clients_db.get_client(client_id)
        if client is None:
            raise HTTPException(status_code=404, detail="Клиент не найден")
        return client
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.post("/api/clients")
def create_client(
    payload: ClientPayload,
    container: AppContainer = Depends(get_container),
    _user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        client_id = container.clients_db.create_client(
            plate=payload.plate,
            last_name=payload.last_name,
            first_name=payload.first_name,
            middle_name=payload.middle_name,
            phone=payload.phone,
            car=payload.car,
            comment=payload.comment,
        )
        if not client_id:
            raise HTTPException(status_code=409, detail="Номер пуст или не удалось создать клиента")
        return {"id": client_id}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.put("/api/clients/{client_id}")
def update_client(
    client_id: int,
    payload: ClientPayload,
    container: AppContainer = Depends(get_container),
    _user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        ok = container.clients_db.update_client(
            client_id=client_id,
            plate=payload.plate,
            last_name=payload.last_name,
            first_name=payload.first_name,
            middle_name=payload.middle_name,
            phone=payload.phone,
            car=payload.car,
            comment=payload.comment,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Клиент не найден или номер некорректен")
        return {"id": client_id}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.delete("/api/clients/{client_id}")
def delete_client(
    client_id: int,
    container: AppContainer = Depends(get_container),
    _user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        ok = container.clients_db.delete_client(client_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Клиент не найден")
        return {"ok": True}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.post("/api/clients/{client_id}/attach")
def attach_client_to_list(
    client_id: int,
    payload: AttachClientPayload,
    container: AppContainer = Depends(get_container),
    _user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        ok = container.clients_db.attach_to_list(client_id, payload.list_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Клиент не найден")
        return {"ok": True}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.delete("/api/clients/{client_id}/attach")
def detach_client_from_list(
    client_id: int,
    container: AppContainer = Depends(get_container),
    _user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        ok = container.clients_db.detach_from_list(client_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Клиент не найден")
        return {"ok": True}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc
