---
last_mapped_commit: 9cfd79b3a864f23127a46c35300f838c212d0007
last_mapped_at: 2026-09-24
---
# External Integrations

**Analysis Date:** 2026-09-24

## APIs & External Services

**Hardware Controllers:**

- DTWONDER2CH relay gate/barrier controller - Sends HTTP GET commands to control physical relays (gates, barriers, access control)
  - SDK/Client: `urllib.request` (stdlib, no external dependency)
  - Connection: HTTP (or HTTPS) to controller IP address
  - Implementation: `controllers/adapters/dtwonder2ch.py`
  - Command format: `http://{address}/relay_cgi.cgi?type=1&relay={index}&on={0|1}&time=1&pwd={password}`
  - Adapter pattern allows adding new controller types via `controllers/registry.py`
  - Service: `ControllerService` sends commands via background threads with 2-second timeout and 10-second error cooldown
  - Auth: Per-controller password (stored in PostgreSQL `controllers.password`)
  - Address: Per-controller HTTP/HTTPS URL (stored in PostgreSQL `controllers.address`)

**RTSP Video Capture:**

- Network RTSP cameras - Live video stream sources for lane/zone monitoring
  - SDK/Client: OpenCV (`cv2.VideoCapture()`)
  - Source URL: RTSP URL with optional embedded credentials stored in PostgreSQL `channels.source`
  - Connection: Direct TCP/RTSP to camera network
  - Implementation: `runtime/channel_runtime.py` (per-channel capture loop)
  - Frame rate: Configurable per-channel (motion detection frame stride, preview FPS limit)

## Data Storage

**Databases:**

- PostgreSQL 16 (primary database for all operational data)
  - Connection: `psycopg[binary]` (psycopg3) via DSN from `POSTGRES_DSN` env var
  - Default DSN: `postgresql://anpr:anpr@postgres:5432/anpr`
  - Credentials: Read from environment (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`)
  - Connection pooling: `psycopg_pool.ConnectionPool`
    - Events pool: min=2, max=10 (configurable via `POSTGRES_POOL_MIN`, `POSTGRES_POOL_MAX`)
    - Lists pool: min=2, max=10 (separate instance)
  - Schema: `database/postgres/schema.sql` (bootstraps lazily with `CREATE TABLE IF NOT EXISTS`)
  - Tables:
    - `events` - Plate recognition events with timestamps, channel refs, screenshots, confidence
    - `channels` - Video source configuration (RTSP URL, ROI, detection settings, controller bindings)
    - `controllers` - Hardware controller definitions (address, password, relay config)
    - `lists` - Allowlist/blocklist/watchlist definitions
    - `clients` - Vehicle owner records linked to lists
    - `zones` - Physical zones (parking, access areas)
    - `users` - User accounts with roles and permissions (password hashed with bcrypt)
    - `app_settings` - Operational settings (one row per leaf key)
    - `app_settings_revision` - Settings cache invalidation counter

**File Storage:**

- Local filesystem only (no S3 or cloud storage)
  - Media directory: `/app/data/screenshots` (configurable via `ANPR_MEDIA_DIR` env var, mounted volume)
  - Contents: Screenshot frames and plate crops from events
  - Logs directory: `/app/logs` (configurable via `ANPR_LOGS_DIR` env var, mounted volume)
  - Live logging to rotating files via `common/logging.py` (hourly rotation per `HourlyFileHandler`)

**Caching:**

- None (no Redis, Memcached, or external cache service)
- In-memory only:
  - `SettingsService` maintains local dict cache of `app_settings` (invalidated by polling `app_settings_revision`)
  - `EventBus` - in-memory pub/sub with asyncio queues for live event streaming to SSE clients
  - `ChannelProcessor` - per-channel state and OCR tracker state held in runtime memory

## Authentication & Identity

**Auth Provider:**

- Custom JWT-based authentication (no OAuth, no LDAP, no SAML)
  - JWT signing: HS256 algorithm with `JWT_SECRET_KEY` env var (enforced minimum 32 bytes in production)
  - Token issue: `app/api/auth_utils.py` - `create_access_token(user_id, role, exp_minutes)`
  - Token verify: `app/api/auth_utils.py` - `decode_access_token(token)` returns payload
  - Token TTL: Configurable per login via `auth.token_ttl_minutes` setting (default ~8 hours)
  - Two auth methods:
    1. `Authorization: Bearer {token}` header (standard REST API calls)
    2. `?token={token}` query parameter (SSE and MJPEG streams, where Authorization header not supported)

**User Accounts:**

- PostgreSQL `users` table with login/password
  - Passwords: Hashed with bcrypt via `bcrypt.hashpw()` (rounds configurable in `hash_password()`)
  - Roles: `superadmin`, `admin`, `operator` (stored as text in `users.role`)
  - Permissions: JSONB array of strings (e.g., `["tab:settings", "tab:channels"]`)
  - Password change tracking: `password_changed_at` timestamp

**Technical Superadmin Account:**

- Name: `superadmin` (no row in `users` table; defined entirely by environment)
- Credentials: `SUPERADMIN_PASSWORD` env var (read fresh on every login attempt)
- Enforcement: Fails fast in production (`APP_ENV=production`) if password unset or too weak
- Dev fallback: Password defaults to "1234" if `SUPERADMIN_PASSWORD` blank (logs warning)
- Cannot be edited through UI (technical account only)

## Monitoring & Observability

**Error Tracking:**

- Not configured (no Sentry, DataDog, or external error aggregator)
- Errors logged locally to rotating files via `common/logging.py`

**Logs:**

- Local filesystem logging to `ANPR_LOGS_DIR` (mounted volume)
- Rolling files: Hourly rotation via `HourlyFileHandler`
- Log level: Bootstrap level from `LOG_LEVEL` env var (applied until first read of `logging.level` from `app_settings`)
- Output format: Datetime, level, module, message (implementation in `common/logging.py`)
- Pipeline logs: Russian language with channel context (`Канал {name} (id={id})`)
- Debug logging: `DEBUG` level available; `ALL` (NOTSET) enables full verbose output including third-party debug

**Live Debug Log Streaming:**

- In-memory debug log bus (`runtime/debug.py`, `DebugLogBus`)
- Consumed by `/api/debug/logs/stream` endpoint (SSE streaming to web UI)
- Does not persist to disk; lost on process restart

## CI/CD & Deployment

**Hosting:**

- Self-hosted on-premises (Docker Compose)
- No cloud platform integration (no AWS, GCP, Azure APIs)
- Health checks configured in docker-compose.yml:
  - PostgreSQL: `pg_isready` probe every 5s
  - API: HTTP HEAD to `/api/health` every 10s
  - Worker: HTTP HEAD to `/worker/health` every 15s
  - Nginx: wget to `/` every 10s

**CI Pipeline:**

- Not configured (no GitHub Actions, GitLab CI, or Jenkins)
- No automated testing in production
- Manual testing via `pytest` in local dev environment

**Deployment Artifacts:**

- Docker images built from `Dockerfile` (shared by api + retention_worker services)
- Image base: `python:3.13-slim` (Debian)
- System dependencies installed via apt-get (libglib2.0-0, libgl1, libgomp1, tzdata)
- Model weights: Committed to repo in binary files:
  - `anpr/models/yolo/best.pt` - YOLO detector
  - `anpr/models/ocr_crnn/crnn_ocr_model_int8_fx.pth` - CRNN OCR model
- Deployment checklist: Must verify model files present at startup (`config/env_settings.py`, `verify_model_files()`)

## Environment Configuration

**Required env vars (for startup):**

- `APP_ENV` - `production` or dev (controls secret policy enforcement)
- `JWT_SECRET_KEY` - JWT signing secret (minimum 32 bytes in production)
- `SUPERADMIN_PASSWORD` - Technical superadmin password (required in production)
- `POSTGRES_DSN` - PostgreSQL connection string (default: `postgresql://anpr:anpr@postgres:5432/anpr`)

**Infrastructure env vars:**

- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` - Database credentials (consumed by postgres service, not app)
- `POSTGRES_PORT` - Database port mapping
- `POSTGRES_POOL_MIN`, `POSTGRES_POOL_MAX` - Connection pool bounds

**Inference env vars:**

- `ANPR_DEVICE` - `cpu` or `cuda` (default: `cpu`)
- `ANPR_YOLO_MODEL_PATH` - Path to YOLO model file (default: `anpr/models/yolo/best.pt`)
- `ANPR_OCR_MODEL_PATH` - Path to CRNN OCR model (default: `anpr/models/ocr_crnn/crnn_ocr_model_int8_fx.pth`)
- `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `OPENBLAS_NUM_THREADS` - Thread limits for ML (default: 2 each)

**Storage & Logging:**

- `ANPR_LOGS_DIR` - Log file directory (default: `logs`, mounted as volume in Docker)
- `ANPR_MEDIA_DIR` - Screenshots/exports directory (default: `data/screenshots`, mounted as volume in Docker)
- `ANPR_IO_POOL_WORKERS` - Thread pool size for screenshot I/O (default: 2)

**HTTP Configuration:**

- `CORS_ALLOWED_ORIGINS` - Comma-separated browser CORS allow-list (default: empty, no cross-origin browser access)
- `LOG_LEVEL` - Bootstrap log level before reading from `app_settings` (default: `INFO`)
- `HTTP_PORT` - Nginx external port (default: 8080, mapped from container 80)

**Secrets location:**

- `.env` file (gitignored, never committed)
- Environment variables at container runtime (Docker Compose `env_file` and `environment` sections)
- Per-object credentials in PostgreSQL:
  - RTSP credentials: Embedded in `channels.source` URL string
  - Controller passwords: `controllers.password` column

## Webhooks & Callbacks

**Incoming:**

- None (no webhook endpoints for third-party event pushes)

**Outgoing:**

- Hardware relay controller commands (HTTP GET to controller IP) - Handled by `ControllerService.send_command()`
- No webhooks to external logging, analytics, or notification services

**Event Streaming (Server-Sent Events):**

- Live plate detection events via `/api/events/stream` (SSE protocol, JSON events)
- Authentication: JWT token in query parameter or Authorization header
- Nginx configured with SSE-specific headers (`proxy_buffering off`, `chunked_transfer_encoding on`, `proxy_read_timeout 1h`)
- Client connects, receives `retry: 3000\n\n` then periodic events as they occur
- Events published to subscribers via in-memory `EventBus` (asyncio Queue per subscriber)

---

*Integration audit: 2026-09-24*
