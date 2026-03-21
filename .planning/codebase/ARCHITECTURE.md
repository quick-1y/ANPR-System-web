# Architecture

**Analysis Date:** 2026-03-21

## Pattern Overview

**Overall:** Layered Architecture with Multi-Process Pipeline
- Web API layer (FastAPI) → Application Services → Core ANPR Processing → ML Model Inference
- Asynchronous event-driven communication between API and processing threads
- Stateless HTTP endpoints backed by persistent storage (PostgreSQL) and runtime state
- Separation of concerns: API server, video processing worker, data retention worker

**Key Characteristics:**
- Event-driven: Processing pipeline emits events via callback to EventBus
- Container-based dependency injection: `AppContainer` manages service lifecycle and initialization
- Thread-safe channel processor: Each video stream runs in isolated thread with synchronized access
- Modular ANPR stages: Detection → Preprocessing → Recognition → Postprocessing → Storage
- Configuration-driven: All behavior controlled via YAML settings with normalization and migrations

## Layers

**Presentation Layer (API):**
- Purpose: HTTP endpoints for system control, configuration, monitoring, and event retrieval
- Location: `app/api/routers/` (channels, events, controllers, lists, settings, debug, data, system)
- Contains: FastAPI route handlers, request/response schemas, dependency injection setup
- Depends on: AppContainer, SettingsManager, PostgreSQL database, EventBus
- Used by: Web clients, external control systems

**Application Service Layer:**
- Purpose: Business logic orchestration, settings management, controller automation, data lifecycle
- Location: `app/shared/`, `config/`, `controllers/service.py`
- Contains: `SettingsManager`, `DataLifecycleService`, `ControllerAutomationService`, configuration normalization
- Depends on: Database, logging, settings schema validation
- Used by: API handlers, container initialization

**Runtime Processing Layer:**
- Purpose: Manages multi-threaded video processing channels, frame capture, stream reconnection
- Location: `runtime/channel_runtime.py`, `runtime/event_sink.py`, `runtime/debug.py`
- Contains: `ChannelProcessor` (channel orchestration), `ChannelContext` (per-channel state), reconnection logic, debug/metrics collection
- Depends on: OpenCV (video capture), ChannelMetrics, ANPR model config, event callbacks
- Used by: AppContainer startup, request handlers needing channel state

**ANPR Core Processing Pipeline:**
- Purpose: End-to-end plate detection, recognition, and validation for single video frame
- Location: `anpr/pipeline/anpr_pipeline.py`
- Contains: `ANPRPipeline` (main orchestrator), `TrackAggregator` (consensus across frames), `TrackDirectionEstimator` (motion analysis), preprocessing/postprocessing delegation
- Depends on: YOLO detector, CRNN recognizer, PlatePreprocessor, PlatePostProcessor
- Used by: ChannelProcessor frame processing loop

**ML Model Layer:**
- Purpose: Neural network inference for plate detection and character recognition
- Location: `anpr/detection/yolo_detector.py`, `anpr/recognition/crnn_recognizer.py`, `anpr/recognition/crnn.py`
- Contains: YOLO model wrapper with tracking fallback, CRNN encoder-decoder for OCR, model weight loading
- Depends on: PyTorch, ONNX, Ultralytics YOLO
- Used by: ANPRPipeline, factory pattern for model instantiation

**Data Processing Pipeline:**
- Purpose: Plate image preprocessing and postprocessing with format validation
- Location: `anpr/preprocessing/plate_preprocessor.py`, `anpr/postprocessing/validator.py`, `anpr/postprocessing/country_config.py`
- Contains: Image normalization, character extraction, country-specific plate validation rules
- Depends on: OpenCV, NumPy
- Used by: ANPRPipeline frame processing

**Storage & Database Layer:**
- Purpose: Event persistence, configuration storage, plate list management
- Location: `database/postgres_event_repository.py`, `database/plate_lists_repository.py`, `config/settings_repository.py`
- Contains: PostgreSQL connection management, SQL schema bootstrapping, query execution
- Depends on: psycopg3 driver, threading locks for thread-safe schema init
- Used by: API handlers, EventSink, DataLifecycleService

**Configuration Management:**
- Purpose: Application settings loading, validation, normalization, and schema evolution
- Location: `config/settings_manager.py`, `config/settings_normalizer.py`, `config/settings_schema.py`, `config/settings_repository.py`
- Contains: Hierarchical config merging, defaults application, migrations runner, YAML file I/O
- Depends on: YAML parser
- Used by: All services during initialization

## Data Flow

**Video Frame Processing Pipeline (per frame in ChannelProcessor):**

1. `ChannelProcessor._run_channel()` captures frame from `cv2.VideoCapture`
2. Frame validation: size check, timestamp tracking, empty frame detection
3. `ChannelProcessor._process_frame()` calls YOLO detection with optional motion-based skipping
4. Motion detection (`MotionDetector`) evaluates if significant change from prior frame
5. `ANPRPipeline.process_frame()` invoked with frame + detection bboxes
6. For each detection:
   - Plate region extracted and cropped
   - `PlatePreprocessor.preprocess()` normalizes image (resize, normalize, contrast)
   - `CRNNRecognizer.recognize_batch()` performs character-level OCR on all plates
   - `TrackAggregator.add_result()` accumulates results across frames for same track_id
   - `TrackDirectionEstimator.update()` estimates approaching/receding based on bbox motion
   - `PlatePostProcessor.process()` validates against country-specific formats
   - Cooldown check prevents duplicate events for same plate
7. Detections enriched with text, confidence, direction, format, country fields
8. `EventSink.insert_event()` saves to PostgreSQL
9. Screenshot saved if enabled
10. Event callback fires: `AppContainer.publish_event_sync()` routes to EventBus and ControllerAutomationService

**HTTP Request Handling Flow:**

1. FastAPI route handler in `app/api/routers/` receives request
2. Container injected via `Depends(get_container)`
3. Handler queries `container.settings.get_X()` for configuration state
4. Handler queries `container.processor.list_states()` for runtime channel metrics
5. Database queries via `container.events_db` or `container.lists_db`
6. Settings mutations: validated in handler, passed to `settings.update_X()`, container restarts affected services
7. JSON response returned to client

**State Management:**

- **Runtime State:** Per-channel metrics, frame buffers, track history stored in `ChannelContext` within `ChannelProcessor._contexts` dict
- **Persistent State:** Settings in YAML file (disk), events in PostgreSQL
- **In-Memory Caches:** TrackAggregator deques per track_id, direction estimator history, plate cooldown dict
- **Lifecycle:**
  - Startup: Container builds all services, ChannelProcessor starts enabled channels (spawns threads)
  - Shutdown: All channel threads stopped, database connections closed
  - Configuration change: Settings file updated, container rebuilds processor, channels restarted

## Key Abstractions

**ANPRPipeline:**
- Purpose: Encapsulates entire detection→recognition→validation flow for frame
- Examples: `anpr/pipeline/anpr_pipeline.py` line 209
- Pattern: Factory pattern instantiation in `anpr/pipeline/factory.py`, Protocol-based recognizer injection for testing

**TrackAggregator:**
- Purpose: Consensus mechanism across frames for same vehicle to emit stable, non-duplicate plate reads
- Examples: `anpr/pipeline/anpr_pipeline.py` line 25
- Pattern: Sliding window with deque, weighted voting, quorum threshold, per-track state dictionary

**TrackDirectionEstimator:**
- Purpose: Estimates vehicle approach vs. recession based on bbox center movement and area change
- Examples: `anpr/pipeline/anpr_pipeline.py` line 88
- Pattern: Configurable smoothing windows, vote aggregation, stale history eviction

**ChannelProcessor:**
- Purpose: Manages lifecycle of single video capture stream thread, reconnection, frame buffering
- Examples: `runtime/channel_runtime.py` line 67
- Pattern: Thread-per-channel with RLock for settings sync, ReconnectConfig for timeout/retry behavior

**AppContainer / WorkerContainer:**
- Purpose: Service locator and dependency injection, one-time initialization of all services
- Examples: `app/api/container.py` line 26, `app/worker/main.py` line 48
- Pattern: Dataclass-based factory with `.build()` class method, lazy initialization of processor

**SettingsManager:**
- Purpose: Single source of truth for application configuration, handles loading, validation, persistence
- Examples: `config/settings_manager.py` line 39
- Pattern: Delegates to SettingsRepository for I/O, SettingsNormalizer for validation, defaults application

**EventSink:**
- Purpose: Asynchronous bridge from video processing threads to PostgreSQL database
- Examples: `runtime/event_sink.py` line 8
- Pattern: Queue-based, lazy schema bootstrap, row → dict serialization

## Entry Points

**API Server:**
- Location: `app/api/main.py`
- Triggers: `uvicorn app.api.main:app` or Docker entrypoint
- Responsibilities: Initialize FastAPI app, register middlewares (CORS, APIKey), mount static web assets, include routers, startup/shutdown container

**Retention Worker:**
- Location: `app/worker/main.py`
- Triggers: Separate service for background data lifecycle operations
- Responsibilities: Initialize WorkerContainer, start RetentionScheduler, periodic cleanup of old events/screenshots per policy

**Channel Processing Threads:**
- Location: `runtime/channel_runtime.py` ChannelProcessor.start()
- Triggers: API call to `/api/channels/{id}/start` or container startup with enabled channels
- Responsibilities: Continuous video capture loop, frame validation, motion detection, ANPR pipeline invocation, event emission

## Error Handling

**Strategy:** Hierarchical try-catch with fallback mechanisms, never crash processing thread

**Patterns:**

- **Video Capture Errors:**
  - `ChannelProcessor._run_channel()` catches frame read exceptions
  - Logs error, increments error_count metric, updates last_error field
  - Re-attempts capture up to reconnect retry interval

- **Model Inference Errors:**
  - YOLO fallback: CUDA operation failures trigger CPU fallback in `YOLODetector._maybe_handle_cuda_op_error()`
  - Recognizer: If batch recognition fails, detection marked as "Нечитаемо" (unreadable)
  - Confidence threshold: Low-confidence results filtered at ANPRPipeline stage

- **Database Errors:**
  - Wrapped in `StorageUnavailableError` at `PostgresEventDatabase`
  - HTTP handlers catch and return 503 Service Unavailable via `AppContainer.storage_503()`
  - EventSink retries on transient errors, skips event on persistent failure

- **Settings Validation Errors:**
  - SettingsNormalizer catches invalid configs, applies defaults
  - HTTPException 422 for global hotkey conflicts in `AppContainer.validate_global_hotkeys()`
  - HTTPException 400 for missing controller references

## Cross-Cutting Concerns

**Logging:**
- Framework: Python `logging` module with custom handlers
- Implementation: `common/logging.py` — LiveDebugHandler for real-time log streaming, ServiceNameFilter adds service context, HourlyFileHandler for file rotation
- Usage: Every module imports `get_logger(__name__)`, logs at appropriate level (debug for detailed flow, warning for recoverable issues, error for failures)

**Validation:**
- Settings: SettingsNormalizer applies schemas, defaults, coercion
- Requests: Pydantic models in `app/api/schemas.py` auto-validate before handler execution
- Plates: PlatePostProcessor validates against country-specific rules (format, character sets)

**Authentication:**
- Middleware: `APIKeyMiddleware` in `app/api/auth.py` checks `API_KEY` env var if set
- Pattern: Reads header `Authorization: Bearer <token>`, responds 401 if mismatch

**Metrics & Observability:**
- `ChannelMetrics` tracked per channel: fps, latency_ms, frame counts, last_error
- `DebugRegistry` collects timing stats per stage: detection, preprocessing, recognition, postprocessing
- Accessible via `/api/debug/` endpoints for real-time introspection

**Thread Safety:**
- `ChannelProcessor._lock` (RLock) protects `_contexts` dictionary
- Individual `ChannelContext.stop_event` signals graceful channel shutdown
- Settings updates use `SettingsRepository._file_lock` to prevent concurrent write

---

*Architecture analysis: 2026-03-21*
