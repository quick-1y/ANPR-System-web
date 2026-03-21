# Technology Stack

**Analysis Date:** 2026-03-21

## Languages

**Primary:**
- Python 3.13 - Core application runtime for ANPR system, API server, and background workers

**Secondary:**
- YAML - Configuration management (`config/settings.yaml`)
- SQL - PostgreSQL database schema (`database/postgres/schema.sql`)

## Runtime

**Environment:**
- Python 3.13-slim (containerized via Docker)
- pip package manager with PyPI + PyTorch index configuration

**Package Manager:**
- pip (PyPI)
- Lockfile: requirements.txt (pinned version specifiers)
- Special indexes: PyTorch CPU wheels from `https://download.pytorch.org/whl/cpu`

## Frameworks

**Core:**
- FastAPI 0.115.0+ - REST API framework for HTTP endpoints and middleware
- Uvicorn - ASGI server for running FastAPI applications
- Starlette - Underlying web framework (via FastAPI)

**ML/Computer Vision:**
- ultralytics 8.3.20 - YOLO v8 object detection for license plate localization
- PyTorch 2.8.0 - Deep learning framework (CPU variant)
- torchvision 0.23.0 - Computer vision utilities (plate preprocessing, model loading)
- OpenCV (opencv-python) - Image processing, frame capture from RTSP streams, JPEG encoding

**Build/Dev:**
- Docker - Container orchestration for local and production deployment
- Docker Compose - Multi-container orchestration (postgres, api, retention_worker, nginx)

## Key Dependencies

**Critical:**
- ultralytics 8.3.20 - YOLO detection engine for plate localization
- pytorch 2.8.0 - Deep learning inference for YOLO and CRNN models
- psycopg[binary] - PostgreSQL adapter (binary psycopg3)
- opencv-python - Video frame capture and image manipulation
- PyYAML - Configuration file parsing
- psutil - Process monitoring (memory, CPU usage tracking)
- fastapi - API request handling, routing, middleware
- uvicorn - Server execution

**Infrastructure:**
- nginx 1.27-alpine - Reverse proxy, static file serving, load balancing
- PostgreSQL 16 - Events, plate lists, and metadata storage
- python:3.13-slim - Base container image with minimal dependencies

## Configuration

**Environment:**
- `.env` file (app-level configuration, see `.env.example`)
- `config/settings.yaml` - Model paths, RTSP sources, detection thresholds, logging levels

**Key Environment Variables:**
- `POSTGRES_DSN` - Database connection string (default: `postgresql://anpr:anpr@postgres:5432/anpr`)
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` - Database credentials
- `API_KEY` - Optional static API key for `/api/*` endpoints (empty disables auth)
- `SETTINGS_PATH` - Path to settings.yaml (default: `/app/config/settings.yaml`)
- `LOG_LEVEL` - Logging verbosity (default: `INFO`)
- `APP_ENV` - Environment context (e.g., `docker`)
- `DEBUG` - Debug flag (boolean, default: `false`)
- `HTTP_PORT` - Nginx port (default: `8080`)

**Build:**
- `Dockerfile` - Multi-stage Python 3.13 image with PyTorch CPU wheels
- `docker-compose.yml` - Full stack orchestration with 4 services

## Platform Requirements

**Development:**
- Docker & Docker Compose installed
- Python 3.13 (for local development without containers)
- RTSP camera sources with credentials in config
- PostgreSQL 16 access (or use docker-compose postgres service)

**Production:**
- Docker runtime environment
- Persistent volumes for: database (`pgdata`), media (`media_data`), logs (`logs_data`)
- Network access to RTSP camera sources
- Minimum CPU/memory: 2+ CPU cores, 2GB+ RAM (depends on number of concurrent channels)

**Deployment Target:**
- Docker Compose stack (development/small deployments)
- Kubernetes ready (multi-container design, health checks on all services)

---

*Stack analysis: 2026-03-21*
