# Codebase Structure

**Analysis Date:** 2026-09-18

## Directory Layout

```
ANPR-System-web/
├── app/                        # FastAPI application and web UI
│   ├── api/                    # REST API layer
│   │   ├── routers/            # API endpoints grouped by domain
│   │   ├── main.py             # FastAPI app initialization and lifespan
│   │   ├── container.py        # Dependency injection container
│   │   ├── deps.py             # FastAPI dependency functions (auth, container)
│   │   ├── auth_utils.py       # JWT creation/validation
│   │   ├── schemas.py          # Pydantic request/response models
│   │   └── __init__.py
│   ├── web/                    # Static HTML/CSS/JS web interface
│   │   ├── index.html          # Main SPA page
│   │   ├── css/                # Stylesheets
│   │   └── js/                 # Frontend logic (vanilla JS)
│   ├── shared/                 # Shared application services
│   │   ├── backup_service.py   # Configuration backup/restore
│   │   ├── data_lifecycle.py   # Screenshot and event retention policies
│   │   └── __init__.py
│   └── worker/                 # Background worker processes (if any)
├── anpr/                       # Automatic Number Plate Recognition pipeline
│   ├── pipeline/               # Orchestration of detection → recognition → validation
│   │   ├── anpr_pipeline.py    # TrackAggregator, consensus voting, OCR budgeting
│   │   ├── factory.py          # Pipeline initialization and configuration
│   │   └── __init__.py
│   ├── detection/              # Plate localization (YOLOv8)
│   │   ├── yolo_detector.py    # YOLOv8 model inference wrapper
│   │   ├── motion_detector.py  # Motion analysis for frame skipping
│   │   └── __init__.py
│   ├── recognition/            # OCR text recognition (CRNN)
│   │   ├── crnn_recognizer.py  # Batch OCR inference
│   │   ├── crnn.py             # Model architecture
│   │   └── __init__.py
│   ├── preprocessing/          # Image preparation for detection/recognition
│   │   ├── plate_preprocessor.py # Resize, normalize, augment
│   │   └── __init__.py
│   ├── postprocessing/         # Result validation and format correction
│   │   ├── validator.py        # PlatePostProcessor: format validation by country
│   │   ├── country_config.py   # Country-specific plate formats
│   │   └── __init__.py
│   ├── models/                 # Pre-trained model weights (not committed)
│   ├── countries/              # Country-specific resources
│   ├── model_config.py         # Model paths and configuration
│   └── __init__.py
├── runtime/                    # Runtime management and orchestration
│   ├── channel_runtime.py      # ChannelProcessor: multi-threaded video processing
│   ├── event_bus.py            # EventBus: async event publishing to subscribers
│   ├── debug.py                # DebugRegistry: feature flags and debug settings
│   ├── debug_log_bus.py        # Live log streaming to web UI
│   └── __init__.py
├── database/                   # Data access layer (repositories + connection pooling)
│   ├── postgres/               # PostgreSQL schema and migrations (if any)
│   ├── base.py                 # PooledDatabase base class, connection pool management
│   ├── channel_repository.py   # CRUD operations for video channels
│   ├── postgres_event_repository.py  # CRUD for plate detection events
│   ├── user_repository.py      # CRUD for user accounts and permissions
│   ├── controller_repository.py # CRUD for relay controllers
│   ├── lists_repository.py     # CRUD for whitelist/blacklist
│   ├── zones_repository.py     # CRUD for zone definitions
│   ├── clients_repository.py   # CRUD for vehicle/owner data
│   ├── errors.py               # Custom exception types
│   └── __init__.py
├── controllers/                # External relay controller integration
│   ├── adapters/               # Protocol adapters (DTWONDER2CH, etc.)
│   ├── service.py              # ControllerService: send relay commands
│   ├── registry.py             # CONTROLLER_ADAPTERS mapping
│   ├── base.py                 # Base adapter interface
│   └── __init__.py
├── config/                     # Configuration management and validation
│   ├── settings_manager.py     # SettingsManager: load/validate/cache settings
│   ├── settings_normalizer.py  # Apply defaults and normalize field values
│   ├── settings_repository.py  # Database access for persistent settings
│   ├── settings_schema.py      # Schema definitions and validators
│   ├── settings.yaml           # YAML configuration file
│   └── __init__.py
├── common/                     # Shared utilities
│   ├── logging.py              # Logger setup, context injection
│   └── __init__.py
├── tests/                      # Unit and integration tests
│   ├── test_track_aggregator.py       # TrackAggregator consensus tests
│   ├── test_auth_*.py                 # Authentication and authorization tests
│   ├── test_*_repository.py           # Data access layer tests
│   ├── test_*_router.py               # API endpoint tests
│   ├── test_*.py                      # Model and utility tests
│   └── __init__.py
├── docs/                       # Project documentation
│   ├── guides/                 # User guides
│   ├── technical/              # Architecture and technical docs
│   ├── roadmap/                # Feature roadmap
│   └── *.md
├── .planning/                  # GSD (Get Shit Done) planning documents
│   ├── codebase/               # Codebase analysis (ARCHITECTURE.md, STRUCTURE.md, etc.)
│   ├── agents/                 # Automated agent instructions
│   ├── commands/               # Custom commands
│   └── hooks/                  # Git hooks
├── nginx/                      # Nginx reverse proxy configuration
├── .claude/                    # Claude Code integration metadata
├── pyproject.toml              # Poetry dependencies and project metadata
├── poetry.lock                 # Locked dependency versions
├── Dockerfile                  # Container image definition
├── docker-compose.yml          # Multi-container orchestration
├── .env.example                # Template for environment variables
├── .dockerignore                # Files excluded from Docker build
├── README.md                   # Project overview
├── LICENSE                     # MIT license
└── AGENTS.md                   # AI agent guidelines
```

## Directory Purposes

**app/api/routers/:**
- Purpose: HTTP endpoint definitions grouped by domain
- Contains: Router modules for `auth`, `channels`, `events`, `users`, `controllers`, `lists`, `zones`, `clients`, `settings`, `system`, `debug`, `data`
- Key files: 
  - `auth.py`: Login, logout, token validation (lines 1-100+)
  - `channels.py`: Video channel CRUD, preview streaming, OCR config
  - `events.py`: Plate detection event queries, SSE streaming
  - `system.py`: System health, version, restart endpoints
  - `settings.py`: Global settings update and retrieval

**app/web/:**
- Purpose: Single-Page Application frontend
- Contains: HTML entry point, CSS stylesheets, vanilla JavaScript modules
- Key files:
  - `index.html`: DOM structure and initialization
  - `js/app.js`: Main application controller
  - `js/api.js`: HTTP client with JWT token handling
  - `js/channels.js`, `js/events.js`, `js/controllers.js`: Tab-specific logic

**anpr/pipeline/:**
- Purpose: Coordinate plate detection, recognition, and validation
- Contains: Main ANPR orchestration logic
- Key files:
  - `anpr_pipeline.py`: `TrackAggregator` (consensus voting, OCR budgeting)
  - `factory.py`: Initialize pipeline with model configuration

**anpr/detection/:**
- Purpose: Locate license plates in video frames
- Contains: YOLOv8 inference and motion detection
- Key files:
  - `yolo_detector.py`: Wraps ultralytics YOLOv8 for plate detection
  - `motion_detector.py`: Temporal motion analysis to skip empty frames

**anpr/recognition/:**
- Purpose: Extract text from detected plate regions
- Contains: CRNN OCR model
- Key files:
  - `crnn_recognizer.py`: Batch inference wrapper
  - `crnn.py`: CRNN architecture (from PyTorch Lightning or custom)

**anpr/postprocessing/:**
- Purpose: Validate and format plate recognition results
- Contains: Format validation by country/region
- Key files:
  - `validator.py`: `PlatePostProcessor` for filtering invalid plates
  - `country_config.py`: Country-specific regex patterns and validation rules

**runtime/channel_runtime.py:**
- Purpose: Multi-threaded video capture and processing orchestration
- Contains: `ChannelProcessor`, `ChannelContext`, `ChannelMetrics`, `ReconnectConfig`
- Key Classes:
  - `ChannelProcessor`: Manages per-channel worker threads, reconnection logic
  - `ChannelContext`: Per-channel state (capture handle, latest frame, stop event)
  - `ChannelMetrics`: Health metrics (FPS, latency, error count)

**database/:**
- Purpose: PostgreSQL data access layer
- Contains: Connection pooling, schema bootstrap, CRUD repositories
- Key files:
  - `base.py`: `PooledDatabase` base class with shared connection pool (psycopg_pool)
  - `channel_repository.py`: Channel config CRUD
  - `postgres_event_repository.py`: Plate event storage and retrieval
  - `user_repository.py`: User account management
  - `controller_repository.py`: Relay controller configuration
  - `lists_repository.py`: Whitelist/blacklist entries

**config/:**
- Purpose: Settings management with schema validation
- Contains: YAML loading, field normalization, database persistence
- Key files:
  - `settings_manager.py`: `SettingsManager` singleton (load YAML, merge DB settings)
  - `settings_schema.py`: Schema and validator definitions
  - `settings_normalizer.py`: Apply defaults and validate field types
  - `settings.yaml`: YAML config with all tunable parameters

**controllers/:**
- Purpose: External relay controller integration for gate automation
- Contains: Adapter pattern for different controller protocols
- Key files:
  - `service.py`: `ControllerService` (send HTTP commands to controllers)
  - `adapters/`: Protocol-specific adapters (DTWONDER2CH, etc.)
  - `registry.py`: Map controller type to adapter

**tests/:**
- Purpose: Unit and integration test coverage
- Contains: Test files co-located by domain (not separate test directory structure)
- Key files:
  - `test_track_aggregator.py`: TrackAggregator consensus and budgeting
  - `test_auth_*.py`: Authentication flow, JWT validation
  - `test_*_repository.py`: Database CRUD operations
  - `test_*_router.py`: API endpoint contract and response structure

## Key File Locations

**Entry Points:**
- `app/api/main.py`: FastAPI application initialization (lines 1-70)
- `config/settings_manager.py`: Configuration loading on startup

**Configuration:**
- `config/settings.yaml`: Main configuration file (YAML format)
- `config/settings_schema.py`: Schema definitions (Pydantic-like)
- `pyproject.toml`: Dependencies and project metadata

**Core Logic:**
- `runtime/channel_runtime.py`: Multi-threaded video processing (37K lines)
- `anpr/pipeline/anpr_pipeline.py`: TrackAggregator consensus (300+ lines)
- `app/api/container.py`: Dependency injection setup (245 lines)
- `app/api/routers/channels.py`: Channel management endpoints (300+ lines)

**Testing:**
- `tests/test_track_aggregator.py`: ANPR pipeline tests
- `tests/test_auth_*.py`: Authentication tests
- `tests/test_*_repository.py`: Database operation tests

## Naming Conventions

**Files:**
- `*_repository.py`: Data access classes (e.g., `channel_repository.py`)
- `*_service.py`: Business logic services (e.g., `service.py` in controllers/)
- `test_*.py`: Test modules (pytest convention)
- `*_adapter.py`: Protocol adapters for external systems

**Directories:**
- `routers/`: FastAPI route definitions
- `adapters/`: Protocol-specific implementations
- `postprocessing/`: Post-processing stages
- `preprocessing/`: Pre-processing stages
- `detection/`, `recognition/`: Model-specific modules

**Classes:**
- `*Database`: Repository classes (e.g., `ChannelDatabase`, `UserDatabase`)
- `*Service`: Service classes (e.g., `ControllerService`)
- `*Payload`: Pydantic request schemas
- `*Out`: Pydantic response schemas

**Functions:**
- `get_*`: Dependency functions returning configured objects (e.g., `get_container()`)
- `list_*()`: Retrieve all items from repository
- `fetch_*()`: Query and transform data
- `find_*()`: Retrieve single item by criteria
- `ensure_*()`: Create if doesn't exist

## Where to Add New Code

**New API Endpoint:**
- Create route in `app/api/routers/{domain}.py` (e.g., `app/api/routers/alerts.py` for new feature)
- Define request schema in `app/api/schemas.py` (e.g., `AlertPayload`)
- Inject `container: AppContainer = Depends(get_container)` for service access
- Add corresponding test in `tests/test_{domain}_router.py`

**New Database Entity:**
- Create repository class in `database/{entity}_repository.py` (e.g., `alert_repository.py`)
- Extend `PooledDatabase` base class and implement `_schema_sql()`
- Add to `AppContainer` initialization in `app/api/container.py` (lines 31-100)
- Add corresponding test in `tests/test_{entity}_repository.py`

**New Business Logic Service:**
- Create service module in appropriate domain directory (e.g., `app/shared/alert_service.py`)
- Inject dependencies (database repositories, configuration) in `__init__()`
- Instantiate in `AppContainer.build()` and assign to container field
- Inject into API routes via container

**New ANPR Processing Stage:**
- Create module in `anpr/{stage}/` (e.g., `anpr/ocr_filter/filter.py`)
- Implement processing function or class
- Register in `anpr/pipeline/factory.py` or call directly from `anpr_pipeline.py`
- Add tests in `tests/test_{stage}*.py`

**Utilities/Helpers:**
- Shared utilities go in `common/` (e.g., `common/validators.py`)
- Import as `from common.validators import func`

## Special Directories

**app/web/:**
- Purpose: Static web UI assets served by FastAPI
- Generated: No (committed source files)
- Committed: Yes (HTML, CSS, JS)
- Build process: None (served as-is by FastAPI `StaticFiles`)

**database/postgres/:**
- Purpose: Database schema, migrations, initialization scripts (if used)
- Generated: No
- Committed: Yes (version control for schema changes)

**.planning/codebase/:**
- Purpose: GSD (Get Shit Done) analysis documents
- Generated: Yes (by Claude codebase mapper)
- Committed: Yes (tracked in git for reference)
- Contents: ARCHITECTURE.md, STRUCTURE.md, CONCERNS.md, CONVENTIONS.md, TESTING.md, STACK.md, INTEGRATIONS.md

**config/models/:**
- Purpose: YOLOv8 and CRNN model weight files
- Generated: No (downloaded at runtime)
- Committed: No (.gitignore excludes)
- Size: Large (several GB)

**data/screenshots/:**
- Purpose: Captured video frames from detected plates
- Generated: Yes (by ChannelProcessor during processing)
- Committed: No
- Lifecycle: Managed by `DataLifecycleService` with configurable retention

---

*Structure analysis: 2026-09-18*
