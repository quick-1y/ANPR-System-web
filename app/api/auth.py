from __future__ import annotations

import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# Paths that must remain accessible without a key.
# /api/health is used by Docker HEALTHCHECK and monitoring probes.
# /api/auth/* endpoints handle their own authentication.
_EXEMPT_PATHS = frozenset({"/api/health"})
_EXEMPT_PREFIXES = ("/api/auth/",)

# Streaming paths accept the key via ?api_key= query parameter because
# EventSource and <img> MJPEG consumers cannot send custom headers.
_STREAMING_PATHS_PREFIX = (
    "/api/events/stream",
    "/api/debug/logs/stream",
    "/api/channels/",  # covers /preview.mjpg and /snapshot.jpg
)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Legacy static API key middleware — kept as a backward-compatible fallback.

    When the ``API_KEY`` environment variable is set, this middleware accepts
    the static key alongside JWT tokens.  Requests that carry a JWT Bearer
    token (recognised by the ``eyJ`` prefix) are passed through without
    API-key validation; the ``get_current_user`` dependency validates the
    JWT later in the request lifecycle.

    Clients may provide the static key in one of:
    - ``X-Api-Key: <key>`` header  (preferred for regular requests)
    - ``?api_key=<key>`` query parameter  (for SSE / MJPEG streams)
    """

    def __init__(self, app: ASGIApp, *, api_key: str) -> None:
        super().__init__(app)
        self._api_key = api_key

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Pass-through: non-API paths, health check, and auth endpoints
        if not path.startswith("/api/") or path in _EXEMPT_PATHS:
            return await call_next(request)
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        # If the request carries a JWT Bearer token, let it through —
        # the get_current_user dependency will validate the JWT.
        auth_header = request.headers.get("Authorization", "").strip()
        if auth_header.startswith("Bearer ") and auth_header[7:].startswith("eyJ"):
            return await call_next(request)

        # If a ?token= query param is present (JWT for streams), pass through.
        if request.query_params.get("token", "").startswith("eyJ"):
            return await call_next(request)

        # Otherwise fall back to static API key comparison.
        provided = (
            request.headers.get("X-Api-Key")
            or request.query_params.get("api_key", "")
        )

        if provided and secrets.compare_digest(provided, self._api_key):
            return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized"},
            headers={"WWW-Authenticate": "Bearer"},
        )
