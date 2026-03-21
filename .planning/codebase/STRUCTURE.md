# Codebase Structure

**Analysis Date:** 2026-03-21

## Directory Layout

```
ANPR-System-v0.8_web/
├── anpr/                   # Core ANPR ML pipeline and processing
│   ├── detection/          # YOLO plate detector wrapper
│   ├── recognition/        # CRNN character recognition models
│   ├── preprocessing/      # Plate image normalization
│   ├── postprocessing/     # Plate validation and format matching
│   ├── pipeline/           # Main ANPRPipeline orchestrator
│   ├── models/             # Model weights directory (binary, large)
│   ├── countries/          # Country-specific plate configs
│   └── model_config.py     # Model initialization and configuration
├── app/                    # Application services and HTTP API
│   ├── api/                # FastAPI application and HTTP handlers
│   │   ├── routers/        # Endpoint implementations by domain
│   │   ├── schemas.py      # Pydantic request/response models
│   │   ├── main.py         # FastAPI app initialization
│   │   ├── container.py    # AppContainer dependency injection
│   │   ├── auth.py         # APIKeyMiddleware
│   │   └── deps.py         # Dependency injection helpers
│   ├── worker/             # Retention scheduler (separate service)
│   ├── shared/             # Shared services (data lifecycle)
│   └── web/                # Static web assets (HTML, CSS, JS, images)
├── runtime/                # Video stream processing and event routing
│   ├── channel_runtime.py  # ChannelProcessor for per-stream threads
│   ├── event_sink.py       # Database event persistence bridge
│   ├── event_bus.py        # In-memory async event publisher
│   └── debug.py            # Performance metrics collection
├── database/               # Data persistence layer
│   ├── postgres/           # PostgreSQL schema and SQL files
│   ├── postgres_event_repository.py  # Event table queries
│   ├── plate_lists_repository.py    # Whitelist/blacklist queries
│   └── errors.py           # StorageUnavailableError
├── config/                 # Configuration management
│   ├── settings_manager.py       # Single source of truth for settings
│   ├── settings_repository.py    # YAML file I/O and locking
│   ├── settings_normalizer.py    # Validation and defaults application
│   ├── settings_schema.py        # Schema definitions and coercion
│   ├── settings_migrations/      # Configuration schema evolution
│   └── settings.yaml       # Application configuration file
├── controllers/            # Hardware relay control abstraction
│   ├── service.py          # Controller and relay management
│   ├── base.py             # ControllerAdapter protocol
│   ├── registry.py         # Adapter registration
│   └── adapters/           # Device-specific implementations
├── common/                 # Shared utilities
│   ├── logging.py          # Logging configuration and handlers
│   └── __init__.py
├── tests/                  # Unit and integration tests
│   ├── test_track_aggregator.py        # Consensus logic tests
│   ├── test_direction_estimator.py     # Motion estimation tests
│   ├── test_plate_validator.py         # Country config tests
│   └── test_motion_detector.py         # Motion detection tests
├── .planning/codebase/     # GSD codebase analysis (generated)
├── nginx/                  # Reverse proxy configuration
├── docker-compose.yml      # Multi-service deployment definition
├── Dockerfile              # Container image definition
├── requirements.txt        # Python package dependencies
├── README.md               # Project documentation
├── AGENTS.md               # AI agent usage guidelines
└── config/settings.yaml    # Runtime configuration (gitignored)
```

## Directory Purposes

**anpr/**
- Purpose: Core ANPR processing — models, algorithms, and data transformation
- Contains: ML model wrappers, preprocessing/postprocessing, detection/recognition pipeline
- Key files: `pipeline/anpr_pipeline.py` (main orchestrator), `model_config.py` (model initialization), `detection/yolo_detector.py`, `recognition/crnn_recognizer.py`
- Note: `models/` subdirectory contains binary weight files (~500MB+), not source code

**app/api/**
- Purpose: HTTP REST API for system control and monitoring
- Contains: FastAPI routes, request validation schemas, dependency injection
- Key files: `main.py` (app initialization), `container.py` (service initialization), `routers/` (endpoint implementations)
- Routers:
  - `channels.py` — video stream lifecycle, snapshot, preview stream
  - `events.py` — plate event retrieval and filtering
  - `controllers.py` — relay trigger and test endpoints
  - `lists.py` — whitelist/blacklist management
  - `settings.py` — configuration CRUD and apply
  - `debug.py` — performance metrics and timing data
  - `data.py` — export bundle creation
  - `system.py` — health status and version info

**app/worker/**
- Purpose: Background data lifecycle management (retention, cleanup)
- Contains: RetentionScheduler, WorkerContainer
- Note: Runs as separate service (`app.worker.main`)

**runtime/**
- Purpose: Multi-threaded video processing orchestration and event emission
- Contains: ChannelProcessor (per-stream threads), EventSink (async DB bridge), debug metrics
- Key files: `channel_runtime.py` (main processor), `event_sink.py` (database persistence), `debug.py` (performance tracking)
- Threading model: One thread per active video stream, main API thread manages them via RLock-protected dict

**database/**
- Purpose: Data persistence and query abstraction
- Contains: PostgreSQL connection management, schema bootstrapping, query execution
- Key files: `postgres_event_repository.py` (event CRUD), `plate_lists_repository.py` (list management), `postgres/schema.sql` (table definitions)
- Note: Lazy schema init on first write — no migrations runner needed at startup

**config/**
- Purpose: Application configuration lifecycle (load, validate, persist, migrate)
- Contains: SettingsManager (orchestrator), SettingsRepository (file I/O), SettingsNormalizer (validation), SettingsSchema (defaults)
- Key files: `settings_manager.py` (API entry point), `settings_normalizer.py` (validation rules), `settings_schema.py` (defaults and coercion)
- Settings flow: YAML file → SettingsRepository.load() → SettingsNormalizer.normalize() → SettingsManager

**controllers/**
- Purpose: Hardware relay control abstraction and automation
- Contains: ControllerService (lifecycle), ControllerAutomationService (rule-based triggering), adapter registry
- Key files: `service.py` (orchestration), `base.py` (ControllerAdapter protocol), `adapters/dtwonder2ch.py` (example device)
- Pattern: Device-specific adapters inherit from ControllerAdapter, register in registry

**common/**
- Purpose: Shared utilities and cross-cutting concerns
- Contains: Logging configuration, log streaming handlers
- Key file: `logging.py` (LiveDebugHandler for real-time logs, HourlyFileHandler for rotation)

**tests/**
- Purpose: Unit and integration test coverage
- Contains: Test suite for core algorithms and services
- Key tests:
  - `test_track_aggregator.py` — consensus voting and deduplication logic
  - `test_direction_estimator.py` — motion direction estimation
  - `test_plate_validator.py` — country-specific format validation
  - `test_motion_detector.py` — frame difference detection
- Framework: pytest, no mocking framework in use (mostly integration tests)

## Key File Locations

**Entry Points:**
- `app/api/main.py` — FastAPI application startup, router registration, middleware setup
- `app/worker/main.py` — Retention worker service initialization
- `runtime/channel_runtime.py` — ChannelProcessor thread spawn and management

**Configuration:**
- `config/settings.yaml` — Application config file (YAML, includes all channels, controllers, models, storage, logging)
- `config/settings_manager.py` — Programmatic config access API
- `config/settings_schema.py` — Schema definitions and default values

**Core Logic:**
- `anpr/pipeline/anpr_pipeline.py` — ANPRPipeline, TrackAggregator, TrackDirectionEstimator
- `runtime/channel_runtime.py` — ChannelProcessor frame processing loop
- `database/postgres_event_repository.py` — Event persistence

**Testing:**
- `tests/test_*.py` — pytest suite

## Naming Conventions

**Files:**
- Modules: `snake_case.py` (e.g., `plate_preprocessor.py`, `event_sink.py`)
- Test files: `test_<module>.py` (e.g., `test_track_aggregator.py`)
- Config files: `settings_*.py` (e.g., `settings_manager.py`, `settings_schema.py`)
- Adapters: `<device_model>_adapter.py` (e.g., `dtwonder2ch.py`)

**Directories:**
- Functionality groups: `snake_case/` (e.g., `api/routers/`, `anpr/preprocessing/`)
- Feature domains: descriptive plural or singular (e.g., `controllers/`, `database/`)

**Classes:**
- Service classes: `<Domain>Service` (e.g., `ControllerService`, `DataLifecycleService`)
- Container/factories: `<Domain>Container` (e.g., `AppContainer`)
- Data containers: `<Domain>Config`, `<Domain>Metrics` (e.g., `ChannelMetrics`, `ReconnectConfig`)
- Processors/managers: `<Domain><Task>` (e.g., `ANPRPipeline`, `PlatePreprocessor`, `PlatePostProcessor`)

**Functions/Methods:**
- Private: `_method_name()` (name mangling with underscore prefix)
- Public: `method_name()`
- Constants: `CONSTANT_NAME`
- Configuration getters: `get_<type>()` (e.g., `get_channels()`, `get_logger()`)
- Configuration setters: `update_<type>()` (e.g., `update_channel()`)

**Variables:**
- Temporary: `temp_`, `i`, `j` (in loops)
- State: full descriptive names (e.g., `last_emitted`, `track_texts`)
- Configuration: `<domain>_settings` (e.g., `plate_settings`, `reconnect_settings`)

## Where to Add New Code

**New Feature (e.g., new detection mode):**
- Primary code: `anpr/detection/` for model wrapper, integrate into `anpr/pipeline/anpr_pipeline.py`
- Tests: `tests/test_<feature>.py` using pytest
- Configuration: Add settings to `config/settings_schema.py` defaults, reference in `AnprModelConfig`

**New Component/Module (e.g., new service):**
- Implementation: Create file in relevant package (e.g., `app/shared/my_service.py`)
- Registration: Add to `AppContainer.build()` in `app/api/container.py`
- Tests: `tests/test_my_service.py`
- Documentation: Add docstring following Russian+English convention in codebase

**New API Endpoint:**
- Implementation: Create router function in appropriate file in `app/api/routers/` or new router file
- Schemas: Add request/response models to `app/api/schemas.py`
- Registration: `app.include_router()` in `app/api/main.py`
- Test: Add to `tests/` with container fixture setup

**Utilities:**
- Shared helpers: `common/<domain>.py` (e.g., `common/helpers.py`)
- Domain-specific utilities: Within domain package (e.g., `anpr/utils.py`)

**Configuration Settings:**
- New setting: Add to `config/settings_schema.py` in appropriate default dict
- Normalization: Add logic to `SettingsNormalizer.normalize_with_meta()` if validation required
- Access: Via `settings.get_<type>()` in SettingsManager

## Special Directories

**anpr/models/**
- Purpose: Model weight files storage (binary, large files)
- Generated: Yes (downloaded/extracted during setup)
- Committed: No (git-ignored, .gitignore excludes *.weights, *.pt, *.onnx)
- Size: ~500MB-2GB typical for YOLO + CRNN models

**data/screenshots/**
- Purpose: Event frame and plate image storage (local filesystem)
- Generated: Yes (created during video processing)
- Committed: No (git-ignored)
- Cleanup: Managed by DataLifecycleService based on retention policy

ormation**.planning/codebase/**
- Purpose: GSD codebase mapping output (generated by /gsd:map-codebase)
- Generated: Yes (auto-created during analysis)
- Committed: No (typically, unless explicitly committed)
- Contents: ARCHITECTURE.md, STRUCTURE.md, CONVENTIONS.md, TESTING.md, CONCERNS.md

**.pytest_cache/**
- Purpose: pytest test result cache
- Generated: Yes (pytest creates on first run)
- Committed: No (git-ignored)

**.idea/**
- Purpose: JetBrains IDE (PyCharm) project settings
- Generated: Yes (auto-created by IDE)
- Committed: No (git-ignored)

**config/settings_migrations/**
- Purpose: Settings schema evolution scripts
- Generated: No
- Committed: Yes (source code)
- Pattern: Runners apply migrations to normalize old config format to new schema

---

*Structure analysis: 2026-03-21*
