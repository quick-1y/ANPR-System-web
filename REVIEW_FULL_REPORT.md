# Full Architectural Review Report
## ANPR System v0.8 Web

**Review date:** 2026-04-14  
**Branch:** dev_db_ref  
**Reviewer:** Automated deep-analysis (Claude Sonnet 4.6)

---

## 1. Architecture Weaknesses

---

### AW-01: `refresh_storage_clients()` does not update `ChannelProcessor._lists_db`

**Severity:** high  
**Confidence:** high

**Evidence:**  
`app/api/container.py:208-226` rebuilds `self.lists_db = ListDatabase(dsn)` and all other DB clients, but the running `ChannelProcessor` at `self.processor` was constructed with a reference to the old `ListDatabase` instance (`self.processor._lists_db`). This reference is never updated.

`app/api/routers/settings.py:87`, `data.py:153`, `data.py:236` all call `container.refresh_storage_clients()` at runtime.

`channel_runtime.py:592`:
```python
client_info = self._lists_db.find_client_by_plate(plate) if self._lists_db else None
```

**Why it is a problem:**  
After a DSN change, events in the recognition pipeline are linked to clients using the old database connection pool, which points to the old DSN. The processor silently continues using stale state. If the new DSN has different data, client_id values will be wrong or DB errors may silently produce `None`.

**Recommended fix:**  
After `refresh_storage_clients()` rebuilds `self.lists_db`, add:
```python
self.processor._lists_db = self.lists_db
```

---

### AW-02: `_io_pool` (ThreadPoolExecutor) never shut down

**Severity:** medium  
**Confidence:** high

**Evidence:**  
`runtime/channel_runtime.py:95`:
```python
self._io_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="screenshot-io")
```

`ChannelProcessor` has no `shutdown()` method and `_io_pool.shutdown()` is never called anywhere. The pool exists at the class level, so it lives for the whole process lifetime.

**Why it is a problem:**  
On container restart or graceful shutdown, in-flight `_save_jpeg` futures may still be running. Depending on how uvicorn shuts down, this may leave open file handles or corrupt partially written JPEG files. If `restart_processor_for_settings()` is called (which creates a new `ChannelProcessor` instance), the old pool and its threads are abandoned without cleanup.

**Recommended fix:**  
Add a `shutdown_io_pool()` method to `ChannelProcessor` that calls `self._io_pool.shutdown(wait=True, cancel_futures=False)`. Call it from `AppContainer.shutdown()`.

---

### AW-03: Direct access to `TrackAggregator._track_states` (private attribute)

**Severity:** medium  
**Confidence:** high

**Evidence:**  
`runtime/channel_runtime.py:549`:
```python
active_tracks = sum(
    1 for s in pipeline.aggregator._track_states.values()
    if not s.finalized
)
```

`_track_states` is a private dict (`_TrackOCRState` keyed by `track_id`). The same access pattern also appears in `tests/test_track_aggregator.py:246` (test only — acceptable there).

**Why it is a problem:**  
`ChannelProcessor` is in `runtime/`, which is supposed to be a consumer of `anpr/`. Reading a private dict from an inner implementation class creates tight coupling. If `TrackAggregator` internals change (rename, replace with a different structure), `channel_runtime.py` breaks silently.

**Recommended fix:**  
Add a public method to `TrackAggregator`:
```python
def has_active_tracks(self) -> bool:
    return any(not s.finalized for s in self._track_states.values())
```
Then use `pipeline.aggregator.has_active_tracks()` in `channel_runtime.py`.

---

### AW-04: Daemon thread spawned inside an HTTP handler

**Severity:** low  
**Confidence:** high

**Evidence:**  
`app/api/routers/channels.py:151-156`:
```python
threading.Thread(
    target=container.sync_channel_runtime,
    args=(channel_id, enabled),
    daemon=True,
    name=f"channel-sync-{channel_id}",
).start()
```
This is inside `update_channel()`, which handles `PUT /api/channels/{id}`.

**Why it is a problem:**  
The caller receives an HTTP 200 before `sync_channel_runtime` has actually completed. Any exception thrown inside the thread is silently swallowed. If rapid successive `PUT` calls are made for the same channel, multiple sync threads may race on `processor.stop()` / `processor.start()`. There is no cancellation mechanism.

**Recommended fix:**  
Call `container.sync_channel_runtime()` directly (synchronously) in the handler, or move to a proper background task mechanism. `sync_channel_runtime` is fast (stop + start) and doesn't warrant fire-and-forget unless profiling shows it blocks responses.

---

### AW-05: `ClientDatabase` has a hidden schema dependency on `ListDatabase`

**Severity:** medium  
**Confidence:** high

**Evidence:**  
`database/clients_repository.py:13-16`:
```python
def _schema_sql(self) -> str:
    # Schema (tables, indexes) is owned by ListDatabase.
    # This no-op satisfies the abstract requirement and marks the instance initialised.
    return "SELECT 1"
```

`ClientDatabase` operates on the `clients` table, which is created by `ListDatabase._schema_sql()`. If `ClientDatabase._ensure_schema()` runs first (or if only `ClientDatabase` is used without `ListDatabase`), all queries will fail with "relation 'clients' does not exist".

**Why it is a problem:**  
The design relies on initialization ordering (`ListDatabase` must be instantiated and must have run a query before `ClientDatabase` can work). This is an invisible contract. The comment acknowledges it but anyone adding a new code path that only creates `ClientDatabase` will get subtle failures.

**Recommended fix:**  
Option A: Move the full schema SQL into a shared `_SHARED_SCHEMA_SQL` constant and have both classes import it. `ClientDatabase._schema_sql()` would return the same DDL.  
Option B (cleaner): Create a `SchemaBootstrap` class that owns the DDL and is run explicitly at startup before any repository is used.

---

### AW-06: `SettingsManager.get_*()` methods call `_fill_*_defaults()` and save on every read

**Severity:** low  
**Confidence:** high

**Evidence:**  
`config/settings_manager.py:103-111`, `get_reconnect()` at line 64-68, `get_plate_settings()` at line 148-152, etc. — every `get_*` method calls the corresponding normalizer filler and, if it returns `True` (meaning a missing key was added), saves the full settings file.

**Why it is a problem:**  
This means any call to `get_storage_settings()` can trigger a disk write. If this method is called in a hot path (e.g., on every request or in the recognition loop), the settings file is repeatedly re-written. The current code avoids calling it in hot paths, but the design makes it easy to introduce accidental write storms.

**Recommended fix:**  
Call all fill methods once during `__init__` (or in `_normalize_and_persist_if_changed`), not on every getter call. Getters should be pure readers after normalization is done at startup.

---

## 2. Directory Structure Issues

No structural problems found. The directory layout is clean and logical:
- `anpr/` — pure domain logic
- `runtime/` — channel processing
- `app/api/` — HTTP layer
- `database/` — repositories
- `config/` — settings
- `controllers/` — hardware integration

No files placed in wrong directories.

---

## 3. Naming Issues

---

### NI-01: SQL alias `e` used for the `clients` table

**Severity:** medium  
**Confidence:** high

**Evidence:**  
`database/lists_repository.py`:
- Line 85: `LEFT JOIN clients e ON e.list_id = l.id`
- Line 172: `FROM clients e`
- Line 189: `FROM clients e`
- Line 211: `FROM clients e`
- Line 243: `FROM clients e`

**Why it is a problem:**  
`e` is the conventional alias for `events`. Throughout the codebase (and in any mental model), `e` = events. Using `e` for clients creates confusion, especially in queries that also join with lists.

**Recommended fix:**  
Replace `e` with `c` (for clients) in all SQL within `lists_repository.py`.

---

### NI-02: `list_plate_lists`, `delete_plate_list`, `update_plate_list` — redundant "plate" prefix

**Severity:** low  
**Confidence:** high

**Evidence:**  
`app/api/routers/lists.py`:
- Line 16: `def list_plate_lists`
- Line 40: `def delete_plate_list`
- Line 51: `def update_plate_list`

These functions are already in the `lists.py` router. The "plate" qualifier is redundant and inconsistent (not used in `create_plate_list` on line 24 — wait, it is used there too, but not in `list_clients_in_list`).

**Recommended fix:**  
Rename to `list_lists`, `delete_list`, `update_list` (aligning with `create_list` pattern in the repository).

---

### NI-03: `all_plates` endpoint name vs. its actual behaviour

**Severity:** low  
**Confidence:** high

**Evidence:**  
`app/api/routers/lists.py:32`:
```python
@router.get("/api/lists/plates")
def all_plates(...)
```
This returns a list of `{plate, list_type}` dicts for ALL plates across ALL lists. It is used as a seed for the frontend's `plateLookup` cache (a plate-to-type map). The name `all_plates` is technically correct but loses the "for lookup" semantics.

**Recommended fix:** Consider `plates_lookup` or `plates_by_type` — not critical, but the current name suggests a full client list rather than a lookup seed.

---

### NI-04: `_create_processor()` vs `_build_lifecycle()` inconsistent factory naming

**Severity:** low  
**Confidence:** high

**Evidence:**  
`app/api/container.py:98` — `_create_processor()`  
`app/api/container.py:118` — `_build_lifecycle()`

Both are private factory methods. One uses `_create_`, the other `_build_`. Minor inconsistency.

**Recommended fix:** Pick one convention (`_build_` or `_create_`) and use it consistently.

---

### NI-05: `ClientDatabase._row_to_dict` returns a different shape from `get_client`

**Severity:** low  
**Confidence:** high

**Evidence:**  
`database/clients_repository.py:225-237`: `_row_to_dict` returns 9 fields (no `list_name`, no `list_type`).  
`database/clients_repository.py:54-67`: `get_client` manually builds a dict with 11 fields (includes `list_name`, `list_type`).

**Why it is a problem:**  
Callers of `list_all_clients()` and `search_clients()` receive dicts without `list_name`/`list_type`. This has caused the frontend to do `state.lists.find(l => l.id === c.list_id)` client-side to resolve list names. If the shape were consistent, that lookup wouldn't be necessary.

**Recommended fix:** Use a single `_row_to_dict_with_list` helper that accepts the full row. Methods that don't join can return `None` for `list_name`/`list_type`.

---

## 4. Security Issues

---

### SI-01: XSS via `innerHTML` with database-sourced values

**Severity:** high  
**Confidence:** high

**Evidence:**  
The following locations set `innerHTML` with values that originate from the database:

| File | Line | Unsafe value |
|------|------|--------------|
| `events.js` | 96 | `displayPlate` (from `event.plate_display`), `channelName` (from `event.channel`) |
| `events.js` | 220 | `entry.list_name`, `entry.first_name`, `entry.last_name`, etc. in `listHtml` |
| `clients.js` | 26-32 | `c.plate`, `c.last_name`, `c.first_name`, `c.phone`, `c.car` |
| `clients.js` | 162 | `l.name` (list name) |
| `lists.js` | 65 | `l.name` (list name) |
| `lists.js` | 94-98 | `c.plate`, `c.first_name`, `c.last_name`, `c.phone`, `c.car`, `c.comment` |
| `journal.js` | 76 | plate display, channel, country — all database fields |
| `debug.js` | 22 | `text` (raw log message — could contain HTML if a camera URL has `<` chars) |

**Why it is a problem:**  
Any user with operator access (or a compromised camera feed that affects stored values) can store `<script>` or `<img onerror=...>` in a plate number, client name, or channel name. When the admin views the UI, the script executes in their session. This is a stored XSS that crosses the operator→admin privilege boundary.

**Recommended fix:**  
Replace pattern:
```javascript
el.innerHTML = `<span>${userValue}</span>`;
```
with:
```javascript
const span = document.createElement('span');
span.textContent = userValue;
el.appendChild(span);
```
Or create a single `esc(str)` helper that escapes HTML entities and use it consistently when building template strings.

---

### SI-02: Default JWT secret in source code

**Severity:** medium  
**Confidence:** high

**Evidence:**  
`app/api/auth_utils.py:15`:
```python
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "anpr-default-secret-change-me")
```

**Why it is a problem:**  
If `JWT_SECRET_KEY` is not set in the deployment environment, any attacker who reads the source code can forge valid JWT tokens for any user ID, bypassing authentication entirely.

**Recommended fix:**  
Replace the default with `None` and raise `RuntimeError` at startup if the env var is unset:
```python
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY environment variable is required")
```

---

## 5. Unused and Legacy Code

---

### UL-01: `idx_events_timestamp` is covered by `idx_events_ts_id_desc`

**Severity:** low  
**Confidence:** high

**Evidence:**  
`database/postgres/schema.sql`:
```sql
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);         -- line 28
CREATE INDEX IF NOT EXISTS idx_events_ts_id_desc ON events(timestamp DESC, id DESC); -- line 32
```

PostgreSQL can use a composite index as a prefix scan. Any query that filters or sorts by `timestamp DESC` alone will use `idx_events_ts_id_desc` (the planner prefers the more selective index). `idx_events_timestamp` is redundant.

Similarly:
```sql
CREATE INDEX IF NOT EXISTS idx_events_channel_id ON events(channel_id, timestamp DESC);                  -- line 29
CREATE INDEX IF NOT EXISTS idx_events_channel_id_ts_id_desc ON events(channel_id, timestamp DESC, id DESC); -- line 33
```
`idx_events_channel_id` is covered by `idx_events_channel_id_ts_id_desc`.

**Why it is a problem:**  
Redundant indexes waste storage and slow down INSERT/UPDATE operations because PostgreSQL must maintain all indexes on every write.

**Recommended fix:**  
Remove `idx_events_timestamp` and `idx_events_channel_id` from `schema.sql`.

---

### UL-02: `idx_events_channel` index on the string `channel` column

**Severity:** low  
**Confidence:** medium

**Evidence:**  
`schema.sql:30`:
```sql
CREATE INDEX IF NOT EXISTS idx_events_channel ON events(channel);
```

All modern query code (`fetch_journal_page`, `fetch_for_export`, etc.) uses `channel_id` (integer), not `channel` (text). The only remaining use of the `channel` column in queries is a fallback in `fetch_for_export` (`elif channel: filters.append("channel = %s")`), which is only triggered if `channel_id` is `None`.

**Why it is a problem:**  
If `channel` text filtering is genuinely needed, the index is fine. But if it is never used in production queries, it is dead weight. Confidence is `medium` because the `fetch_for_export` fallback path is real code.

**Recommended fix:**  
Verify whether any export query uses `channel` text filtering. If not, remove the index and the fallback branch in `fetch_for_export`.

---

### UL-03: `_CONSECUTIVE_FAILURE_LIMIT` module-level constant in `anpr_pipeline.py`

**Severity:** low  
**Confidence:** high

**Evidence:**  
`anpr/pipeline/anpr_pipeline.py:30`:
```python
_CONSECUTIVE_FAILURE_LIMIT = 5
```
Used only as the default value of `max_consecutive_empty_ocr` parameter in `TrackAggregator.__init__`. Not referenced anywhere else.

**Why it is a problem:**  
This constant is public (visible at module level from outside the class) but has no use outside the class. It gives the impression it can be used externally. The same default value is also re-stated in `ANPRPipeline.__init__` via the `factory.py` call chain.

**Recommended fix:**  
Move it inside `TrackAggregator` as a class constant `_DEFAULT_CONSECUTIVE_FAILURE_LIMIT = 5`.

---

## 6. Migration and Compatibility Code

(See separate report: `REVIEW_MIGRATION_COMPAT.md`)

Summary:
- `schema.sql` contains 2 migration `DO $$` blocks — safe to remove
- `lists_repository.py._schema_sql()` contains 7 `ALTER TABLE` migration lines — safe to remove
- `settings_normalizer.py` contains 2 legacy field cleanup blocks — safe to remove
- `settings_migrations/runner.py` contains `_apply_legacy_compat()` — conditional removal

---

## 7. Performance and Memory Risks

---

### PM-01: `all_plates_with_type()` returns unbounded rows; used as frontend cache seed

**Severity:** medium  
**Confidence:** high

**Evidence:**  
`database/lists_repository.py:165-177` — query has no `LIMIT`. Returns one row per non-deleted client.  
`app/web/js/lists.js:14-28` — frontend calls `/api/lists/plates`, loads all into `state.plateLookup`.  
`lists.js:37`: `loadLists()` calls `refreshPlateLookup()` on every list tab visit.

**Why it is a problem:**  
If a deployment has 100 000 plate entries, every `loadLists()` call fetches 100 000 rows over HTTP and builds a JavaScript object with 100 000 keys. This will cause noticeable latency and potential tab freezes.

**Recommended fix:**  
For large deployments: replace the full-dump approach with a server-side lookup (`/api/lists/lookup?plate=<normalized>` called only when rendering event cards). For MVP scale: acceptable, but document the limit.

---

### PM-02: `state.allEvents` DOM is fully rebuilt on `forceRebuild`

**Severity:** low  
**Confidence:** high

**Evidence:**  
`app/web/js/events.js:111-121`: Full DOM rebuild when `forceRebuild=true`.  
`lists.js:37`: `loadLists()` calls `renderEventFeed(true)` — every list tab interaction rebuilds the entire event feed.

**Why it is a problem:**  
If `state.allEvents` has 500 items and the user interacts with the lists tab repeatedly, the event feed is torn down and rebuilt on every interaction. This is O(500) DOM operations triggered by an unrelated operation.

**Recommended fix:**  
`loadLists()` should not call `renderEventFeed(true)`. The `plateLookup` cache update should only force a re-colour of existing event cards (update their CSS class), not rebuild the entire feed.

---

### PM-03: `trimEventFeedOverflow()` forces multiple layout reflows

**Severity:** low  
**Confidence:** high

**Evidence:**  
`app/web/js/events.js:8-12`:
```javascript
function trimEventFeedOverflow(feed) {
  if (!feed) return;
  while (feed.lastElementChild && feed.scrollHeight > feed.clientHeight) {
    feed.removeChild(feed.lastElementChild);
  }
}
```

Each `scrollHeight` read after `removeChild` triggers a layout reflow. If the feed has 50+ items to remove, this is 50+ forced reflows.

**Recommended fix:**  
Compute the target count once (binary-search or estimate from average item height), remove the tail in one operation using `slice`, then do one reflow.

---

### PM-04: Sequential HTTP calls in CSV import

**Severity:** medium  
**Confidence:** high

**Evidence:**  
`app/web/js/lists.js:229-250`:
```javascript
for (const line of dataLines) {
    ...
    const result = await jfetch(api('/api/clients'), 'POST', {...});
    if (result?.id) {
        await jfetch(api(`/api/clients/${result.id}/attach`), 'POST', { list_id: ... });
    }
    imported++;
}
```
Each row: 2 sequential HTTP round-trips. A 1000-row CSV = 2000 sequential HTTP calls.

**Recommended fix:**  
Add a bulk import endpoint `POST /api/lists/{id}/import` that accepts a JSON array of client records and inserts them in a single transaction.

---

### PM-05: `find_client_by_plate()` DB call in the hot recognition loop

**Severity:** medium  
**Confidence:** high

**Evidence:**  
`runtime/channel_runtime.py:592`:
```python
client_info = self._lists_db.find_client_by_plate(plate) if self._lists_db else None
```
This runs for every recognized plate event. The query hits PostgreSQL synchronously from the channel thread.

**Why it is a problem:**  
On a system with 4 active cameras and 5-second cooldown, this is ~0.8 DB queries/second at steady state. With heavy plate traffic or a slow DB, this adds latency to the channel thread's inner loop, which is also responsible for frame capture.

**Recommended fix:**  
Short-term: keep as-is (acceptable for MVP). Medium-term: maintain a small in-memory LRU cache of `{normalized_plate: client_id}` with a short TTL (e.g., 60 seconds). The channel thread updates the cache on miss.

---

## 8. Recognition Pipeline Observations

The ANPR pipeline architecture (YOLODetector → ANPRPipeline → TrackAggregator → PlatePostProcessor) is well-designed:

- Frame-level processing is stateless (no shared mutable state between frames)
- Track-level aggregation is isolated per track_id with proper TTL eviction
- Budget exhaustion and consensus are handled cleanly
- Direction estimation uses its own TTL-evicted history

**Minor concerns:**

### RP-01: Adaptive stride reads private aggregator state (see AW-03)

### RP-02: Untracked detections bypass the aggregator entirely

**Evidence:**  
`anpr_pipeline.py:487-496`:
```python
else:
    # Untracked detection — no aggregation available.
    if confidence < self.min_confidence:
        ...
        continue
    detection["text"] = current_text
    detection["confidence"] = confidence
```
If `track_id` is `None` (detector lost the track), a single OCR result with sufficient confidence is immediately accepted without quorum or validation. This is a fast-path that could emit noisy results.

**Recommended fix:**  
Document explicitly why this path is intentional. If it is a legacy fallback, consider gating it behind a feature flag.

### RP-03: `_last_seen` cooldown dict grows without explicit cleanup on channel teardown

**Evidence:**  
`anpr_pipeline.py:397-407`: The `_last_seen` dict is cleaned of stale entries only during `_on_cooldown()` calls. If a channel is stopped and restarted, the old `ANPRPipeline` (and its `_last_seen` dict) is discarded anyway (new pipeline built in `build_components`). Not a leak in practice, but worth noting.

---

## 9. Miscellaneous Technical Debt

### TD-01: `settings_manager.py` leaks internal normalizer references

`app/api/container.py:31` — `self._file_lock = self._repo._file_lock` — directly copies the lock reference from the private internals of `SettingsRepository`. This is a needless coupling.

### TD-02: `ChannelProcessor.__init__` has a fallback DB construction path that should not exist in production

`channel_runtime.py:85-87`:
```python
self._events_db = events_db if events_db is not None else PostgresEventDatabase(
    str(self._storage_settings.get("postgres_dsn", ""))
)
```
The `else` branch creates a new `PostgresEventDatabase` directly. In practice, `events_db` is always passed by `AppContainer`. The fallback produces an object with a potentially empty DSN. This should raise `ValueError("events_db is required")` instead.

### TD-03: `update_channel` accepts a raw `Dict[str, Any]` with no validation

`app/api/routers/channels.py:145`:
```python
def update_channel(channel_id: int, payload: Dict[str, Any], ...):
```
This endpoint accepts any JSON dict. The `put_channel_config`, `update_channel_ocr`, and `update_channel_filter` sub-endpoints correctly use Pydantic schemas and delegate here, but the raw `PUT /api/channels/{id}` path is unvalidated. Documented as a known issue in `AGENTS.md` but still present.
