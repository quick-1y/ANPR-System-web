from __future__ import annotations

from contextlib import asynccontextmanager

import cv2
import torch

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.container import AppContainer, WEB_DIR
from config.env_settings import enforce_secret_policy, load_env_config
from app.api.routers.auth import router as auth_router
from app.api.routers.channels import router as channels_router
from app.api.routers.clients import router as clients_router
from app.api.routers.controllers import router as controllers_router
from app.api.routers.data import router as data_router
from app.api.routers.debug import router as debug_router
from app.api.routers.events import router as events_router
from app.api.routers.lists import router as lists_router
from app.api.routers.preferences import router as preferences_router
from app.api.routers.public import router as public_router
from app.api.routers.settings import router as settings_router
from app.api.routers.system import router as system_router
from app.api.routers.users import router as users_router
from app.api.routers.zones import router as zones_router


def _configure_thread_limits() -> None:
    """Limit internal threading for PyTorch/OpenCV to prevent CPU oversubscription."""
    omp = load_env_config().omp_num_threads
    torch.set_num_threads(omp)
    torch.set_num_interop_threads(min(2, omp))
    cv2.setNumThreads(omp)


def _enforce_secret_policy_on_startup() -> None:
    """Fail-fast on weak infrastructure secrets before the app serves.

    Called at import time, like _configure_thread_limits() above: with
    APP_ENV=production a default or too-short JWT_SECRET_KEY (or a missing
    BOOTSTRAP_SUPERADMIN_PASSWORD) must abort the process, not start
    serving requests signed with a publicly known secret.
    """
    enforce_secret_policy()


def _cors_allowed_origins() -> list[str]:
    """Browser-facing CORS allow-list, from CORS_ALLOWED_ORIGINS (comma-
    separated origins, e.g. "https://dash.example.com,https://a.example.org").

    Empty by default — no origin gets cross-origin browser access until an
    operator explicitly configures one. This only affects browsers: CORS is
    enforced client-side, and Starlette's CORSMiddleware never rejects a
    request based on Origin — it only controls whether the *browser* is
    allowed to expose the response to page JS. Non-browser clients
    (server-to-server integrations authenticated with their own token, curl,
    another backend) never go through this check at all, regardless of this
    setting.
    """
    return list(load_env_config().cors_allowed_origins)


_configure_thread_limits()
_enforce_secret_policy_on_startup()


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = AppContainer.build()
    await container.startup()
    app.state.container = container
    yield
    container.shutdown()


app = FastAPI(title="ANPR Core API", version="0.8-stage8", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/web", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

app.include_router(auth_router)
app.include_router(public_router)
app.include_router(users_router)
app.include_router(preferences_router)
app.include_router(system_router)
app.include_router(channels_router)
app.include_router(events_router)
app.include_router(debug_router)
app.include_router(controllers_router)
app.include_router(lists_router)
app.include_router(clients_router)
app.include_router(settings_router)
app.include_router(data_router)
app.include_router(zones_router)
