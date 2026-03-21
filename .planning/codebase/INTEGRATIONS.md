# External Integrations

**Analysis Date:** 2026-03-21

## APIs & External Services

**RTSP Camera Streams:**
- Multiple RTSP sources configured per channel in `config/settings.yaml`
- Authentication: Embedded credentials in RTSP URL (e.g., `rtsp://admin:admin@camera-ip:2000/0`)
- Handled by: `cv2.VideoCapture()` (OpenCV)
- Reconnection: Configurable signal loss and periodic reconnect policies in settings

**HTTP Controller API:**
- DTWONDER2CH relay controller via HTTP
  - SDK/Client: urllib.request (Python stdlib)
  - URL pattern: `http://{address}/relay_cgi.cgi?type={}&relay={}&on={}&time={}&pwd={}`
  - Implementation: `controllers/adapters/dtwonder2ch.py` (Dtwonder2ChAdapter)
  - Auth: Per-relay password field

## Data Storage

**Databases:**
- PostgreSQL 16
  - Connection: Environment variable `POSTGRES_DSN` (default: `postgresql://anpr:anpr@postgres:5432/anpr`)
  - Client: psycopg[binary] (psycopg3 with C extensions)
  - Schema: `database/postgres/schema.sql` (auto-initialized on startup)

**File Storage:**
- Local filesystem only (no S3/cloud storage configured)
  - Screenshots: `data/screenshots/` (configurable via settings.yaml `storage.screenshots_dir`)
  - Logs: `data/logs/` (configurable via settings.yaml `storage.logs_dir`)
  - Exports: `data/exports/` (configured in settings.yaml `storage.export_dir`)
  - Media retention: Auto-cleanup enabled with configurable retention (14-30 days)

**Caching:**
- None - No Redis or memcached configured
- In-memory event bus used for runtime event distribution: `runtime/event_bus.py`

## Authentication & Identity

**Auth Provider:**
- Custom static API key (optional)
- Implementation: `app/api/auth.py` (APIKeyMiddleware)
- Methods:
  - Header: `X-Api-Key: <key>`
  - Header: `Authorization: Bearer <key>`
  - Query param: `?api_key=<key>` (for MJPEG/SSE streams)
- Source: Environment variable `API_KEY` (empty = disabled)
- Exempt paths: `/api/health` (required for Docker healthcheck)

**Camera Authentication:**
- RTSP credentials embedded in stream URLs (plaintext in config)
- HTTP controller passwords per relay (stored in settings.yaml)

## Monitoring & Observability

**Error Tracking:**
- Not detected - No Sentry, DataDog, or external error tracking

**Logs:**
- File-based logging to `data/logs/` directory
- Configured via `config/settings.yaml` (`logging` section)
- Levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Retention: Configurable (default 30 days auto-cleanup)
- Live log streaming via `/api/debug/logs/stream` (Server-Sent Events)

**Metrics:**
- In-app channel metrics tracking (via `ChannelMetrics` dataclass)
- Exposed via `/api/channels/{channel_id}/status` endpoints
- Runtime debug registry for performance diagnostics (`runtime/debug.py`)

## CI/CD & Deployment

**Hosting:**
- Docker Compose (development/small deployments)
- No external CI/CD detected (local build via `docker-compose build`)

**Container Orchestration:**
- Docker Compose with 4 services:
  1. `postgres` - PostgreSQL 16
  2. `api` - FastAPI server (port 8080 internal)
  3. `retention_worker` - Async cleanup service (port 8092 internal)
  4. `nginx` - Reverse proxy (port 8080 external, configurable via `HTTP_PORT`)

**Health Checks:**
- postgres: `pg_isready` SQL check
- api: HTTP GET `/api/health` endpoint
- retention_worker: HTTP GET `/worker/health` endpoint
- nginx: wget http://localhost/

## Environment Configuration

**Required env vars:**
- `POSTGRES_DSN` - Database connection string (CRITICAL)
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` - Database credentials (CRITICAL)
- `SETTINGS_PATH` - Path to settings.yaml (default available)
- `API_KEY` - Optional but recommended for security
- `LOG_LEVEL` - Operational configuration (default: INFO)

**Optional env vars:**
- `APP_ENV` - Context identifier (default: docker)
- `DEBUG` - Debug mode flag (default: false)
- `HTTP_PORT` - Nginx external port (default: 8080)

**Secrets location:**
- `.env` file at project root (not committed to git)
- Database password in `POSTGRES_PASSWORD` env var
- API key in `API_KEY` env var
- RTSP credentials in `config/settings.yaml` (embedded in URLs)
- HTTP controller passwords in `config/settings.yaml` (relay section)

## Webhooks & Callbacks

**Incoming:**
- None detected - No incoming webhook endpoints

**Outgoing:**
- None detected - No external webhook delivery configured
- Internal event bus: `runtime/event_bus.py` publishes events to subscribers (in-process only)
- Event publishing: Via `app/api/container.py` AppContainer.publish_event_sync()

## Data Integration Points

**Event Storage Flow:**
1. Detection pipeline processes RTSP frames
2. Events published via internal EventBus
3. Events persisted to PostgreSQL via `database/postgres_event_repository.py`
4. Events queryable via REST API (`/api/events/*`)
5. Auto-cleanup via `app/shared/data_lifecycle.py` (retention policy)

**Plate List Integration:**
- Plate lists stored in PostgreSQL
- Queried during event processing for allow/block logic
- Adapter: `database/plate_lists_repository.py` (ListDatabase class)

**Controller Integration Flow:**
1. Event triggers plate-in-list check
2. Automation service queries matched lists
3. Command generated via adapter (Dtwonder2ChAdapter)
4. HTTP request sent to controller URL
5. Relay activated/deactivated based on detection

---

*Integration audit: 2026-03-21*
