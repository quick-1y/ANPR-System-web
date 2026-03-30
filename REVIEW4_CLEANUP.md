# REVIEW #4 — Cleanup Candidates

**Date:** 2026-03-28

---

## Safe to Remove Now

| # | Item | File | Lines | Evidence |
|---|------|------|-------|----------|
| 1 | ~~`RELAY_MODES` dict~~ ✅ Removed | `controllers/service.py` | 20-23 | Grep: no reads outside `__all__` and re-export |
| 2 | ~~`CONTROLLER_TYPES` dict~~ ✅ Removed | `controllers/service.py` | 14-16 | Only `SUPPORTED_CONTROLLER_TYPES` (tuple) is used |
| 3 | ~~`normalize_region_config` wrapper~~ ✅ Removed | `config/settings_manager.py` | 31-32 | Module-level function with zero callers |
| 4 | ~~`import os` in TYPE_CHECKING~~ ✅ Removed (Task 1) | `anpr/pipeline/factory.py` | 14 | Unused import |
| 5 | ~~`favicon` endpoint~~ ✅ Removed | `app/worker/main.py` | 123-125 | Returns dummy JSON, no real favicon |

## Needs Verification Before Removal

| # | Item | File | Concern |
|---|------|------|---------|
| 1 | `get_inference_settings()` | `settings_manager.py:417` | No internal callers. May be used by external tools |
| 2 | `inference_defaults()` | `settings_schema.py:92` | Referenced in `build_default_settings()` — removing changes YAML structure |
| 3 | `build_command_url` standalone | `controllers/service.py:26` | In `__all__`, only called internally. Might be public API |
| 4 | `_FallbackRecognizer` | `anpr/pipeline/factory.py:24-31` | Safety fallback during init race. Removing may cause crash on startup |

## Should Be Refactored, Not Removed

| # | Item | File | Action |
|---|------|------|--------|
| 1 | ~~14 delegation methods~~ ✅ Removed | `settings_manager.py:111-151` | Remove pass-throughs, call normalizer directly |
| 2 | ~~Worker `on_event` lifecycle~~ ✅ Done | `app/worker/main.py:75,83` | Migrated to `lifespan` context manager |
| 3 | ~~`config` imports `controllers`~~ ✅ Done | `settings_normalizer.py:17` | Moved to `config/settings_schema.py` |
| 4 | ~~Duplicate pool init~~ ✅ Done | `postgres_event_repository.py` + `plate_lists_repository.py` | Extracted `PooledDatabase` base class in `database/base.py` |
| 5 | ~~`"Нечитаемо"` string sentinel~~ ✅ Done | `anpr_pipeline.py:432,482,541` | Replaced with boolean `unreadable` flag; display string moved to event layer |
| 6 | ~~Duplicate DSN resolution~~ ✅ Done | `app/api/container.py` (3 places) | Extracted `_resolve_dsn()` helper |
| 7 | ~~Inconsistent error handling~~ ✅ Done | `plate_lists_repository.py:156` | Now raises `StorageUnavailableError` like other methods |
| 8 | Monolithic `app.js` (3138 lines) ⏳ In progress (2026-03-30 step 1) | `app/web/app.js`, `app/web/js/api.js`, `app/web/js/state.js`, `app/web/js/channels.js`, `app/web/index.html` | Steps 1-3 done: API/auth extracted to `api.js`, shared state extracted to `state.js`, channels block extracted to `channels.js`; continue incremental module split |
