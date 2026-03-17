from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# Paths that must remain accessible without a key.
# /api/health is used by Docker HEALTHCHECK and monitoring probes.
_EXEMPT_PATHS = frozenset({"/api/health"})

# Streaming paths accept the key via ?api_key= query parameter because
# EventSource and <img> MJPEG consumers cannot send custom headers.
_STREAMING_PATHS_PREFIX = (
    "/api/events/stream",
    "/api/debug/logs/stream",
    "/api/channels/",  # covers /preview.mjpg and /snapshot.jpg
)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Require a static API key on all /api/* routes except health checks.

    The key is read from the ``API_KEY`` environment variable at startup.
    If the variable is empty the middleware is not added (see main.py).

    Clients must provide the key in one of:
    - ``X-Api-Key: <key>`` header  (preferred for regular requests)
    - ``Authorization: Bearer <key>`` header
    - ``?api_key=<key>`` query parameter  (required for SSE / MJPEG streams)
    """

    def __init__(self, app: ASGIApp, *, api_key: str) -> None:
        super().__init__(app)
        self._api_key = api_key

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Pass-through: non-API paths and the health check
        if not path.startswith("/api/") or path in _EXEMPT_PATHS:
            return await call_next(request)

        provided = (
            request.headers.get("X-Api-Key")
            or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            or request.query_params.get("api_key", "")
        )

        if provided != self._api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)
