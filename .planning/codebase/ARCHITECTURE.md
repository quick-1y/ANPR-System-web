---
last_mapped_commit: 9cfd79b3a864f23127a46c35300f838c212d0007
last_mapped_at: 2026-09-24
---
<!-- refreshed: 2026-09-24 -->

# Architecture

**Analysis Date:** 2026-09-24

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                         Frontend (Browser)                              │
│  `app/web/index.html` + ES modules under `app/web/js/app.js`           │
└────────────────────┬────────────────────────────────────────────────────┘
                     │ HTTP/SSE
         ┌───────────┴────────────────┐
         │                            │
┌────────▼──────────────┐    ┌────────▼──────────────┐
│   FastAPI API Server  │    │  Nginx Reverse Proxy  │
│ `app/api/main.py`     │    │  `nginx/default.conf` │
│  (AppContainer)       │    │                       │
└────────┬──────────────┘    └─────────────────────┘
         │                              │
         │ Per-channel                  │ MJPEG/SSE
         │ processing threads           │
         │                              │
┌────────▼──────────────────────────────┐
│  ChannelProcessor Runtime             │
│  `runtime/channel_runtime.py`         │
│  - Per-channel ChannelContext          │
│  - Threading RLock protection          │
│  - RTSP capture + motion detection     │
│  - YOLO object detection               │
│  - CRNN OCR recognition                │
│  - Event publishing                    │
└────────┬───────────────────────────────┘
         │
         │ Events via EventBus
         │ + Controller automation
         │
┌────────▼──────────────────────────────┐
│  PostgreSQL Database                   │
│  `database/postgres/schema.sql`        │
│  - Events, channels, users             │
│  - Settings (app_settings)             │
│  - Lists, clients, controllers         │
└─────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| AppContainer | Dependency injection, lifecycle, channel state | `app/api/container.py` |
| ChannelProcessor | Multi-threaded per-channel processing orchestration | `runtime/channel_runtime.py` |
| ChannelContext | Per-channel state, metrics, stop signal, preview | `runtime/channel_runtime.py` |
| ANPRPipeline | YOLO detection → ROI → CRNN OCR chain | `anpr/pipeline/anpr_pipeline.py` |
| TrackAggregator | OCR consensus, budget tracking per track | `anpr/pipeline/anpr_pipeline.py` |
| PlatePostProcessor | Country-specific plate validation/formatting | `anpr/postprocessing/validator.py` |
| EventBus | In-memory pub/sub for SSE broadcast | `runtime/event_bus.py` |
| SettingsService | Settings read/write via `app_settings` table | `config/settings_service.py` |
| PostgresEventDatabase | Event CRUD, psycopg_pool + connection pooling | `database/postgres_event_repository.py` |
| ControllerAutomationService | Event → controller relay dispatch logic | `controllers/service.py` |
| RetentionScheduler | Cleanup policy polling, lifecycle management | `app/worker/main.py` |

## Pattern Overview

**Overall:** Layered monolith with multi-threaded channel isolation

**Key Characteristics:**

- Two FastAPI services: API server + retention worker (separate processes)
- Dependency injection via container pattern (`AppContainer`, `WorkerContainer`)
- Per-channel video processing runs in dedicated daemon threads, isolated by `ChannelContext`
- Thread-safe state management with `threading.RLock` (ChannelProcessor._lock, ChannelContext.stop_event)
- Shared singleton ML recognizers (YOLO detector, CRNN OCR) to save memory
- In-memory event bus with SSE streaming for real-time plate updates
- PostgreSQL as the only persistent backend; no file-based settings, no SQLite fallback
- Nginx reverse proxy for SSL termination, request routing, SSE/MJPEG support

## Layers

**Presentation (Browser/SSE):**

- Purpose: Real-time plate updates, channel monitoring, configuration UI
- Location: `app/web/` (HTML + ES modules)
- Contains: SVG icons, CSS themes, JS modules with imports from state/api/ui
- Depends on: REST API + EventSource (SSE) from FastAPI
- Used by: End operators/administrators

**API Gateway (FastAPI + Nginx):**

- Purpose: HTTP request routing, authentication, SSE streaming, MJPEG proxy
- Location: `app/api/main.py` (FastAPI), `nginx/default.conf`
- Contains: Route handlers in `app/api/routers/`, Pydantic schemas, auth utilities, DI setup
- Depends on: PostgreSQL, ChannelProcessor (via AppContainer)
- Used by: Frontend, external integrations, webhooks

**Application/Domain Logic:**

- Purpose: ANPR pipeline, track aggregation, plate validation, event persistence, automation
- Location: `anpr/pipeline/`, `app/api/routers/`, `config/`, `controllers/`
- Contains: ANPRPipeline, TrackAggregator, PlatePostProcessor, SettingsService, ControllerAutomationService
- Depends on: ANPR models, country configs, database repositories
- Used by: ChannelProcessor, API handlers, retention worker

**Channel Runtime (Threading):**

- Purpose: Orchestrate per-channel video processing with isolation and metrics
- Location: `runtime/channel_runtime.py`
- Contains: ChannelProcessor, ChannelContext, ChannelMetrics, ReconnectConfig
- Depends on: ANPRPipeline, EventBus, PostgreSQL (events, lists), ControllerAutomationService
- Used by: AppContainer.startup(), AppContainer.sync_channel_runtime()

**Persistence (PostgreSQL):**

- Purpose: Events, channels, users, settings, lists, clients, zones, controllers
- Location: `database/`, `database/postgres/schema.sql`
- Contains: Repository classes (PostgresEventDatabase, ListDatabase, ChannelDatabase, etc.) with psycopg_pool
- Depends on: PostgreSQL 16 driver (psycopg[binary])
- Used by: All layers (API, runtime, worker)

**Retention Worker (Scheduled Cleanup):**

- Purpose: Automated data lifecycle management (screenshots, events)
- Location: `app/worker/main.py`
- Contains: WorkerContainer, RetentionScheduler, DataLifecycleService
- Depends on: SettingsService (policy from `app_settings`), PostgreSQL
- Used by: Cron/Docker-scheduled process (separate from API server)

## Data Flow

### Primary Request Path: Video Capture → Event Persistence → SSE Broadcast

1. **ChannelProcessor._run_channel() thread** (`runtime/channel_runtime.py:_run_channel()`)
   - Opens RTSP source via OpenCV
   - Reads frames in a loop, handling reconnect
   
2. **Motion Detection** (`anpr/detection/motion_detector.py`)
   - Detects foreground motion if enabled; skips frame if no motion
   
3. **YOLO Detection** (`anpr/detection/yolo_detector.py`)
   - Runs YOLO detector on frame
   - Extracts license plate bounding boxes (ROI)
   
4. **ROI Filtering** (`anpr/pipeline/anpr_pipeline.py`)
   - Filters detections by ROI bounds (user-defined region or plate size)
   
5. **CRNN OCR Recognition** (`anpr/recognition/crnn_recognizer.py`)
   - Preprocesses plate image (`anpr/preprocessing/plate_preprocessor.py`)
   - Runs CRNN OCR recognizer; returns (text, confidence)
   
6. **Track Aggregation** (`anpr/pipeline/anpr_pipeline.py:TrackAggregator`)
   - Groups OCR results per track ID
   - Achieves consensus with quorum or returns best candidate when budget exhausted
   - Updates `_track_states` (OCR attempt count, consecutive failures)
   
7. **Plate Validation** (`anpr/postprocessing/validator.py:PlatePostProcessor`)
   - Loads country-specific regex config from `anpr/countries/*.yaml`
   - Validates plate format (RU/UA/BY/KZ patterns)
   - Normalizes format (uppercase, spacing)
   
8. **Event Creation & Persistence**
   - ChannelProcessor publishes event to PostgreSQL via `events_db.write()`
   - Event captured: plate, confidence, timestamp, screenshot path, track ID, zone info
   
9. **Event Broadcasting** (`runtime/event_bus.py`)
   - ChannelProcessor calls `event_callback()` (AppContainer.publish_event_sync)
   - publish_event_sync() schedules async task: EventBus.publish() to all SSE subscribers
   
10. **SSE Streaming** (`app/api/routers/events.py` via `/api/events/stream`)
    - Browser SSE client receives event in real-time
    - Frontend (`app/web/js/events.js`) renders plate in event feed
    
11. **Controller Automation** (optional)
    - ControllerAutomationService.dispatch_event() checks if event matches automation rules
    - Sends HTTP request to controller relay (gate, barrier)

### Settings and Configuration Flow

1. **Environment Load** (`config/env_settings.py`)
   - Reads `.env` file (secrets, DSN, model paths, thread limits)
   - Only place the environment is read
   
2. **Settings Registry** (`config/registry.py`)
   - Declares all operational settings: class (D/A/C/L), type, bounds, default
   - ENUMS for domains (COUNTRIES, DETECTION_MODES, etc.)
   
3. **Settings Schema** (`config/settings_schema.py`)
   - Code defaults for every setting (channel_defaults, logging_defaults, etc.)
   - Value normalizers (no version migrations — project policy)
   
4. **SettingsService** (`config/settings_service.py`)
   - Reads/writes `app_settings` JSON table in PostgreSQL
   - Caches settings in memory
   - Called by: AppContainer, routers, ChannelProcessor
   
5. **API Settings Endpoint** (`app/api/routers/settings.py`)
   - GET /api/settings/schema → registry enums + timezone list
   - GET /api/settings/{section} → SettingsService.get_section()
   - PUT /api/settings/{section} → SettingsService.update_section()
   - Triggers AppContainer.restart_processor_for_settings() if needed

### Personal UI State (Browser Only)

- **Theme, style, grid layout, sidebar pin, debug panel, channel metrics**
- Stored in: Browser `localStorage` (`app/web/js/appearance.js`, `app/web/js/device-prefs.js`)
- No server persistence, no `users.preferences` table
- Synced per-device, not per-account

**State Management:**

- Channel context: `Dict[int, ChannelContext]` protected by `threading.RLock()` in ChannelProcessor
- Event backlog: `asyncio.Queue(maxsize=512)` per SSE subscriber (dropped if full)
- Settings cache: In-memory dict in SettingsService, reloaded on DB read
- Logging config: Applied per-service on startup, re-read on settings change

## Key Abstractions

**ChannelContext:**

- Purpose: Encapsulates per-channel state (thread, stop signal, metrics, preview frame)
- Examples: `runtime/channel_runtime.py:ChannelContext`
- Pattern: Dataclass with default_factory fields for thread-safe access

**TrackAggregator:**

- Purpose: Manages OCR budget and consensus per video track
- Examples: `anpr/pipeline/anpr_pipeline.py:TrackAggregator`
- Pattern: Maintains state dicts by track_id; emits consensus or best-effort when finalizing

**PlatePostProcessor:**

- Purpose: Country-specific validation and normalization
- Examples: `anpr/postprocessing/validator.py:PlatePostProcessor`
- Pattern: Loads YAML config, applies regex/format rules

**SettingsService:**

- Purpose: Single interface for all settings read/write
- Examples: `config/settings_service.py:SettingsService`
- Pattern: Wraps AppSettingsRepository; manages cache lifecycle

**ControllerAutomationService:**

- Purpose: Rules-based dispatch of events to physical relays
- Examples: `controllers/service.py:ControllerAutomationService`
- Pattern: Checks event against lists/rules; sends HTTP to controller

## Entry Points

**API Server:**

- Location: `app/api/main.py`
- Triggers: Docker run, or `uvicorn app.api.main:app --host 0.0.0.0 --port 8000`
- Responsibilities: 
  - Build AppContainer (DI, channel processor, DB connections)
  - Mount static web UI (`app/web/`)
  - Start ChannelProcessor threads for enabled channels
  - Register FastAPI routers (auth, events, channels, settings, etc.)
  - Handle shutdown: stop threads, close DB pools

**Retention Worker:**

- Location: `app/worker/main.py`
- Triggers: Docker run (separate service in docker-compose.yml)
- Responsibilities:
  - Build WorkerContainer (SettingsService, DataLifecycleService, RetentionScheduler)
  - Poll settings.cleanup_interval_minutes every POLICY_POLL_SECONDS
  - Run retention cycle: delete old events/screenshots per policy

**Frontend Entry:**

- Location: `app/web/index.html` → `app/web/js/app.js`
- Triggers: Browser GET /web/
- Responsibilities:
  - Initialize authentication (login form or token from localStorage)
  - Load settings schema, channels, users, lists, zones
  - Render UI tabs (obs/events/journal/lists/clients/controllers/settings)
  - Open EventSource (SSE) for real-time plate events
  - Handle user actions: create/edit/delete, run retention, import/export

## Architectural Constraints

- **Threading:** Daemon threads per channel (1 thread per enabled video stream); ChannelProcessor._lock protects _contexts dict; no async video I/O (cv2.VideoCapture is blocking)
- **Global state:** ChannelProcessor._contexts (Dict[int, ChannelContext]) is the single source of truth for channel runtime state; AppContainer.processor is the singleton instance
- **Circular imports:** Avoid importing `controllers/` in `config/` (existing coupling is tech debt per AGENTS.md; do not add more)
- **Model sharing:** YOLO detector and CRNN recognizer are singletons, created once in `anpr/pipeline/factory.py` and shared across all channels to save GPU/CPU memory
- **Database:** Two separate psycopg_pool.ConnectionPool instances (min=2, max=10): one for events, one for lists; no dual-write, no fallback storage
- **Settings loading:** SettingsService reads from `app_settings` JSON table on first access; defaults from `config/settings_schema.py` if table is empty; no file-based settings
- **Authorization (currently UNDECIDED — redesign pending):** Current state: `tab:*` permissions are navigation visibility only; no endpoint-level enforcement except `tab:settings` on 18 endpoints; phase 11 of roadmap will redesign this; do not treat current model as target

## Anti-Patterns

### Synchronous Channel Startup (Long Block)

**What happens:** AppContainer.startup() calls processor.ensure_channel() + processor.start() in a loop; if RTSP connect hangs, the entire API startup blocks.
**Why it's wrong:** Causes slow deployment, blocks subsequent routes, no timeout protection.
**Do this instead:** Refactor startup to spawn channel threads asynchronously; add per-channel connect timeouts in _open_capture().

### Missing Reconnect Cache Invalidation

**What happens:** ChannelProcessor.get_reconnect_config() caches for 30 seconds; if admin changes reconnect.signal_loss.enabled, channels don't respect it until 30s pass.
**Why it's wrong:** Settings changes should take effect immediately for critical settings.
**Do this instead:** Invalidate cache on every PUT /api/settings; restart_processor_for_settings() already does this for some settings, extend to reconnect.

### Broad Exception Catch in Database Layer

**What happens:** `database/postgres_event_repository.py` catches `StorageUnavailableError` broadly; does not distinguish between connection pool exhaustion vs. query timeout vs. schema error.
**Why it's wrong:** Hides root cause; makes debugging production issues harder.
**Do this instead:** Catch specific psycopg3 exceptions; re-wrap only connection/transport errors as StorageUnavailableError.

## Error Handling

**Strategy:** HTTP 503 Service Unavailable for DB errors; HTTP 422 Validation Error for bad input; HTTP 401 Unauthorized for auth failures.

**Patterns:**

- `StorageUnavailableError` propagates from repositories; caught in routers, re-raised as HTTP 503
- Validation errors in Pydantic schemas raise ValueError; FastAPI converts to HTTP 422
- Authentication failures in `get_current_user()` raise HTTP 401
- Channel not found in runtime: HTTP 404 (channel exists but not running, or never existed)
- Invalid settings update: HTTP 400 (constraint violation, e.g. max > min) or HTTP 422 (schema mismatch)

## Cross-Cutting Concerns

**Logging:** Python `logging` module via `common/logging.py`; `get_logger(__name__)` at module level; Russian messages for business logic in `anpr/`, English for tests; `%s`/`%d` lazy formatting (never f-strings in log calls); channel context prefix (`Канал {name} (id={id})`) in pipeline logs.

**Validation:** Pydantic schemas in `app/api/schemas.py` for request/response; country regex validation in PlatePostProcessor; ROI bounds clamping in ChannelProcessor; settings type/bound checking in registry.

**Authentication:** JWT in Authorization header; token issued by `app/api/auth_utils.py:issue_token()` (HS256, signed with JWT_SECRET_KEY); verified by `get_current_user()` dependency; superadmin is a technical account read fresh from SUPERADMIN_PASSWORD env var on every login (`app/api/superadmin.py`).

---

*Architecture analysis: 2026-09-24*
