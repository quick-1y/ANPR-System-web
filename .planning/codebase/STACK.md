# Technology Stack

**Analysis Date:** 2026-04-14

## Languages

**Primary:**
- Python 3.13 — All backend logic, ML inference, API server (`Dockerfile`: `python:3.13-slim`)

**Secondary:**
- HTML/CSS/JS — Static web frontend served from `app/web/` via FastAPI `StaticFiles`
- YAML — Configuration management (`config/settings.yaml`)
- SQL — Database schema and queries (`database/postgres/schema.sql`)

## Runtime

**Environment:**
- Python 3.13-slim Docker image (Debian-based)
- System deps in Dockerfile: `libglib2.0-0`, `libgl1`, `libgomp1` (required by OpenCV and numeric libs)
- `PYTHONDONTWRITEBYTECODE=1` and `PYTHONUNBUFFERED=1` set in Dockerfile
- Thread limits configured at startup via env vars: `OMP_NUM_THREADS=2`, `MKL_NUM_THREADS=2`, `OPENBLAS_NUM_THREADS=2`
  - Applied to PyTorch (`torch.set_num_threads`), OpenCV (`cv2.setNumThreads`) to prevent CPU oversubscription

**Package Manager:**
- **Poetry** (`pyproject.toml`) — replaced pip/requirements.txt
- Dev dependencies group: `pytest>=9.0.2,<10.0.0`
- Special index: PyTorch CPU wheels from `https://download.pytorch.org/whl/cpu` (named `pytorch-cpu`, priority `explicit`)

## Frameworks

**Core:**
- FastAPI (unpinned) — REST API framework (`app/api/main.py`, `app/worker/main.py`)
- Uvicorn (unpinned) — ASGI server; command: `uvicorn app.api.main:app --host 0.0.0.0 --port 8080`

**ML/Computer Vision:**
- ultralytics 8.3.20 — YOLO object detection for license plate localization
- PyTorch 2.8.0 (CPU-only) — Deep learning runtime
- torchvision 0.23.0 (CPU-only) — Image transforms for CRNN OCR model
- OpenCV (`opencv-python`, unpinned) — Video capture (RTSP), image processing, JPEG encoding

**Auth:**
- PyJWT (unpinned) — JWT token creation and verification (HS256)
- bcrypt (unpinned) — Password hashing for user credentials

**Build/Dev:**
- Docker + Docker Compose — Containerized deployment
- Nginx 1.27-alpine — Reverse proxy (`nginx/default.conf`)

## Key Dependencies

**From `pyproject.toml`:**

| Package | Version | Purpose |
|---------|---------|---------|
| `ultralytics` | 8.3.20 | YOLO license plate detection |
| `opencv-python` | unpinned | Video capture and image processing |
| `psutil` | unpinned | System resource monitoring (CPU, memory, disk) |
| `PyYAML` | unpinned | Settings YAML parsing |
| `fastapi` | unpinned | HTTP API framework |
| `python-multipart` | unpinned | Multipart form uploads |
| `uvicorn` | unpinned | ASGI server |
| `psycopg[binary]` | unpinned | PostgreSQL driver (psycopg3 with C extensions) |
| `psycopg_pool` | unpinned | PostgreSQL connection pooling |
| `bcrypt` | unpinned | Password hashing |
| `PyJWT` | unpinned | JWT token auth |
| `torch` | 2.8.0 | PyTorch CPU build (explicit index) |
| `torchvision` | 0.23.0 | Image transforms (explicit index) |

**Dev dependencies:**
| Package | Version | Purpose |
|---------|---------|---------|
| `pytest` | >=9.0.2,<10.0.0 | Test runner |

**Infrastructure (Docker images):**
- `postgres:16` — Event and plate list storage
- `nginx:1.27-alpine` — Reverse proxy
- `python:3.13-slim` — Base application image

## Configuration

**Environment (from `.env`):**
- `APP_ENV` — Runtime environment identifier (default: `docker`)
- `JWT_SECRET_KEY` — JWT signing secret (default: `anpr-default-secret-change-me` — must be changed in production)
- `JWT_EXPIRATION_MINUTES` — JWT token TTL in minutes (default: `480` = 8 hours)
- `DEBUG` — Debug mode flag (default: `false`)
- `LOG_LEVEL` — Logging verbosity (default: `INFO`)
- `SETTINGS_PATH` — Path to YAML settings file (default: `/app/config/settings.yaml`)
- `HTTP_PORT` — Nginx external port (default: `8080`)
- `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` — PostgreSQL credentials
- `POSTGRES_DSN` — Full PostgreSQL connection string
- `OMP_NUM_THREADS` / `MKL_NUM_THREADS` / `OPENBLAS_NUM_THREADS` — Thread limits (default: `2`)

**Application Settings (YAML via `config/settings_schema.py`):**
- `models` — YOLO and OCR model paths, device (`cpu`)
- `ocr` — Image dimensions, alphabet, confidence threshold
- `detector` — Detection confidence, bbox padding
- `inference` — Worker count, shared memory flag
- `debug` — Channel metrics, log panel, video output toggles
- `channels` — Per-channel detection config (ROI, motion, size filter, controller binding, list filter)
- `controllers` — Hardware relay controller definitions
- `reconnect` — Signal loss and periodic reconnect policies
- `storage` — Directories, retention days, cleanup intervals
- `tracking` — Best shots, cooldown, OCR confidence, direction tracking
- `plates` — Country configs directory, enabled countries
- `logging` — Level, retention days
- `time` — Timezone, offset

**Build:**
- `Dockerfile` — Single-stage Python 3.13-slim image with two-phase pip install (PyTorch first, then remaining deps)
- `docker-compose.yml` — 4-service orchestration

## Services Architecture

**Docker Compose defines 4 services:**

| Service | Image | Port | Health Check | Purpose |
|---------|-------|------|-------------|---------|
| `postgres` | postgres:16 | 5432 (internal) | `pg_isready` every 5s, 12 retries | Event and plate list storage |
| `api` | Custom (Dockerfile) | 8080 (internal) | `GET /api/health` every 10s, 6 retries | Main API + ANPR processing |
| `retention_worker` | Custom (Dockerfile) | 8092 (internal) | `GET /worker/health` every 15s, 6 retries | Scheduled data cleanup |
| `nginx` | nginx:1.27-alpine | 80 -> `HTTP_PORT` | `wget /` every 10s, 6 retries | Reverse proxy, SSE support |

**Startup order:** postgres (healthy) -> api + retention_worker (healthy) -> nginx

**Docker volumes:**
- `pgdata` — PostgreSQL data persistence
- `media_data` — Screenshots and exports (`/app/data`)
- `logs_data` — Application logs (`/app/logs`)
- `./config:/app/config` — Settings YAML (bind mount, not named volume)

## Platform Requirements

**Development:**
- Docker and Docker Compose
- `.env` file in project root (see `.env` for template)
- `config/settings.yaml` — application settings
- ANPR model weights: `anpr/models/yolo/best.pt` and `anpr/models/ocr_crnn/crnn_ocr_model_int8_fx.pth`

**Production:**
- Docker host with CPU (no GPU required — CPU-only PyTorch)
- Network access to RTSP camera sources
- Change `JWT_SECRET_KEY` to a random 32+ byte value before deploying

---

*Stack analysis: 2026-04-14*
