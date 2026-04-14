# Architectural Review — Executive Summary
## ANPR System v0.8 Web

**Review date:** 2026-04-14  
**Reviewer:** Automated deep-analysis (Claude Sonnet 4.6)  
**Branch:** dev_db_ref

---

## Overall Assessment

The project has a **solid foundation**: clear layered architecture, proper dependency injection, a central `AppContainer`, parameterised SQL throughout, protocol-based OCR abstraction, and a reasonably well-tested domain layer. Architecture quality is above average for an active MVP.

However, **several concrete problems exist** that will create maintenance pain, security exposure, or silent runtime bugs as the project grows. None are architectural disasters, but most should be addressed before the first production release.

---

## Main Risks (ranked)

| # | Risk | Severity | Confidence |
|---|------|----------|------------|
| 1 | XSS: database values injected via `innerHTML` in 5 JS files | high | high |
| 2 | `refresh_storage_clients()` replaces `container.lists_db` but the running `ChannelProcessor` still holds the old reference — list lookups in the recognition loop silently use a stale object | high | high |
| 3 | `_io_pool` (ThreadPoolExecutor) in `ChannelProcessor` is never shut down — file-write threads may outlive the process | medium | high |
| 4 | `channel_runtime.py:549` directly reads `pipeline.aggregator._track_states` — private coupling, breaks if `TrackAggregator` internals change | medium | high |
| 5 | Migration-guard `DO $$` blocks in `schema.sql` run on every cold start against a fresh DB (dead work, hides schema intent) | medium | high |
| 6 | `ListDatabase._schema_sql()` contains 7 `ALTER TABLE … ADD COLUMN IF NOT EXISTS` statements that exist only for backward compat with old installs | medium | high |
| 7 | Default `JWT_SECRET_KEY = "anpr-default-secret-change-me"` in `auth_utils.py` — trivially guessable if env var not set in deployment | medium | high |
| 8 | `idx_events_timestamp` and `idx_events_channel_id` indexes are covered by wider composite indexes already present in the schema — wasted storage and write overhead | low | high |
| 9 | `ClientDatabase._schema_sql()` returns `SELECT 1` — hidden implicit dependency: `ListDatabase._ensure_schema()` must run first on the same DSN | medium | medium |
| 10 | Daemon thread spawned inside an HTTP handler (`update_channel`) for `sync_channel_runtime` — fire-and-forget with no error surface | low | high |

---

## Highest-Priority Cleanup Opportunities

1. **Fix XSS** — replace `innerHTML` with user-controlled data with `textContent` / `createElement` in `events.js`, `clients.js`, `lists.js`, `journal.js`, `debug.js`. Attackers can inject HTML via plate numbers or client names stored in the DB.

2. **Sync `processor._lists_db` after `refresh_storage_clients()`** — one-line fix: after rebuilding `self.lists_db`, call `self.processor._lists_db = self.lists_db`.

3. **Remove the 7 `ALTER TABLE … ADD COLUMN IF NOT EXISTS` lines from `ListDatabase._schema_sql()`** — the `CREATE TABLE` already defines all columns. These only exist for old installations that predate those columns. With a fresh DB, they are dead code that runs on every startup.

4. **Remove migration `DO $$` blocks from `schema.sql`** — both guarded `ALTER TABLE` blocks (`plate_display`, `password_changed_at`) are already in the `CREATE TABLE` definition. Remove them.

5. **Add `_io_pool.shutdown(wait=False)` to `ChannelProcessor` teardown** — prevents orphaned file-write threads after process stop.

6. **Add `TrackAggregator.has_active_tracks()`** — expose a public method so `channel_runtime.py` does not need to read `aggregator._track_states` directly.

---

## Migration / Backfill / Compatibility Code Assessment

**Exists — and can be aggressively removed:**

| Location | Type | Safe to remove? |
|----------|------|-----------------|
| `schema.sql` lines 17-26, 49-58 | Migration guards (DO $$ blocks) | Yes — columns already in CREATE TABLE |
| `lists_repository.py` `_schema_sql()` lines 62-74 | ALTER TABLE backfill columns | Yes — CREATE TABLE already defines them |
| `settings_normalizer.py:76-79` | Removes old `export_dir` field | Yes — was for old config format |
| `settings_normalizer.py:121-123` | Removes old `ocr.confidence_threshold` | Yes — was for old config format |
| `settings_migrations/runner.py` `_apply_legacy_compat()` | Legacy config path (no `settings_lineage`) | Conditional — needed only if existing YAML configs exist without the lineage key |

The `run_settings_migrations` runner itself should stay; only the legacy compat path inside it is a candidate for removal once all deployed configs have been upgraded.

---

## Summary Score

| Area | Score | Notes |
|------|-------|-------|
| Architecture separation | 8/10 | Clean layers, good DI |
| Naming consistency | 6/10 | `e` alias for clients, redundant "plate" prefixes, some misleading names |
| Security | 5/10 | XSS in 5 JS files, default JWT secret |
| Database schema cleanliness | 6/10 | Migration leftovers in two places |
| Performance risks | 7/10 | Minor issues, no critical bottlenecks |
| Maintainability | 7/10 | Private state access, fire-and-forget threads, implicit schema ordering |

**Overall: 6.5/10 — Good foundation, concrete cleanup list is manageable.**
