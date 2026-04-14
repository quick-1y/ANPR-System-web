# Migration, Backfill, and Compatibility Code Report
## ANPR System v0.8 Web

**Review date:** 2026-04-14  
**Context:** This project uses a fresh database on every run. No database migrations are needed. Old-version compatibility layers are not needed unless the current runtime still truly depends on them.

---

## Summary

| # | Location | Type | Lines | Safe to remove? |
|---|----------|------|-------|-----------------|
| M-01 | `database/postgres/schema.sql:17-26` | Migration guard (DO $$) | 9 | Yes |
| M-02 | `database/postgres/schema.sql:49-58` | Migration guard (DO $$) | 9 | Yes |
| M-03 | `database/lists_repository.py:62-74` | ALTER TABLE compat columns | 13 | Yes |
| M-04 | `config/settings_normalizer.py:76-79` | Removes legacy `export_dir` field | 4 | Yes |
| M-05 | `config/settings_normalizer.py:120-124` | Removes legacy `ocr.confidence_threshold` | 4 | Yes |
| M-06 | `config/settings_migrations/runner.py:17-34` | `_apply_legacy_compat()` | ~18 | Conditional |

---

## M-01: `schema.sql` — `plate_display` migration guard

**Severity:** medium  
**Confidence:** high

**Evidence:**  
`database/postgres/schema.sql:17-26`:
```sql
-- Migration: add plate_display column to existing installations.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'events' AND column_name = 'plate_display'
    ) THEN
        ALTER TABLE events ADD COLUMN plate_display TEXT;
    END IF;
END $$;
```

The `plate_display TEXT` column is already defined in the `CREATE TABLE events` on line 7. On a fresh database, this `DO $$` block runs an `information_schema` query to check if the column exists, finds it (because CREATE TABLE just ran), and does nothing. This is pure dead work.

**Why it should be removed:**  
With a fresh DB on every run, the CREATE TABLE statement always includes `plate_display`. The DO $$ block is a migration shim for an older schema where the column was added later. It adds an unnecessary `information_schema` query on every cold start.

**Recommended fix:**  
Remove lines 17-26 from `schema.sql`. The column is already in CREATE TABLE.

---

## M-02: `schema.sql` — `password_changed_at` migration guard

**Severity:** medium  
**Confidence:** high

**Evidence:**  
`database/postgres/schema.sql:49-58`:
```sql
-- Migration: add password_changed_at column to existing installations.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'password_changed_at'
    ) THEN
        ALTER TABLE users ADD COLUMN password_changed_at TIMESTAMPTZ DEFAULT NULL;
    END IF;
END $$;
```

The `password_changed_at TIMESTAMPTZ DEFAULT NULL` column is already defined in the `CREATE TABLE users` on line 47. Identical situation to M-01.

**Recommended fix:**  
Remove lines 49-58 from `schema.sql`.

---

## M-03: `ListDatabase._schema_sql()` — 7 ALTER TABLE backward-compat statements

**Severity:** medium  
**Confidence:** high

**Evidence:**  
`database/lists_repository.py:62-74`:
```sql
ALTER TABLE lists ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS last_name TEXT NOT NULL DEFAULT '';
ALTER TABLE clients ADD COLUMN IF NOT EXISTS first_name TEXT NOT NULL DEFAULT '';
ALTER TABLE clients ADD COLUMN IF NOT EXISTS middle_name TEXT NOT NULL DEFAULT '';
ALTER TABLE clients ADD COLUMN IF NOT EXISTS phone TEXT NOT NULL DEFAULT '';
ALTER TABLE clients ADD COLUMN IF NOT EXISTS car TEXT NOT NULL DEFAULT '';
ALTER TABLE clients ADD COLUMN IF NOT EXISTS comment TEXT NOT NULL DEFAULT '';
```

All 8 columns (`is_deleted`, `last_name`, `first_name`, `middle_name`, `phone`, `car`, `comment`) are already declared in the `CREATE TABLE clients` statement on lines 51-70. On a fresh DB, these ALTER statements check whether each column exists and find it, doing nothing. This is dead code that runs on every first query to `ListDatabase`.

Additionally, line 73-74:
```sql
DROP INDEX IF EXISTS uq_clients_list_plate;
CREATE UNIQUE INDEX IF NOT EXISTS uq_clients_list_plate ON clients(list_id, plate_normalized) WHERE is_deleted = FALSE;
```
The DROP is a migration that removes an old index before recreating it. On a fresh DB, the old index never existed and `DROP INDEX IF EXISTS` silently does nothing.

**Why it should be removed:**  
These ALTER TABLE statements were added to backfill columns into databases that predate those fields. On a clean schema they are no-ops with overhead.

**Recommended fix:**  
Remove lines 62-74 (the 8 ALTER TABLE statements). The columns are already in CREATE TABLE. Keep the `CREATE UNIQUE INDEX` on line 74, but remove the `DROP INDEX IF EXISTS` on line 73 (replace with just the CREATE UNIQUE INDEX IF NOT EXISTS).

After cleanup, `_schema_sql()` should contain only CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS statements.

---

## M-04: `settings_normalizer.py` — removes legacy `export_dir` field

**Severity:** low  
**Confidence:** high

**Evidence:**  
`config/settings_normalizer.py:76-79`:
```python
if "export_dir" in storage:
    storage.pop("export_dir", None)
    changed = True
```

This removes a field that existed in an old version of the settings schema (`storage.export_dir`). The current schema no longer has this field. On a fresh install, `export_dir` never exists and this block does nothing.

**Why it should be removed:**  
The old schema with `export_dir` is no longer used. If any running instance still has the field in their `settings.yaml`, they should be migrated manually (or the migration runner should handle it explicitly with a version bump rather than a silent normalizer patch).

**Recommended fix:**  
Remove lines 76-79. If this is still needed for an active user base with old configs, move it into `settings_migrations/runner.py` as a named migration step tied to a version increment.

---

## M-05: `settings_normalizer.py` — removes legacy `ocr.confidence_threshold`

**Severity:** low  
**Confidence:** high

**Evidence:**  
`config/settings_normalizer.py:120-124`:
```python
# Remove legacy confidence_threshold — OCR confidence is per-channel (ocr_min_confidence)
if "confidence_threshold" in ocr:
    del ocr["confidence_threshold"]
    changed = True
```

This removes `ocr.confidence_threshold`, which existed in an older schema where confidence was a global setting. The current schema uses per-channel `ocr_min_confidence`. On a fresh install, `confidence_threshold` never exists under `ocr`.

**Recommended fix:**  
Same as M-04: remove the block or move to a versioned migration step.

---

## M-06: `settings_migrations/runner.py` — `_apply_legacy_compat()`

**Severity:** low  
**Confidence:** medium

**Evidence:**  
`config/settings_migrations/runner.py:17-34`:
```python
def _apply_legacy_compat(data: Dict[str, Any]) -> Dict[str, Any]:
    """Подтягивает legacy-конфиг (исторические форматы ROI/direction) к текущему виду полей."""
    ...
    # Fills direction defaults into tracking section
    # Normalizes channel region config to current format
```

Called at `runner.py:63` when `settings_lineage` key is absent from the config:
```python
if lineage is None:
    upgraded = _apply_legacy_compat(migrated)
```

This handles YAML configs written before `settings_lineage` was added to the schema.

**Why this is conditional:**  
- On a **fresh install** (no `settings.yaml`), `SettingsRepository` creates a new config from defaults, which always includes `settings_lineage`. The `lineage is None` branch is never taken.
- On an **existing deployment** where `settings.yaml` was created by an older version (before `settings_lineage` was added), this branch runs exactly once, upgrades the config, writes it back with `settings_lineage: mainline`, and never runs again.

**Assessment:**  
This is **legacy code but still potentially needed** if any active deployments have old config files. If the team controls all deployments and has already upgraded all config files, the `_apply_legacy_compat` function and the `lineage is None` branch can be removed. If there are unknown deployments with old configs, keep it.

**Recommended fix:**  
- If removing: collapse the `lineage is None` check in `run_settings_migrations` into the `else` (unsupported lineage) branch, and delete `_apply_legacy_compat`.
- If keeping: add a `TODO: remove after v1.0` comment with evidence of when all deployments were confirmed to have `settings_lineage`.

---

## What Should Definitely Stay

The `run_settings_migrations` runner framework itself should remain. It is:
1. The correct place to handle future schema version bumps
2. Already wired into `SettingsNormalizer.normalize_with_meta()`
3. Has a proper version/lineage guard (`_validate_current_lineage_version`)

Only the legacy content inside it (`_apply_legacy_compat`) is a candidate for removal.

---

## Impact of Full Removal

After removing M-01 through M-05:
- `schema.sql`: 18 lines shorter, cleaner intent
- `lists_repository._schema_sql()`: 13 lines shorter, pure CREATE TABLE + CREATE INDEX
- `settings_normalizer.py`: 8 lines shorter, no silent field removals
- No functional change on fresh DB (which is the documented operating mode)
- **Risk:** If applied to an existing deployment without a migration step, old DBs with missing columns would break on first query. This is only a risk if the code is deployed to existing installations without a fresh schema.
