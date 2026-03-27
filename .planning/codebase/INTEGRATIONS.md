# External Integrations

**Analysis Date:** 2026-03-25

## APIs & External Services

**RTSP Camera Streams:**
- Consumed via OpenCV `cv2.VideoCapture()` for live video feeds
- Configured per-channel in `config/settings.yaml` (channel source URLs)
- Authentication: Credentials embedded in RTSP URL (e.g., `rtsp://admin:pass@camera-ip:554/stream`)
- Reconnection policies defined in `config/settings_schema.py` (`reconnect_defaults()`):
  - Signal loss: enabled by default, 5s frame timeout, 5s retry interval
  - Periodic: disabled by default, 60min interval

**Hardware Controllers (HTTP relay devices):**
- DTWONDER2CH adapter: `controllers/adapters/dtwonder2ch.py` (`Dtwonder2ChAdapter`)
  - Communicates via HTTP GET to relay CGI endpoint
  - URL pattern: `http://{address}/relay_cgi.cgi?type={}&relay={}&on={}&time={}&pwd={}`
  - Supports 2 relays per controller (index 0 and 1)
  - Relay modes: `pulse` (type=1, time=1) and `pulse_timer` (type=2, configurable time)
  - Auth: per-device password sent as `pwd` query parameter
  - Base class: `controllers/base.py` (`ControllerAdapter`)
- Adapter system is pluggable via `controllers/adapters/` directory

**SSE (Server-Sent Events):**
- `/api/events/stream` - Live ANPR event stream to web clients
- `/api/debug/logs/stream` - Live log stream to web clients
- Nginx configured with `proxy_buffering off`, `proxy_cache off`, 1h `proxy_read_timeout` for SSE paths

**MJPEG / Snapshot Streaming:**
- `/api/channels/{id}/preview.mjpg` - Live camera preview (MJPEG)
- `/api/channels/{id}/snapshot.jpg` - Single frame capture

## Data Storage

**PostgreSQL 16:**
- Connection: `POSTGRES_DSN` env var (default: `postgresql://anpr:anpr@postgres:5432/anpr`)
- Driver: `psycopg[binary]` (psycopg3 with C extensions)
- Connection pooling: `psycopg_pool.ConnectionPool`
  - Pool config: `min_size=2, max_size=10, open=True`
  - `database/postgres_event_repository.py` (`PostgresEventDatabase._get_pool()`) - lazy init, one pool per instance
  - `database/plate_lists_repository.py` (`ListDatabase._get_pool()`) - lazy init, one pool per instance
  - Two separate pools per process (events + plate lists)
- Schema bootstrap:
  - Events: `database/postgres/schema.sql` applied via `_ensure_schema()` on first access, validated at startup (`_SCHEMA_SQL_PATH.is_file()`)
  - Plate lists: inline DDL in `database/plate_lists_repository.py` (`CREATE TABLE IF NOT EXISTS`)
- Docker init: `schema.sql` also mounted to `/docker-entrypoint-initdb.d/01-schema.sql` for fresh databases

**Tables:**
- `events` - ANPR detection events (id, timestamp, channel_id, channel, plate, plate_display, country, confidence, source, frame_path, plate_path, direction)
- `plate_lists` - Named lists with types (`white`, `info`, `black`)
- `plate_list_entries` - Individual plate entries linked to lists (with unique constraint on `list_id, plate_normalized`)

**File Storage (local filesystem via Docker volumes):**
- Screenshots: `data/screenshots/` (Docker volume `media_data` mounted at `/app/data`)
- Exports: `data/exports/` (same volume)
- Logs: `logs/` (Docker volume `logs_data` mounted at `/app/logs`)
- Hourly log rotation: `common/logging.py` (`HourlyFileHandler`) with naming pattern `{service}_{YYYY-MM-DD_HH-00}.log`

**Caching:**
- None (no Redis or external cache)
- In-memory `EventBus` for live pub/sub (`runtime/event_bus.py`) - asyncio queue-based, max 512 per subscriber
- In-memory `DebugLogBus` for live log streaming (`runtime/debug.py`, capacity=2000)

## Authentication & Identity

**API Key Middleware (`app/api/auth.py`):**
- Class: `APIKeyMiddleware` (extends `BaseHTTPMiddleware`)
- Enabled only when `API_KEY` env var is non-empty (`app/api/main.py` lines 39-41)
- Timing-safe comparison: `secrets.compare_digest()` (resistant to timing attacks)
- Key delivery methods (checked in order):
  1. `X-Api-Key` header (preferred)
  2. `Authorization: Bearer <key>` header
  3. `?api_key=<key>` query parameter (for SSE/MJPEG streams that cannot send headers)
- Exempt paths: `/api/health` (Docker healthcheck), all non-`/api/` paths
- Streaming paths accepting query param: `/api/events/stream`, `/api/debug/logs/stream`, `/api/channels/`

**No user management** - single shared API key model for trusted LAN deployments.

## Monitoring & Observability

**Health Checks (Docker Compose):**

| Service | Endpoint | Interval | Timeout | Retries | Probe |
|---------|----------|----------|---------|---------|-------|
| postgres | - | 5s | 5s | 12 | `pg_isready -U anpr -d anpr` |
| api | `/api/health` | 10s | 5s | 6 | Python `urllib.request.urlopen` with 3s timeout |
| retention_worker | `/worker/health` | 15s | 5s | 6 | Python `urllib.request.urlopen` with 3s timeout |
| nginx | `/` | 10s | 5s | 6 | `wget -q -O /dev/null` |

**Logging (`common/logging.py`):**
- Async queue-based: `QueueHandler` + `QueueListener` (avoids blocking application threads)
- Format: `%(asctime)s [%(levelname)s] [%(service)s] %(name)s: %(message)s`
- File handler: `HourlyFileHandler` - rotates log files every hour
- Console handler: `StreamHandler` to stdout
- Live debug handler: `LiveDebugHandler` publishes to `DebugLogBus` for SSE streaming
- Service name filter: auto-tags all log records with service identifier
- Noisy loggers suppressed to WARNING: `matplotlib`, `PIL`, `urllib3`, `httpcore`, `httpx`, `uvicorn.access`, `multipart`
- Log cleanup: background thread runs every 3600s, deletes logs older than `retention_days` (default 30)

**System Metrics:**
- `psutil` for CPU, memory, disk monitoring
- Exposed via `/api/system/` routes (`app/api/routers/system.py`)

**Error Tracking:**
- No external service (no Sentry, DataDog, etc.)
- Custom `StorageUnavailableError` for database connectivity issues (`database/errors.py`)

## CI/CD & Deployment

**Hosting:**
- Self-hosted Docker Compose deployment (no cloud provider)

**CI Pipeline:**
- Not detected - no `.github/workflows/`, `Jenkinsfile`, or `.gitlab-ci.yml`

**Deployment:**
- `docker-compose up --build`
- Config bind-mounted from host: `./config:/app/config`
- All services set `restart: unless-stopped`

**Reverse Proxy (Nginx 1.27-alpine, `nginx/default.conf`):**
- Routes `/worker/` to `retention_worker:8092`
- Routes `/api/events/stream` with SSE config (no buffering, `Connection: ""`, 1h timeout, `X-Accel-Buffering: no`)
- Routes everything else to `api:8080`
- `client_max_body_size 50m`
- External port: `HTTP_PORT` env var (default: `8080`)

## Environment Configuration

**Required env vars:**
- `POSTGRES_DSN` - PostgreSQL connection string (critical for both api and retention_worker)
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` - Used by postgres container initialization

**Optional env vars:**
- `API_KEY` - Empty = no auth (default)
- `APP_ENV` - Environment identifier (default: `docker`)
- `DEBUG` - Debug flag (default: `false`)
- `LOG_LEVEL` - Log verbosity (default: `INFO`)
- `SETTINGS_PATH` - YAML config path (default: `/app/config/settings.yaml`)
- `HTTP_PORT` - External HTTP port (default: `8080`)

**Secrets location:**
- `.env` file in project root (gitignored)
- `.env.example` provides template with safe defaults
- RTSP credentials embedded in stream URLs (plaintext in `config/settings.yaml`)
- Controller passwords in `config/settings.yaml` (relay config sections)

## Webhooks & Callbacks

**Incoming:**
- None detected

**Outgoing:**
- HTTP GET to hardware controllers (relay CGI endpoints) triggered by plate recognition events
- Flow: plate detected -> list check -> adapter builds URL -> HTTP request to controller

## Data Lifecycle

**Retention Worker (`app/worker/main.py`):**
- Separate FastAPI service on port 8092
- `RetentionScheduler` runs async loop based on `cleanup_interval_minutes` (default 30)
- Uses `app/shared/data_lifecycle.py` (`DataLifecycleService`)
- Configurable policies from `config/settings_schema.py` (`storage_defaults()`):
  - `events_retention_days`: 30 (default)
  - `media_retention_days`: 14 (default)
  - `max_screenshots_mb`: 4096 (default)
- Manual trigger: `POST /worker/retention/run`
- Health/status: `GET /worker/health` (returns policy + last run result)

---

*Integration audit: 2026-03-25*
