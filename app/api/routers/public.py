"""Endpoints that need no authentication.

Only what the login screen cannot do without: the instance's default look.
Nothing else may be added here — anything sensitive belongs behind
`get_current_user`.
"""
from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends

from app.api.container import AppContainer
from app.api.deps import get_container, require_access

router = APIRouter()


@router.get("/api/public/appearance")
def public_appearance(
    container: AppContainer = Depends(get_container),
    _access: None = Depends(require_access("public")),
) -> Dict[str, str]:
    """`{default_theme, default_style}` from the `SettingsService` cache.

    Never fails because of the database: the service falls back to its last
    cache or the registry defaults, and `block=False` keeps unauthenticated
    callers from queueing behind a slow database.
    """
    service = container.settings_service
    return {
        "default_theme": service.get("interface.default_theme", block=False),
        "default_style": service.get("interface.default_style", block=False),
    }
