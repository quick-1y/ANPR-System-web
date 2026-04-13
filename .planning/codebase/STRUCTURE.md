# Codebase Structure

**Analysis Date:** 2026-03-25

## Directory Layout

```
ANPR-System-v0.8_web/
├── anpr/                       # ANPR core: detection, recognition, pipeline
│   ├── countries/              # Country plate format YAML configs
│   ├── detection/              # YOLO detector, motion detector
│   ├── models/                 # ML model weights
│   │   ├── ocr_crnn/           # CRNN OCR quantized model (.pth)
│   │   └── yolo/               # YOLOv8 plate detector (.pt)
│   ├── pipeline/               # ANPRPipeline, TrackAggregator, factory
│   ├── postprocessing/         # Plate validation, country config loader
│   ├── preprocessing/          # Plate image preprocessing
│   ├── recognition/            # CRNN recognizer
│   └── model_config.py         # AnprModelConfig dataclass
├── app/                        # Application layer
│   ├── api/                    # FastAPI main API server
│   │   ├── routers/            # Route handlers (channels, events, etc.)
│   │   ├── auth.py             # APIKeyMiddleware
│   │   ├── container.py        # AppContainer (DI wiring)
│   │   ├── deps.py             # FastAPI dependency injection helpers
│   │   ├── main.py             # FastAPI app entry point
│   │   └── schemas.py          # Request/response schemas
│   ├── shared/                 # Shared application services
│   │   └── data_lifecycle.py   # RetentionPolicy, DataLifecycleService
│   ├── web/                    # Static frontend (HTML/JS/CSS)
│   │   ├── assets/             # JS, CSS assets
│   │   ├── favicon/            # Favicon files
│   │   └── images/             # UI images, country flags
│   └── worker/                 # Retention worker service
│       └── main.py             # WorkerContainer, RetentionScheduler
├── common/                     # Shared utilities
│   └── logging.py              # Logging setup, LiveDebugHandler, HourlyFileHandler
├── config/                     # Configuration management
│   ├── settings_migrations/    # Versioned settings migration scripts
│   │   ├── __init__.py
│   │   └── runner.py           # Migration runner
│   ├── settings_manager.py     # SettingsManager (main config API)
│   ├── settings_normalizer.py  # SettingsNormalizer (validation/defaults)
│   ├── settings_repository.py  # JSON file I/O with locking
│   └── settings_schema.py      # Default values, schema constants
├── controllers/                # Physical gate/barrier controller integration
│   ├── adapters/               # Controller protocol adapters
│   │   └── dtwonder2ch.py      # DTWONDER2CH 2-relay adapter
│   ├── base.py                 # ControllerAdapter abstract base
│   ├── registry.py             # Adapter type registry
│   └── service.py              # ControllerService, ControllerAutomationService
├── database/                   # Data persistence
│   ├── postgres/               # PostgreSQL-specific files
│   │   └── schema.sql          # Database schema (verified at startup)
│   ├── errors.py               # StorageUnavailableError
│   ├── clients_repository.py   # ClientDatabase — client CRUD, search, attach/detach
│   ├── lists_repository.py     # ListDatabase — list CRUD + plate matching (channel automation)
│   └── postgres_event_repository.py  # Event CRUD with psycopg_pool
├── runtime/                    # Channel processing runtime
│   ├── channel_runtime.py      # ChannelProcessor, ChannelContext, ChannelMetrics
│   ├── debug.py                # DebugRegistry, DebugLogBus, DebugSettings
│   ├── event_bus.py            # EventBus (async pub/sub)
│   └── event_sink.py           # EventSink (sync DB write wrapper)
├── nginx/                      # Nginx reverse proxy config
├── tests/                      # Unit tests
│   ├── test_direction_estimator.py
│   ├── test_motion_detector.py
│   ├── test_plate_validator.py
│   └── test_track_aggregator.py
├── .planning/                  # GSD planning documents
│   └── codebase/               # Codebase analysis docs
├── Dockerfile                  # Docker build definition
├── docker-compose.yml          # Multi-service Docker Compose
├── requirements.txt            # Python dependencies
├── .env.example                # Environment variable template
├── AGENTS.md                   # Agent instructions
└── README.md                   # Project documentation
```

## Directory Purposes

**`anpr/`:**
- Purpose: All ANPR/ML logic -- detection, recognition, pipeline orchestration
- Contains: Python modules for YOLO detection, CRNN OCR, plate preprocessing, postprocessing validation, country configs
- Key files: `pipeline/anpr_pipeline.py` (ANPRPipeline, TrackAggregator), `pipeline/factory.py` (build_components), `model_config.py` (AnprModelConfig)

**`anpr/countries/`:**
- Purpose: Country-specific plate format definitions
- Contains: YAML files with regex patterns for plate validation (e.g., RU, UA, BY, KZ)

**`anpr/models/`:**
- Purpose: Pre-trained ML model weights
- Contains: `yolo/best.pt` (YOLOv8 plate detector), `ocr_crnn/crnn_ocr_model_int8_fx.pth` (quantized CRNN OCR)
- Generated: Yes (trained externally)
- Committed: Yes (binary model files)

**`app/api/`:**
- Purpose: FastAPI HTTP API server
- Contains: App entry point, routers, auth, DI container, schemas
- Key files: `main.py` (app), `container.py` (AppContainer), `deps.py` (get_container)

**`app/api/routers/`:**
- Purpose: API route handlers organized by domain
- Contains: 9 router modules (channels, clients, controllers, data, debug, events, lists, settings, system)

**`app/shared/`:**
- Purpose: Services shared between API and worker
- Contains: `data_lifecycle.py` (RetentionPolicy, DataLifecycleService)

**`app/web/`:**
- Purpose: Static frontend served at `/web`
- Contains: HTML, JS, CSS, images, favicons
- Served by: `FastAPI.mount("/web", StaticFiles(...))`

**`app/worker/`:**
- Purpose: Background retention worker service
- Contains: `main.py` (WorkerContainer, RetentionScheduler, health/run endpoints)

**`common/`:**
- Purpose: Cross-cutting utilities shared by all layers
- Contains: `logging.py` (configure_logging, get_logger, LiveDebugHandler, HourlyFileHandler)

**`config/`:**
- Purpose: Settings management with schema, normalization, migration, persistence
- Contains: Manager, normalizer, schema, repository, migration runner
- Key files: `settings_manager.py` (SettingsManager), `settings_schema.py` (defaults)

**`controllers/`:**
- Purpose: Physical barrier/gate controller integration
- Contains: Service layer, automation service, adapter registry, protocol adapters
- Key files: `service.py` (ControllerService, ControllerAutomationService)

**`database/`:**
- Purpose: PostgreSQL data access layer
- Contains: Event repository, plate lists repository, schema SQL, error types
- Key files: `postgres_event_repository.py`, `lists_repository.py`, `postgres/schema.sql`

**`runtime/`:**
- Purpose: Video processing runtime, event delivery, debug infrastructure
- Contains: Channel processor, event bus, event sink, debug registry
- Key files: `channel_runtime.py` (ChannelProcessor), `debug.py` (DebugRegistry, DebugLogBus)

**`tests/`:**
- Purpose: Unit tests
- Contains: test files covering direction estimator, motion detector, plate validator, track aggregator, lists/clients repository (ListDatabase + ClientDatabase)

## Key File Locations

**Entry Points:**
- `app/api/main.py`: API server FastAPI app (run with `uvicorn app.api.main:app`)
- `app/worker/main.py`: Retention worker FastAPI app (run with `uvicorn app.worker.main:app`)

**Configuration:**
- `config/settings_manager.py`: Main settings API
- `config/settings_schema.py`: All default values and schema constants
- `config/settings_normalizer.py`: Validation and normalization logic
- `config/settings_repository.py`: JSON file persistence
- `.env.example`: Environment variable template (POSTGRES_DSN, API_KEY)

**Core Logic:**
- `anpr/pipeline/anpr_pipeline.py`: ANPRPipeline, TrackAggregator, TrackDirectionEstimator
- `anpr/pipeline/factory.py`: `build_components()` factory
- `anpr/detection/yolo_detector.py`: YOLODetector with tracking
- `anpr/detection/motion_detector.py`: MotionDetector for frame gating
- `anpr/recognition/crnn_recognizer.py`: CRNNRecognizer batch OCR
- `anpr/postprocessing/validator.py`: PlatePostProcessor
- `runtime/channel_runtime.py`: ChannelProcessor (main processing loop)

**DI / Wiring:**
- `app/api/container.py`: AppContainer (API service wiring)
- `app/api/deps.py`: FastAPI dependency injection

**Database:**
- `database/postgres_event_repository.py`: PostgresEventDatabase
- `database/lists_repository.py`: ListDatabase (list CRUD + channel automation plate matching)
- `database/clients_repository.py`: ClientDatabase (client CRUD, search, attach/detach)
- `database/postgres/schema.sql`: PostgreSQL schema DDL
- `database/errors.py`: StorageUnavailableError

**Testing:**
- `tests/test_track_aggregator.py`: TrackAggregator unit tests
- `tests/test_direction_estimator.py`: TrackDirectionEstimator unit tests
- `tests/test_motion_detector.py`: MotionDetector unit tests
- `tests/test_plate_validator.py`: PlatePostProcessor unit tests

## Naming Conventions

**Files:**
- `snake_case.py` for all Python modules
- Router files named by domain: `channels.py`, `events.py`, `controllers.py`
- Test files prefixed with `test_`: `test_track_aggregator.py`

**Directories:**
- `snake_case` for all directories
- Domain-oriented grouping: `anpr/detection/`, `anpr/recognition/`, `anpr/postprocessing/`

**Classes:**
- `PascalCase`: `ChannelProcessor`, `ANPRPipeline`, `TrackAggregator`
- Dataclasses for simple data containers: `ChannelMetrics`, `ChannelContext`, `ReconnectConfig`
- Private helper classes prefixed with `_`: `_TrackOCRState`, `_FallbackRecognizer`

**Functions:**
- `snake_case`: `build_components()`, `get_container()`, `configure_logging()`
- Private methods prefixed with `_`: `_run_channel()`, `_evict_stale()`

## Where to Add New Code

**New API Endpoint:**
- Create or extend router in `app/api/routers/`
- Register router in `app/api/main.py` via `app.include_router()`
- Add any new service dependencies to `AppContainer` in `app/api/container.py`
- Add request/response models to `app/api/schemas.py`

**New ANPR Processing Step:**
- Add module in `anpr/preprocessing/` or `anpr/postprocessing/`
- Wire into `ANPRPipeline.process_frame()` in `anpr/pipeline/anpr_pipeline.py`
- If configurable, add default values in `config/settings_schema.py`

**New Country Plate Format:**
- Add YAML config file in `anpr/countries/`
- Add country code to `enabled_countries` list in settings

**New Controller Adapter:**
- Create adapter class in `controllers/adapters/` extending `ControllerAdapter`
- Register in `controllers/registry.py` (`CONTROLLER_ADAPTERS` dict)
- Add type to `SUPPORTED_CONTROLLER_TYPES` in `controllers/service.py`

**New Settings Section:**
- Add defaults function in `config/settings_schema.py`
- Add `_fill_*_defaults()` method in `config/settings_normalizer.py`
- Add get/save methods in `config/settings_manager.py`
- Call fill method in `SettingsNormalizer.normalize_with_meta()`

**New Database Table:**
- Add DDL to `database/postgres/schema.sql`
- Create repository class in `database/`
- Wire into `AppContainer` if needed

**New Test:**
- Add test file in `tests/` as `test_*.py`
- Follow existing pattern: `pytest` with plain assert statements

**New Shared Utility:**
- Add to `common/` package

## Special Directories

**`anpr/models/`:**
- Purpose: Pre-trained ML model weight files
- Generated: Yes (trained externally, not generated at build time)
- Committed: Yes (binary files tracked in git)

**`data/screenshots/`:**
- Purpose: Captured frame and plate crop images organized by date/channel
- Structure: `{date}/channel_{id}/{timestamp}_ch{id}_{plate}_frame.jpg`
- Generated: Yes (at runtime)
- Committed: No (in .dockerignore, runtime data)

**`data/exports/`:**
- Purpose: CSV and ZIP export bundles
- Generated: Yes (at runtime via data export API)
- Committed: No

**`logs/`:**
- Purpose: Hourly rotated log files per service
- Pattern: `{service}_{YYYY-MM-DD_HH-00}.log`
- Generated: Yes (at runtime)
- Committed: No

**`.planning/`:**
- Purpose: GSD codebase analysis and planning documents
- Generated: Yes (by Claude Code agents)
- Committed: Yes

**`nginx/`:**
- Purpose: Nginx reverse proxy configuration for production deployment
- Committed: Yes

---

*Structure analysis: 2026-03-25*
