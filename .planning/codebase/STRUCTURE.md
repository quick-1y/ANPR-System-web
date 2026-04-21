# Codebase Structure

**Analysis Date:** 2026-04-14

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
│   │   ├── routers/            # Route handlers by domain
│   │   │   ├── auth.py         # Login, logout, /me
│   │   │   ├── channels.py     # Channel CRUD, preview, start/stop
│   │   │   ├── clients.py      # Plate list client CRUD
│   │   │   ├── controllers.py  # Hardware controller CRUD
│   │   │   ├── data.py         # Export, backup, retention policy
│   │   │   ├── debug.py        # Debug overlay, log stream
│   │   │   ├── events.py       # ANPR events, SSE stream
│   │   │   ├── lists.py        # Named plate lists CRUD
│   │   │   ├── settings.py     # App settings read/write
│   │   │   ├── system.py       # Health, resource metrics
│   │   │   └── users.py        # User management (superadmin)
│   │   ├── auth_utils.py       # JWT create/verify, bcrypt hash/verify
│   │   ├── container.py        # AppContainer (DI wiring)
│   │   ├── deps.py             # get_current_user, require_role, require_permission
│   │   ├── main.py             # FastAPI app entry point, lifespan
│   │   └── schemas.py          # Pydantic request/response models
│   ├── shared/                 # Shared application services
│   │   ├── backup_service.py   # DB backup/restore, settings export
│   │   └── data_lifecycle.py   # RetentionPolicy, DataLifecycleService
│   ├── web/                    # Static frontend (HTML/JS/CSS)
│   │   ├── assets/             # Static assets
│   │   ├── favicon/            # Favicon files
│   │   ├── images/             # UI images, country flags
│   │   ├── index.html          # Single-page app shell
│   │   ├── styles.css          # Global styles
│   │   ├── api.js              # API client wrapper
│   │   ├── app.js              # App bootstrap and routing
│   │   ├── backup.js           # Backup/restore UI
│   │   ├── channels.js         # Channel management UI
│   │   ├── clients.js          # Plate client UI
│   │   ├── controllers.js      # Controller management UI
│   │   ├── debug.js            # Debug panel UI
│   │   ├── events.js           # Live event stream UI
│   │   ├── help.js             # Help panel
│   │   ├── journal.js          # Event journal UI
│   │   ├── lists.js            # Plate list UI
│   │   ├── plate-size-editor.js# Plate size ROI editor
│   │   ├── roi-editor.js       # ROI polygon editor
│   │   ├── settings.js         # Settings UI
│   │   ├── state.js            # Global app state
│   │   ├── system.js           # System metrics UI
│   │   ├── ui.js               # Shared UI utilities
│   │   ├── users.js            # User management UI
│   │   └── video-grid.js       # Video grid/preview UI
│   └── worker/                 # Retention worker service
│       └── main.py             # WorkerContainer, RetentionScheduler
├── common/                     # Shared utilities
│   └── logging.py              # configure_logging, get_logger, LiveDebugHandler, HourlyFileHandler
├── config/                     # Configuration management
│   ├── settings_migrations/    # Versioned settings migration scripts
│   │   └── runner.py           # Migration runner
│   ├── settings_manager.py     # SettingsManager (main config API)
│   ├── settings_normalizer.py  # SettingsNormalizer (validation/defaults)
│   ├── settings_repository.py  # YAML file I/O with locking
│   └── settings_schema.py      # Default values, schema constants
├── controllers/                # Physical gate/barrier controller integration
│   ├── adapters/               # Controller protocol adapters
│   │   └── dtwonder2ch.py      # DTWONDER2CH 2-relay adapter
│   ├── base.py                 # ControllerAdapter abstract base
│   ├── registry.py             # Adapter type registry
│   └── service.py              # ControllerService, ControllerAutomationService
├── database/                   # Data persistence
│   ├── postgres/               # PostgreSQL-specific files
│   │   └── schema.sql          # Database schema (bootstrapped at startup)
│   ├── base.py                 # PooledDatabase base, get_shared_pool, close_shared_pool
│   ├── errors.py               # StorageUnavailableError
│   ├── channel_repository.py   # ChannelDatabase — channel config persistence
│   ├── clients_repository.py   # ClientDatabase — client CRUD, search, attach/detach
│   ├── controller_repository.py# ControllerDatabase — controller config persistence
│   ├── lists_repository.py     # ListDatabase — list CRUD + plate matching
│   ├── postgres_event_repository.py  # PostgresEventDatabase — event CRUD
│   └── user_repository.py      # UserDatabase — user account CRUD
├── runtime/                    # Channel processing runtime
│   ├── channel_runtime.py      # ChannelProcessor, ChannelContext, ChannelMetrics
│   ├── debug.py                # DebugRegistry, DebugSettings
│   ├── debug_log_bus.py        # DebugLogBus (live log streaming)
│   └── event_bus.py            # EventBus (async pub/sub)
├── nginx/                      # Nginx reverse proxy config
│   └── default.conf            # Proxy rules, SSE config
├── tests/                      # Unit tests (pytest)
│   ├── test_auth_deps.py       # get_current_user, require_role, require_permission
│   ├── test_auth_router.py     # Login, logout, me endpoints
│   ├── test_auth_utils.py      # JWT and bcrypt utilities
│   ├── test_direction_estimator.py  # TrackDirectionEstimator
│   ├── test_lists_repository.py    # ListDatabase, ClientDatabase
│   ├── test_motion_detector.py     # MotionDetector
│   ├── test_permission_guards.py   # Permission guard dependencies
│   ├── test_plate_validator.py     # PlatePostProcessor
│   ├── test_settings_storage_cleanup.py  # Settings + storage lifecycle
│   ├── test_track_aggregator.py    # TrackAggregator
│   ├── test_user_repository.py     # UserDatabase
│   └── test_users_router.py        # Users CRUD endpoints
├── .planning/                  # GSD planning documents
│   └── codebase/               # Codebase analysis docs
├── Dockerfile                  # Docker build definition
├── docker-compose.yml          # Multi-service Docker Compose
├── pyproject.toml              # Poetry dependencies and dev dependencies
├── .env                        # Environment variables (gitignored)
└── README.md                   # Project documentation
```

## Directory Purposes

**`anpr/`:**
- Purpose: All ANPR/ML logic — detection, recognition, pipeline orchestration
- Key files: `pipeline/anpr_pipeline.py` (ANPRPipeline, TrackAggregator), `pipeline/factory.py` (build_components), `model_config.py` (AnprModelConfig)

**`anpr/countries/`:**
- Purpose: Country-specific plate format definitions
- Contains: YAML files with regex patterns per country (RU, UA, BY, KZ, etc.)

**`anpr/models/`:**
- Purpose: Pre-trained ML model weights (tracked in git)
- Contains: `yolo/best.pt` (YOLOv8), `ocr_crnn/crnn_ocr_model_int8_fx.pth` (quantized CRNN)

**`app/api/`:**
- Purpose: FastAPI HTTP API server
- Key files: `main.py` (app), `container.py` (AppContainer), `deps.py` (auth dependencies), `auth_utils.py` (JWT/bcrypt)

**`app/api/routers/`:**
- Purpose: API route handlers organized by domain (11 router modules)
- Auth protection: most endpoints use `require_role("superadmin")` or `require_permission()`

**`app/shared/`:**
- Purpose: Services shared between API and worker
- Contains: `data_lifecycle.py` (RetentionPolicy, DataLifecycleService), `backup_service.py` (DB backup/restore)

**`app/web/`:**
- Purpose: Static frontend served at `/web`
- Split into ~20 JS modules by domain (channels, events, journal, lists, controllers, users, etc.)
- Served by: `FastAPI.mount("/web", StaticFiles(...))`

**`app/worker/`:**
- Purpose: Background retention worker service on port 8092
- Contains: `main.py` (WorkerContainer, RetentionScheduler, health/run endpoints)

**`common/`:**
- Purpose: Cross-cutting utilities shared by all layers
- Contains: `logging.py` (configure_logging, get_logger, LiveDebugHandler, HourlyFileHandler)

**`config/`:**
- Purpose: Settings management with schema, normalization, migration, persistence
- Key files: `settings_manager.py` (SettingsManager), `settings_schema.py` (all defaults)

**`controllers/`:**
- Purpose: Physical barrier/gate controller integration
- Key files: `service.py` (ControllerService, ControllerAutomationService)

**`database/`:**
- Purpose: PostgreSQL data access layer
- Base: `base.py` (PooledDatabase, shared pool management)
- Key files: `postgres_event_repository.py`, `lists_repository.py`, `user_repository.py`, `postgres/schema.sql`

**`runtime/`:**
- Purpose: Video processing runtime, event delivery, debug infrastructure
- Key files: `channel_runtime.py` (ChannelProcessor), `debug.py` (DebugRegistry), `event_bus.py` (EventBus)

**`tests/`:**
- Purpose: Unit tests (13 files, ~2762 lines)
- Covers: auth system, ANPR pipeline components, DB repositories, settings lifecycle

## Key File Locations

**Entry Points:**
- `app/api/main.py` — API server FastAPI app (run with `uvicorn app.api.main:app`)
- `app/worker/main.py` — Retention worker FastAPI app (run with `uvicorn app.worker.main:app`)

**Configuration:**
- `config/settings_manager.py` — Main settings API
- `config/settings_schema.py` — All default values and schema constants
- `config/settings_normalizer.py` — Validation and normalization logic
- `.env` — Environment variables (POSTGRES_DSN, JWT_SECRET_KEY, etc.)

**Authentication:**
- `app/api/auth_utils.py` — JWT creation/verification, bcrypt operations
- `app/api/deps.py` — `get_current_user`, `require_role`, `require_permission`
- `app/api/routers/auth.py` — Login endpoint with rate limiter

**Core Logic:**
- `anpr/pipeline/anpr_pipeline.py` — ANPRPipeline, TrackAggregator, TrackDirectionEstimator
- `anpr/pipeline/factory.py` — `build_components()` factory
- `anpr/detection/yolo_detector.py` — YOLODetector with tracking
- `anpr/recognition/crnn_recognizer.py` — CRNNRecognizer batch OCR
- `anpr/postprocessing/validator.py` — PlatePostProcessor
- `runtime/channel_runtime.py` — ChannelProcessor (main processing loop)

**DI / Wiring:**
- `app/api/container.py` — AppContainer (API service wiring)
- `app/api/deps.py` — FastAPI dependency injection

**Database:**
- `database/base.py` — PooledDatabase, get_shared_pool, close_shared_pool
- `database/postgres_event_repository.py` — PostgresEventDatabase
- `database/lists_repository.py` — ListDatabase
- `database/user_repository.py` — UserDatabase
- `database/postgres/schema.sql` — PostgreSQL schema DDL

**Testing:**
- `tests/test_auth_router.py` — API-level auth tests (unittest.mock pattern)
- `tests/test_track_aggregator.py` — Core aggregation logic
- `tests/test_plate_validator.py` — Plate validation
- `tests/test_user_repository.py` — User DB operations

## Naming Conventions

**Files:**
- `snake_case.py` for all Python modules
- Router files named by domain: `channels.py`, `events.py`, `users.py`
- Test files prefixed with `test_`: `test_track_aggregator.py`

**Classes:**
- `PascalCase`: `ChannelProcessor`, `ANPRPipeline`, `TrackAggregator`, `UserDatabase`
- Dataclasses for data containers: `ChannelMetrics`, `ChannelContext`, `ReconnectConfig`
- Private helpers prefixed with `_`: `_TrackOCRState`, `_FallbackRecognizer`
- API schemas: `*Payload` for requests, `*Out` for responses (e.g., `LoginRequest`, `UserOut`)

**Functions:**
- `snake_case`: `build_components()`, `get_current_user()`, `configure_logging()`
- Private methods prefixed with `_`: `_run_channel()`, `_evict_stale()`

## Where to Add New Code

**New API Endpoint:**
- Create or extend router in `app/api/routers/`
- Register router in `app/api/main.py` via `app.include_router()`
- Add service dependencies to `AppContainer` in `app/api/container.py`
- Add request/response models to `app/api/schemas.py`
- Protect with `Depends(require_role("superadmin"))` or `Depends(require_permission(...))`

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

**New Database Repository:**
- Extend `PooledDatabase` from `database/base.py`
- Wire into `AppContainer` in `app/api/container.py`

**New Settings Section:**
- Add defaults function in `config/settings_schema.py`
- Add `_fill_*_defaults()` in `config/settings_normalizer.py`
- Add get/save methods in `config/settings_manager.py`

**New Test:**
- Add `tests/test_*.py`
- Use `pytest` with plain asserts; unittest.mock for API tests

## Special Directories

**`anpr/models/`:**
- Pre-trained ML model weight files tracked in git (binary, externally trained)

**`data/screenshots/`:**
- Captured frame and plate crop images organized by date/channel
- Structure: `{date}/channel_{id}/{timestamp}_ch{id}_{plate}_frame.jpg`
- Runtime-generated, not committed

**`logs/`:**
- Hourly rotated log files per service: `{service}_{YYYY-MM-DD_HH-00}.log`
- Runtime-generated, not committed

**`.planning/`:**
- GSD codebase analysis and planning documents
- Committed to git

---

*Structure analysis: 2026-04-14*
