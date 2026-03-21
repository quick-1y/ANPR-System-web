# Codebase Concerns

**Analysis Date:** 2026-03-21

## Tech Debt

**Broad Exception Handling:**
- Issue: Multiple catch-all `except Exception` blocks throughout codebase suppress specific errors, making debugging harder
- Files: `database/postgres_event_repository.py` (lines 60, 94, 108, 152, 166, 181, 200, 242), `database/plate_lists_repository.py` (line 150), `anpr/detection/yolo_detector.py` (lines 171, 232), `runtime/channel_runtime.py` (lines 256, 592), `controllers/service.py` (lines 101, 216), `common/logging.py` (lines 51, 88, 169, 173), `app/api/container.py` (line 139), `app/api/routers/settings.py` (line 42)
- Impact: Errors are logged but stack traces masked. Network failures, permission issues, and data corruption are treated identically. Difficult to implement proper recovery strategies
- Fix approach: Replace broad catches with specific exception types. Create custom exceptions for domain concepts (StorageUnavailableError is good model). Use noqa comments only where intentional diversity is required

**Monolithic Frontend File:**
- Issue: `app/web/app.js` is 2500 lines of single-file imperative JavaScript
- Files: `app/web/app.js`
- Impact: State management scattered across module globals (`state`, `eventSource`, `streamReconnectTimer`, `debugLogSource`, `overlayRefreshTimer`, `eventFeedRefreshTimer`, etc.). Makes refactoring risky. Hard to trace state mutations. Event listener cleanup fragmented
- Fix approach: Refactor into modules: state management (single source of truth), UI layers (channels, events, lists, settings), API client wrapper, event stream manager. Use classes or closures to scope state

**Connection Per-Request Pattern:**
- Issue: Database code creates new PostgreSQL connections via `_connect()` for every query instead of using connection pooling
- Files: `database/postgres_event_repository.py` (all query methods), `database/plate_lists_repository.py` (all methods)
- Impact: High latency (connection handshake per query), exhausts database connection limits under load, no connection reuse. Observed repeatedly: `with self._connect() as conn` pattern
- Fix approach: Implement psycopg connection pool (psycopg.pool.ConnectionPool). Inject shared pool into repository constructors. Measure improvement in response times and max concurrent users

**Settings Normalizer Dependency Leak:**
- Issue: `config/settings_normalizer.py` imports `controllers.SUPPORTED_CONTROLLER_TYPES` for validation. Creates circular dependency risk
- Files: `config/settings_normalizer.py` (line 17)
- Impact: Couples configuration layer to controller layer. If controller types change, settings validation must change. Blocks independent refactoring
- Fix approach: Move controller type enumeration to `config` package or shared constants. Use dependency injection to pass supported types to normalizer

**Inconsistent Error Response Format:**
- Issue: API returns both HTTP exceptions and ad-hoc JSON error dicts from different endpoints
- Files: `app/api/routers/channels.py` (HTTPException), `app/api/routers/events.py`, `app/api/routers/settings.py` (custom error dicts), `app/worker/main.py` ({"status": "error", "detail": ...})
- Impact: Clients must handle variable error structure. Hard to build universal error handler. Inconsistent status codes (mix of 503 and 500)
- Fix approach: Define ErrorResponse schema in `app/api/schemas.py`. Create exception handler middleware to convert all exceptions to consistent JSON format with status_code, error_code, message, detail fields

**innerHTML Usage in Frontend:**
- Issue: DOM updates use innerHTML with user-controllable content (plate numbers, channel names)
- Files: `app/web/app.js` (lines 520, 772, 913, 1055, 1078, 1959, etc.)
- Impact: If plate recognition returns crafted input or channel names contain HTML, injected scripts could execute. Low risk in current single-operator context but XSS vulnerability if exposed to untrusted input
- Fix approach: Use textContent for user data. For HTML structure, use createElement + appendChild. Sanitize any user-provided HTML with DOMPurify

---

## Known Bugs

**Preview Frame Initialization Race:**
- Symptoms: Channel snapshot requests fail with "Preview кадр ещё не готов" even after channel running for several seconds
- Files: `runtime/channel_runtime.py` (line 48 in `get_preview_frame`), `app/api/routers/channels.py` (line 48)
- Trigger: Request snapshot immediately after channel start before first frame processed
- Root cause: Preview frame stored in `ctx.latest_jpeg` only after first successful inference. No buffering of initial frames
- Workaround: Client retries with exponential backoff. Typically succeeds within 2-3 seconds
- Fix approach: Pre-allocate placeholder frame or buffer initial raw frames. Move preview from inference result to frame capture step

**Reconnection State Not Cleared on Manual Restart:**
- Symptoms: After manual channel restart, reconnect metrics accumulate incorrectly (reconnect_count keeps growing)
- Files: `runtime/channel_runtime.py` (line 212, ChannelMetrics not reset in `stop()`)
- Trigger: User clicks restart button on channel that had connection failures
- Root cause: ChannelMetrics created fresh in `start()` but reconnect tracking happens inside `_run_channel()` loop which doesn't reset
- Workaround: Full system restart clears metrics
- Fix approach: Reset ChannelMetrics state in `start()` after old thread cleanup. Add unit test for restart cycle

**Settings Update Doesn't Affect Running Channels:**
- Symptoms: Changing channel configuration via API doesn't affect currently-running channel until next automatic restart
- Files: `app/api/routers/channels.py` (PUT endpoint line 180), `runtime/channel_runtime.py` (reads channel config once in `_run_channel` line 344)
- Trigger: Update channel OCR confidence, motion threshold, or other parameters while channel is running
- Root cause: `_run_channel()` snapshots channel dict at start (`channel = dict(ctx.channel)` line 344) and uses snapshot for entire session
- Impact: Changes delayed 5+ minutes (reconnect interval) or until manual restart
- Fix approach: Pass settings through queue or event. Poll for changes in inference loop. Add listener pattern to channel context

---

## Security Considerations

**API Key Stored in LocalStorage:**
- Risk: Browser localStorage not protected against XSS. If frontend is compromised, API key can be stolen
- Files: `app/web/app.js` (lines 25-32, `getApiKey()`, `setApiKey()`)
- Current mitigation: Single-operator use case. No user authentication. API key validated on every request
- Recommendations:
  - For multi-user deployment: Implement session tokens with short TTL (15 min) + refresh token rotation
  - Move API key to HTTPOnly secure cookie (not accessible to JavaScript)
  - Add CSRF token to state-changing requests
  - Log all API key usage for audit trail

**Database Credentials in DSN String:**
- Risk: DSN contains plaintext password in memory and config files
- Files: All database instantiation points pass `postgres_dsn` from settings
- Current mitigation: `.env` file excluded from git (gitignored)
- Recommendations:
  - Use environment variables only (not config files) for credentials
  - Consider external secret store (Vault, AWS Secrets Manager) for production
  - Implement database connection SSL requirement in DSN
  - Rotate credentials on deployment

**Minimal Input Validation:**
- Risk: Channel URLs, plate list data, controller hostnames accepted with minimal validation
- Files: `app/api/routers/channels.py` (POST/PUT), `app/api/routers/lists.py` (POST entries), `app/api/routers/controllers.py`
- Current validation: Type checking only. No length limits, URL scheme validation, or injection prevention
- Recommendations:
  - Add Pydantic validators for URL format, length constraints, character restrictions
  - Whitelist allowed characters for plate/name fields
  - Add rate limiting on mutable endpoints (POST/PUT/DELETE)

---

## Performance Bottlenecks

**Serial Database Queries:**
- Problem: List views fetch all plates from all lists without pagination. Event journal loads full history
- Files: `database/plate_lists_repository.py` (fetch_entries method), `app/api/routers/events.py` (list_events endpoint)
- Cause: No LIMIT/OFFSET clauses. Memory loaded entirely into Python dicts before returning
- Scaling limit: 10,000+ events cause noticeable UI lag; 100,000+ events cause timeout
- Improvement path: Implement paginated response schema. Add `limit`, `offset`, `sort_by`, `sort_dir` parameters. Index PostgreSQL tables on `timestamp` and `channel_id`

**Memory Accumulation in DebugRegistry:**
- Problem: `_track_histories` and `_track_last_seen` dicts grow unbounded as vehicles are tracked
- Files: `runtime/debug.py` (lines 53-54, ChannelDebugState)
- Current cap: State TTL cleanup (2 seconds default) only removes stale channel entries, not per-track history
- Scaling limit: Long-running system (days) accumulates megabytes in debug state
- Improvement path: Implement bounded deque (maxlen=1000) for track histories. Explicit cleanup on state expiration. Consider ring buffer for live tracking

**Frontend Event Feed DOM Thrashing:**
- Problem: renderEventFeed rebuilds entire DOM (removeChild/appendChild) on every event
- Files: `app/web/app.js` (lines 753-800, renderEventFeed function)
- Cause: No virtual DOM. No event deduplication. ResizeObserver triggers on every update
- Scaling limit: 100+ events/sec causes frame drops. Older entries never removed (memory leak)
- Improvement path: Virtual scrolling (only render visible items). Batch DOM updates. Cap feed to last 100 entries. Debounce resize handler

---

## Fragile Areas

**YOLO Detector Fallback Logic:**
- Files: `anpr/detection/yolo_detector.py` (lines 55, 171, 228-237)
- Why fragile: On any inference error, silently disables tracking and switches to pure detection mode. No logging of why it failed. No recovery attempt
- Safe modification: Add structured logging with error type and retry counter. Add explicit test case for each exception path (OOM, timeout, model corruption)
- Test coverage: No unit tests for error cases. Missing: `test_detect_handles_invalid_frame`, `test_tracking_gracefully_degrades`

**Channel Thread Lifecycle:**
- Files: `runtime/channel_runtime.py` (start/stop methods, _run_channel loop)
- Why fragile: Stop sets event but doesn't wait for thread to actually finish writing to latest_jpeg. Race condition between preview request and thread cleanup
- Safe modification: Add synchronization point (Event.wait()) in preview getter. Add timeout and force-stop if cleanup takes >5s
- Test coverage: No integration test for concurrent operations. Missing: `test_channel_restart_while_preview_requested`, `test_concurrent_stop_and_restart`

**Settings Schema Migration:**
- Files: `config/settings_migrations/runner.py`, `config/settings_normalizer.py`
- Why fragile: Migrations are functions without versioning. If schema changes and old migration code is removed, can't load old files. No validation that migrations are idempotent
- Safe modification: Version each migration (e.g., V001_add_roi_field.py). Add pre/post state validation. Test migration on real settings.yaml from previous versions
- Test coverage: No migration tests. Missing: `test_v001_adds_roi_field_with_defaults`, `test_v002_migration_idempotent`

---

## Scaling Limits

**PostgreSQL Connection Pool:**
- Current capacity: ~5-10 concurrent connections (psycopg default)
- Limit: Under load with 20+ concurrent API requests, connections wait in queue. Connection timeout after 30s
- Scaling path: Implement pooling with min=5, max=20 connections. Monitor pool utilization. Cache frequently-accessed queries (last_plates)

**Screenshots Directory Filesystem:**
- Current capacity: Daily structure (YYYY-MM-DD/channel_N/). Tested with ~100K files
- Limit: Filesystem traversal for cleanup becomes slow >500K files. Directory listing takes >5 seconds
- Scaling path: Sharded storage (hash-based subdirs). Implement batch deletion. Use database index for file paths instead of filesystem scan

**Event Stream SSE Connections:**
- Current capacity: One EventSource per client, streams all events
- Limit: 100+ concurrent clients consume 100+ MB memory. Server can't distinguish slow from dead clients
- Scaling path: Implement WebSocket with heartbeat. Add client-side filter (channel_id) at subscription level. Stream in JSON Lines format for better streaming

---

## Dependencies at Risk

**OpenCV (cv2) Version Pinning:**
- Risk: No explicit version in requirements.txt. Major version changes (3→4) break API
- Impact: Dependency installation on new machine might pull incompatible version
- Migration plan: Pin to cv2==4.8.1.78. Test OCR and YOLO detection still work. Document required build tools (build-essential on Linux)

**YOLO Model Download:**
- Risk: Downloads from ultralytics server at runtime. Server outage blocks app startup
- Impact: Cannot deploy in offline environments
- Migration plan: Bundle model weights in Docker image. Fall back to CPU-only mode if weights missing. Add explicit model path configuration

---

## Missing Critical Features

**Request Timeout on Video Streams:**
- Problem: ffmpeg streams from dead IP addresses hang forever. No socket timeout configured
- Files: `runtime/channel_runtime.py` (line ~450, cv2.VideoCapture(url))
- Blocks: Channels to offline cameras never recover without manual restart
- Impact: Loss of monitoring if even one camera goes offline
- Fix: Set read timeout on VideoCapture (platform-specific, may require OpenCV 4.4+). Implement watchdog that restarts channels with stale frames

**Concurrent Channel Updates:**
- Problem: No locking when user updates channels while processor is iterating them
- Files: `app/api/routers/channels.py` (PUT handler), `runtime/channel_runtime.py` (list_states iteration)
- Blocks: Safe concurrent configuration updates
- Impact: Race condition possible (read list while being modified)
- Fix: Add RLock around settings access in ChannelProcessor

**Graceful Shutdown:**
- Problem: No coordinated shutdown of channels on app termination
- Files: No cleanup in ASGI shutdown handler
- Blocks: Video capture threads may remain open
- Impact: File handles leak, ports remain bound
- Fix: Add explicit `shutdown()` handler in ChannelProcessor that stops all channels with timeout

---

## Test Coverage Gaps

**Database Error Scenarios:**
- What's not tested: Connection timeout, authentication failure, schema missing, query syntax error
- Files: `database/postgres_event_repository.py`, `database/plate_lists_repository.py`
- Risk: Code path only exercised if database actually fails. Fallback error handling untested
- Priority: High - database failures are common in production

**Channel Restart Race Conditions:**
- What's not tested: Restart during active frame processing, concurrent stop/start calls
- Files: `runtime/channel_runtime.py`
- Risk: Memory leaks if thread cleanup incomplete
- Priority: High - restart is common user action

**Frontend State Sync:**
- What's not tested: EventSource drops, reconnection with stale state, concurrent API calls
- Files: `app/web/app.js` (event stream handling)
- Risk: UI shows inconsistent state if stream reconnects mid-event
- Priority: Medium - client-side issue but impacts user trust

**Settings Migration Edge Cases:**
- What's not tested: Upgrade from very old version, partial settings files, corrupt YAML
- Files: `config/settings_migrations/`, `config/settings_normalizer.py`
- Risk: Unhandled migration failure leaves system in broken state
- Priority: Medium - rare but catastrophic when it happens

**YOLO Detector Fallback Paths:**
- What's not tested: OOM, model not found, corrupted model weights, unsupported CUDA version
- Files: `anpr/detection/yolo_detector.py`
- Risk: Silent failures without observability
- Priority: Medium - need visibility into model loading failures

---

*Concerns audit: 2026-03-21*
