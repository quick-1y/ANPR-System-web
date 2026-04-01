# AGENTS.md

## Purpose

This file is the primary operating manual for AI agents working in this repository.

It should give the agent enough context to:

- understand what the project does;
- follow the correct architecture and conventions;
- place code in the right directories;
- run the right commands for setup, validation, and testing;
- avoid unsafe or low-quality changes;
- know when to stop and ask a human.

---

## Project Snapshot

- Project name: Web ANPR System
- Project type: web app (self-hosted)
- One-line description: Multi-channel automatic number plate recognition system with web UI, REST API, and hardware controller integration.
- Primary users: Security operators, parking/access-control administrators
- Business/domain context: Video surveillance, license plate recognition (LPR/ANPR), vehicle access control
- Lifecycle stage: MVP / active development
- Maintainers / owning team: Solo developer
- Default branch: main
- Repo status notes: Active feature development on `dev` branch; frontend is a monolithic JS file pending modularization

---

## Agent Principles

Unless the user explicitly asks otherwise, the agent should:

- prefer the smallest safe change that solves the task;
- preserve existing architecture and naming conventions;
- update tests when behavior changes;
- update docs, config, or examples when they become stale because of the change;
- verify work before finishing;
- avoid speculative refactors;
- ask before destructive, irreversible, expensive, or production-affecting operations.

### Optimize For

1. Correctness
2. Maintainability
3. Speed

### Never Do These By Default

- Rewrite architecture without being asked.
- Introduce a new dependency when an existing project dependency can solve the problem.
- Manually edit generated files if the intended workflow is regeneration.
- Ignore failing checks related to the files or behavior you changed.
- Guess around security-sensitive, billing-sensitive, or compliance-sensitive behavior.
- Convert the project back to desktop architecture.
- Couple channels together.
- Move core ANPR/ML logic into frontend code.
- Make large cleanup-only refactors outside the task scope.
- Add SQLite, dual-write, fallback storage paths, or compatibility layers (PostgreSQL is the only backend).
- Remove documentation, diagrams, or architecture notes from `README.md` without replacing them with updated versions.
- Rename or move files en masse without clear necessity.

---

## Sources Of Truth

| Source | Path / URL | When To Use It |
| --- | --- | --- |
| Project documentation | `README.md` | Architecture overview, deployment, runtime flow (in Russian) |
| Agent instructions | `AGENTS.md` | Conventions, boundaries, file placement, workflow rules |
| Codebase analysis | `.planning/codebase/` | Detailed architecture, stack, structure, concerns, conventions, testing patterns |
| Settings schema | `config/settings_schema.py` | Default values and settings structure |
| DB schema | `database/postgres/schema.sql` | PostgreSQL table definitions |
| API routers | `app/api/routers/` | Available REST endpoints and request/response shapes |
| Environment template | `.env.example` | Required and optional env vars |

If documentation and code disagree, prefer code and mention the mismatch in your final summary.

---

## Tech Stack

### Core Stack

- Language(s): Python 3.13
- Runtime(s): Python 3.13-slim Docker image (Debian-based)
- Framework(s): FastAPI (unpinned), Uvicorn (unpinned)
- Package manager(s): Poetry; `pyproject.toml` + `poetry.lock` (PyTorch CPU wheels via explicit Poetry source)
- Build tool(s): Docker + Docker Compose
- Database(s): PostgreSQL 16
- Messaging / queueing: none (in-memory `EventBus` with asyncio queues)
- Cache / storage: none (no Redis; in-memory only)
- Hosting / infrastructure: self-hosted Docker Compose on-prem

### Key Libraries And Services

| Area | Library / Service | Version | Purpose | Notes / Constraints |
| --- | --- | --- | --- | --- |
| ML detection | ultralytics | 8.3.20 (pinned) | YOLO license plate detection | Internal tracker API used; pin version strictly |
| ML runtime | torch | 2.8.0 (CPU-only) | Deep learning inference | Installed from `download.pytorch.org/whl/cpu` |
| ML vision | torchvision | 0.23.0 (CPU-only) | Image transforms for CRNN OCR | Installed with torch |
| Video | opencv-python | unpinned | RTSP capture, image processing, JPEG encoding | Requires `libglib2.0-0`, `libgl1` system deps |
| Database driver | psycopg[binary] | unpinned | PostgreSQL driver (psycopg3) | — |
| Database pooling | psycopg_pool | unpinned | Connection pooling (min=2, max=10) | Two separate pools: events + lists |
| System monitoring | psutil | unpinned | CPU, memory, disk metrics | — |
| Config parsing | PyYAML | unpinned | Settings YAML parsing | — |
| Reverse proxy | nginx | 1.27-alpine | SSE support, request routing | Docker image |

### Version Policy

- Required versions: Python 3.13, PostgreSQL 16, ultralytics 8.3.20, torch 2.8.0
- Version source of truth: `pyproject.toml` + `poetry.lock`
- Dependency update policy: manual
- Compatibility requirements: CPU-only inference (no GPU required); RTSP camera network access

---

## Architecture

- Architecture style: Layered monolith with multi-threaded channel processing
- High-level description: Two FastAPI services (API server + retention worker) with per-channel video processing threads managed by `ChannelProcessor`. Container pattern (`AppContainer`, `WorkerContainer`) for dependency wiring. Shared singleton OCR recognizer across all channel threads.
- Main modules / bounded contexts: `anpr` (ANPR pipeline/ML), `app/api` (HTTP API), `app/worker` (retention), `runtime` (channel processing), `config` (settings), `database` (PostgreSQL), `controllers` (hardware relay automation)
- Main data flow: RTSP frame capture → motion detection → YOLO detection → ROI filtering → CRNN OCR → track aggregation (consensus/budget) → plate validation → event persistence → SSE broadcast → controller automation
- State management approach: Settings in JSON file with in-memory cache; channel state in `Dict[int, ChannelContext]` protected by `threading.RLock`; event streaming via `EventBus` with `asyncio.Queue` per SSE subscriber
- Integration boundaries: RTSP cameras (OpenCV), hardware relay controllers (HTTP), PostgreSQL, web browser (SSE/MJPEG)
- Areas under migration: Frontend has been modularized into ES modules under `app/web/js/` with `app/web/js/app.js` as the entry point
- Hard constraints: Channels must remain isolated (failure of one must not break others). PostgreSQL is the only storage backend. All ANPR logic stays server-side.

### Architectural Rules

- Put API/web logic in `app/api/`, not in `anpr/` or `runtime/`.
- Put ANPR pipeline logic in `anpr/`, not in `app/` or `runtime/`.
- Put channel orchestration in `runtime/`, not in `app/api/` routers.
- Keep `config/` independent from domain logic (known coupling with `controllers/` for `SUPPORTED_CONTROLLER_TYPES` exists as tech debt).
- New API endpoints must go through `AppContainer` for dependency access.
- New settings sections require schema defaults in `config/settings_schema.py`, normalizer fill in `config/settings_normalizer.py`, and get/save methods in `config/settings_manager.py`.
- Do not bypass `SettingsNormalizer` — all settings reads go through `SettingsManager`.

---

## Repository Structure

```text
ANPR-System-v0.8_web/
├── anpr/                       # ANPR core: detection, recognition, pipeline
│   ├── countries/              # Country plate format YAML configs
│   ├── detection/              # YOLO detector, motion detector
│   ├── models/                 # ML model weights (committed binary files)
│   │   ├── ocr_crnn/           # CRNN OCR quantized model (.pth)
│   │   └── yolo/               # YOLOv8 plate detector (.pt)
│   ├── pipeline/               # ANPRPipeline, TrackAggregator, factory
│   ├── postprocessing/         # Plate validation, country config loader
│   ├── preprocessing/          # Plate image preprocessing
│   └── recognition/            # CRNN recognizer
├── app/                        # Application layer
│   ├── api/                    # FastAPI main API server
│   │   ├── routers/            # Route handlers (channels, events, settings, etc.)
│   │   ├── auth.py             # APIKeyMiddleware
│   │   ├── container.py        # AppContainer (DI wiring)
│   │   ├── deps.py             # FastAPI dependency injection helpers
│   │   ├── main.py             # FastAPI app entry point
│   │   └── schemas.py          # Pydantic request/response schemas
│   ├── shared/                 # Shared services (API + worker)
│   │   └── data_lifecycle.py   # RetentionPolicy, DataLifecycleService
│   ├── web/                    # Static frontend (HTML/JS/CSS)
│   └── worker/                 # Retention worker service
│       └── main.py             # WorkerContainer, RetentionScheduler
├── common/                     # Shared utilities
│   └── logging.py              # Logging setup, LiveDebugHandler, HourlyFileHandler
├── config/                     # Configuration management
│   ├── settings_migrations/    # Versioned settings migration scripts
│   ├── settings_manager.py     # SettingsManager (main config API)
│   ├── settings_normalizer.py  # Validation and defaults
│   ├── settings_repository.py  # JSON file I/O with locking
│   └── settings_schema.py      # Default values, schema constants
├── controllers/                # Physical gate/barrier controller integration
│   ├── adapters/               # Controller protocol adapters
│   ├── base.py                 # ControllerAdapter abstract base
│   ├── registry.py             # Adapter type registry
│   └── service.py              # ControllerService, ControllerAutomationService
├── database/                   # PostgreSQL data access layer
│   ├── postgres/               # PostgreSQL-specific files
│   │   └── schema.sql          # Database schema DDL
│   ├── errors.py               # StorageUnavailableError
│   ├── plate_lists_repository.py  # Plate lists CRUD
│   └── postgres_event_repository.py  # Event CRUD with psycopg_pool
├── runtime/                    # Channel processing runtime
│   ├── channel_runtime.py      # ChannelProcessor, ChannelContext, ChannelMetrics
│   ├── debug.py                # DebugRegistry, DebugLogBus
│   ├── event_bus.py            # EventBus (async pub/sub for SSE)
│   └── event_sink.py           # EventSink (sync DB write wrapper)
├── nginx/                      # Nginx reverse proxy config
├── tests/                      # Unit tests (pytest)
├── Dockerfile                  # Docker build definition
├── docker-compose.yml          # Multi-service orchestration (4 services)
├── pyproject.toml              # Python dependencies (Poetry)
├── poetry.lock                 # Locked dependency versions
├── .env.example                # Environment variable template
├── AGENTS.md                   # This file
└── README.md                   # Project documentation (Russian)
```

### Directory Responsibilities

| Path | Responsibility | Typical Contents | Must Not Contain |
| --- | --- | --- | --- |
| `anpr/` | All ANPR/ML logic | Detectors, recognizers, pipeline, preprocessing, postprocessing, country configs | API handlers, HTTP logic, UI code |
| `app/api/` | HTTP API server | Routers, schemas, auth, container, app entry point | ANPR logic, direct DB queries outside container |
| `app/web/` | Static frontend | HTML, JS, CSS, images, favicons | Server-side logic, Python files |
| `runtime/` | Channel processing runtime | Channel processor, event bus, debug registry | API route handlers, settings logic |
| `config/` | Settings management | Manager, normalizer, schema, repository, migrations | Domain logic, API handlers |
| `database/` | PostgreSQL persistence | Repositories, schema SQL, error types | Business logic, API handlers |
| `controllers/` | Hardware controller integration | Adapters, service, registry | ANPR logic, settings management |
| `common/` | Cross-cutting utilities | Logging setup and helpers | Domain-specific logic |
| `tests/` | Unit tests | `test_*.py` files | Production code |

### File Placement Rules

- New API endpoints: create or extend router in `app/api/routers/`, register in `app/api/main.py`.
- New ANPR processing steps: add module in `anpr/preprocessing/` or `anpr/postprocessing/`, wire into `ANPRPipeline`.
- New country plate formats: add YAML config in `anpr/countries/`.
- New controller adapters: create in `controllers/adapters/`, register in `controllers/registry.py`.
- New settings sections: add defaults in `config/settings_schema.py`, fill method in `config/settings_normalizer.py`, get/save in `config/settings_manager.py`.
- New DB tables: add DDL to `database/postgres/schema.sql`, create repository in `database/`.
- New tests: add `test_*.py` in `tests/`.
- New shared utilities: add to `common/`.
- Generated runtime data (`data/screenshots/`, `data/exports/`, `logs/`): not committed.
- ML model weights (`anpr/models/`): committed binary files, trained externally.
- Env/config files: `.env` (gitignored), `config/settings.yaml` (bind-mounted in Docker).

---

## Environment Setup

### Required Tooling

- Required tools: Docker, Docker Compose
- Install dependencies: `docker compose build`
- Start local environment: `docker compose up -d`
- Start dependent services only: `docker compose up -d postgres`
- Seed / bootstrap data: Schema bootstraps lazily on first DB write; also mounted as Docker init script
- Load environment variables from: `.env` (copy from `.env.example`)
- Required local services: PostgreSQL 16 (via Docker)

### Setup Notes

- Copy `.env.example` to `.env` before first run.
- `config/settings.yaml` is bind-mounted from host (`./config:/app/config`).
- ANPR model weights (`anpr/models/yolo/best.pt`, `anpr/models/ocr_crnn/crnn_ocr_model_int8_fx.pth`) must be present.
- Docker is required for the standard deployment; no standalone Python run instructions exist.
- Database schema bootstrap is safe to run repeatedly (`CREATE TABLE IF NOT EXISTS`).
- No manual credentials or certificates are needed beyond `.env` values.

---

## Development Commands

| Task | Command | Scope | Notes |
| --- | --- | --- | --- |
| Build containers | `docker compose build` | repo | Builds API + worker images |
| Start all services | `docker compose up -d` | repo | Starts postgres, api, retention_worker, nginx |
| Stop all services | `docker compose down` | repo | Stops and removes containers |
| View logs | `docker compose logs -f api` | service | Follow API service logs |
| Run all tests | `pytest` | repo | Requires Python env with deps installed |
| Run one test file | `pytest tests/test_track_aggregator.py` | repo | — |
| Run one test case | `pytest tests/test_track_aggregator.py::TestTrackAggregator::test_emits_on_quorum` | repo | — |
| Run tests verbose | `pytest -v` | repo | Shows individual test names |

### Verification Strategy

1. Run the specific test file related to your change.
2. Run `pytest` for the full test suite.
3. For API or runtime changes, test manually via `docker compose up` and the web UI or curl.
4. For settings schema changes, verify migration compatibility path is updated.

---

## Testing Guide

- Test framework(s): pytest (no config file — uses defaults)
- Unit test location(s): `tests/`
- Integration test location(s): none
- E2E test location(s): none
- Contract test location(s): none
- Naming pattern(s): `test_*.py` files, `Test*` classes, `test_*` methods
- CI workflow location: none (no CI pipeline configured)

### Testing Rules

- Framework: pytest. No mocking libraries — use test doubles (simple class implementations) instead.
- Test files go in `tests/` at project root, named `test_<component>.py`.
- Tests are grouped in classes prefixed with `Test`, methods named `test_<behavior>`.
- Test data builders are module-level functions prefixed with underscore: `_blank()`, `_ru_country()`.
- If you change core logic (aggregator, validator, detector, motion), add or update corresponding tests.
- Every behavior change should be backed by tests when practical.
- Bug fixes should include a regression test when practical.
- No mocking library (`unittest.mock`, `pytest-mock`); use inline stub classes that implement the expected interface.
- Use `pytest.approx()` for floating-point comparisons.
- Use plain `assert` statements (pytest rewrites).

### Test Matrix

| Test Type | Path / Scope | Command | When To Run |
| --- | --- | --- | --- |
| Unit | `tests/test_track_aggregator.py` | `pytest tests/test_track_aggregator.py` | Changes to TrackAggregator |
| Unit | `tests/test_plate_validator.py` | `pytest tests/test_plate_validator.py` | Changes to PlatePostProcessor or country configs |
| Unit | `tests/test_motion_detector.py` | `pytest tests/test_motion_detector.py` | Changes to MotionDetector |
| Unit | `tests/test_direction_estimator.py` | `pytest tests/test_direction_estimator.py` | Changes to TrackDirectionEstimator |
| All | `tests/` | `pytest` | Before any PR or after broad changes |

---

## Code Style And Naming

- Formatter: none (no automated formatter configured; consistent 4-space indentation)
- Linter: none formal (informal ruff/flake8 awareness via `# noqa: BLE001` comments)
- Type policy: type hints on all function signatures; `from __future__ import annotations` in every file
- Comments policy: Russian docstrings and inline comments for business logic; English for test method docstrings; `# noqa:` with rule codes for linter suppressions
- Import policy: absolute from project root (`from common.logging import get_logger`), relative within same package (`from .country_config import ...`); `TYPE_CHECKING` blocks for annotation-only imports
- Error handling style: `StorageUnavailableError` for DB issues → HTTP 503; broad `except Exception` with `# noqa: BLE001` in infrastructure code; Pydantic validators raise `ValueError` with Russian messages
- Logging style: Python `logging` module via `common/logging.py`; `get_logger(__name__)` at module level; `%s`/`%d` formatting (never f-strings in log calls); Russian log messages in pipeline code prefixed with channel label (`Канал {name} (id={id})`)
- Configuration style: JSON file with versioned schema, normalizer pipeline, migration runner

### Naming Conventions

| Item | Preferred | Avoid | Example |
| --- | --- | --- | --- |
| Files | `snake_case.py` | camelCase, PascalCase | `anpr_pipeline.py` |
| Directories | `snake_case` | camelCase | `anpr/postprocessing/` |
| Classes / components | `PascalCase` | snake_case | `ChannelProcessor`, `ANPRPipeline` |
| Functions / methods | `snake_case` | camelCase | `build_components()`, `process_frame()` |
| Private methods | `_snake_case` | no prefix | `_evict_stale()`, `_run_channel()` |
| Variables | `snake_case` | camelCase | `track_id`, `best_shots` |
| Constants | `UPPER_SNAKE_CASE` | lowercase | `SETTINGS_VERSION`, `DEFAULT_LEVEL` |
| Dataclasses | `PascalCase` | — | `ChannelMetrics`, `ReconnectConfig` |
| Private dataclasses | `_PascalCase` | — | `_TrackOCRState` |
| Pydantic models | `PascalCase` + `Payload` suffix | — | `ChannelPayload`, `ControllerPayload` |
| Test files | `test_<component>.py` | — | `test_track_aggregator.py` |
| Test classes | `Test<Component>` | — | `TestTrackAggregator` |
| Test methods | `test_<behavior>` | `test_works_correctly` | `test_no_emission_below_quorum` |
| Test helpers | `_<name>()` module-level | shared conftest | `_blank()`, `_ru_country()` |
| Branch names | `dev`, `feat/<description>`, `fix/<description>` | — | `dev`, `feat/export-csv` |

### Style Do / Don't

Do:

- always add `from __future__ import annotations` as the first import in every new Python file;
- use `get_logger(__name__)` for logging (never `logging.getLogger()` directly);
- use `%s`/`%d`/`%.2f` lazy formatting in log calls;
- write docstrings in Russian for classes and key methods;
- use `Protocol` from `typing` for duck-typing interfaces;
- use dataclasses for internal domain models, Pydantic `BaseModel` for API request validation;
- use keyword-only arguments for optional/config params;
- clamp config values in `__init__` with `max()`/`min()`.

Don't:

- create "utils" dumping grounds for unrelated logic;
- use f-strings in `logger.info()` / `logger.debug()` calls;
- use `logging.getLogger()` directly — always use `get_logger()` from `common/logging`;
- use mocking libraries — write simple test double classes instead;
- import from `controllers/` in `config/` (existing coupling is tech debt, do not add more).

---

## Preferred Patterns And Reference Implementations

### Good Examples To Copy

- `tests/test_track_aggregator.py`: well-structured unit tests with inline builders, behavior-focused test names, multiple test classes per file
- `tests/test_plate_validator.py`: good example of testing with custom config loaders (inline stubs), YAML loading, section separators
- `anpr/pipeline/anpr_pipeline.py`: proper channel-context logging pattern (`_channel_label`), protocol-based dependency injection
- `anpr/pipeline/factory.py`: factory function pattern, shared singleton with thread-safe lazy init
- `anpr/postprocessing/validator.py`: clean domain logic with country-specific regex validation
- `app/api/container.py`: container pattern for dependency wiring with `build()` classmethod

### Patterns To Avoid Copying

- Legacy monolithic `app/web/app.js` pattern (removed) — `innerHTML` XSS risks and global mutable state still exist in some modules under `app/web/js/`, do not extend these patterns
- Broad `except Exception` blocks in `database/` repositories — existing tech debt, prefer specific exception types in new code
- `PUT /api/channels/{channel_id}` accepting raw `Dict[str, Any]` — use Pydantic validation for new endpoints

---

## Data, Contracts, Codegen, And Migrations

- Schema location: `database/postgres/schema.sql`
- Migration location: `config/settings_migrations/` (settings schema migrations, not DB migrations)
- API contract location: `app/api/routers/` + `app/api/schemas.py` (no OpenAPI spec file; auto-generated by FastAPI)
- Event contract location: none
- Generated code location: none
- Regeneration command: none

### Rules

- PostgreSQL schema bootstrap is lazy (on first write) and idempotent (`CREATE TABLE IF NOT EXISTS`).
- `schema.sql` is also mounted as Docker init script for fresh databases.
- Settings schema changes require version bump and migration path (see Settings Schema Versioning below).
- Preserve backward compatibility for API responses unless the task explicitly allows a breaking change.

### Settings Schema Versioning Rules

- Any change to `config/settings.yaml` schema (new parameter, removed/renamed field, changed structure or value format) requires bumping the settings schema version.
- When bumping the schema version, always add or update the upgrade/migration path for old configs to the new version.
- Do not add new settings parameters without accounting for the versioning/compatibility mechanism.
- Do not add, rename, or remove settings fields without updating the compatibility/upgrade path.
- A task is not complete if the settings schema changed but the migration path was not updated.

---

## Security And Safety Boundaries

### Hard Rules

- Never commit secrets, private keys, access tokens, or production credentials.
- Never hardcode secrets in source code, tests, fixtures, or documentation.
- Redact sensitive values in logs and examples.
- Validate and sanitize untrusted input at the proper boundary.
- RTSP credentials are embedded in stream URLs in `config/settings.yaml` — treat this file as sensitive.
- Controller passwords are stored in `config/settings.yaml` — same sensitivity.

### Human Approval Required Before

- deleting data or files;
- applying irreversible migrations;
- changing auth or permission logic;
- changing deployment or production infrastructure;
- installing or replacing major dependencies;
- rotating secrets or changing security configuration.

### Sensitive Areas

- Authentication / authorization: `app/api/auth.py` (APIKeyMiddleware), `API_KEY` env var
- Personal or regulated data: plate numbers in `database/postgres_event_repository.py`, screenshot images in `data/screenshots/`
- Production configuration / infrastructure: `docker-compose.yml`, `nginx/default.conf`, `.env`
- Credentials: RTSP URLs and controller passwords in `config/settings.yaml`

---

## Git, PR, And Definition Of Done

- Branch naming convention: `dev` (development), `feat/<description>`, `fix/<description>`
- Commit message convention: free-form (no strict conventional commits enforced)
- PR title convention: no strict format; PRs should be written in Russian
- Changelog policy: none
- Release notes policy: none

### PR Rules

- Make all Pull Requests in Russian.
- In the PR description, briefly explain: what changed, why it changed, whether README was updated.

### Definition Of Done

A change is not complete until:

1. relevant tests pass (run `pytest`);
2. tests are added or updated where needed;
3. `README.md` is updated if user-visible behavior, API, architecture, storage, or runtime flow changed (in Russian);
4. file placement and naming follow this document;
5. settings schema version is bumped if settings were changed;
6. settings migration path is updated if schema version was bumped;
7. assumptions, risks, and follow-up work are documented.

---

## Documentation Rules

- `README.md` is part of the product documentation, not disposable text.
- Do not delete README sections, diagrams, tables, examples, or architecture notes unless they are truly obsolete.
- If documentation becomes outdated because of your code change, update it accurately instead of deleting it.
- Do not simplify README by removing diagrams or explanatory blocks just to make the diff smaller.
- When adding or changing user-visible behavior, API, architecture, storage, or runtime flow, update `README.md` in Russian.

---

## Logging Rules

- Log levels: `ALL`, `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.
- `ALL` (NOTSET) enables full verbose output including DEBUG; `INFO` filters DEBUG out.
- OCR pipeline logs must include channel context (`Канал {name} (id={id})`).
- OCR result and pipeline log messages must be in Russian (after the logger/module prefix).
- `INFO` mode: concise summaries (consensus reached, budget exhausted, candidate rejected).
- `ALL` mode: per-attempt OCR diagnostics, validator results, matched country/template.
- Do not pollute logs with unrelated third-party debug noise.
- Use `get_logger(__name__)` from `common/logging` — never `logging.getLogger()` directly.
- Use `%s`/`%d`/`%.2f` lazy formatting in log calls — never f-strings.

---

## Database Rules

- PostgreSQL is the only supported storage backend for runtime data.
- Do not add SQLite, dual-write, fallback storage paths, or compatibility layers.
- Do not introduce a second source of truth for settings if existing settings/config already covers the case.
- Both `PostgresEventDatabase` and `ListDatabase` use `psycopg_pool.ConnectionPool` (min=2, max=10).
- Do not replace connection pooling with per-request connections.
- Schema bootstrap is lazy (on first write). `database/postgres/schema.sql` is also mounted as init script in Docker.
- If you change storage behavior, keep docs and config consistent with the real implementation.

---

## Known Pitfalls

- Settings changes do not affect running channels until the channel is restarted. Only reconnect settings are dynamically updated.
- The YOLO detector uses internal `ultralytics` tracker API attributes (`model.predictor.trackers`, `predictor.vid_path`) — upgrading ultralytics may break tracking silently.
- `refresh_storage_clients()` in `app/api/container.py` creates new DB pool instances without closing old ones — potential connection leak.
- `PUT /api/channels/{channel_id}` accepts raw dict without validation — do not use this pattern for new endpoints.
- Channel threads are daemon threads with 3-second join timeout — `stop()` may return before the thread exits if blocked on `cap.read()`.
- `innerHTML` usage in frontend modules (`app/web/js/`) creates XSS risk — use `textContent` or `createElement` for new frontend code.
- The settings normalizer imports from `controllers/` — known coupling, do not add more cross-domain imports in `config/`.
- JPEG preview encoding runs on every frame regardless of whether any client is viewing.

---

## When The Agent Must Stop And Ask

The agent should pause and ask a human when:

- requirements are ambiguous and there are multiple valid implementations;
- a change may break API compatibility, data compatibility, or deployment safety;
- documentation and code materially disagree;
- tests fail for reasons unrelated to the task and the cause is unclear;
- the task requires secrets, production access, or product-policy decisions;
- the safest path depends on a tradeoff the user has not chosen;
- the change involves auth logic, settings schema version bumps, or database schema changes.

---

## Cross-Tool Alignment

This repository also uses:

- `CLAUDE.md` — Claude Code specific instructions (if present)
- `README.md` — project documentation (Russian, kept up-to-date with architecture)
- `AGENTS_old.md` — previous version of this file (historical reference only)

Prefer `AGENTS.md` as the authoritative source for agent behavior.
