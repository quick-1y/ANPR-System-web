---
last_mapped_commit: 9cfd79b3a864f23127a46c35300f838c212d0007
last_mapped_at: 2026-09-24
---
# Technology Stack

**Analysis Date:** 2026-09-24

## Languages

**Primary:**

- Python 3.13 - FastAPI API server, retention worker, channel processing, ANPR pipeline, configuration management

## Runtime

**Environment:**

- Python 3.13-slim Docker image (Debian-based, from `Dockerfile`)
- Docker Compose orchestration with 4 services: postgres, api, retention_worker, nginx

**Package Manager:**

- Poetry (v1.8+ implicit; `pyproject.toml` + `poetry.lock`)
- Lockfile: `poetry.lock` (committed)
- Dependency installation: `poetry install --no-root --only main` (Dockerfile line 22)

## Frameworks

**Core API:**

- FastAPI (unpinned, latest) - HTTP API server (`app/api/main.py`)
- Uvicorn (unpinned, latest) - ASGI server
  - API: `uvicorn app.api.main:app --host 0.0.0.0 --port 8080`
  - Worker: `uvicorn app.worker.main:app --host 0.0.0.0 --port 8092`

**Reverse Proxy:**

- nginx 1.27-alpine - Request routing, SSE support, CORS proxy (`nginx/default.conf`)

**Testing:**

- pytest (9.0.2–9.9.x from `pyproject.toml` dev dependency)

**Build/Dev:**

- Docker + Docker Compose (for all deployments)

## Key Dependencies

**ML Detection & Recognition:**

- ultralytics 8.3.20 (pinned, required) - YOLOv8 license plate detection via internal `model.predictor` tracker API
- torch 2.8.0 (pinned, CPU-only from `download.pytorch.org/whl/cpu`) - Deep learning inference runtime
- torchvision 0.23.0 (pinned, CPU-only) - Image transforms for CRNN OCR pipeline
- opencv-python (unpinned) - RTSP video capture, frame processing, JPEG encoding

**Database:**

- psycopg[binary] (unpinned) - PostgreSQL driver (psycopg3)
- psycopg_pool (unpinned) - Connection pooling (min=2, max=10; two separate pools: events + lists)

**Authentication & Cryptography:**

- bcrypt (unpinned) - Password hashing for users
- PyJWT (unpinned) - JWT token issue/verify (HS256 algorithm, `app/api/auth_utils.py`)

**Configuration & Data:**

- PyYAML (unpinned) - Parse country plate format configs (`anpr/countries/*.yaml`)

**System Monitoring:**

- psutil (unpinned) - CPU, memory, disk metrics

**Utilities:**

- python-multipart (unpinned) - FastAPI form data parsing
- tzdata (unpinned) - Timezone support

## Configuration

**Environment:**

- Read-once at startup via `config/env_settings.py` (only place that reads `os.environ`)
- `.env` file (gitignored) with defaults from `.env.example` (Russian comments)
- `EnvConfig` dataclass validates types and enforces minimum secret length

**Operational Settings:**

- Class A settings: Stored in PostgreSQL `app_settings` table (one row per leaf key)
- Settings schema: `config/registry.py` (class, type, default, bounds, `requires_restart`, owner)
- No settings file; YAML config removed as of dev branch commit e4ad237
- Read/written through `SettingsService` (`config/settings_service.py`)
- Revision tracking via `app_settings_revision` table for cache invalidation

**Personal UI State:**

- Browser `localStorage` only (no server persistence)
  - Theme, style, sidebar pin, debug panel, channel metrics
  - Implementation: `app/web/js/appearance.js`, `app/web/js/device-prefs.js`

**Application Secrets:**

- `JWT_SECRET_KEY` - JWT signing secret (env var, min 32 bytes in production, enforced at startup)
- `SUPERADMIN_PASSWORD` - Technical superadmin account (env var, read fresh on every login)

**Build Configuration:**

- `pyproject.toml` - Poetry dependencies and metadata
- `poetry.lock` - Locked versions (committed for reproducibility)
- `Dockerfile` - Multi-stage build (Python 3.13-slim, system deps, poetry install)
- `docker-compose.yml` - 4-service orchestration (postgres, api, retention_worker, nginx)

## Platform Requirements

**Development:**

- Docker & Docker Compose required (no standalone Python instructions)
- PostgreSQL 16 (via Docker)
- Python 3.13 (via Docker image)

**System Dependencies (in Docker image):**

- libglib2.0-0 - Required by OpenCV
- libgl1 - Required by OpenCV
- libgomp1 - OpenMP runtime for parallel processing
- tzdata - Timezone database

**Production Deployment:**

- Self-hosted on-premises (Docker Compose)
- CPU-only inference (no GPU required, no CUDA)
- Network access to RTSP cameras and hardware controllers (HTTP/HTTPS)
- Ports: 8080 (HTTP via nginx), 5432 (PostgreSQL, internal only)

**Volume Mounts:**

- `pgdata` - PostgreSQL persistent data
- `media_data` - Screenshots and exports (`/app/data`)
- `logs_data` - Application logs (`/app/logs`)

---

*Stack analysis: 2026-09-24*
