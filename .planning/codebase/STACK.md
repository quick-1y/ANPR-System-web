# Technology Stack

**Analysis Date:** 2026-09-18

## Languages

**Primary:**
- Python 3.13 - Backend API, ANPR detection/recognition, data processing
- JavaScript (Vanilla) - Frontend UI (no framework)
- YAML - Configuration files

## Runtime

**Environment:**
- Docker containers (Python 3.13-slim base image)
- Uvicorn ASGI server for FastAPI applications
- Nginx reverse proxy (in docker-compose)

**Package Manager:**
- Poetry 1.x - Python dependency management
- Lockfile: `poetry.lock` (present)

## Frameworks

**Core Web:**
- FastAPI - REST API framework (`app.api.main`, version in pyproject.toml `*`)
- Uvicorn - ASGI server (runs on port 8080 in Docker)

**ML/Computer Vision:**
- Ultralytics YOLOv8 - License plate detection (version 8.3.20)
- OpenCV (opencv-python) - Image processing, video stream capture and processing
- PyTorch - Deep learning runtime (version 2.8.0, CPU variant)
  - TorchVision (version 0.23.0) - Vision utilities
- CRNN OCR Model - Character recognition for license plates (`anpr/models/ocr_crnn/`)

**Testing:**
- pytest (9.0.2+) - Unit and integration testing

**Build/Dev:**
- Docker - Containerization
- nginx 1.27-alpine - Reverse proxy and static file serving

## Key Dependencies

**Critical (core functionality):**
- `ultralytics` 8.3.20 - YOLOv8 for ANPR detection
- `opencv-python` - Video capture, frame processing
- `torch` 2.8.0 - Deep learning inference (CPU)
- `torchvision` 0.23.0 - Vision model utilities
- `fastapi` - Web framework
- `uvicorn` - ASGI server

**Database:**
- `psycopg` with binary extras - PostgreSQL adapter for Python
- `psycopg_pool` - Connection pooling for PostgreSQL (min_size=2, max_size=10)

**Security:**
- `bcrypt` - Password hashing
- `PyJWT` - JWT token encoding/decoding

**System:**
- `python-multipart` - Multipart form data parsing
- `psutil` - System metrics
- `PyYAML` - YAML parsing for configuration

## Configuration

**Environment:**
- Configured via environment variables:
  - `APP_ENV` - Environment mode (e.g., "docker")
  - `JWT_SECRET_KEY` - JWT signing key (must be 32+ bytes in production)
  - `JWT_EXPIRATION_MINUTES` - Token TTL (default: 480 minutes / 8 hours)
  - `DEBUG` - Debug logging flag
  - `LOG_LEVEL` - Logging level (ALL, DEBUG, INFO, WARNING, ERROR, CRITICAL)
  - `HTTP_PORT` - HTTP server port (default: 8080)
  - `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `OPENBLAS_NUM_THREADS` - Thread limits for PyTorch/OpenCV
  - `POSTGRES_*` - PostgreSQL connection (DB, user, password, DSN)

**Configuration Files:**
- `.env` / `.env.example` - Environment variables (stored in `.env.example` for safe default values)
- There is no settings file. Operational settings live in PostgreSQL (`app_settings`, declared in `config/registry.py`, served by `SettingsService`); personal preferences in `users.preferences`; deployment values (paths, DSN, secrets, device, pool limits) in environment variables read only by `config/env_settings.py`. See `docs/technical/configuration.md`.

**Build Configuration:**
- `Dockerfile` - Multi-stage Docker image definition
- `docker-compose.yml` - Orchestration with PostgreSQL, FastAPI API, retention worker, and Nginx
- `pyproject.toml` - Poetry project manifest with dependencies and build config

## Platform Requirements

**Development:**
- Python 3.13+ (requires 3.13 as minimum)
- Poetry (for package management)
- Docker (optional, for containerized development)
- libglib2.0-0, libgl1, libgomp1 (OpenCV dependencies - handled in Dockerfile)

**Production:**
- Docker container runtime
- PostgreSQL 16 (in docker-compose)
- 2 GB+ RAM (minimum for PyTorch model inference)
- CPU (recommended: multi-core for concurrent channel processing)
- Network access to video sources (RTSP/HTTP streams)

## Project Structure

**Entry Points:**
- `app/api/main.py` - FastAPI application initialization
- `app/worker/main.py` - Retention/lifecycle worker service

**Key Module Organization:**
- `app/api/` - REST API routers and dependencies
- `app/web/` - Static frontend HTML, CSS, JavaScript
- `anpr/` - ANPR detection and recognition modules
- `database/` - PostgreSQL repository pattern implementations
- `runtime/` - Channel processing, event bus, controller automation
- `controllers/` - Hardware controller adapters (relay control)
- `config/` - Settings management and configuration system
- `common/` - Shared utilities (logging, etc.)

---

*Stack analysis: 2026-09-18*
