# External Integrations

**Analysis Date:** 2026-09-18

## APIs & External Services

**Hardware Relay Controllers:**
- DTWONDER2CH - HTTP-based relay control system
  - Purpose: Trigger relay actions (gate control, barrier raising, etc.) in response to license plate events
  - Adapter: `controllers/adapters/dtwonder2ch.py` implements command URL building
  - Integration: Controller command URL constructed with relay index, mode, timer, and password
  - Communication: HTTP GET requests via `urllib.request` (`controllers/service.py`)
  - Example: `http://<controller_address>/?type=<mode>&relay=<index>&on=<bool>&time=<timer>&pwd=<password>`

**Video Streams:**
- RTSP/HTTP video stream sources configured per channel
- Purpose: Input for ANPR detection pipeline
- Framework: OpenCV (cv2) captures and processes frame streams
- Integration: `runtime/channel_runtime.py` manages channel stream processing

## Data Storage

**Databases:**
- PostgreSQL 16
  - Provider: Self-hosted (docker-compose includes `postgres:16` service)
  - Connection: Via psycopg (PostgreSQL adapter for Python)
  - Client: psycopg with connection pooling (psycopg_pool)
    - Pool configuration: min_size=2, max_size=10 (shared across all repository classes)
  - Connection: Environment variable `POSTGRES_DSN` (default: `postgresql://anpr:anpr@postgres:5432/anpr`)
  - Credentials: Environment variables `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
  - Schema: Auto-initialized by repository classes on first use
  - Health check: PostgreSQL service health verified before API startup

**Schema/Tables (inferred from repository classes):**
- Events - License plate detection events (`database/postgres_event_repository.py`)
- Channels - Video channel configuration (`database/channel_repository.py`)
- Users - System user accounts (`database/user_repository.py`)
- Controllers - Relay controller definitions (`database/controller_repository.py`)
- Zones - Detection zones for multi-zone triggers (`database/zones_repository.py`)
- Lists - License plate whitelist/blacklist (`database/lists_repository.py`)
- Clients - Client/account management (`database/clients_repository.py`)

**File Storage:**
- Local filesystem
  - Screenshots directory: `ANPR_MEDIA_DIR` (default: `data/screenshots`; a volume mount point, not a UI setting)
  - Logs directory: `logs/` (in docker-compose: `logs_data` volume)
  - Media retention: Automatic cleanup based on retention policies
  - Screenshot retention: Configurable max size and retention days (`storage.max_screenshots_mb`, `storage.media_retention_days`)

**Caching:**
- None detected - No Redis, Memcached, or in-memory cache beyond runtime objects

## Authentication & Identity

**Auth Provider:**
- Custom JWT-based implementation (no external provider)
  - Implementation location: `app/api/auth_utils.py`
  - Token algorithm: HS256 (HMAC-SHA256)
  - Secret key: Environment variable `JWT_SECRET_KEY` (default weak value for dev only)
  - Token fields: `sub` (user_id), `role`, `exp` (expiration), `iat` (issued at)
  - Expiration: Configurable via `JWT_EXPIRATION_MINUTES` (default: 480 minutes)
  - Password hashing: bcrypt with salt (via bcrypt library)

**Auth Flow:**
1. Login endpoint (`app/api/routers/auth.py`): Username + password exchange for JWT
2. Password verification: `verify_password()` checks bcrypt hash
3. Token creation: `create_access_token()` generates signed JWT
4. Token validation: Middleware/dependencies use `decode_access_token()` to validate incoming requests
5. Token transmission: JWT in Authorization header or `?token=<jwt>` query parameter (for SSE/MJPEG streams)

**User Roles:**
- Based on `role` field in JWT payload
- Access control: `require_permission()`, `require_role()` dependency functions in `app/api/deps.py`
- Known roles: "superadmin" (referenced in debug router access control)

## Monitoring & Observability

**Error Tracking:**
- Not detected - No external error tracking (Sentry, etc.)
- Custom exception handling: `StorageUnavailableError` for database connectivity issues
- HTTP exceptions: FastAPI HTTPException for API errors

**Logs:**
- Approach: File-based logging with hourly rotation
- Implementation: `common/logging.py` with custom `HourlyFileHandler`
- Format: Formatted log records with service prefix
- Log files: Hourly files in configured `logs_dir` (default: `logs/`)
- Service prefix: Log files named by service (`api`, `worker`, etc.)
- Log retention: Configurable `logging.retention_days` (default: 30 days)
- Log levels: Configurable via `LOG_LEVEL` environment variable
- Streaming logs: LiveDebugHandler publishes logs to DebugLogBus for real-time UI display
- Channel-specific logging: Logs can be tagged with `channel_id` for filtering

**Metrics/Debug:**
- Debug registry: `runtime/debug.py` - Configurable debug features
- Channel metrics: CPU/memory usage per channel (when `debug.show_channel_metrics` enabled)
- Live log bus: Real-time log streaming to connected clients (capacity: 2000 messages)
- Debug endpoints: `/api/debug/*` routes provide live logs and system diagnostics

## CI/CD & Deployment

**Hosting:**
- Docker containers (self-hosted)
- Orchestration: docker-compose (3 services + PostgreSQL)

**Services:**
1. `api` - Main FastAPI application (port 8080 internal, exposed via Nginx)
   - Health check: HTTP endpoint `/api/health`
   - Startup dependency: PostgreSQL must be healthy
2. `retention_worker` - Data lifecycle/cleanup service (port 8092 internal)
   - Health check: HTTP endpoint `/worker/health`
   - Function: Event retention, screenshot cleanup per policy
3. `nginx` - Reverse proxy and static file server (port 8080 external)
   - Health check: HTTP root endpoint
   - Static serving: Web UI from `app/web/` directory
4. `postgres` - PostgreSQL 16 database
   - Health check: pg_isready command
   - Initialization: SQL schema from `database/postgres/schema.sql`

**CI Pipeline:**
- Not detected - No GitHub Actions, GitLab CI, or other CI configuration found

**Deployment Artifacts:**
- Docker image built from `Dockerfile` (Python 3.13-slim base)
- Docker Compose configuration in `docker-compose.yml`
- Environment configuration: `.env` file (not in repo, use `.env.example`)

## Environment Configuration

**Required env vars:**
- `POSTGRES_DSN` - PostgreSQL connection string (default: `postgresql://anpr:anpr@postgres:5432/anpr`)
- `JWT_SECRET_KEY` - JWT signing key (must be 32+ bytes in production, default weak value)

**Recommended env vars:**
- `JWT_EXPIRATION_MINUTES` - Token expiration time (default: 480)
- `LOG_LEVEL` - Logging level (default: INFO, options: ALL, DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `OMP_NUM_THREADS` - PyTorch/OpenMP thread limit (default: 2, prevents CPU oversubscription)
- `HTTP_PORT` - External HTTP port (default: 8080)
- `APP_ENV` - Environment mode (e.g., "docker")
- `DEBUG` - Debug mode flag (default: false)

**Database env vars:**
- `POSTGRES_DB` - Database name (default: anpr)
- `POSTGRES_USER` - Database user (default: anpr)
- `POSTGRES_PASSWORD` - Database password (default: anpr)
- `POSTGRES_PORT` - Database port (default: 5432, docker-compose only)

**Secrets location:**
- `.env` file (git-ignored, use `.env.example` for template)
- Sensitive values: `JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, database credentials

## Webhooks & Callbacks

**Incoming:**
- Not detected - No webhook endpoints exposed

**Outgoing:**
- Not detected - No external webhooks called
- Event bus: Internal event publishing to `runtime/event_bus.py` (in-process only)
- Controller automation: Events trigger relay control but no external notifications

## Real-time Communication

**SSE (Server-Sent Events):**
- Live event streaming: `/api/events/stream` - Streams detected license plate events
- Live debug logs: `/api/debug/logs/stream` - Streams system logs in real-time
- Implementation: AsyncIO with event loop, StreamingResponse with `text/event-stream` media type
- Access: Requires JWT authentication or `?token=` query parameter

**MJPEG Streaming:**
- Live video preview: `/api/channels/{channel_id}/preview` - MJPEG encoded video stream
- Implementation: OpenCV frame encoding + streaming response
- Access: Requires JWT authentication or `?token=` query parameter
- Purpose: Real-time video display in web UI

## Data Flow Patterns

**Event Processing:**
1. Video stream captured via OpenCV
2. Frame passed to YOLOv8 detector (plate detection)
3. Detected plates passed to CRNN OCR for text recognition
4. Recognition results stored to PostgreSQL events table
5. Event published to event bus
6. Event bus subscribers triggered (UI updates, controller automation, logging)
7. Controller automation evaluates license plate against whitelists/blacklists
8. If match: Relay control command sent to hardware controller (HTTP)

**Screenshot Storage:**
- Captured frames saved to `data/screenshots/` on match
- Automatic cleanup: Retention worker monitors disk usage and age
- Cleanup policy: Based on `storage.media_retention_days` and `storage.max_screenshots_mb`

**Log Archival:**
- Logs written hourly to `logs/` directory
- Automatic cleanup: Retention worker removes logs older than `logging.retention_days`

---

*Integration audit: 2026-09-18*
