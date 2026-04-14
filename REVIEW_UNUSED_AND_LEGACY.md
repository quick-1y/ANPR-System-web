# Unused, Legacy, and Dead Code — Inventory
## ANPR System v0.8 Web

**Review date:** 2026-04-14

---

## Table 1: Safe to Remove Now

Evidence-based. These are confirmed dead on a fresh-DB runtime.

| ID | Location | What it is | Evidence of non-use |
|----|----------|------------|---------------------|
| R-01 | `schema.sql:17-26` | DO $$ migration guard for `plate_display` | Column already in CREATE TABLE on line 7 |
| R-02 | `schema.sql:49-58` | DO $$ migration guard for `password_changed_at` | Column already in CREATE TABLE on line 47 |
| R-03 | `lists_repository.py:62-70` | `ALTER TABLE … ADD COLUMN IF NOT EXISTS` for `is_deleted`, `last_name`, `first_name`, `middle_name`, `phone`, `car`, `comment` | All 7 columns declared in CREATE TABLE on lines 51-70 |
| R-04 | `lists_repository.py:73` | `DROP INDEX IF EXISTS uq_clients_list_plate` | Index never exists on fresh DB; DROP is a migration step |
| R-05 | `settings_normalizer.py:76-79` | Removes `export_dir` from storage settings | Field not in current schema, never written on fresh install |
| R-06 | `settings_normalizer.py:120-124` | Removes `ocr.confidence_threshold` | Field not in current schema, never written on fresh install |

---

## Table 2: Needs Verification Before Removal

These are referenced by live code but their removal depends on confirming that no active deployments use the old format.

| ID | Location | What it is | Why uncertain |
|----|----------|------------|---------------|
| V-01 | `settings_migrations/runner.py:17-34` (`_apply_legacy_compat`) | Handles configs without `settings_lineage` key | Needed for existing deployments with pre-lineage YAML configs. Safe to remove only if all deployed settings.yaml files have been confirmed to contain `settings_lineage: mainline`. |
| V-02 | `schema.sql:30` | `idx_events_channel ON events(channel)` index | Used in `fetch_for_export` fallback only when `channel_id` is None. Verify whether any current client passes `channel` text without `channel_id`. |

---

## Table 3: Should Be Refactored, Not Removed

These are problems where the code does the wrong thing or does more than needed, but outright deletion would break things.

| ID | Location | What it is | Recommended action |
|----|----------|------------|--------------------|
| RF-01 | `database/lists_repository.py` SQL aliases | `e` alias used for `clients` table in all SQL queries | Rename `e` → `c` throughout all SQL in the file |
| RF-02 | `database/clients_repository.py:13-16` | `_schema_sql()` returning `SELECT 1` | Introduce shared schema bootstrap so `ClientDatabase` doesn't silently depend on `ListDatabase` running first |
| RF-03 | `runtime/channel_runtime.py:549` | Direct access to `pipeline.aggregator._track_states` | Replace with a new public method `TrackAggregator.has_active_tracks()` |
| RF-04 | `app/api/container.py:208-226` (`refresh_storage_clients`) | Replaces all DB clients but doesn't update `processor._lists_db` | Add `self.processor._lists_db = self.lists_db` after rebuilding lists_db |
| RF-05 | `app/api/auth_utils.py:15` | Default JWT secret hardcoded in source | Raise RuntimeError at startup if env var is not set |
| RF-06 | `app/api/routers/channels.py:145` | `update_channel()` accepts raw `Dict[str, Any]` | Add Pydantic schema or validate keys explicitly |
| RF-07 | `runtime/channel_runtime.py:85-87` | Fallback DB construction path with empty DSN | Raise `ValueError` if `events_db` is not passed |
| RF-08 | `anpr/pipeline/anpr_pipeline.py:30` | Module-level `_CONSECUTIVE_FAILURE_LIMIT` constant | Move inside `TrackAggregator` as class constant |

---

## Table 4: Migration / Backfill / Compatibility Code to Eliminate

For details, see `REVIEW_MIGRATION_COMPAT.md`.

| ID | Location | Lines | Type | Action |
|----|----------|-------|------|--------|
| M-01 | `schema.sql:17-26` | 9 | DB migration guard | Remove |
| M-02 | `schema.sql:49-58` | 9 | DB migration guard | Remove |
| M-03 | `lists_repository.py:62-74` | 13 | ALTER TABLE backfill | Remove (keep CREATE UNIQUE INDEX) |
| M-04 | `settings_normalizer.py:76-79` | 4 | Old field cleanup | Remove |
| M-05 | `settings_normalizer.py:120-124` | 4 | Old field cleanup | Remove |
| M-06 | `settings_migrations/runner.py:17-34` | ~18 | Legacy config compat | Remove only after all existing configs confirmed upgraded |

---

## Notes on Frontend

The frontend JS does not have unused modules. All 18 JS files under `app/web/js/` are imported and used. However, the following patterns are legacy antipatterns that need refactoring (not removal):

| File | Lines | Issue |
|------|-------|-------|
| `events.js` | 96, 220 | `innerHTML` with database values (XSS) |
| `clients.js` | 26-32, 162 | `innerHTML` with database values (XSS) |
| `lists.js` | 65, 94-98, 129 | `innerHTML` with database values (XSS) |
| `journal.js` | 76 | `innerHTML` with database values (XSS) |
| `debug.js` | 22 | `innerHTML` with log text (XSS) |
| `lists.js` | 229-250 | Sequential per-row HTTP in CSV import |
