from __future__ import annotations

import os
from contextlib import asynccontextmanager

import cv2
import torch

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.auth import APIKeyMiddleware
from app.api.container import AppContainer, WEB_DIR
from app.api.routers.channels import router as channels_router
from app.api.routers.controllers import router as controllers_router
from app.api.routers.data import router as data_router
from app.api.routers.debug import router as debug_router
from app.api.routers.events import router as events_router
from app.api.routers.lists import router as lists_router
from app.api.routers.settings import router as settings_router
from app.api.routers.system import router as system_router


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

_api_key = os.getenv("API_KEY", "").strip()
if _api_key:
    app.add_middleware(APIKeyMiddleware, api_key=_api_key)

app.mount("/web", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

app.include_router(system_router)
app.include_router(channels_router)
app.include_router(events_router)
app.include_router(debug_router)
app.include_router(controllers_router)
app.include_router(lists_router)
app.include_router(settings_router)
app.include_router(data_router)
