# Codebase Concerns

**Analysis Date:** 2026-04-14

## Tech Debt

**Broad Exception Handling:**
- Issue: Multiple `except Exception` blocks throughout suppress specific errors, making debugging harder
- Files: `database/postgres_event_repository.py`, `database/lists_repository.py`, `anpr/detection/yolo_detector.py`, `runtime/channel_runtime.py`, `controllers/service.py`, `common/logging.py`, `app/api/container.py`, `app/api/routers/settings.py`
- Impact: Network failures, permission issues, and data corruption treated identically. The YOLO detector silently falls back to CPU on any exception, not just CUDA errors
- Fix approach: Replace broad catches with specific types (`psycopg.OperationalError`, `psycopg.IntegrityError`, etc.). Keep broad catch only in `_run_channel` top-level crash guard

**Frontend Module Size:**
- Issue: Several JS modules are very large without lazy loading
- Files: `app/web/video-grid.js` (701 lines), `app/web/channels.js` (638 lines)
- Impact: No code splitting, heavy upfront load even for unused tabs
- Status: The monolithic `app.js` was split into domain modules — a significant improvement — but individual modules remain large

**Unvalidated Channel Update Payload:**
- Issue: `PUT /api/channels/{channel_id}` accepts raw `Dict[str, Any]` without schema validation
- Files: `app/api/routers/channels.py`
- Impact: Arbitrary key-value pairs can be injected into channel settings; no type coercion or bounds checking
- Fix approach: Apply Pydantic validation to all channel update endpoints, or whitelist allowed keys

**Settings Normalizer Coupling to Controllers:**
- Issue: `config/settings_normalizer.py` imports `SUPPORTED_CONTROLLER_TYPES` from `controllers/__init__.py`
- Impact: Config layer cannot be used independently of the controllers package
- Fix approach: Move `SUPPORTED_CONTROLLER_TYPES` to `config/settings_schema.py` or a shared constants module

**OCR Consensus Recomputed on Every Call:**
- Issue: `TrackAggregator` recomputes weighted majority on every `add_result()` call
- Files: `anpr/pipeline/anpr_pipeline.py`
- Impact: CPU overhead grows with `best_shots` count; result could be cached after quorum
- Fix approach: Cache the consensus result after first computation; invalidate only on new additions

**Settings Deserialization Not Cached:**
- Issue: `SettingsManager` may parse YAML on every settings read depending on call frequency
- Files: `config/settings_repository.py`, `config/settings_manager.py`
- Impact: Disk I/O per request in high-frequency settings access patterns
- Fix approach: The in-memory `settings` dict is already cached; verify no redundant file reads occur per request

**Media Cleanup Uses Full Directory Walk:**
- Issue: `rglob()` walks entire screenshots directory without an index
- Files: `app/shared/data_lifecycle.py`
- Impact: Slow on large media directories with many files/subdirectories
- Fix approach: Maintain a lightweight index or use date-based directory pruning

## Known Bugs

**Settings Update Does Not Affect Running Channels:**
- Issue: Channel threads snapshot config at start via `channel = dict(ctx.channel)`. Settings changes do not propagate until channel restart
- Files: `runtime/channel_runtime.py` (lines 346-347, 358-392)
- Impact: Users change settings expecting immediate effect but see no change until manual restart
- Fix approach: Implement config-reload mechanism checked periodically by the channel loop, or document and auto-restart on relevant config changes

**Preview Frame Initialization Race:**
- Issue: Gap between `metrics.state = "running"` and first successful frame encode where `latest_jpeg` is `None`. API returns 503 during this window
- Files: `runtime/channel_runtime.py`, `app/api/routers/channels.py`
- Impact: Frontend preview panels briefly flash an error state on channel start
- Fix approach: Add a "starting" state handled gracefully by the frontend, or buffer first frame before transitioning to "running"

**Reconnection Metrics Not Reset on Restart:**
- Issue: `ChannelMetrics` reused without resetting `reconnect_count`, `timeout_count`, `error_count`, `failed_frames` when `restart()` calls `stop()` then `start()`
- Files: `runtime/channel_runtime.py`
- Impact: Metrics accumulate across restarts, showing misleading cumulative counts
- Fix approach: Reset metric counters in `start()` or create a fresh `ChannelMetrics` instance

**No Server-Side Token Revocation:**
- Issue: JWT logout is client-side only; tokens remain valid until natural expiry (8h default)
- Files: `app/api/routers/auth.py`
- Impact: A stolen token or a deactivated user's token remains usable until expiry
- Fix approach: Maintain a token blocklist (Redis or in-memory with TTL), or use short-lived tokens with refresh token rotation

## Security Considerations

**Default JWT Secret in Production:**
- Risk: `JWT_SECRET_KEY` defaults to `"anpr-default-secret-change-me"` if env var not set
- Files: `app/api/auth_utils.py` (line with `os.getenv("JWT_SECRET_KEY", ...)`)
- Current mitigation: Comment in `.env` warns to change it; default is weak and public
- Recommendations: Fail startup if `JWT_SECRET_KEY` equals the default value in non-dev environments

**Default Password `1234`:**
- Risk: Default admin account uses password `1234` (documented in README, hardcoded in test helpers)
- Files: `tests/test_auth_router.py` (`_make_user(password="1234")`)
- Recommendations: Force password change on first login; do not document default passwords in public README

**JWT Token in Query Parameter:**
- Risk: `?token=<jwt>` query parameter for SSE/MJPEG streams appears in server access logs and browser history
- Files: `app/api/deps.py` (`_extract_token` function)
- Current mitigation: Nginx `X-Accel-Buffering: no` does not help with log exposure
- Recommendations: Use short-lived stream tokens issued by a dedicated endpoint; or cookie-based auth for streaming

**Per-IP Rate Limiting (Not Per-Username):**
- Risk: Distributed brute force can bypass the 5-attempts-per-IP limit by rotating IPs
- Files: `app/api/routers/auth.py` (`_check_rate_limit`)
- Current mitigation: 5 attempts per 60-second window per IP
- Recommendations: Add per-username rate limiting in addition to per-IP; consider exponential backoff

**Authentication Timing Attack:**
- Risk: Login endpoint reveals user existence via response timing: user lookup is fast when user not found vs. slow bcrypt verify when user exists
- Files: `app/api/routers/auth.py` (login endpoint)
- Recommendations: Always run bcrypt verification (against a dummy hash) regardless of whether user exists

**XSS via innerHTML in Frontend:**
- Risk: Country codes or other user-controlled data injected into HTML attributes without escaping
- Files: `app/web/` JS files — multiple `innerHTML` usages with interpolated data
- Recommendations: Replace `innerHTML` with `textContent` for text content; introduce an HTML escape utility

**RTSP Credentials in Plaintext Config:**
- Risk: Camera credentials stored plaintext in `config/settings.yaml` (bind-mounted from host)
- Recommendations: Encrypt sensitive config values at rest; or use environment variables for credentials

## Performance Bottlenecks

**Unbounded Export Query:**
- Problem: `fetch_for_export` has no `LIMIT`. Loads entire matching events table into Python memory at once
- Files: `database/postgres_event_repository.py`
- Impact: Potential OOM on large datasets (months of multi-camera operation)
- Fix: Use server-side cursors or streaming. Add date range limits. Consider background export jobs

**In-Memory Export (CSV/ZIP):**
- Problem: CSV and ZIP exports use `io.BytesIO()` without streaming
- Files: `app/api/routers/data.py`, `app/shared/data_lifecycle.py`
- Impact: Large exports occupy full memory before response begins
- Fix: Use `StreamingResponse` with generator-based chunked export

**JPEG Encoding on Every Frame:**
- Problem: Every captured frame is JPEG-encoded for preview regardless of whether any client is watching
- Files: `runtime/channel_runtime.py`
- Impact: Wasted CPU proportional to number of channels × framerate
- Fix: Track active MJPEG/snapshot consumers; skip encoding when `preview_consumers == 0`

**DebugRegistry Track History Accumulation:**
- Problem: `_track_histories` in `ChannelDebugState` grows with each new track_id; `_fallback_seq` increments unboundedly
- Files: `runtime/debug.py`
- Impact: Memory grows over long-running sessions with many plate detections
- Fix: Cap total number of track entries per channel; cleanup logic exists but may not run on idle frames

**Blocking Database Restore:**
- Problem: Database restore operations use blocking I/O inside async endpoints
- Files: `app/api/routers/data.py`
- Impact: Blocks the async event loop during restore, affecting other concurrent requests
- Fix: Run restore in `asyncio.to_thread()` or a dedicated executor

## Fragile Areas

**YOLO Detector Fallback Logic:**
- Files: `anpr/detection/yolo_detector.py`
- Why fragile: Multi-layered fallback chain (track → detect on CUDA error → detect on any exception). Once `_tracking_supported = False`, no recovery path for the lifetime of the instance
- Test coverage: None

**Channel Thread Lifecycle:**
- Files: `runtime/channel_runtime.py`
- Why fragile: Daemon threads with 3-second join timeout on stop. `cap.read()` can hang indefinitely on some RTSP sources; `stop()` may return before thread actually exits
- Test coverage: None

**Settings Schema Migration:**
- Files: `config/settings_migrations/runner.py`, `config/settings_schema.py`
- Why fragile: Single monolithic `_apply_legacy_compat` function; no incremental migration steps. Adding a new schema version requires modifying this function rather than adding a new migration
- Test coverage: None

**Settings Lock Not Async-Safe:**
- Issue: `SettingsManager` uses `threading.Lock` (via `_file_lock`) for file operations. This lock is not `asyncio`-compatible; if called from an async context (e.g., during SSE streaming), it could block the event loop
- Files: `config/settings_manager.py`, `config/settings_repository.py`

**SSE Connection Leak on Client Disconnect:**
- Issue: SSE subscriber queues may not be cleaned up promptly on client disconnect depending on Starlette/uvicorn behavior
- Files: `app/api/routers/events.py`, `runtime/event_bus.py`
- Impact: Stale queues accumulate in `EventBus._subscribers` list under high reconnect churn

## Scaling Limits

**PostgreSQL Connection Pool:**
- Current: Single shared pool, min=2, max=10 connections total (all repos share one pool per DSN)
- Limit: Under heavy load, pool exhaustion causes blocking. Pool size not configurable at runtime
- Scaling path: Make pool size configurable via settings; consider async DB access for API layer

**Screenshots Directory (Filesystem):**
- Current: Unlimited growth; manual retention trigger required
- Limit: Filesystem inode and disk space limits
- Files: `runtime/channel_runtime.py`, `app/shared/data_lifecycle.py`

**SSE / MJPEG Connections:**
- Current: Unbounded connections; each MJPEG client polls at ~12.5fps (80ms sleep)
- Limit: Many concurrent browser tabs or clients create CPU and memory pressure
- Scaling path: Add per-endpoint connection limits; shared frame broadcasting instead of per-client polling

**No Persistent Event Cache:**
- SSE clients lose all events buffered during disconnect — no replay on reconnect
- Files: `runtime/event_bus.py`

## Dependencies at Risk

**Ultralytics YOLO:**
- Risk: Frequent breaking changes between versions. Tracker fallback logic depends on internal predictor attributes (`model.predictor.trackers`, `predictor.vid_path`) not in public API
- Impact: YOLO upgrade may silently break tracking at runtime
- Files: `anpr/detection/yolo_detector.py`
- Mitigation: Version pinned at 8.3.20 in `pyproject.toml`

**psycopg / psycopg_pool:**
- Risk: Import errors surface at runtime, not at startup (lazy import pattern)
- Impact: If psycopg_pool not installed, application starts but crashes on first DB operation
- Mitigation: Import at module level or add explicit startup check

## Missing Critical Features

**No Automated Data Retention:**
- Problem: `RetentionScheduler` runs in the worker service, but the worker is a separate container. If the worker fails or is not deployed, disk fills unboundedly
- Files: `app/worker/main.py`, `app/shared/data_lifecycle.py`

**No Audit Trail:**
- Problem: No logging of data access/modification operations (who deleted what, who changed settings)
- Impact: Cannot reconstruct actions for security incidents or compliance

**No Media Encryption:**
- Problem: Screenshots stored as plaintext JPEG files on disk
- Impact: Physical or filesystem access exposes all captured license plate images

**No Automated Backup:**
- Problem: Database backup requires manual UI trigger via `/api/data/export/bundle`
- Impact: Data loss risk in unattended deployments

## Test Coverage Gaps

**Overall coverage remains incomplete:**
- Untested: `YOLODetector`, `ChannelProcessor`, `CRNNRecognizer`, `ANPRPipeline` (full integration), settings migrations, controller service

**No Channel Runtime Tests:**
- `runtime/channel_runtime.py` (most complex module: threading, OpenCV, state management) has zero test coverage
- Priority: High

**No YOLO / ML Model Tests:**
- `anpr/detection/yolo_detector.py`, `anpr/recognition/crnn_recognizer.py` untested
- Priority: Medium (requires model files)

**No Settings Migration Tests:**
- `config/settings_migrations/runner.py` untested
- Risk: Bad migration corrupts user settings on upgrade
- Priority: Medium

---

*Concerns audit: 2026-04-14*
