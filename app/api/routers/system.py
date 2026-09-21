from __future__ import annotations

from typing import Any, Dict, List

import psutil
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.api.container import AppContainer, WEB_DIR
from app.api.deps import get_container, get_current_user, require_access
from common.timeutil import utc_now

router = APIRouter()


@router.get("/")
def root() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@router.get("/api/health")
def health(container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    metrics = container.processor.list_states()
    return {
        "status": "ok",
        "channels_total": len(container.channel_db.list_channels()),
        "channels_running": sum(1 for item in metrics.values() if item.state == "running"),
    }


@router.get("/api/system/time")
def system_time(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(require_access("authenticated"))) -> Dict[str, Any]:
    """Server clock (UTC) and the zone an administrator chose for the instance.

    `display_timezone` is `None` until an administrator stores a zone: the
    client then shows its own system time, which is the default behaviour.
    Once a zone is stored (even `UTC`), everyone sees that zone.
    """
    service = container.settings_service
    configured = service.is_configured("interface.display_timezone")
    return {
        "server_utc": utc_now().isoformat(),
        "display_timezone": service.get("interface.display_timezone") if configured else None,
        "timezone_configured": configured,
    }


@router.get("/api/system/resources")
def system_resources(_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, float]:
    vm = psutil.virtual_memory()
    return {
        "cpu_percent": float(psutil.cpu_percent(interval=None)),
        "ram_percent": float(vm.percent),
    }


@router.get("/api/storage/status")
def storage_status(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return container.db_status()


@router.get("/api/telemetry/channels")
def channels_telemetry(container: AppContainer = Depends(get_container), _user: Dict[str, Any] = Depends(get_current_user)) -> List[Dict[str, Any]]:
    channels = {int(item["id"]): item for item in container.channel_db.list_channels()}
    metrics = container.processor.list_states()
    items: List[Dict[str, Any]] = []
    for channel_id, metric in metrics.items():
        items.append(
            {
                "channel_id": channel_id,
                "name": channels.get(channel_id, {}).get("name", f"channel-{channel_id}"),
                "state": metric.state,
                "fps": metric.fps,
                "latency_ms": metric.latency_ms,
                "reconnect_count": metric.reconnect_count,
                "timeout_count": metric.timeout_count,
                "error_count": metric.error_count,
                "last_event_at": metric.last_event_at,
                "last_error": metric.last_error,
            }
        )
    return items
