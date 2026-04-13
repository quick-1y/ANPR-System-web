# Architecture

**Analysis Date:** 2026-03-25

## Pattern Overview

**Overall:** Layered monolith with multi-threaded channel processing

**Key Characteristics:**
- Two FastAPI services: main API server and retention worker
- Per-channel video processing threads managed by `ChannelProcessor`
- In-memory event bus for real-time SSE streaming to frontend
- PostgreSQL-only storage via `psycopg_pool` connection pooling
- JSON file-based settings with migration and normalization pipeline
- Container pattern (`AppContainer`, `WorkerContainer`) for dependency wiring
- Shared singleton OCR recognizer across all channel threads (thread-safe lazy init)

## Layers

**Presentation (API):**
- Purpose: HTTP REST API, SSE streaming, static web UI serving
- Location: `app/api/`
- Contains: FastAPI app, routers, Pydantic-like schemas, auth middleware, dependency injection
- Entry: `app/api/main.py` -- FastAPI app with lifespan context manager
- Routers (all under `app/api/routers/`):
  - `system.py`: `GET /`, `GET /api/health`, `GET /api/system/resources`, `GET /api/storage/status`
  - `channels.py`: `GET|POST /api/channels`, `GET|PUT|DELETE /api/channels/{id}`, `GET /api/channels/{id}/snapshot.jpg`, `GET /api/channels/{id}/preview.mjpg`, `POST /api/channels/{id}/start|stop|restart`, `PUT /api/channels/{id}/config`, `PUT /api/channels/{id}/ocr`, `PUT /api/channels/{id}/filter`, `GET /api/channels/{id}/health`, `GET /api/channels/{id}/preview/status`, `GET /api/channels/last-plates`
  - `events.py`: `GET /api/events`, `GET /api/events/item/{id}`, `GET /api/events/item/{id}/media/{kind}`, `GET /api/events/stream` (SSE)
  - `controllers.py`: `GET|POST /api/controllers`, `PUT|DELETE /api/controllers/{id}`, `POST /api/controllers/{id}/test`
  - `clients.py`: `GET /api/clients`, `POST /api/clients`, `GET /api/clients/search`, `GET|PUT|DELETE /api/clients/{id}`, `POST|DELETE /api/clients/{id}/attach`
  - `lists.py`: `GET|POST /api/lists`, `DELETE|PUT /api/lists/{id}`, `GET /api/lists/{id}/clients`, `GET /api/lists/entry-by-plate`, `GET /api/lists/plates`
  - `settings.py`: `GET|PUT /api/settings`
  - `data.py`: `GET|PUT /api/data/policy`, `POST /api/data/retention/run`, `GET /api/data/export/events.csv`, `POST /api/data/export/bundle`
  - `debug.py`: `GET|PUT /api/debug/settings`, `GET /api/debug/channels`, `GET /api/debug/state`, `GET /api/debug/logs`, `GET /api/debug/logs/stream` (SSE)
- Auth: `app/api/auth.py` -- `APIKeyMiddleware` activated when `API_KEY` env var is set; constant-time comparison via `hmac.compare_digest`
- Deps: `app/api/deps.py` -- `get_container()` extracts `AppContainer` from `request.app.state`

**Application Services (Container):**
- Purpose: Dependency wiring, lifecycle management, cross-layer coordination
- Location: `app/api/container.py` (API), `app/worker/main.py` (worker)
- `AppContainer` (dataclass): holds `SettingsManager`, `PostgresEventDatabase`, `ListDatabase`, `ClientDatabase`, `ControllerService`, `ControllerAutomationService`, `EventBus`, `DebugRegistry`, `DebugLogBus`, `ChannelProcessor`, `DataLifecycleService`
- `WorkerContainer` (dataclass): holds `SettingsManager`, `DataLifecycleService`, `RetentionScheduler`
- `AppContainer.build()`: constructs all services, wires callbacks
- `AppContainer.startup()`: starts all enabled channels via `processor.ensure_channel()` + `processor.start()`
- `AppContainer.publish_event_sync()`: bridges thread-based channel events to async `EventBus` via `loop.call_soon_threadsafe` + dispatches to `ControllerAutomationService`

**Runtime Processing:**
- Purpose: Per-channel video capture, frame processing loop, reconnection logic
- Location: `runtime/channel_runtime.py`
- `ChannelProcessor`: manages `Dict[int, ChannelContext]` with `threading.RLock`
- Each channel runs in a daemon thread (`_run_channel`)
- `ChannelContext` (dataclass): holds channel config, thread ref, stop event, metrics, latest JPEG preview
- `ChannelMetrics` (dataclass): tracks state, reconnect/timeout/error counts, FPS, latency, processed frames, motion stats
- `ReconnectConfig` (frozen dataclass): signal loss and periodic reconnect parameters with 30s cache TTL
- ROI filtering: polygon-based detection filtering via `cv2.pointPolygonTest`
- Motion detection: optional `MotionDetector` gating per channel
- Frame stride: configurable `detector_frame_stride` to skip frames

**ANPR Core (Pipeline):**
- Purpose: Plate detection, OCR recognition, track aggregation, direction estimation
- Location: `anpr/pipeline/`
- `ANPRPipeline` (`anpr/pipeline/anpr_pipeline.py`): main orchestrator
  - Accepts `channel_id` and `channel_name` params for per-channel logging context
  - Constructs `_channel_label` as `"Канал {name} (id={id})"`
  - Owns `TrackAggregator`, `PlatePreprocessor`, `TrackDirectionEstimator`, `PlatePostProcessor`
  - `process_frame(frame, detections)`: batch OCR, aggregation, post-processing, cooldown
- `TrackAggregator`: per-track OCR budget management
  - Accepts `channel_label` param for contextual logging
  - Exposes `last_result_type`: `"consensus"`, `"budget_best"`, `"budget_none"`, `""`
  - Quorum-based consensus: weighted majority across `best_shots` attempts
  - Budget exhaustion: finalizes with best candidate or marks unreadable
  - Track eviction: TTL-based stale track cleanup
- `TrackDirectionEstimator`: APPROACHING/RECEDING estimation from bbox history
- `build_components()` (`anpr/pipeline/factory.py`): factory function creating `(ANPRPipeline, YOLODetector)` tuple
  - Accepts `channel_id` and `channel_name` params, passes to `ANPRPipeline`
  - Shared singleton `CRNNRecognizer` via `_get_shared_recognizer()` with thread-safe double-checked locking

**ML Models:**
- Purpose: YOLO plate detection, CRNN OCR recognition
- Location: `anpr/detection/`, `anpr/recognition/`, `anpr/models/`
- `YOLODetector` (`anpr/detection/yolo_detector.py`): plate detection with tracking, size filtering, bbox padding
- `MotionDetector` (`anpr/detection/motion_detector.py`): frame differencing for motion gating
- `CRNNRecognizer` (`anpr/recognition/crnn_recognizer.py`): batch OCR with quantized model
- `PlatePreprocessor` (`anpr/preprocessing/plate_preprocessor.py`): plate image preprocessing before OCR
- Model files: `anpr/models/yolo/best.pt`, `anpr/models/ocr_crnn/crnn_ocr_model_int8_fx.pth`

**Data Processing (Postprocessing):**
- Purpose: Plate validation, country detection, format matching
- Location: `anpr/postprocessing/`
- `PlatePostProcessor` (`anpr/postprocessing/validator.py`): validates plates against country-specific regex patterns
- `CountryConfigLoader` (`anpr/postprocessing/country_config.py`): loads YAML configs from `anpr/countries/`
- Country configs: `anpr/countries/` (YAML files with plate format patterns per country)

**Storage:**
- Purpose: Event persistence, plate list management, schema bootstrap
- Location: `database/`
- `PostgresEventDatabase` (`database/postgres_event_repository.py`): PostgreSQL event CRUD with lazy schema bootstrap from `database/postgres/schema.sql`; uses `psycopg_pool` connection pooling
- `ListDatabase` (`database/lists_repository.py`): list CRUD + plate-matching helpers (`plate_in_list_type`, `plate_in_lists`, `find_client_by_plate`) for channel automation and event enrichment
- `ClientDatabase` (`database/clients_repository.py`): client CRUD, search, attach/detach to lists; schema owned by `ListDatabase`
- `EventSink` (`runtime/event_sink.py`): thin write-only wrapper around `PostgresEventDatabase` used by channel threads
- `StorageUnavailableError` (`database/errors.py`): custom exception for DB connectivity issues
- Schema: `database/postgres/schema.sql` -- verified at startup

**Configuration:**
- Purpose: Settings management with schema, normalization, migrations, persistence
- Location: `config/`
- `SettingsManager` (`config/settings_manager.py`): thread-safe settings access with file lock; get/save methods for each settings section
- `SettingsNormalizer` (`config/settings_normalizer.py`): fills defaults, validates types, normalizes hotkeys, upgrades ROI regions
- Settings schema (`config/settings_schema.py`): all default value functions, `build_default_settings()`
- Settings migrations (`config/settings_migrations/`): versioned migration runner
- Settings repository (`config/settings_repository.py`): JSON file I/O with file locking
- `POSTGRES_DSN` always read from `POSTGRES_DSN` env var (not from settings file)

**Controllers:**
- Purpose: Physical barrier/gate controller automation
- Location: `controllers/`
- `ControllerService` (`controllers/service.py`): sends HTTP commands to physical controllers
- `ControllerAutomationService` (`controllers/service.py`): dispatches ANPR events to controllers based on channel-controller bindings and plate list matching
- `ControllerAdapter` (`controllers/base.py`): abstract adapter protocol
- Adapters: `controllers/adapters/dtwonder2ch.py` (DTWONDER2CH 2-relay controller)
- Registry: `controllers/registry.py` maps type strings to adapter classes

## Data Flow

**Video Frame Processing Pipeline:**

1. `ChannelProcessor._run_channel()` opens `cv2.VideoCapture` for channel source URL
2. Frame read loop with reconnection logic (signal loss timeout, periodic reconnect)
3. Optional `MotionDetector` gating -- skips frames when no motion detected
4. Optional frame stride -- processes every Nth frame for detector
5. `YOLODetector.track(frame)` returns detections with bboxes and track IDs
6. ROI polygon filtering -- drops detections outside configured region
7. `ANPRPipeline.process_frame(frame, detections)`:
   a. `TrackDirectionEstimator.update()` estimates APPROACHING/RECEDING per track
   b. `TrackAggregator.should_process()` checks if track still has OCR budget
   c. `PlatePreprocessor.preprocess()` prepares plate crops
   d. `CRNNRecognizer.recognize_batch()` performs batch OCR
   e. `TrackAggregator.add_result()` accumulates results, checks consensus/budget
   f. `PlatePostProcessor.process()` validates against country patterns
   g. Cooldown check prevents duplicate emissions
8. Channel thread saves frame/plate JPEGs to `data/screenshots/{date}/channel_{id}/`
9. `EventSink.insert_event()` persists to PostgreSQL
10. `AppContainer.publish_event_sync()` bridges to async `EventBus` + `ControllerAutomationService`
11. `EventBus.publish()` pushes to SSE subscriber queues

**HTTP Request Handling:**

1. Request hits FastAPI with optional `APIKeyMiddleware` check
2. Router handler calls `get_container(request)` to get `AppContainer`
3. Handler accesses services through container (events_db, lists_db, processor, settings, etc.)
4. `StorageUnavailableError` caught and returned as HTTP 503

**State Management:**
- Settings: JSON file with in-memory cache, thread-safe via `_file_lock`
- Channel state: `Dict[int, ChannelContext]` protected by `threading.RLock` in `ChannelProcessor`
- Event streaming: `EventBus` with `asyncio.Queue` per SSE subscriber (maxsize=512, drops oldest on overflow)
- Debug state: `DebugRegistry` with per-channel overlay data and stage timings, TTL-based cleanup

## Key Abstractions

**AppContainer:**
- Purpose: Wires all API-side dependencies, manages lifecycle
- Location: `app/api/container.py`
- Pattern: Dataclass with `build()` classmethod factory

**ChannelProcessor:**
- Purpose: Manages per-channel processing threads
- Location: `runtime/channel_runtime.py`
- Pattern: Thread pool manager with start/stop/restart per channel

**ANPRPipeline:**
- Purpose: Orchestrates detection -> OCR -> aggregation -> validation
- Location: `anpr/pipeline/anpr_pipeline.py`
- Pattern: Pipeline with injected recognizer, aggregator, postprocessor
- Note: Receives `channel_id` and `channel_name` for per-channel log context

**TrackAggregator:**
- Purpose: Per-track OCR consensus with budget management
- Location: `anpr/pipeline/anpr_pipeline.py`
- Pattern: Stateful accumulator with quorum voting
- Note: Receives `channel_label` for contextual logging; exposes `last_result_type`

**SettingsManager:**
- Purpose: Thread-safe settings access with normalization and persistence
- Location: `config/settings_manager.py`
- Pattern: Repository + normalizer + schema defaults

**EventBus:**
- Purpose: In-memory async pub/sub for live event streaming
- Location: `runtime/event_bus.py`
- Pattern: Observer with bounded async queues

**EventSink:**
- Purpose: Write-only PostgreSQL event persistence for channel threads
- Location: `runtime/event_sink.py`
- Pattern: Thin wrapper delegating to `PostgresEventDatabase`

**DebugRegistry:**
- Purpose: Real-time debug overlay state (bboxes, OCR text, timings) per channel
- Location: `runtime/debug.py`
- Pattern: Thread-safe registry with TTL-based state cleanup

**DebugLogBus:**
- Purpose: Live log streaming from any thread to async SSE subscribers
- Location: `runtime/debug.py`
- Pattern: Thread-safe ring buffer with cross-thread pub/sub via `loop.call_soon_threadsafe`

## Entry Points

**API Server:**
- Location: `app/api/main.py`
- Run: `uvicorn app.api.main:app`
- Triggers: HTTP requests, lifespan startup/shutdown
- Responsibilities: REST API, SSE streaming, static web UI, channel lifecycle management

**Retention Worker:**
- Location: `app/worker/main.py`
- Run: `uvicorn app.worker.main:app`
- Triggers: Scheduled timer loop, manual HTTP trigger
- Responsibilities: Event/media retention cleanup, CSV/ZIP export

**Channel Threads:**
- Location: `runtime/channel_runtime.py` (`ChannelProcessor._run_channel`)
- Triggers: `AppContainer.startup()` or API channel start/restart
- Responsibilities: Video capture, ANPR processing, event generation

## Error Handling

**Strategy:** Exception catching with logging; graceful degradation for storage failures

**Patterns:**
- `StorageUnavailableError` raised by database layer, caught by API handlers and returned as HTTP 503
- `AppContainer.storage_503()` helper converts exceptions to `HTTPException(503)`
- Channel thread: broad `except Exception` in `_run_channel` sets metrics to error state, logs full traceback, stops thread gracefully
- Reconnection: automatic retry on frame read failure or signal loss timeout with configurable intervals
- OCR init failure: `_FallbackRecognizer` returns empty results until real recognizer is ready
- Settings normalization: missing keys filled with defaults, invalid values corrected silently
- Controller errors: bounded error state dict (max 100 entries) in `ControllerService`

## Cross-Cutting Concerns

**Logging:**
- Module: `common/logging.py`
- Levels: ALL (maps to NOTSET), DEBUG, INFO, WARNING, ERROR, CRITICAL
- ALL mode: logs every OCR attempt with candidate text and confidence per track per channel
- INFO mode: logs only consensus/budget-exhaustion results and validation outcomes
- `LiveDebugHandler`: forwards all log records to `DebugLogBus` for SSE streaming to debug panel
- `HourlyFileHandler`: rotates log files by hour with service prefix (`api_2026-03-25_14-00.log`)
- `ServiceNameFilter`: injects service name into every log record
- Async-safe: uses `QueueHandler` + `QueueListener` to avoid blocking channel threads
- Log cleanup: background thread removes logs older than `retention_days` every hour
- Noisy third-party loggers (matplotlib, urllib3, etc.) forced to WARNING level

**Validation:**
- Settings normalization on every read (fill missing defaults, correct invalid types)
- Plate validation via country-specific regex patterns in `PlatePostProcessor`
- Controller type validation against `SUPPORTED_CONTROLLER_TYPES` registry
- Hotkey uniqueness validation across all controllers (`validate_global_hotkeys`)
- Channel-controller binding validation (`validate_channel_controller_binding`)

**Authentication:**
- `APIKeyMiddleware` in `app/api/auth.py`
- Activated only when `API_KEY` env var is non-empty
- Constant-time comparison via `hmac.compare_digest` to prevent timing attacks
- Skips auth for static `/web` paths

**Thread Safety:**
- `ChannelProcessor`: `threading.RLock` protects `_contexts` dict
- `DebugRegistry`: `threading.RLock` protects channel states and settings
- `SettingsManager`: `_file_lock` protects settings read/write
- `EventBus`: `asyncio.Lock` protects subscriber list
- `DebugLogBus`: `threading.Lock` protects buffer and subscriber list
- Cross-thread event delivery: `loop.call_soon_threadsafe(asyncio.create_task, ...)` in `publish_event_sync`
- OCR singleton: double-checked locking with `threading.RLock` + `threading.Event` in factory

---

*Architecture analysis: 2026-03-25*
