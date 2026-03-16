# Web ANPR System

This project is a web-first automatic number plate recognition system.

The system processes multiple video channels on the server side.
Each channel must work independently from the others.

## Core principles

- SOLID
- DRY
- KISS
- Modularity
- Clear separation of responsibilities between UI, API, runtime, and storage

## Architectural rules

- Keep the project web-only. Do not add desktop GUI, local operator UI, or other non-web entrypoints.
- Keep ANPR logic on the server side. Do not move detection, OCR, tracking, or postprocessing into the browser.
- Keep channels isolated. Failure or restart of one channel must not break other channels.
- Keep service boundaries clear:
  - `app/api` — API, web entrypoint, channel management, SSE, settings
  - `app/worker` — retention and background jobs
  - `packages/anpr_core` — channel runtime and orchestration
  - `anpr` — domain logic, pipeline, OCR, detection, storage, controllers

## Change rules

- Make minimal, targeted changes.
- Do not rewrite working code without a clear reason.
- Do not rename/move files массово without necessity.
- Prefer fixing the root cause over adding temporary hacks.
- Preserve backward compatibility where practical.

## Documentation rules

- `README.md` is part of the product documentation, not disposable text.
- Do not delete README sections, diagrams, tables, examples, or architecture notes unless they are truly obsolete.
- If documentation becomes outdated because of your code change, update it accurately instead of deleting it.
- Do not simplify README by removing diagrams or explanatory blocks just to make the diff smaller.
- Keep architecture diagrams in `README.md` unless the architecture really changed and you replace them with updated ones.
- Keep the project structure section in `README.md` up to date.
- When adding or changing user-visible behavior, API, architecture, storage, or runtime flow, update `README.md` in Russian.

## Storage and config rules

- PostgreSQL is the only supported storage backend for runtime data.
- Do not add SQLite, dual-write, fallback storage paths, or compatibility layers.
- Do not introduce a second source of truth for settings if existing settings/config already cover the case.
- If you change storage behavior, keep docs and config consistent with the real implementation.
- Do not claim a migration or refactor is complete unless the code actually matches that claim.

## Pull Requests

- Make all Pull Requests in Russian.
- In the PR description, briefly explain:
  - what changed
  - why it changed
  - whether README was updated

## Forbidden actions

- Do not remove documentation just because it looks redundant.
- Do not remove diagrams from `README.md` unless you replace them with correct updated diagrams.
- Do not convert the project back to desktop architecture.
- Do not couple channels together.
- Do not move core business logic into frontend code.
- Do not make large cleanup-only refactors outside the task scope.

## Settings schema versioning rules

- Любое изменение схемы `config/settings.yaml` (новый параметр, удаление/переименование поля, изменение структуры, изменение формата значения) обязательно требует повышения версии схемы настроек.
- При повышении версии схемы обязательно добавляйте/обновляйте путь совместимости (upgrade/migration) до новой актуальной версии для старых конфигов.
- Нельзя добавлять новые параметры в схему без учета versioning/compatibility механизма.
- Нельзя добавлять, переименовывать или удалять поля настроек без обновления механизма совместимости (compatibility/upgrade path).
- Нельзя считать задачу завершенной, если схема настроек изменилась, а механизм подтягивания старых конфигов до актуальной версии не обновлен.
