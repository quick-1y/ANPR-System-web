# Independent Implementation Tasks
## ANPR System v0.8 Web — Cleanup and Optimization Roadmap

**Review date:** 2026-04-14  
**Source:** REVIEW_FULL_REPORT.md, REVIEW_MIGRATION_COMPAT.md, REVIEW_UNUSED_AND_LEGACY.md

Each task is self-contained. Tasks do not depend on each other unless explicitly noted. They can be given one by one for implementation.

---

## TASK-01: Remove migration DO $$ blocks from schema.sql

**Problem:**  
`database/postgres/schema.sql` contains two `DO $$` migration guards (lines 17-26 and 49-58) that check `information_schema.columns` before adding columns. Both columns (`plate_display`, `password_changed_at`) are already declared in the `CREATE TABLE` statements above them. On a fresh DB these blocks run two unnecessary `information_schema` queries at every cold start.

**What to change:**  
Remove lines 17-26 (the `plate_display` migration block) and lines 49-58 (the `password_changed_at` migration block) from `database/postgres/schema.sql`. No other changes needed.

**Files / modules affected:**  
- `database/postgres/schema.sql`

**Expected result:**  
Schema file is shorter and expresses only intent (not migration history). Cold-start time slightly reduced. No functional change on fresh DB.

**Risk level:** low — columns already present in CREATE TABLE. Only risk: if an existing installation uses this file for migration (e.g., old DB without those columns). Confirm fresh-DB-only deployment context first.

---

## TASK-02: Remove ALTER TABLE backward-compat lines from ListDatabase._schema_sql()

**Problem:**  
`database/lists_repository.py` lines 62-74 contain 7 `ALTER TABLE … ADD COLUMN IF NOT EXISTS` statements and one `DROP INDEX IF EXISTS`. All columns are already declared in the `CREATE TABLE clients` statement on lines 51-70. These ALTER TABLE lines exist only for old databases that predate those columns.

**What to change:**  
In `database/lists_repository.py`, inside `_schema_sql()`, remove lines 62-73 (the 7 ALTER TABLE ADD COLUMN statements and the DROP INDEX). Keep line 74 (`CREATE UNIQUE INDEX IF NOT EXISTS uq_clients_list_plate`). The result should be: CREATE TABLE lists, CREATE TABLE clients (with all columns), then CREATE INDEX statements only.

**Files / modules affected:**  
- `database/lists_repository.py`

**Expected result:**  
`_schema_sql()` contains only DDL that reflects the current schema intent. No migration history. Tests should continue to pass.

**Risk level:** low — same fresh-DB context note as TASK-01.

---

## TASK-03: Remove legacy field cleanup from SettingsNormalizer

**Problem:**  
`config/settings_normalizer.py` silently removes two fields from settings configs that existed in old schema versions:
- `storage.export_dir` (lines 76-79)
- `ocr.confidence_threshold` (lines 120-124)

These fields no longer exist in the current schema. On a fresh install the settings file never contains them. The cleanup code does nothing but adds confusion.

**What to change:**  
1. In `_fill_storage_defaults()`: remove lines 76-79 (the `if "export_dir" in storage:` block).  
2. In `_fill_ocr_defaults()`: remove lines 120-124 (the `if "confidence_threshold" in ocr:` block and its comment).

**Files / modules affected:**  
- `config/settings_normalizer.py`

**Expected result:**  
Normalizer only adds missing keys — it no longer silently removes old keys. Existing tests should pass. No functional change on current configs.

**Risk level:** low. Note: if any existing `settings.yaml` contains these fields, they will no longer be removed on load. This is fine — extra unknown keys are harmless.

---

## TASK-04: Remove redundant database indexes

**Problem:**  
`database/postgres/schema.sql` has two pairs of redundant indexes:
- `idx_events_timestamp ON events(timestamp DESC)` is fully covered by `idx_events_ts_id_desc ON events(timestamp DESC, id DESC)`
- `idx_events_channel_id ON events(channel_id, timestamp DESC)` is fully covered by `idx_events_channel_id_ts_id_desc ON events(channel_id, timestamp DESC, id DESC)`

PostgreSQL can use composite indexes as prefix scans. The narrower indexes waste storage and slow INSERT/UPDATE.

**What to change:**  
Remove from `schema.sql`:
```sql
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_channel_id ON events(channel_id, timestamp DESC);
```
Keep `idx_events_ts_id_desc` and `idx_events_channel_id_ts_id_desc`.

**Files / modules affected:**  
- `database/postgres/schema.sql`

**Expected result:**  
Two fewer indexes. Slightly faster event writes. All existing query patterns continue to use the composite indexes. No application code changes needed.

**Risk level:** low.

---

## TASK-05: Fix XSS — replace innerHTML with DB values in events.js

**Problem:**  
`app/web/js/events.js:96` sets `div.innerHTML` with `displayPlate` (from `event.plate_display`) and `channelName` (from `event.channel`). These are database-sourced values that could contain HTML. A stored XSS attack is possible.

**What to change:**  
In `makeItem()` function (events.js): replace the single `div.innerHTML = ...` assignment with a series of `createElement`/`textContent` operations. Build the inner elements:
- `ev-plate` span: `span.textContent = displayPlate`
- `ev-direction` span: `span.textContent = direction.label`
- `ev-meta-channel` span: `span.textContent = channelName`
- `ev-meta-time` span: `span.textContent = timeStr`
- `ev-conf` span: `span.textContent = conf.toFixed(2)`
- `flagHtml(item.country)` — this should only insert a known flag emoji or SVG, verify it is already safe

Also fix `openEventDetails()` (line 220): the `meta.innerHTML` assignment builds rows from DB values (`payload.channel`, client fields). Replace with DOM construction or an `esc()` HTML-escape helper.

**Files / modules affected:**  
- `app/web/js/events.js`

**Expected result:**  
Event feed and event detail modal no longer injectable via plate numbers or channel names. All visual output identical to current.

**Risk level:** medium — need to verify flag rendering and CSS class assignment work correctly after the refactor. Test in browser.

---

## TASK-06: Fix XSS — replace innerHTML with DB values in clients.js, lists.js, journal.js

**Problem:**  
Multiple innerHTML assignments use database-sourced values (plate numbers, client names, list names) without HTML escaping:
- `clients.js:26-32` — `tr.innerHTML` with plate, last_name, first_name, phone, car
- `clients.js:162` — `row.innerHTML` with list name
- `lists.js:65` — `div.innerHTML` with list name
- `lists.js:94-98` — `tr.innerHTML` with plate, first_name, last_name, phone, car, comment
- `lists.js:129-133` — picker row innerHTML with client label and plate
- `journal.js:76` — `tr.innerHTML` with time, plate, channel, country, confidence, direction

**What to change:**  
Create a shared `esc(str)` helper in `ui.js`:
```javascript
export function esc(str) {
    return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
```
Import and use it in all template literal assignments in the above files.

**Files / modules affected:**  
- `app/web/js/ui.js` (add `esc` helper)
- `app/web/js/clients.js`
- `app/web/js/lists.js`
- `app/web/js/journal.js`

**Expected result:**  
All DB-sourced values HTML-escaped before insertion. Visual output identical (HTML entities render as their characters).

**Risk level:** low — the esc() approach is minimal and non-breaking.

---

## TASK-07: Add TrackAggregator.has_active_tracks() public method

**Problem:**  
`runtime/channel_runtime.py:549` reads `pipeline.aggregator._track_states.values()` — a private attribute. This creates tight coupling between `channel_runtime` (runtime layer) and `anpr_pipeline` (domain layer).

**What to change:**  
1. Add to `TrackAggregator` in `anpr/pipeline/anpr_pipeline.py`:
```python
def has_active_tracks(self) -> bool:
    """Return True if any track is still being processed (not yet finalized)."""
    return any(not s.finalized for s in self._track_states.values())
```
2. In `runtime/channel_runtime.py:547-553`, replace:
```python
active_tracks = sum(
    1 for s in pipeline.aggregator._track_states.values()
    if not s.finalized
)
if active_tracks == 0:
```
with:
```python
if not pipeline.aggregator.has_active_tracks():
```

**Files / modules affected:**  
- `anpr/pipeline/anpr_pipeline.py`
- `runtime/channel_runtime.py`

**Expected result:**  
Encapsulation restored. Same adaptive stride behaviour. No external access to private dict.

**Risk level:** low.

---

## TASK-08: Shut down _io_pool in ChannelProcessor

**Problem:**  
`runtime/channel_runtime.py:95` creates a `ThreadPoolExecutor(max_workers=2)` assigned to `self._io_pool`. This pool is never shut down when the processor is stopped or when `restart_processor_for_settings()` creates a new `ChannelProcessor` instance. Abandoned pools leave threads running.

**What to change:**  
1. Add a `shutdown(wait=True)` method to `ChannelProcessor`:
```python
def shutdown_io_pool(self) -> None:
    self._io_pool.shutdown(wait=True, cancel_futures=False)
```
2. In `AppContainer.shutdown()` (`app/api/container.py:134-137`), after stopping all channels, call:
```python
self.processor.shutdown_io_pool()
```
3. In `AppContainer.restart_processor_for_settings()` (`container.py:154-166`), before creating the new processor, call:
```python
old_processor = self.processor
...
self.processor = self._create_processor()
...
old_processor.shutdown_io_pool()
```

**Files / modules affected:**  
- `runtime/channel_runtime.py`
- `app/api/container.py`

**Expected result:**  
JPEG write threads are cleanly joined on shutdown. No orphaned threads after processor restart.

**Risk level:** low. The `wait=True` will block until in-flight saves complete, which is the correct behaviour.

---

## TASK-09: Sync processor._lists_db after refresh_storage_clients()

**Problem:**  
`app/api/container.py:208-226` (`refresh_storage_clients()`) rebuilds all DB client objects including `self.lists_db = ListDatabase(dsn)`, but the running `ChannelProcessor` still holds a reference to the old `ListDatabase` instance via `self.processor._lists_db`. After refresh, the processor performs client lookups against the old connection pool.

**What to change:**  
In `refresh_storage_clients()`, after the line `self.lists_db = ListDatabase(dsn)`, add:
```python
self.processor._lists_db = self.lists_db
```

**Files / modules affected:**  
- `app/api/container.py`

**Expected result:**  
After a DSN change (or any settings save that triggers `refresh_storage_clients`), the channel processor uses the updated database connection. Client lookups in the recognition loop are consistent with the rest of the application.

**Risk level:** low — one-line fix. The `_lists_db` field is not protected by any lock in `ChannelProcessor`, but it is a simple reference assignment (atomic in Python's GIL). Worst case: a channel thread that is currently calling `find_client_by_plate` on the old object will finish its current call on the old pool and use the new reference on the next event.

---

## TASK-10: Rename SQL alias `e` to `c` in lists_repository.py

**Problem:**  
`database/lists_repository.py` uses `e` as the table alias for `clients` throughout all SQL queries (lines 85, 172, 189, 211, 243). The alias `e` conventionally means `events`. This creates confusion when reading queries that join `clients` with `lists`.

**What to change:**  
In `database/lists_repository.py`, replace all occurrences of:
- `FROM clients e` → `FROM clients c`
- `JOIN clients e ON` → `JOIN clients c ON`
- `LEFT JOIN clients e ON` → `LEFT JOIN clients c ON`
- `e.plate_normalized` → `c.plate_normalized`
- `e.id` → `c.id` (in context of clients join)
- `e.list_id` → `c.list_id`
- `e.is_deleted` → `c.is_deleted`
- `e.plate` → `c.plate` (in client context)
- `e.last_name`, `e.first_name`, etc. → `c.last_name`, `c.first_name`, etc.

Be careful to only change aliases in the client-related queries, not to affect any future event joins.

**Files / modules affected:**  
- `database/lists_repository.py`

**Expected result:**  
All SQL in the file uses clear, conventional aliases. No functional change.

**Risk level:** low. Run the test suite (`pytest tests/test_lists_repository.py`) after the change.

---

## TASK-11: Harden JWT_SECRET_KEY — fail at startup if not set

**Problem:**  
`app/api/auth_utils.py:15`:
```python
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "anpr-default-secret-change-me")
```
If the env var is not set, the application starts with a well-known, publicly visible secret. Any attacker who reads this source code can forge valid JWT tokens for any user.

**What to change:**  
```python
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "").strip()
if not JWT_SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY environment variable is required. "
        "Set it to a random secret before starting the application."
    )
```
Also update `.env.example` to document this requirement clearly.

**Files / modules affected:**  
- `app/api/auth_utils.py`
- `.env.example`

**Expected result:**  
Application refuses to start without a secret. No silent production deployment with default credentials possible.

**Risk level:** low for production security. Note: tests that don't set `JWT_SECRET_KEY` will break. Either set it in test fixtures, or add `os.environ.setdefault("JWT_SECRET_KEY", "test-secret-only")` in a test conftest.

---

## TASK-12: Add bulk import endpoint for CSV list import

**Problem:**  
`app/web/js/lists.js:229-250` imports CSV rows one by one, making 2 HTTP calls per row (POST /api/clients, then POST /api/clients/{id}/attach). A 500-row CSV = 1000 sequential HTTP calls, causing slow import and high DB connection pressure.

**What to change:**  
1. Add endpoint `POST /api/lists/{list_id}/import` in `app/api/routers/lists.py`:
   - Accept `application/json` body: `{"clients": [{plate, first_name, last_name, ...}, ...]}`
   - Insert all clients in a single transaction and attach to list in one loop
   - Return `{"imported": N, "skipped": N, "errors": [...]}`
2. Add a corresponding method `ClientDatabase.bulk_create_and_attach(list_id, clients)` in `database/clients_repository.py`
3. Update `importCurrentListCSV()` in `lists.js` to batch-POST to the new endpoint

**Files / modules affected:**  
- `app/api/routers/lists.py`
- `app/api/schemas.py` (new Pydantic schema for bulk import payload)
- `database/clients_repository.py`
- `app/web/js/lists.js`

**Expected result:**  
CSV import is a single HTTP call. Import time for 1000 rows drops from ~5-10 seconds to <1 second.

**Risk level:** medium — new endpoint, new DB method. Test with large CSV files (1000+ rows) and test duplicate plate handling.

---

## TASK-13: Rename router functions in lists.py for consistency

**Problem:**  
`app/api/routers/lists.py` has function names with a redundant "plate" prefix that doesn't match the module context: `list_plate_lists`, `delete_plate_list`, `update_plate_list`.

**What to change:**  
Rename:
- `list_plate_lists` → `list_lists`
- `create_plate_list` → `create_list`
- `delete_plate_list` → `delete_list`
- `update_plate_list` → `update_list`
- `all_plates` → `plates_by_type` (or `list_plates_with_type`)

These are internal Python function names; the API routes (`/api/lists`, `/api/lists/{id}`) are not affected.

**Files / modules affected:**  
- `app/api/routers/lists.py`

**Expected result:**  
Consistent naming throughout the router. No API contract change.

**Risk level:** very low — internal names only.

---

## TASK-14: Remove ChannelProcessor fallback DB construction

**Problem:**  
`runtime/channel_runtime.py:85-87`:
```python
self._events_db = events_db if events_db is not None else PostgresEventDatabase(
    str(self._storage_settings.get("postgres_dsn", ""))
)
```
The fallback creates a `PostgresEventDatabase` with a potentially empty DSN. In practice, `AppContainer._create_processor()` always passes `events_db`. The fallback is dead code that could silently create a broken DB client with `dsn=""`.

**What to change:**  
Replace the fallback with:
```python
if events_db is None:
    raise ValueError("events_db is required for ChannelProcessor")
self._events_db = events_db
```

**Files / modules affected:**  
- `runtime/channel_runtime.py`

**Expected result:**  
Programming error is detected at initialization instead of silently degrading at runtime.

**Risk level:** low. Only risk: any test that creates `ChannelProcessor` without passing `events_db` will now fail with a clear error message instead of silently. Update such tests to pass a mock/stub.

---

## Notes on Priority

Suggested order for maximum impact per effort:

| Priority | Tasks |
|----------|-------|
| Do first | TASK-05, TASK-06 (XSS fixes) |
| Do soon | TASK-09 (stale lists_db reference), TASK-11 (JWT secret) |
| Clean up | TASK-01, TASK-02, TASK-03, TASK-04 (migration/compat/index cleanup) |
| Refactor | TASK-07, TASK-08, TASK-10, TASK-13, TASK-14 |
| Feature | TASK-12 (bulk import) |
