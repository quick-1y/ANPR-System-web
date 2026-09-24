---
last_mapped_commit: 9cfd79b3a864f23127a46c35300f838c212d0007
last_mapped_at: 2026-09-24
---
# Codebase Structure

**Analysis Date:** 2026-09-24

## Directory Layout

```
ANPR-System-web/
├── anpr/                       # ANPR core: ML pipeline, detection, recognition
│   ├── countries/              # Country plate format YAML configs (RU, UA, BY, KZ)
│   ├── detection/              # YOLO detector, motion detector (cv2 background subtraction)
│   ├── models/                 # Committed binary ML model weights
│   │   ├── ocr_crnn/           # CRNN OCR quantized model (.pth)
│   │   └── yolo/               # YOLOv8 plate detector (.pt)
│   ├── pipeline/               # ANPRPipeline, TrackAggregator, factory
│   ├── postprocessing/         # Plate validation, country config loader, regex formats
│   ├── preprocessing/          # Plate image preprocessing (crop, normalize, pad)
│   ├── recognition/            # CRNN recognizer wrapper, OCR execution
│   ├── model_config.py         # ML model configuration, inference setup
│   └── __init__.py
├── app/                        # Application layer: API, UI, worker
│   ├── api/                    # FastAPI REST API server
│   │   ├── routers/            # Route handlers by domain
│   │   │   ├── auth.py         # Login, logout, token refresh
│   │   │   ├── channels.py     # Channel CRUD, enable/disable, config
│   │   │   ├── events.py       # Event list, fetch, media access, SSE stream
│   │   │   ├── settings.py     # Settings schema, get/put sections
│   │   │   ├── users.py        # User CRUD, password change, permissions
│   │   │   ├── controllers.py  # Controller CRUD, relay test, automation
│   │   │   ├── lists.py        # Whitelist/blacklist CRUD, plate lookup
│   │   │   ├── clients.py      # Client CRUD, list assignment
│   │   │   ├── zones.py        # Zone CRUD, channel binding
│   │   │   ├── debug.py        # Debug log stream, video output toggle
│   │   │   ├── data.py         # Export events, backup/restore, retention run
│   │   │   ├── system.py       # Health status, system resources (CPU/mem/disk)
│   │   │   └── __init__.py
│   │   ├── main.py             # FastAPI app entry point, lifespan, router registration
│   │   ├── container.py        # AppContainer: DI wiring, lifecycle management
│   │   ├── deps.py             # FastAPI dependencies: get_container, get_current_user
│   │   ├── auth_utils.py       # JWT issue/verify, bcrypt password hashing, superadmin
│   │   ├── schemas.py          # Pydantic request/response models
│   │   ├── superadmin.py       # Superadmin technical account (env var only)
│   │   └── __init__.py
│   ├── shared/                 # Services used by both API + worker
│   │   ├── data_lifecycle.py   # RetentionPolicy, DataLifecycleService (cleanup)
│   │   ├── backup_service.py   # Database backup/restore via pg_dump
│   │   └── __init__.py
│   ├── web/                    # Static frontend (HTML, JS, CSS, icons)
│   │   ├── index.html          # Main entry point, login form, tab container
│   │   ├── js/                 # ES modules (import/export pattern)
│   │   │   ├── app.js          # Application entry point, initialization
│   │   │   ├── api.js          # HTTP client, token management, jfetch wrapper
│   │   │   ├── state.js        # Global state: user, events, SSE EventSource
│   │   │   ├── ui.js           # DOM helpers, tab switching, modal control
│   │   │   ├── channels.js     # Channel CRUD, video grid, ROI/plate size editors
│   │   │   ├── events.js       # Event feed render, SSE subscription, modal
│   │   │   ├── journal.js      # Journal tab (event history with filtering)
│   │   │   ├── lists.js        # Lists tab (whitelist/blacklist management)
│   │   │   ├── clients.js      # Clients tab (customer management)
│   │   │   ├── controllers.js  # Controllers tab (relay configuration)
│   │   │   ├── zones.js        # Zones tab (camera zones, entry/exit)
│   │   │   ├── settings.js     # Settings tab (general, debug, logging, retention)
│   │   │   ├── users.js        # Users tab (user/admin management)
│   │   │   ├── system.js       # System info panel (CPU, memory, disk)
│   │   │   ├── debug.js        # Debug panel (log stream, video output)
│   │   │   ├── backup.js       # Backup/restore UI bindings
│   │   │   ├── appearance.js   # Theme/style switching (localStorage only)
│   │   │   ├── appearance-core.js  # Core theme CSS injection
│   │   │   ├── device-prefs.js # Personal UI state (localStorage: grid, sidebar pin)
│   │   │   ├── schema.js       # Settings schema cache, enum rendering
│   │   │   ├── video-grid.js   # Responsive grid layout (2x2, 3x3, etc.)
│   │   │   ├── roi-editor.js   # ROI polygon editor for channels
│   │   │   ├── plate-size-editor.js  # Plate size bounds editor
│   │   │   ├── datetime.js     # Timezone sync, server time offset
│   │   │   ├── server-time.js  # Server time fetch and caching
│   │   │   ├── help.js         # Help system (keyboard shortcuts, tooltips)
│   │   │   └── __init__.py     # (implicit ES module)
│   │   ├── css/                # Stylesheets
│   │   │   ├── styles.css      # Main styles (layout, components, utilities)
│   │   │   └── themes/         # Theme variants (aurora.css, graphite-minimal.css)
│   │   ├── assets/             # Static media
│   │   │   ├── icons/          # SVG icons (channels, events, users, etc.)
│   │   │   └── ...
│   │   └── favicon/            # Browser tab icons (16px, 32px, 180px, 192px)
│   └── worker/                 # Retention worker service
│       ├── main.py             # Worker entry point, RetentionScheduler, lifespan
│       └── __init__.py
├── common/                     # Cross-cutting utilities
│   ├── logging.py              # get_logger(), LiveDebugHandler, HourlyFileHandler
│   └── __init__.py
├── config/                     # Configuration management (no file-based settings)
│   ├── env_settings.py         # EnvConfig: reads .env (only place env is read)
│   ├── registry.py             # Settings registry: class, type, bounds, enums
│   ├── settings_schema.py      # Code defaults, normalizers
│   ├── settings_service.py     # SettingsService: read/write app_settings via DB
│   ├── logging_setup.py        # LoggingApplier: applies logging config from settings
│   └── __init__.py
├── controllers/                # Hardware gate/barrier controller integration
│   ├── adapters/               # Controller protocol implementations
│   │   ├── http_relay.py       # HTTP-based relay controller
│   │   └── ...
│   ├── base.py                 # ControllerAdapter abstract base class
│   ├── registry.py             # Controller type registry, adapter factory
│   ├── service.py              # ControllerService, ControllerAutomationService
│   └── __init__.py
├── database/                   # PostgreSQL persistence layer
│   ├── postgres/               # PostgreSQL-specific
│   │   └── schema.sql          # DDL: tables, constraints, indices, view
│   ├── base.py                 # close_shared_pool(), connection pooling config
│   ├── errors.py               # StorageUnavailableError exception
│   ├── postgres_event_repository.py   # PostgresEventDatabase CRUD + journal queries
│   ├── channel_repository.py   # ChannelDatabase: channel config CRUD
│   ├── user_repository.py      # UserDatabase: user/admin management
│   ├── clients_repository.py   # ClientDatabase: customer CRUD
│   ├── controllers_repository.py   # ControllerDatabase: relay config
│   ├── lists_repository.py     # ListDatabase: whitelist/blacklist management
│   ├── zones_repository.py     # ZoneDatabase: camera zones
│   ├── settings_repository.py  # AppSettingsRepository: app_settings JSON store
│   └── __init__.py
├── runtime/                    # Channel processing runtime (threading, events)
│   ├── channel_runtime.py      # ChannelProcessor, ChannelContext, ChannelMetrics
│   ├── event_bus.py            # EventBus: in-memory pub/sub for SSE
│   ├── event_sink.py           # EventSink: sync wrapper around async DB writes
│   ├── debug.py                # DebugRegistry, DebugLogBus
│   └── __init__.py
├── nginx/                      # Reverse proxy configuration
│   └── default.conf            # Nginx config: SSL, routing, SSE/MJPEG support
├── tests/                      # Unit tests (pytest)
│   ├── test_track_aggregator.py      # TrackAggregator behavior tests
│   ├── test_plate_validator.py       # PlatePostProcessor validation
│   ├── test_motion_detector.py       # MotionDetector threshold tests
│   ├── test_direction_estimator.py   # TrackDirectionEstimator
│   ├── test_schema_sync.py           # DB schema vs. repo sync check
│   └── test_*.py                     # (Other test modules)
├── docs/                       # Project documentation (Markdown)
│   ├── technical/              # Technical deep-dives (endpoints, pipeline, etc.)
│   ├── guides/                 # User/admin guides
│   └── roadmap/                # Development roadmap (phase planning)
├── .env.example                # Environment variable template
├── .env                        # Actual environment (gitignored, copy from example)
├── docker-compose.yml          # Multi-service orchestration (api, worker, postgres, nginx)
├── Dockerfile                  # Docker image definition (Python 3.13-slim)
├── pyproject.toml              # Poetry dependencies (FastAPI, torch, ultralytics, etc.)
├── poetry.lock                 # Locked dependency versions
├── AGENTS.md                   # Agent instructions, conventions, rules
├── README.md                   # Project documentation (Russian)
└── LICENSE                     # License file
```

## Directory Purposes

**anpr/:**

- Purpose: All ANPR/ML logic (detection, recognition, validation)
- Contains: YOLO detector, CRNN recognizer, TrackAggregator, plate validation, country configs
- Key files: `anpr/pipeline/anpr_pipeline.py`, `anpr/postprocessing/validator.py`, `anpr/models/` (committed weights)

**app/api/:**

- Purpose: REST API server
- Contains: Route handlers (routers/), Pydantic schemas, authentication, dependency injection
- Key files: `app/api/main.py` (entry), `app/api/container.py` (DI)

**app/web/:**

- Purpose: Static frontend (HTML, JS, CSS)
- Contains: ES modules, themes, icons, responsive grid
- Key files: `app/web/index.html`, `app/web/js/app.js` (entry)

**app/worker/:**

- Purpose: Retention worker service (data lifecycle management)
- Contains: RetentionScheduler, cleanup policy polling
- Key files: `app/worker/main.py`

**config/:**

- Purpose: Configuration management (settings registry, SettingsService)
- Contains: Env loading, settings schema, defaults, normalizers
- Key files: `config/registry.py`, `config/settings_service.py`

**controllers/:**

- Purpose: Hardware controller integration (relays, gates, barriers)
- Contains: Controller adapters, automation service
- Key files: `controllers/service.py`

**database/:**

- Purpose: PostgreSQL data access layer
- Contains: Repositories (channels, events, users, settings, etc.), schema DDL, connection pooling
- Key files: `database/postgres/schema.sql`, `database/postgres_event_repository.py`

**runtime/:**

- Purpose: Channel processing runtime (multi-threaded orchestration)
- Contains: ChannelProcessor, per-channel context, event bus, metrics
- Key files: `runtime/channel_runtime.py`

**tests/:**

- Purpose: Unit tests (pytest framework)
- Contains: `test_*.py` files grouped by component
- Key files: `tests/test_track_aggregator.py`, `tests/test_plate_validator.py`

**docs/:**

- Purpose: Project documentation
- Contains: Technical guides, architecture notes, roadmap
- Key files: `docs/roadmap/configuration-architecture.md`

## Key File Locations

**Entry Points:**

- API Server: `app/api/main.py` (FastAPI app definition, lifespan, routers)
- Worker: `app/worker/main.py` (retention worker entry, scheduler)
- Frontend: `app/web/index.html` + `app/web/js/app.js` (browser entry, ES module imports)

**Configuration:**

- Environment: `config/env_settings.py` (only place env vars are read)
- Settings Registry: `config/registry.py` (all operational settings declared once)
- Defaults: `config/settings_schema.py` (code-level defaults, normalizers)
- SettingsService: `config/settings_service.py` (DB read/write for app_settings)

**Core Logic:**

- ANPR Pipeline: `anpr/pipeline/anpr_pipeline.py` (ANPRPipeline, TrackAggregator)
- Channel Runtime: `runtime/channel_runtime.py` (ChannelProcessor, ChannelContext)
- Plate Validation: `anpr/postprocessing/validator.py` (PlatePostProcessor, regex rules)
- Database Access: `database/postgres_event_repository.py` (Event CRUD, psycopg_pool)
- Controller Automation: `controllers/service.py` (ControllerAutomationService)

**Testing:**

- Track Aggregator Tests: `tests/test_track_aggregator.py`
- Plate Validator Tests: `tests/test_plate_validator.py`
- Schema Sync Test: `tests/test_schema_sync.py` (DB schema vs. repo sanity check)

**Persistence:**

- Database Schema: `database/postgres/schema.sql` (DDL for all tables)

## Naming Conventions

**Files:**

- Python: `snake_case.py` (e.g., `channel_runtime.py`, `anpr_pipeline.py`)
- HTML/CSS: `lowercase-kebab.css`, `index.html` (static files use kebab-case or lowercase)
- JavaScript: `camelCase.js` (e.g., `eventSource.js`, `api.js`) — except for config files (`schema.js`)

**Directories:**

- `snake_case` (e.g., `anpr/`, `api/routers/`, `postprocessing/`)

**Classes / Components:**

- `PascalCase` (e.g., `ChannelProcessor`, `ANPRPipeline`, `TrackAggregator`)
- Dataclasses: `PascalCase` (e.g., `ChannelMetrics`, `ChannelContext`)
- Pydantic models: `PascalCase` + `Payload` suffix (e.g., `ChannelPayload`, `SettingsPayload`)

**Functions / Methods:**

- Public: `snake_case` (e.g., `build_components()`, `process_frame()`)
- Private: `_snake_case` (e.g., `_evict_stale()`, `_run_channel()`)

**Variables:**

- Local: `snake_case` (e.g., `track_id`, `best_shots`, `event_data`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_TTL`, `MAX_ATTEMPTS`)

**Test Files & Methods:**

- Files: `test_<component>.py` (e.g., `test_track_aggregator.py`)
- Classes: `Test<Component>` (e.g., `TestTrackAggregator`)
- Methods: `test_<behavior>` (e.g., `test_emits_on_quorum`, `test_no_emission_below_quorum`)

## Where to Add New Code

**New REST Endpoint:**

1. Create or extend a router in `app/api/routers/` (e.g., `app/api/routers/channels.py`)
2. Define Pydantic request/response schemas in `app/api/schemas.py` (or inline if trivial)
3. Use `Depends(get_container)` and `Depends(get_current_user)` for DI
4. Register router in `app/api/main.py` via `app.include_router()`
5. Return HTTP responses (dict or FileResponse); container handles DB errors

**New ANPR Processing Step:**

1. Create module in `anpr/preprocessing/` (pre-detection) or `anpr/postprocessing/` (post-detection)
2. Implement logic with type hints and Russian docstrings
3. Wire into `ANPRPipeline._process_frame()` or `_validate_plate()`
4. Write tests in `tests/test_<component>.py`

**New Country Plate Format:**

1. Add YAML config in `anpr/countries/` (e.g., `anpr/countries/RU.yaml`)
2. Define regex patterns, format, spacing rules (see existing configs for template)
3. Country code must match `COUNTRIES` in `config/registry.py`

**New Controller Adapter:**

1. Create implementation in `controllers/adapters/` (e.g., `controllers/adapters/tcp_relay.py`)
2. Extend `ControllerAdapter` abstract base from `controllers/base.py`
3. Register in `controllers/registry.py` (ADAPTER_TYPES dict)
4. Write test doubles for non-HTTP controllers

**New Settings:**

1. Add specification to `config/registry.py` (class, type, default, bounds, requires_restart, owner)
2. Add code default to `config/settings_schema.py` (if A/D class)
3. Add to `.env.example` if environment-sourced (EnvConfig)
4. Expose via `PUT /api/settings/<section>` and `GET /api/settings/<section>` (auto-generated by SettingsService)
5. For personal UI state with no server owner: add to `app/web/js/device-prefs.js` (localStorage only, document in registry class L section)

**New Database Table:**

1. Add DDL (CREATE TABLE, indices, constraints) to `database/postgres/schema.sql`
2. Create repository class in `database/<entity>_repository.py` (with inline _SCHEMA for lazy bootstrap)
3. Register in `AppContainer.build()` and `WorkerContainer.build()` if needed
4. Update `app/api/container.py` if exposed to API
5. Add test data builders in `tests/test_<entity>.py` if complex

**New Frontend Feature:**

1. Create JS module in `app/web/js/` (e.g., `app/web/js/export-csv.js`)
2. Import into `app/web/js/app.js` and call initialization function
3. Use `api()` wrapper from `app/web/js/api.js` for HTTP calls
4. Store personal state in `localStorage` if user-specific (do not use server table)
5. Update HTML in `app/web/index.html` if adding new UI elements

**New Unit Test:**

1. Create `tests/test_<component>.py` with pytest-style classes and methods
2. Write test helpers as module-level functions prefixed with `_` (e.g., `_blank()`, `_ru_country()`)
3. Use plain `assert` statements (pytest rewrites them); avoid mocking libraries
4. Group related tests in `Test<Component>` classes with docstrings
5. Run: `pytest tests/test_<component>.py` or `pytest` for all

## Special Directories

**anpr/models/:**

- Purpose: Committed binary ML model weights (YOLO .pt, CRNN .pth)
- Generated: No (trained externally, committed as binary files)
- Committed: Yes (required for inference)

**app/web/ (static assets):**

- Purpose: Served by FastAPI StaticFiles middleware at `/web/`
- Generated: No (manually edited)
- Committed: Yes (HTML, CSS, JS, SVG icons)

**data/ (runtime output):**

- Purpose: Event screenshots, debug logs, export files
- Generated: Yes (on each event, on debug toggle, on export)
- Committed: No (gitignored)

**.env:**

- Purpose: Environment variable overrides (.env.example is the template)
- Generated: No (copied from .env.example)
- Committed: No (gitignored; secrets)

**database/postgres/schema.sql:**

- Purpose: PostgreSQL DDL; also mounted as Docker init script for fresh databases
- Generated: No (manually edited)
- Committed: Yes (source of truth for schema)

---

*Structure analysis: 2026-09-24*
