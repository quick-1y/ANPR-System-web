# Architecture

**Analysis Date:** 2026-09-18

## Pattern Overview

**Overall:** Layered architecture with real-time video processing, multi-threaded channel management, and REST API orchestration.

**Key Characteristics:**
- Multi-layer design: API → Services → Data Access → Video Processing
- Dependency injection via AppContainer for centralized service management
- Multi-threaded channel processors for concurrent video stream handling
- Event-driven communication between video processing and API layers
- PostgreSQL persistence with connection pooling
- Separation of concerns: ANPR pipeline (detection/recognition) isolated from API logic

## Layers

**API Layer:**
- Purpose: HTTP request handling, user authentication, schema validation
- Location: `app/api/routers/` and `app/api/main.py`
- Contains: FastAPI routers (`auth`, `channels`, `events`, `users`, `controllers`, `lists`, `zones`, `clients`, `settings`, `system`, `debug`, `data`)
- Depends on: AppContainer, authentication, request validation
- Used by: Web UI (`app/web/`), external integrations

**Business Logic Layer:**
- Purpose: Coordinate domain operations, enforce business rules
- Location: `controllers/` (relay automation), `app/shared/` (data lifecycle), runtime services
- Contains: `ControllerService` (relay control), `ControllerAutomationService` (plate-triggered actions), `DataLifecycleService` (retention policies)
- Depends on: Database repositories, ANPR pipeline, event bus
- Used by: API routers, configuration services

**Channel Processing Layer:**
- Purpose: Real-time video capture, frame processing, ANPR pipeline execution
- Location: `runtime/channel_runtime.py`, `anpr/pipeline/`
- Contains: `ChannelProcessor` (thread pool management), `ChannelContext` (per-channel state), `ChannelMetrics` (health tracking)
- Depends on: Video capture (OpenCV), ANPR models, database for results
- Used by: API layer (metrics, preview streams), configuration management

**ANPR Pipeline Layer:**
- Purpose: Convert frames to license plates through detection, recognition, validation
- Location: `anpr/detection/`, `anpr/recognition/`, `anpr/postprocessing/`, `anpr/preprocessing/`
- Contains: Plate detection (YOLOv8), OCR recognition (CRNN), motion detection, post-validation
- Depends on: PyTorch, OpenCV, model files
- Used by: ChannelProcessor

**Data Access Layer:**
- Purpose: PostgreSQL operations with connection pooling and schema management
- Location: `database/`
- Contains: `PooledDatabase` base class, repository classes (`EventDatabase`, `ChannelDatabase`, `UserDatabase`, `ControllerDatabase`, etc.)
- Depends on: psycopg (PostgreSQL driver)
- Used by: Business logic layer, configuration services

**Configuration Layer:**
- Purpose: Settings management, schema validation, defaults
- Location: `config/`
- Contains: `EnvConfig` (environment), the registry, `SettingsService` (`app_settings`), preferences, code defaults
- Depends on: PostgreSQL
- Used by: AppContainer during initialization

## Data Flow

**Video Processing Pipeline:**

1. **Capture Phase** → `ChannelProcessor.start(channel_id)` spawns thread with reconnection logic
2. **Read Phase** → OpenCV `VideoCapture.read()` with timeout/retry handling
3. **Motion Detection** → Optional motion detection to skip frames without activity
4. **Plate Detection** → YOLOv8 model detects plate regions in frame
5. **Track Aggregation** → `TrackAggregator` collects detections across frames
6. **Plate Recognition** → CRNN OCR recognizes text from best shots
7. **Validation** → Post-processor validates format by country/region
8. **Result Emission** → Event callback publishes to EventBus and database
9. **Controller Automation** → If plate matches list, `ControllerAutomationService` triggers relay
10. **Frame Storage** → Screenshot saved to filesystem (if configured)

**API Request Flow:**

1. Request arrives at FastAPI endpoint (e.g., `GET /api/channels`)
2. Authentication: `get_current_user()` dependency extracts JWT from header/query
3. User lookup: JWT sub claims → `UserDatabase.find_by_id()`
4. Container injection: `get_container()` dependency retrieves `AppContainer`
5. Business logic: Router calls service methods on container entities
6. Data access: Repositories execute SQL via shared connection pool
7. Response: Pydantic schema serialization to JSON
8. Error handling: `HTTPException` for API errors, `StorageUnavailableError` for DB failures

**Event Publishing:**

1. ANPR pipeline emits event via `event_callback(dict)` from worker thread
2. `AppContainer.publish_event_sync()` bridges thread-safe event to main event loop
3. `EventBus.publish()` notifies all SSE subscribers
4. `ControllerAutomationService.dispatch_event()` checks automation rules (plate in list → trigger relay)
5. Event stored in PostgreSQL via `EventDatabase`

**State Management:**

- **Channel State**: Per-channel metrics, capture handle, latest JPEG frame in `ChannelContext`
- **Track State**: OCR attempt budget, finalization status per detection track in `TrackAggregator._track_states`
- **User State**: JWT claims include role, permissions; validated per request
- **Configuration State**: environment read once at startup (`EnvConfig`); operational settings cached by `SettingsService` and invalidated by the `app_settings_revision` counter, so API and worker see changes without restart

## Key Abstractions

**AppContainer:**
- Purpose: Dependency injection container and service orchestrator
- Examples: `app/api/container.py` (lines 31-245)
- Pattern: Dataclass with factory method (`build()`) initializing all services at startup; lifespan management with FastAPI
- Usage: Injected into every API route via `get_container()` dependency

**ChannelProcessor:**
- Purpose: Manages concurrent video capture and processing across channels
- Examples: `runtime/channel_runtime.py` (lines 69-100+)
- Pattern: Thread pool executor with per-channel context dictionaries; reconnection logic with exponential backoff
- Usage: Started at app startup, stopped at shutdown; called by API for metrics/preview

**TrackAggregator:**
- Purpose: Accumulates ANPR results for a single plate detection across multiple frames
- Examples: `anpr/pipeline/anpr_pipeline.py` (lines 45-100+)
- Pattern: Consensus voting with OCR budget; emits plate number when quorum reached or budget exhausted
- Usage: One per channel, receives OCR results, tracks finalization state

**Database Repositories:**
- Purpose: Database abstraction with pooled connections
- Examples: `database/channel_repository.py`, `database/postgres_event_repository.py`, `database/user_repository.py`
- Pattern: `PooledDatabase` base class with lazy schema initialization; methods return Dict[str, Any] for flexibility
- Usage: CRUD operations for domain entities (channels, events, users, controllers, zones)

**ChannelMetrics:**
- Purpose: Runtime health snapshot for a channel
- Examples: `runtime/channel_runtime.py` (lines 25-43)
- Pattern: Dataclass with mutable state fields (FPS, latency, error counts)
- Usage: Queried by API for `/api/channels` endpoint; updated by processor threads

## Entry Points

**FastAPI Application:**
- Location: `app/api/main.py`
- Triggers: Server startup (e.g., `uvicorn app.api.main:app`)
- Responsibilities: Configure CORS, mount static files, register routers, manage lifespan

**ChannelProcessor Worker:**
- Location: `runtime/channel_runtime.py`
- Triggers: `AppContainer.startup()` on app launch
- Responsibilities: Spawn per-channel threads, coordinate frame capture/processing

**Configuration Loader:**
- Location: `config/env_settings.py`, `config/settings_service.py`
- Triggers: `AppContainer.build()` during initialization
- Responsibilities: read the environment, fail fast on missing weights or weak secrets, serve operational settings with registry defaults

## Error Handling

**Strategy:** Layered validation with graceful degradation.

**Patterns:**

- **HTTP Exceptions**: API routers raise `HTTPException` for user-facing errors (400 Bad Request, 401 Unauthorized, 403 Forbidden, 404 Not Found, 503 Service Unavailable)
- **Storage Unavailable**: Database failures caught as `StorageUnavailableError`, wrapped in 503 response via `container.storage_503()`
- **Reconnection Logic**: Video capture failures trigger reconnect with configurable backoff (signal-loss timeout, retry interval)
- **Thread Safety**: Database operations protected by connection pool; channel state accessed via `threading.RLock()`
- **Validation**: Pydantic schemas validate on API input; normalizers apply business rules before storage
- **Logging**: All errors logged to configurable level (DEBUG, INFO, WARNING, ERROR, CRITICAL) with context

## Cross-Cutting Concerns

**Logging:** 
- Framework: `common/logging.py` with context injection (service name, channel ID)
- Pattern: bootstrap from `LOG_LEVEL`, then reconfigured from `app_settings` (`config/logging_setup.py`)
- Output: File and stderr with rotation

**Validation:** 
- Pydantic schemas in `app/api/schemas.py` for HTTP payloads
- Normalizers in `config/settings_normalizer.py` for configuration defaults
- Business logic validation in service methods and `AppContainer` helpers (e.g., `validate_global_hotkeys()`)

**Authentication:** 
- JWT tokens issued by `/api/auth/login` endpoint
- Token extraction from Authorization header or query parameter in `get_current_user()`
- User lookup from PostgreSQL on each request
- Role-based access control via `require_role()` and `require_permission()` dependencies

**Metrics & Observability:**
- Channel metrics (FPS, latency, errors) tracked in `ChannelMetrics`
- Debug registry in `runtime/debug.py` for feature flags and debug settings
- Live log bus in `runtime/debug_log_bus.py` for streaming logs to UI
- Event history stored in PostgreSQL (configurable retention)

---

*Architecture analysis: 2026-09-18*
