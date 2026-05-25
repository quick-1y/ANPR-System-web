from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from database.errors import StorageUnavailableError
from apps.api.container import AppContainer
from apps.api.deps import get_container, get_current_user
from apps.api.schemas import ZonePayload, ZoneUpdatePayload

router = APIRouter()


def _zone_with_occupancy(zone: Dict[str, Any], container: AppContainer) -> Dict[str, Any]:
    occupied = container.zone_db.get_zone_occupancy(int(zone["id"]))
    capacity = int(zone["capacity"])
    return {
        "id": zone["id"],
        "name": zone["name"],
        "capacity": capacity,
        "occupied": occupied,
        "free": max(0, capacity - occupied),
    }


@router.get("/api/zones")
def list_zones(
    container: AppContainer = Depends(get_container),
    _user: Dict[str, Any] = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    try:
        zones = container.zone_db.list_zones()
        return [_zone_with_occupancy(z, container) for z in zones]
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.post("/api/zones")
def create_zone(
    payload: ZonePayload,
    container: AppContainer = Depends(get_container),
    _user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        zone_id = container.zone_db.create_zone(payload.name, payload.capacity)
        zone = container.zone_db.get_zone(zone_id)
        if not zone:
            raise HTTPException(status_code=500, detail="Не удалось создать зону")
        return _zone_with_occupancy(zone, container)
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.get("/api/zones/{zone_id}")
def get_zone(
    zone_id: int,
    container: AppContainer = Depends(get_container),
    _user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        zone = container.zone_db.get_zone(zone_id)
        if not zone:
            raise HTTPException(status_code=404, detail="Зона не найдена")
        result = _zone_with_occupancy(zone, container)
        result["channels"] = container.zone_db.get_channels_for_zone(zone_id)
        return result
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.put("/api/zones/{zone_id}")
def update_zone(
    zone_id: int,
    payload: ZoneUpdatePayload,
    container: AppContainer = Depends(get_container),
    _user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        if not container.zone_db.get_zone(zone_id):
            raise HTTPException(status_code=404, detail="Зона не найдена")
        container.zone_db.update_zone(zone_id, payload.name, payload.capacity)
        zone = container.zone_db.get_zone(zone_id)
        return _zone_with_occupancy(zone, container)
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.delete("/api/zones/{zone_id}")
def delete_zone(
    zone_id: int,
    container: AppContainer = Depends(get_container),
    _user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        zone = container.zone_db.get_zone(zone_id)
        if not zone:
            raise HTTPException(status_code=404, detail="Зона не найдена")
        affected_channels = container.zone_db.get_channels_for_zone(zone_id)
        container.zone_db.delete_zone(zone_id)
        return {"status": "deleted", "affected_channels": affected_channels}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc
