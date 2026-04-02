# Codebase Concerns

**Analysis Date:** 2026-03-25

## Tech Debt

**Broad Exception Handling:**
- Issue: Multiple catch-all `except Exception` blocks throughout the codebase suppress specific errors, making debugging harder and preventing targeted recovery
- Files: `database/postgres_event_repository.py` (lines 72, 107, 121, 165, 179, 194, 213, 256), `database/lists_repository.py` (lines 70, 156), `anpr/detection/yolo_detector.py` (lines 55, 171, 232), `runtime/channel_runtime.py` (lines 268, 601), `controllers/service.py` (lines 105, 210), `common/logging.py` (lines 51, 88, 169, 173), `app/api/container.py` (line 139), `app/api/routers/settings.py` (line 68)
- Impact: Network failures, permission issues, and data corruption are treated identically. Database repository methods wrap all exceptions into `StorageUnavailableError`, losing granularity (connection timeout vs constraint violation vs encoding error). The YOLO detector silently falls back to CPU or disables tracking on any exception, not just CUDA/NMS errors
- Fix approach: Replace broad catches with specific exception types (`psycopg.OperationalError`, `psycopg.IntegrityError`, `torch.cuda.CudaError`, etc.). Keep broad catch only at top-level channel loop in `_run_channel` where it acts as a crash guard

**Monolithic Frontend (2833 lines):**
- Issue: The entire UI is a single JavaScript file with no modules, bundling, or component separation
- Files: `app/web/app.js` (2833 lines)
- Impact: No code splitting, no tree shaking, all UI logic loaded at once. Changes to one panel risk breaking unrelated panels. No type checking. Global state object (`state`) is mutated freely from anywhere
- Fix approach: Migrate to a module-based structure (ES modules or a lightweight framework). Extract panels (events, channels, lists, journal, settings, controllers) into separate modules

**Extensive innerHTML Usage (XSS Risk):**
- Issue: At least 25 uses of `innerHTML` with interpolated data throughout `app/web/app.js`, including user-provided values like plate numbers, channel names, and log messages
- Files: `app/web/app.js` (lines 505, 540, 795, 811, 893, 931, 1067, 1073, 1091, 1096, 1282, 1294, 1441, 1445, 1764, 1811, 2070, 2204, 2298, 2369, 2548, 2793)
- Impact: Plate numbers, channel names, and log messages are interpolated directly into HTML without escaping. A crafted plate number or channel name containing `<script>` or event handlers could execute arbitrary JavaScript
- Fix approach: Replace `innerHTML` with `textContent` for text-only content. Use `createElement`/`appendChild` patterns for structured HTML. Introduce an HTML escaping utility for cases where template strings are necessary

**Settings Normalizer Coupling to Controllers:**
- Issue: `config/settings_normalizer.py` imports `SUPPORTED_CONTROLLER_TYPES` from `controllers/__init__.py`, creating a circular dependency between configuration and controller domains
- Files: `config/settings_normalizer.py` (line 17), `controllers/service.py` (line 18)
- Impact: The config layer cannot be used independently of the controllers package. The file itself documents this as "known architectural coupling" (line 6 docstring)
- Fix approach: Move `SUPPORTED_CONTROLLER_TYPES` to `config/settings_schema.py` or a shared constants module

**Duplicate Connection Pools:**
- Issue: `PostgresEventDatabase` and `ListDatabase` each create their own independent `ConnectionPool` (min_size=2, max_size=10) with the same DSN. Additionally, `refresh_storage_clients()` in `app/api/container.py` creates entirely new instances without closing old pools
- Files: `database/postgres_event_repository.py` (line 51), `database/lists_repository.py` (line 35), `app/api/container.py` (lines 187-190)
- Impact: Up to 20 connections consumed (2 pools x max 10) under normal operation. When `refresh_storage_clients()` is called, old pool instances are orphaned without explicit `close()`, potentially leaking connections until garbage collected
- Fix approach: Share a single `ConnectionPool` between both repositories. Explicitly close old pools in `refresh_storage_clients()` before creating new ones

**Unvalidated Channel Update Payload:**
- Issue: `PUT /api/channels/{channel_id}` accepts raw `Dict[str, Any]` and calls `channels[idx].update(payload)` without schema validation
- Files: `app/api/routers/channels.py` (line 152, 156)
- Impact: Any arbitrary key-value pair can be injected into channel settings. No type coercion or bounds checking. Contrast with `put_channel_config` (line 178) which uses a Pydantic model
- Fix approach: Apply Pydantic validation to all channel update endpoints, or at minimum whitelist allowed keys

## Known Bugs

**Settings Update Does Not Affect Running Channels:**
- Issue: Channel threads snapshot their configuration at start time via `channel = dict(ctx.channel)` in `_run_channel`. Settings changes (OCR confidence, detection mode, motion thresholds, etc.) do not propagate until the channel is restarted
- Files: `runtime/channel_runtime.py` (lines 346-347, 358-392)
- Impact: Users change settings expecting immediate effect but see no change until manual restart. Only reconnect settings are dynamically updated via `get_reconnect_config()`
- Fix approach: Either implement a config-reload mechanism that the channel loop checks periodically, or document that channel restart is required and auto-restart on relevant config changes

**Preview Frame Initialization Race:**
- Issue: When a channel starts, there is a window between `metrics.state = "running"` (line 350) and the first successful frame encode where `preview_ready` is `False` and `latest_jpeg` is `None`. The API returns 503 during this window
- Files: `runtime/channel_runtime.py` (lines 350, 583-593), `app/api/routers/channels.py` (lines 48-54)
- Impact: Frontend preview panels briefly flash an error state on channel start. Fast polling clients may interpret 503 as a permanent failure
- Fix approach: Add a "starting" state that the frontend handles gracefully, or buffer the first frame before transitioning state to "running"

**Reconnection Metrics Not Reset on Restart:**
- Issue: When `restart()` calls `stop()` then `start()`, `ChannelMetrics` is reused without resetting `reconnect_count`, `timeout_count`, `error_count`, `failed_frames`, etc. The `stop()` method only sets `state = "stopped"`
- Files: `runtime/channel_runtime.py` (lines 213-229, lines 26-41)
- Impact: Metrics accumulate across restarts, giving misleading counts. A channel restarted 10 times shows cumulative reconnect counts rather than per-session values
- Fix approach: Reset metrics counters in `start()` or create a fresh `ChannelMetrics` instance

## Security Considerations

**API Key Stored in localStorage:**
- Risk: API key stored in browser `localStorage` is accessible to any JavaScript running on the same origin, including XSS payloads
- Files: `app/web/app.js` (lines 26-27)
- Current mitigation: None. The key is also sent as a query parameter in SSE/MJPEG URLs (line 32), which means it appears in server logs and browser history
- Recommendations: Use HttpOnly cookies for session management. If API keys must be used, send them only via headers, never as query parameters

**API Key Passed as Query Parameter:**
- Risk: `apiUrl()` appends `api_key=<key>` as a URL query parameter for EventSource and MJPEG streams
- Files: `app/web/app.js` (line 32)
- Current mitigation: None
- Recommendations: EventSource does not support custom headers natively. Consider a token-exchange endpoint that returns a short-lived stream token, or use cookie-based auth for streaming endpoints

**Input Validation Gaps in Channel Update:**
- Risk: `PUT /api/channels/{channel_id}` accepts arbitrary dict payload without validation
- Files: `app/api/routers/channels.py` (line 152)
- Current mitigation: The settings normalizer fills defaults but does not reject unknown keys
- Recommendations: Apply Pydantic schema validation to all mutation endpoints

## Performance Bottlenecks

**Unbounded Export Query (`fetch_for_export`):**
- Problem: `fetch_for_export` has no `LIMIT` clause. Exports the entire events table matching filters in a single query
- Files: `database/postgres_event_repository.py` (lines 227-257)
- Cause: `cursor.fetchall()` loads all matching rows into Python memory at once. For a system running months with multiple cameras, this could be millions of rows
- Improvement path: Use server-side cursors or streaming (`cursor.itersize`). Add pagination or chunked export. Consider background export jobs for large datasets

**JPEG Encoding on Every Frame:**
- Problem: Every frame is JPEG-encoded for preview regardless of whether any client is viewing
- Files: `runtime/channel_runtime.py` (lines 583-593)
- Cause: The preview encode runs unconditionally in the frame processing loop (gated only by `disable_video_output` debug flag)
- Improvement path: Track active MJPEG/snapshot consumers and skip encoding when no one is watching. Alternatively, encode at a lower framerate than the processing framerate

**DebugRegistry Track History Accumulation:**
- Problem: `_track_histories` dict in `ChannelDebugState` grows with each new track_id. Stale entries are cleaned based on TTL, but `_fallback_seq` increments unboundedly when tracking is unavailable
- Files: `runtime/debug.py` (lines 53-56, 226-228, 281-300)
- Cause: Each detection without a track_id creates a new `fallback:N` key. The deque maxlen (28) limits history length per track but not the number of tracks
- Improvement path: Cap the total number of track entries per channel. The cleanup logic exists but only runs on detection frames, not idle frames when `should_process` is False (though `cleanup_stale` is called on skipped frames at line 519)

## Fragile Areas

**YOLO Detector Fallback Logic:**
- Files: `anpr/detection/yolo_detector.py` (lines 218-238)
- Why fragile: The `track()` method has a multi-layered fallback chain: track -> detect (on CUDA error) -> detect (on ModuleNotFoundError) -> detect (on any exception). Once `_tracking_supported` is set to `False`, it stays `False` for the lifetime of the detector instance with no recovery path
- Safe modification: Any changes to detection/tracking must preserve the fallback chain. Test with and without CUDA, with and without tracking dependencies
- Test coverage: No tests exist for `YOLODetector`

**Channel Thread Lifecycle:**
- Files: `runtime/channel_runtime.py` (lines 203-229, 344-617)
- Why fragile: Channel threads are daemon threads with a 3-second join timeout on stop. If a thread is blocked on `cap.read()` (which can hang indefinitely on some RTSP sources), `stop()` returns before the thread actually exits. A subsequent `start()` may then create a second thread for the same channel while the old one is still running
- Safe modification: Always check `ctx.thread.is_alive()` before starting. The current code does this (line 206) but only under the lock -- the thread may become alive between the check and the actual start
- Test coverage: No tests exist for `ChannelProcessor`

**Settings Schema Migration:**
- Files: `config/settings_migrations/runner.py`, `config/settings_schema.py`
- Why fragile: The migration system uses a lineage key and version number but has no individual migration steps -- only a single `_apply_legacy_compat` function. Adding a new schema version requires modifying the monolithic compat function rather than adding an incremental migration
- Safe modification: Test migrations with settings files from all previous versions. Keep a collection of sample settings at each version
- Test coverage: No tests exist for settings migrations

## Scaling Limits

**PostgreSQL Connection Pool Sizing:**
- Current capacity: Two pools x (min 2, max 10) = 4-20 connections total
- Limit: Under high load with many concurrent API requests and channel threads, pool contention causes blocking. Each `with self._connect()` call blocks until a connection is available
- Scaling path: Share a single pool between repositories. Make pool size configurable via settings. Consider async database access for the API layer (psycopg async)

**Screenshots Directory (Filesystem):**
- Current capacity: Unlimited growth, organized by date/channel subdirectories
- Limit: Filesystem inode limits, disk space. No automatic cleanup unless retention policy is manually triggered via `POST /api/data/retention/run`
- Scaling path: The `DataLifecycleService` exists but must be invoked manually. Implement scheduled cleanup (cron or background task). Consider object storage for production deployments
- Files: `runtime/channel_runtime.py` (lines 253-259), `app/shared/data_lifecycle.py`

**SSE / MJPEG Connections:**
- Current capacity: Unbounded. Each SSE or MJPEG client holds an open connection and an asyncio task
- Limit: Each MJPEG stream polls `get_preview_frame` at ~12.5 fps (80ms sleep). With many browser tabs or clients, this creates CPU and memory pressure
- Scaling path: Add connection limits per endpoint. Implement shared frame broadcasting instead of per-client polling
- Files: `app/api/routers/channels.py` (lines 85-103), `app/api/routers/events.py` (lines 93-120)

## Dependencies at Risk

**Ultralytics YOLO:**
- Risk: Heavy dependency with frequent breaking changes between versions. The tracker fallback logic (`_tracking_supported`, `_reset_tracker_state`) depends on internal YOLO predictor attributes (`model.predictor.trackers`, `predictor.vid_path`) that are not part of the public API
- Impact: YOLO version upgrade may silently break tracking or crash at runtime
- Files: `anpr/detection/yolo_detector.py` (lines 46-59)
- Migration plan: Pin version strictly. Add integration tests that verify tracker state reset works with the pinned version

**psycopg / psycopg_pool:**
- Risk: Lazy import (`from psycopg_pool import ConnectionPool`) means import errors surface at runtime, not at startup
- Impact: If psycopg_pool is not installed, the application starts successfully but crashes on first database operation
- Files: `database/postgres_event_repository.py` (line 49), `database/lists_repository.py` (line 33)
- Migration plan: Import at module level or add an explicit startup check

## Missing Critical Features

**No Automated Data Retention:**
- Problem: Retention policy exists (`DataLifecycleService`) but only runs when manually triggered via API endpoint
- Blocks: Unattended long-running deployments will eventually fill disk
- Files: `app/shared/data_lifecycle.py`, `app/api/routers/data.py` (lines 31-37)

**No Health Check for Database Connectivity at Startup:**
- Problem: Database schema bootstrap (`_ensure_schema`) runs lazily on first query. If PostgreSQL is unreachable at startup, the application starts but all operations fail with 503
- Blocks: Deployment orchestrators (Docker, systemd) cannot distinguish healthy from unhealthy state
- Files: `database/postgres_event_repository.py` (lines 57-74)

## Test Coverage Gaps

**Overall Coverage is Minimal:**
- What's not tested: Only 4 test files exist, covering `plate_validator`, `track_aggregator`, `motion_detector`, and `direction_estimator`
- Files: `tests/test_plate_validator.py`, `tests/test_track_aggregator.py`, `tests/test_motion_detector.py`, `tests/test_direction_estimator.py`
- Risk: The entire API layer, database repositories, channel runtime, settings normalizer, YOLO detector, and controller service have zero test coverage
- Priority: High

**No API Endpoint Tests:**
- What's not tested: All FastAPI routers (channels, events, settings, controllers, lists, data, debug, system)
- Files: `app/api/routers/*.py`
- Risk: Regressions in request validation, error responses, and authorization are undetectable without manual testing
- Priority: High

**No Database Repository Tests:**
- What's not tested: `PostgresEventDatabase` and `ListDatabase` query logic, schema bootstrap, connection pool lifecycle
- Files: `database/postgres_event_repository.py`, `database/lists_repository.py`
- Risk: SQL query changes (especially in `fetch_journal_page` with dynamic WHERE clauses) cannot be verified without running against a real database
- Priority: High

**No Channel Runtime Tests:**
- What's not tested: Channel start/stop lifecycle, reconnection logic, preview frame generation, event emission
- Files: `runtime/channel_runtime.py`
- Risk: The most complex module (616 lines) with threading, OpenCV, and state management has no automated verification
- Priority: High

**No Settings Migration Tests:**
- What's not tested: Legacy format upgrade, version validation, lineage checking
- Files: `config/settings_migrations/runner.py`
- Risk: A bad migration could corrupt user settings on upgrade
- Priority: Medium

---

*Concerns audit: 2026-03-25*
