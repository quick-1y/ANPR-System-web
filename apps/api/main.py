from __future__ import annotations

import os
from contextlib import asynccontextmanager

import cv2
import torch

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from apps.api.container import AppContainer, WEB_DIR
from apps.api.routers.auth import router as auth_router
from apps.api.routers.channels import router as channels_router
from apps.api.routers.clients import router as clients_router
from apps.api.routers.controllers import router as controllers_router
from apps.api.routers.data import router as data_router
from apps.api.routers.debug import router as debug_router
from apps.api.routers.events import router as events_router
from apps.api.routers.lists import router as lists_router
from apps.api.routers.settings import router as settings_router
from apps.api.routers.system import router as system_router
from apps.api.routers.users import router as users_router
from apps.api.routers.zones import router as zones_router


def _configure_thread_limits() -> None:
    """Limit internal threading for PyTorch/OpenCV to prevent CPU oversubscription."""
    omp = int(os.environ.get("OMP_NUM_THREADS", 2))
    torch.set_num_threads(omp)
    torch.set_num_interop_threads(min(2, omp))
    cv2.setNumThreads(omp)


_configure_thread_limits()


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
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/web", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

app.include_router(auth_router)
app.include_router(users_router)
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
