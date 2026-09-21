"""`/api/me/preferences` — personal preferences of the calling user (class U).

Deliberately open to any authenticated user: a preference belongs to the
person, not to a tab or an administrative right (roadmap 4.11), so neither a
navigation permission nor a role is checked here. The endpoints take no user
id — they can only ever read or change the caller's own record.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.api.container import AppContainer
from app.api.deps import get_container, require_access
from config.preferences import effective_timezone, resolve, validate_patch
from config.registry import SettingValidationError
from database.errors import StorageUnavailableError

router = APIRouter()


class PreferencesPatch(BaseModel):
    """Partial update; an omitted field is left alone, `null` resets it to the
    inherited value. Unknown fields (including any attempt to name another
    user) are rejected."""

    model_config = ConfigDict(extra="forbid")

    theme: Optional[str] = None
    style: Optional[str] = None
    sidebar_locked: Optional[bool] = None
    debug_panel_enabled: Optional[bool] = None
    channel_metrics_visible: Optional[bool] = None
    timezone: Optional[str] = None


def _view(container: AppContainer, stored: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "preferences": resolve(stored, container.settings_service),
        "display_timezone": effective_timezone(stored, container.settings_service),
    }


@router.get("/api/me/preferences")
def get_my_preferences(
    container: AppContainer = Depends(get_container),
    user: Dict[str, Any] = Depends(require_access("self")),
) -> Dict[str, Any]:
    try:
        stored = container.user_db.get_preferences(int(user["id"]))
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc
    if stored is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return _view(container, stored)


@router.patch("/api/me/preferences")
def patch_my_preferences(
    payload: PreferencesPatch,
    container: AppContainer = Depends(get_container),
    user: Dict[str, Any] = Depends(require_access("self")),
) -> Dict[str, Any]:
    try:
        patch = validate_patch(payload.model_dump(exclude_unset=True))
    except SettingValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        stored = container.user_db.merge_preferences(int(user["id"]), patch)
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc
    if stored is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return _view(container, stored)
