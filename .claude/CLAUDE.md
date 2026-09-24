<!-- GSD:project-start source:PROJECT.md -->

## Project

**Web ANPR System — Роли, пользователи и права доступа**

Самостоятельно разворачиваемая многоканальная система распознавания автомобильных номеров (ANPR) с веб-интерфейсом, REST API и управлением реле шлагбаумов/ворот. Текущий цикл полностью перерабатывает модель пользователей и прав: администратор создаёт роли с произвольным названием, отмечает галочками доступы по разделам (Просмотр / Изменение / Удаление) и назначает роль любому числу пользователей. Для охранников-операторов и администраторов парковок/КПП.

**Core Value:** Администратор может гибко выдать любому пользователю ровно те доступы, которые нужны, через роли с галочками, и сервер реально соблюдает эти права, а не только скрывает вкладки.

### Constraints

- **Tech stack**: FastAPI, PostgreSQL как единственное хранилище, без Redis — изменения только в рамках существующего стека
- **Схема БД**: прямые изменения в `database/postgres/schema.sql` + inline `_SCHEMA` репозиториев (синхронизацию проверяет `tests/test_schema_sync.py`); без миграционных модулей и слоёв совместимости
- **Безопасность**: смена логики авторизации требует подтверждения владельца; права проверяются на сервере; superadmin не хранится в БД
- **Разделение понятий**: личные настройки UI не требуют прав (identity is the authorization); защиту эндпоинта выбирать по владельцу данных, а не по экрану UI
- **Документация**: README, `docs/technical/`, `docs/guides/` обновляются на русском; PR на русском
- **Тесты**: pytest, без библиотек моков — только простые тестовые двойники

<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->

## Technology Stack

## Languages

- Python 3.13 - FastAPI API server, retention worker, channel processing, ANPR pipeline, configuration management

## Runtime

- Python 3.13-slim Docker image (Debian-based, from `Dockerfile`)
- Docker Compose orchestration with 4 services: postgres, api, retention_worker, nginx
- Poetry (v1.8+ implicit; `pyproject.toml` + `poetry.lock`)
- Lockfile: `poetry.lock` (committed)
- Dependency installation: `poetry install --no-root --only main` (Dockerfile line 22)

## Frameworks

- FastAPI (unpinned, latest) - HTTP API server (`app/api/main.py`)
- Uvicorn (unpinned, latest) - ASGI server
- nginx 1.27-alpine - Request routing, SSE support, CORS proxy (`nginx/default.conf`)
- pytest (9.0.2–9.9.x from `pyproject.toml` dev dependency)
- Docker + Docker Compose (for all deployments)

## Key Dependencies

- ultralytics 8.3.20 (pinned, required) - YOLOv8 license plate detection via internal `model.predictor` tracker API
- torch 2.8.0 (pinned, CPU-only from `download.pytorch.org/whl/cpu`) - Deep learning inference runtime
- torchvision 0.23.0 (pinned, CPU-only) - Image transforms for CRNN OCR pipeline
- opencv-python (unpinned) - RTSP video capture, frame processing, JPEG encoding
- psycopg[binary] (unpinned) - PostgreSQL driver (psycopg3)
- psycopg_pool (unpinned) - Connection pooling (min=2, max=10; two separate pools: events + lists)
- bcrypt (unpinned) - Password hashing for users
- PyJWT (unpinned) - JWT token issue/verify (HS256 algorithm, `app/api/auth_utils.py`)
- PyYAML (unpinned) - Parse country plate format configs (`anpr/countries/*.yaml`)
- psutil (unpinned) - CPU, memory, disk metrics
- python-multipart (unpinned) - FastAPI form data parsing
- tzdata (unpinned) - Timezone support

## Configuration

- Read-once at startup via `config/env_settings.py` (only place that reads `os.environ`)
- `.env` file (gitignored) with defaults from `.env.example` (Russian comments)
- `EnvConfig` dataclass validates types and enforces minimum secret length
- Class A settings: Stored in PostgreSQL `app_settings` table (one row per leaf key)
- Settings schema: `config/registry.py` (class, type, default, bounds, `requires_restart`, owner)
- No settings file; YAML config removed as of dev branch commit e4ad237
- Read/written through `SettingsService` (`config/settings_service.py`)
- Revision tracking via `app_settings_revision` table for cache invalidation
- Browser `localStorage` only (no server persistence)
- `JWT_SECRET_KEY` - JWT signing secret (env var, min 32 bytes in production, enforced at startup)
- `SUPERADMIN_PASSWORD` - Technical superadmin account (env var, read fresh on every login)
- `pyproject.toml` - Poetry dependencies and metadata
- `poetry.lock` - Locked versions (committed for reproducibility)
- `Dockerfile` - Multi-stage build (Python 3.13-slim, system deps, poetry install)
- `docker-compose.yml` - 4-service orchestration (postgres, api, retention_worker, nginx)

## Platform Requirements

- Docker & Docker Compose required (no standalone Python instructions)
- PostgreSQL 16 (via Docker)
- Python 3.13 (via Docker image)
- libglib2.0-0 - Required by OpenCV
- libgl1 - Required by OpenCV
- libgomp1 - OpenMP runtime for parallel processing
- tzdata - Timezone database
- Self-hosted on-premises (Docker Compose)
- CPU-only inference (no GPU required, no CUDA)
- Network access to RTSP cameras and hardware controllers (HTTP/HTTPS)
- Ports: 8080 (HTTP via nginx), 5432 (PostgreSQL, internal only)
- `pgdata` - PostgreSQL persistent data
- `media_data` - Screenshots and exports (`/app/data`)
- `logs_data` - Application logs (`/app/logs`)

<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

## Naming Patterns

- `snake_case.py` - All Python files use lowercase with underscores (e.g., `channel_runtime.py`, `anpr_pipeline.py`, `plate_validator.py`)
- `snake_case()` - Public functions use lowercase with underscores (e.g., `process_frame()`, `build_components()`)
- `_snake_case()` - Private/internal functions prefixed with single underscore (e.g., `_configure_thread_limits()`, `_normalize()`, `_build_reconnect_config()`)
- `PascalCase` - Standard classes in PascalCase (e.g., `ChannelProcessor`, `TrackAggregator`, `PlatePostProcessor`)
- `_PascalCase` - Private dataclasses prefixed with underscore (e.g., `_TrackOCRState`)
- `snake_case` - Local variables and instance variables (e.g., `track_id`, `best_shots`, `reconnect_config`)
- `UPPER_SNAKE_CASE` - Module-level constants (e.g., `DEFAULT_LEVEL`, `LOG_FILENAME_TIME_FORMAT`, `_EVICT_INTERVAL`)
- `PascalCase` - Public value objects (e.g., `ChannelMetrics`, `ChannelContext`, `ReconnectConfig`, `PlatePostprocessResult`)
- `PascalCase` suffix - Request/response models typically end with `Payload` or have a suffix (e.g., `LoginRequest`, `LoginResponse`, `UserOut`)
- `test_<component>.py` - Test files named after component (e.g., `test_track_aggregator.py`, `test_plate_validator.py`, `test_motion_detector.py`)
- `Test<Component>` - Test classes prefixed with `Test` (e.g., `TestTrackAggregator`, `TestLogin`, `TestRussiaConfig`)
- `test_<behavior>` - Test methods start with `test_` and describe behavior in snake_case (e.g., `test_no_emission_below_quorum`, `test_emits_on_quorum`)
- `_<name>()` - Module-level builder/helper functions prefixed with underscore (e.g., `_blank()`, `_noisy()`, `_make_format()`, `_ru_country()`, `_processor_with_ru()`)
- `_UPPER_SNAKE_CASE` or `_snake_case` - Private module-level variables prefixed with underscore (e.g., `_EVICT_INTERVAL`, `_LOG_QUEUE`, `_CLEANUP_THREAD`, `_failed_attempts`)

## Code Style

- No automated formatter configured (no .prettierrc, biome.json, or equivalent)
- Consistent 4-space indentation expected throughout codebase
- No ESLint or equivalent JavaScript linter
- Required on all function signatures
- Use `from __future__ import annotations` at the top of every Python file
- Use PEP 604 union syntax: `str | None` instead of `Optional[str]`
- Use `TYPE_CHECKING` blocks for annotation-only imports to avoid circular dependencies:
- Order: standard library, third-party packages, local project imports
- Absolute imports from project root preferred: `from common.logging import get_logger`
- Relative imports within same package acceptable: `from .country_config import CountryConfig`
- Example structure:

## Error Handling

- Broad `except Exception` blocks allowed in infrastructure/database code with explicit `# noqa: BLE001` comment
- Custom exceptions used for domain errors (e.g., `StorageUnavailableError`)
- Pydantic validators raise `ValueError` with Russian messages for domain validation
- FastAPI endpoints raise `HTTPException` with appropriate status codes and Russian error messages

## Logging

- Always use `get_logger(__name__)` from `common/logging.py`, never `logging.getLogger()` directly
- Module-level logger instance: `logger = get_logger(__name__)`
- Use lazy `%` formatting: `logger.info("%s: %d frames", channel_name, count)`
- Never use f-strings in log calls (they evaluate eagerly)
- Channel context prefix pattern for ANPR pipeline: `"Канал {name} (id={id})"`
- Russian log messages for pipeline/domain logic (`anpr/`, `runtime/`)
- English log messages for infrastructure/API code
- Use Russian log messages when channel context is included
- `DEBUG`: Per-frame diagnostics, detailed state tracking, validation results
- `INFO`: Consensus reached, budget exhausted, important state changes
- `WARNING`: Errors, retries, unusual conditions
- `ERROR`: Serious failures, data loss risks
- `CRITICAL`: System-level failures

## Comments

- Document non-obvious business logic (especially plate format rules, country-specific handling)
- Explain algorithm choices and edge cases
- Note workarounds, constraints, or version-specific quirks
- Mark technical debt with inline notes
- Russian for business logic and domain explanations
- English for infrastructure, API, and general technical notes
- Russian docstrings for classes and methods that implement business logic
- English docstrings for infrastructure, utility, and API functions
- Example:
- Use `# noqa: <CODE>` with explanatory comment for linter suppressions
- Example: `except Exception as exc:  # noqa: BLE001 - хотим логировать любые сбои`

## Function Design

- Use `*` to mark optional/config parameters as keyword-only:
- Clamp config/parameter values in `__init__` with `max()`/`min()`:
- Explicit return type hints on all function signatures
- Use empty string `""` for "no result" in string-returning functions (not `None`)
- Use boolean for detection/validation functions

## Module Design

- Prefix internal module functions with `_`
- Private dataclasses prefixed with `_PascalCase`
- Private module variables prefixed with `_`
- Functions/classes without `_` are public API
- Use `__all__` to define explicit exports (optional but recommended)
- Dataclasses for internal domain models: `ChannelMetrics`, `ChannelContext`, `PlatePostprocessResult`
- Pydantic `BaseModel` for API request/response validation: `LoginRequest`, `LoginResponse`, `UserOut`
- Use `Protocol` from `typing` for duck-typing interfaces instead of inheritance:

## Import Guidelines

- Do not create "utils" dumping grounds for unrelated logic
- Do not import from `controllers/` in `config/` (known coupling, is tech debt)
- Do not use `logging.getLogger()` directly (use `get_logger()`)
- Always add `from __future__ import annotations` as the first import
- Group imports: stdlib → third-party → local
- Use `TYPE_CHECKING` blocks for annotation-only imports

<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

## System Overview

```text

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

- Two FastAPI services: API server + retention worker (separate processes)
- Dependency injection via container pattern (`AppContainer`, `WorkerContainer`)
- Per-channel video processing runs in dedicated daemon threads, isolated by `ChannelContext`
- Thread-safe state management with `threading.RLock` (ChannelProcessor._lock, ChannelContext.stop_event)
- Shared singleton ML recognizers (YOLO detector, CRNN OCR) to save memory
- In-memory event bus with SSE streaming for real-time plate updates
- PostgreSQL as the only persistent backend; no file-based settings, no SQLite fallback
- Nginx reverse proxy for SSL termination, request routing, SSE/MJPEG support

## Layers

- Purpose: Real-time plate updates, channel monitoring, configuration UI
- Location: `app/web/` (HTML + ES modules)
- Contains: SVG icons, CSS themes, JS modules with imports from state/api/ui
- Depends on: REST API + EventSource (SSE) from FastAPI
- Used by: End operators/administrators
- Purpose: HTTP request routing, authentication, SSE streaming, MJPEG proxy
- Location: `app/api/main.py` (FastAPI), `nginx/default.conf`
- Contains: Route handlers in `app/api/routers/`, Pydantic schemas, auth utilities, DI setup
- Depends on: PostgreSQL, ChannelProcessor (via AppContainer)
- Used by: Frontend, external integrations, webhooks
- Purpose: ANPR pipeline, track aggregation, plate validation, event persistence, automation
- Location: `anpr/pipeline/`, `app/api/routers/`, `config/`, `controllers/`
- Contains: ANPRPipeline, TrackAggregator, PlatePostProcessor, SettingsService, ControllerAutomationService
- Depends on: ANPR models, country configs, database repositories
- Used by: ChannelProcessor, API handlers, retention worker
- Purpose: Orchestrate per-channel video processing with isolation and metrics
- Location: `runtime/channel_runtime.py`
- Contains: ChannelProcessor, ChannelContext, ChannelMetrics, ReconnectConfig
- Depends on: ANPRPipeline, EventBus, PostgreSQL (events, lists), ControllerAutomationService
- Used by: AppContainer.startup(), AppContainer.sync_channel_runtime()
- Purpose: Events, channels, users, settings, lists, clients, zones, controllers
- Location: `database/`, `database/postgres/schema.sql`
- Contains: Repository classes (PostgresEventDatabase, ListDatabase, ChannelDatabase, etc.) with psycopg_pool
- Depends on: PostgreSQL 16 driver (psycopg[binary])
- Used by: All layers (API, runtime, worker)
- Purpose: Automated data lifecycle management (screenshots, events)
- Location: `app/worker/main.py`
- Contains: WorkerContainer, RetentionScheduler, DataLifecycleService
- Depends on: SettingsService (policy from `app_settings`), PostgreSQL
- Used by: Cron/Docker-scheduled process (separate from API server)

## Data Flow

### Primary Request Path: Video Capture → Event Persistence → SSE Broadcast

### Settings and Configuration Flow

### Personal UI State (Browser Only)

- **Theme, style, grid layout, sidebar pin, debug panel, channel metrics**
- Stored in: Browser `localStorage` (`app/web/js/appearance.js`, `app/web/js/device-prefs.js`)
- No server persistence, no `users.preferences` table
- Synced per-device, not per-account
- Channel context: `Dict[int, ChannelContext]` protected by `threading.RLock()` in ChannelProcessor
- Event backlog: `asyncio.Queue(maxsize=512)` per SSE subscriber (dropped if full)
- Settings cache: In-memory dict in SettingsService, reloaded on DB read
- Logging config: Applied per-service on startup, re-read on settings change

## Key Abstractions

- Purpose: Encapsulates per-channel state (thread, stop signal, metrics, preview frame)
- Examples: `runtime/channel_runtime.py:ChannelContext`
- Pattern: Dataclass with default_factory fields for thread-safe access
- Purpose: Manages OCR budget and consensus per video track
- Examples: `anpr/pipeline/anpr_pipeline.py:TrackAggregator`
- Pattern: Maintains state dicts by track_id; emits consensus or best-effort when finalizing
- Purpose: Country-specific validation and normalization
- Examples: `anpr/postprocessing/validator.py:PlatePostProcessor`
- Pattern: Loads YAML config, applies regex/format rules
- Purpose: Single interface for all settings read/write
- Examples: `config/settings_service.py:SettingsService`
- Pattern: Wraps AppSettingsRepository; manages cache lifecycle
- Purpose: Rules-based dispatch of events to physical relays
- Examples: `controllers/service.py:ControllerAutomationService`
- Pattern: Checks event against lists/rules; sends HTTP to controller

## Entry Points

- Location: `app/api/main.py`
- Triggers: Docker run, or `uvicorn app.api.main:app --host 0.0.0.0 --port 8000`
- Responsibilities: 
- Location: `app/worker/main.py`
- Triggers: Docker run (separate service in docker-compose.yml)
- Responsibilities:
- Location: `app/web/index.html` → `app/web/js/app.js`
- Triggers: Browser GET /web/
- Responsibilities:

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

### Missing Reconnect Cache Invalidation

### Broad Exception Catch in Database Layer

## Error Handling

- `StorageUnavailableError` propagates from repositories; caught in routers, re-raised as HTTP 503
- Validation errors in Pydantic schemas raise ValueError; FastAPI converts to HTTP 422
- Authentication failures in `get_current_user()` raise HTTP 401
- Channel not found in runtime: HTTP 404 (channel exists but not running, or never existed)
- Invalid settings update: HTTP 400 (constraint violation, e.g. max > min) or HTTP 422 (schema mismatch)

## Cross-Cutting Concerns

<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
