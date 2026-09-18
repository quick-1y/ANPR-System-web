"""Pure CORS allow-list parsing.

Kept dependency-free (no FastAPI/torch/cv2) so it's cheaply importable and
testable on its own — see app/api/main.py for where this is wired into the
actual CORSMiddleware configuration.
"""
from __future__ import annotations


def parse_cors_allowed_origins(raw: str | None) -> list[str]:
    """Parse a comma-separated CORS_ALLOWED_ORIGINS value into an origin list.

    Empty or unset input yields an empty list — no origin gets cross-origin
    browser access until explicitly configured. Whitespace around each
    origin is stripped, and empty entries (e.g. a trailing comma) are
    dropped.
    """
    if not raw:
        return []
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
