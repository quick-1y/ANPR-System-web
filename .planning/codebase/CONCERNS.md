# Codebase Concerns

**Analysis Date:** 2026-09-18

## SQL Injection via Table/Column Names (Medium Risk)

**Issue:** SQL queries constructed with f-strings containing table and column names.

**Files:**
- `app/shared/backup_service.py` (lines 78, 148, 175, 184-186)

**Current mitigation:** Table names are hardcoded to known values in `_BACKUP_TABLES` constant, limiting attack surface.

**Fix approach:** 
- Use `psycopg.sql.Identifier()` for safe table/column name quoting
- Replace f-string SQL with parameterized identifiers:
  ```python
  from psycopg import sql
  cur.execute(sql.SQL("SELECT {cols} FROM {table}").format(
      cols=sql.SQL(", ").join(sql.Identifier(c) for c in columns),
      table=sql.Identifier(table)
  ), values)
  ```

**Impact:** Potential data exfiltration or corruption if backup logic is modified to accept dynamic table names. Currently low risk due to static enumeration.

---

## Unsafe Process Termination (High Risk)

**Issue:** `os._exit(0)` used in database restore procedure without proper shutdown sequence.

**Files:**
- `app/api/routers/data.py` (lines 162-168)

**Problem:** 
- Skips cleanup handlers and context managers
- Thread running `_delayed_exit()` may interrupt ongoing operations
- No graceful shutdown of FastAPI, database connections, or worker processes
- Inconsistent state if called during active requests

**Fix approach:**
- Use standard shutdown mechanism: `sys.exit(0)` instead of `os._exit()`
- Allow FastAPI lifespan handlers to run
- Or use signal handlers: `signal.raise_signal(signal.SIGTERM)`
- Document that restore requires manual restart after completion

**Impact:** Risk of data corruption, lost connections, or hanging processes.

---

## Broad Exception Handling Without Context

**Issue:** Some endpoints catch generic `Exception` without distinguishing error types.

**Files:**
- `app/api/routers/data.py` (lines 107-109, 146-148, 158-160)
- Multiple routers catch `Exception` and return HTTP 500

**Problem:**
- Swallows unexpected errors that should surface
- Makes debugging difficult
- Can hide security-relevant failures

**Fix approach:**
- Catch specific exception types: `ValueError`, `OSError`, `StorageUnavailableError`
- Let uncaught exceptions bubble for monitoring
- Add structured logging with full context

**Impact:** Operational difficulty; errors hidden from error tracking/monitoring.

---

## Incomplete JWT Validation

**Issue:** Client-side JWT decoding in `app/web/js/api.js:16-26` without server verification of claims.

**Files:**
- `app/web/js/api.js` (lines 16-26)
- `app/api/deps.py` handles server validation, but relies on client-side checks first

**Current state:** Server-side validation exists (`decode_access_token` in deps.py), but frontend performs client-side expiry check.

**Risk:** 
- Frontend shows false positive about token validity
- Expired tokens sent to server (caught by server, but bad UX)

**Improvement:** Trust server-side validation only; remove client-side exp checks or use as UI hint only.

---

## Missing CSRF Protection

**Issue:** POST/PUT/DELETE endpoints lack CSRF tokens.

**Files:**
- All router files in `app/api/routers/`

**Problem:**
- Cross-site request forgery possible from forms/scripts
- No CSRF token validation on state-changing endpoints

**Current mitigation:** FastAPI's default CORS policy is restrictive (only same-origin).

**Fix approach:**
- Add `fastapi-csrf-protect` or similar
- Implement CSRF token middleware
- OR use SameSite cookie policy (recommended)

**Impact:** Medium risk if users authenticated to ANPR UI visit malicious sites simultaneously.

---

## Rate Limiting State Leakage

**Issue:** In-memory rate limiting dict accumulates entries indefinitely without pruning.

**Files:**
- `app/api/routers/auth.py` (lines 37-46)

**Problem:**
- `_failed_attempts` dictionary retains entries for all IPs
- Memory grows unbounded if many unique IPs attempt login
- On system restart, all rate limits are reset

**Fix approach:**
- Implement age-based pruning (remove entries older than 2 × `_RATE_WINDOW_SECONDS`)
- Or use Redis for persistent, memory-efficient rate limiting
- Call `_evict_old_attempts()` on each check

**Impact:** Memory leak under brute-force attack; potential DoS.

---

## Validation Gaps in Backup/Export Endpoints

**Issue:** Limited validation of user-provided dates and channel IDs in export operations.

**Files:**
- `app/api/routers/data.py` (lines 53-88)
- `app/shared/data_lifecycle.py` (lines 120-143)

**Problem:**
- `start` and `end` parameters passed directly to database queries without format validation
- No bounds checking on channel_id
- Large exports can consume excessive memory/disk

**Fix approach:**
- Validate `start`/`end` as ISO-8601 strings: `datetime.fromisoformat(start)`
- Limit export size (max rows, max date range)
- Add timeout to export operations
- Validate channel_id exists before querying

**Impact:** Potential DoS through large exports; invalid dates could cause database errors.

---

## Media File Path Traversal Risk (Low)

**Issue:** Media file names from database written to ZIP without path validation.

**Files:**
- `app/shared/data_lifecycle.py` (lines 158-163)

**Current state:** Uses `media_path.name` only (filename without directory), limiting traversal risk.

**Residual risk:** If database paths can be manipulated externally, could write outside intended directory.

**Fix approach:**
- Validate that resolved path is within `screenshots_dir`: 
  ```python
  if not str(media_path.resolve()).startswith(str(self.screenshots_dir)):
      continue  # Skip
  ```

---

## No Input Validation on Zone/Channel Binding

**Issue:** Payload validation in container methods is minimal.

**Files:**
- `app/api/container.py` (lines 187-200)

**Problem:**
- `validate_channel_controller_binding()` checks if controller exists, but no type validation
- Zone binding allows None on both fields (valid) but no mutual exclusivity enforcement
- No validation of payload structure/types

**Fix approach:**
- Move validation to Pydantic schemas
- Enforce invariants (e.g., zone XOR controller, not both)
- Use explicit validation functions

---

## Tracker State Not Reset on Size Change (Low)

**Issue:** YOLO detector may retain stale tracking state if input frame size changes mid-stream.

**Files:**
- `anpr/detection/yolo_detector.py` (lines 94-102)

**Current mitigation:** `_maybe_reset_tracker()` resets tracker when frame shape changes.

**Residual risk:** If shape change occurs between frames, one frame may use mismatched state.

**Recommendation:** Current approach is sound; monitor logs for "Сбрасываем состояние YOLO-трекера".

---

## Large File Upload Without Timeout

**Issue:** Database backup restoration accepts uploaded files without size/timeout limits.

**Files:**
- `app/api/routers/data.py` (lines 112-177, specifically line 125: `await file.read()`)

**Problem:**
- No `max_size` on UploadFile; attacker can upload 1GB+ files
- `await file.read()` loads entire file into memory
- No timeout on operation

**Fix approach:**
```python
from fastapi import UploadFile, HTTPException

MAX_BACKUP_SIZE = 100 * 1024 * 1024  # 100MB
file_size = 0
chunks = []
async for chunk in file.file:
    file_size += len(chunk)
    if file_size > MAX_BACKUP_SIZE:
        raise HTTPException(status_code=413, detail="File too large")
    chunks.append(chunk)
data = b"".join(chunks)
```

**Impact:** Memory exhaustion DoS; delayed restore operations.

---

## Race Condition in Container Processor Replacement

**Issue:** Processor replaced without synchronization during concurrent requests.

**Files:**
- `app/api/container.py` (lines 157-171)

**Problem:**
- `restart_processor_for_settings()` stops old processor and creates new one
- Other threads may be using old processor during replacement
- No lock preventing concurrent modifications

**Risk:** Untracked detections, missed events during settings update.

**Fix approach:**
- Add `asyncio.Lock` to container
- Hold lock during processor replacement
- Queue processor operations instead of immediate replacement

---

## Database Connection Error Not Surfaced Consistently

**Issue:** Some paths catch `StorageUnavailableError`, others don't.

**Files:**
- `app/api/routers/data.py` (lines 70, 88)
- `app/api/routers/events.py` (likely similar pattern)

**Problem:**
- Inconsistent error handling across routers
- Database connection failures may be logged but not returned to client
- Client cannot distinguish temporary vs permanent failures

**Fix approach:**
- Create error handling middleware that catches all `StorageUnavailableError` globally
- Return consistent HTTP 503 with detail
- Log all storage failures

---

## Missing Content-Type Validation on Settings Restore

**Issue (resolved 2026-09-21):** settings restore used to accept any YAML. It now accepts only a JSON dump of `app_settings`, validated against the registry (format, version, unknown keys, value bounds) before anything is written.

**Files:**
- `app/api/routers/data.py` (lines 198-228)

**Current mitigation:** `validate_settings_dump()` in `app/shared/backup_service.py`.

**Residual risk:** 
- None for settings: unknown keys and out-of-range values are rejected
- No validation of actual setting values (ranges, formats)

**Fix approach:**
- Use Pydantic model for settings schema
- Validate each setting's type and range
- Reject unknown keys

---

## AsyncIO Event Loop Not Null-Checked in publish_event_sync

**Issue:** Unsafe access to `main_loop` without full guards.

**Files:**
- `app/api/container.py` (lines 151-155)

**Current code:**
```python
if self.main_loop and self.main_loop.is_running():
    self.main_loop.call_soon_threadsafe(...)
```

**Risk:** Race condition between None check and `is_running()` call if event loop stops.

**Fix approach:**
```python
if self.main_loop is not None:
    try:
        if self.main_loop.is_running():
            self.main_loop.call_soon_threadsafe(...)
    except RuntimeError:  # Loop closed
        pass
```

---

## Tests Missing for Critical Paths

**Issue:** No test files found for some critical modules.

**Files without tests:**
- `app/api/routers/channels.py`
- `app/api/routers/clients.py`
- `app/api/routers/zones.py`
- `app/api/routers/settings.py`
- `app/shared/data_lifecycle.py`
- `anpr/detection/yolo_detector.py`
- Database restore functions

**Impact:** High-risk paths (backup/restore, zone configuration) lack regression test coverage.

**Fix approach:** Add test suite for all routers and lifecycle operations.

---

## No Timeout on External Stream Connections

**Issue:** Stream connections to channels may hang indefinitely.

**Files:**
- `app/api/routers/channels.py` (likely uses EventSource or similar)

**Problem:**
- Network partitions/slow clients can exhaust connection pool
- No idle timeout on streaming endpoints

**Fix approach:**
- Set `timeout` parameter on `response_streaming()`
- Implement heartbeat/keepalive messages
- Add client timeout in frontend (SSE reconnection policy)

**Impact:** Connection leak under poor network conditions.

---

## Logging May Expose Sensitive Data

**Issue:** Logs include user passwords or tokens in some debug paths.

**Files:**
- All routers log request/response data
- Debug logs may include plate numbers, channel credentials

**Risk:** Log files committed to disk without encryption could expose sensitive data.

**Fix approach:**
- Sanitize auth headers before logging
- Implement log redaction for PII fields
- Use structured logging with explicit field filtering

---

## YOLO Model Loading Blocks Startup

**Issue:** Model loading is synchronous and blocks application startup.

**Files:**
- `app/api/container.py` (lines 106-107)
- `anpr/detection/yolo_detector.py` (line 40: `YOLO(model_path)`)

**Problem:**
- If model file is missing or corrupted, entire application fails to start
- Large model (100MB+) can cause 30+ second startup delay

**Fix approach:**
- Lazy load model on first use
- Load model in background task during lifespan
- Return degraded service (detect-only, no OCR) if model fails

**Impact:** Deployment issues; increased startup time.

---

## Cleanup of Stale Tracks Has No Metrics

**Issue:** Evicted tracks are removed silently with no observability.

**Files:**
- `anpr/pipeline/anpr_pipeline.py` (lines 84-90, 320-324)

**Problem:**
- Impossible to detect if eviction is dropping valid tracks
- No alerting if eviction happens frequently (indicates misconfiguration)

**Fix approach:**
- Emit metrics: `tracks_evicted_total`, `tracks_active_gauge`
- Log eviction when it happens (INFO level)
- Alert if eviction rate exceeds threshold

---

## Exception Type Confusion in Restore Backup

**Issue:** Both `ValueError` and generic `Exception` caught for restore operations.

**Files:**
- `app/api/routers/data.py` (lines 129-130, 144-148)

**Problem:**
- Unclear which errors are expected vs unexpected
- May mask underlying bugs

**Fix approach:**
- Define custom exceptions: `InvalidBackupError`, `BackupRestoreError`
- Catch specific types
- Log unexpected errors as WARNING/ERROR

---

## Zone TTL Not Synchronized with Retention

**Issue:** Stale zone tracking may outlive event retention.

**Files:**
- Event zones stored in database with indefinite TTL
- Events deleted by retention policy, but zone associations persist

**Risk:** Orphaned zone records accumulate over time.

**Fix approach:**
- Delete zone associations when parent event is deleted
- Or implement zone TTL matching event TTL
- Add cleanup job for orphaned zones

---

## No Backpressure on Event Publishing

**Issue:** Event publishing is fire-and-forget; no flow control.

**Files:**
- `app/api/container.py` (lines 151-155)
- `runtime/event_bus.py` (likely buffered without limits)

**Problem:**
- High-throughput scenarios may overflow event bus
- No indication to caller if event was actually delivered

**Fix approach:**
- Add bounded queue to event bus
- Return `Future` from publish; caller can await
- Drop oldest events if queue full (with logging)

---

## Plate Cooldown May Suppress Valid Detections

**Issue:** Duplicate plate suppression uses simple time-based cooldown.

**Files:**
- `anpr/pipeline/anpr_pipeline.py` (lines 401-414)

**Problem:**
- Same plate number reported legitimately at different times may be suppressed
- Cooldown reset on system restart
- No per-lane tracking (same plate on different lane suppressed incorrectly)

**Fix approach:**
- Use (plate, zone) tuple for cooldown key
- Implement per-channel cooldown
- Log suppressed events for audit

**Impact:** May miss legitimate duplicate plates at busy intersections.

---

## Symlink Handling in Media Cleanup

**Issue:** File cleanup uses `Path.unlink()` without checking for symlinks.

**Files:**
- `app/shared/data_lifecycle.py` (lines 80, 106)

**Problem:**
- Following symlinks could delete files outside screenshots_dir
- Malicious administrator could create symlinks to system files

**Fix approach:**
```python
if media_path.is_symlink():
    logger.warning("Skipping symlink: %s", media_path)
    continue
```

**Impact:** Low if file permissions are correct; high if compromised admin account.

---

## No Graceful Degradation if CRNN Model Unavailable

**Issue:** CRNN recognizer required; no fallback if model fails to load.

**Files:**
- `app/api/container.py` (lines 102-117)

**Problem:**
- Missing model file causes complete application failure
- No way to run detection-only mode (without OCR)

**Fix approach:**
- Load model lazily
- Detect availability and return empty recognizer if unavailable
- Log warnings, continue with degraded functionality

---

## Connection Pool May Not Reconnect After Extended Outage

**Issue:** Database connection pool configured without reconnection strategy.

**Files:**
- `database/base.py` (pool initialization, not shown but likely issue)

**Risk:** If PostgreSQL down for > timeout, connection pool remains unusable until restart.

**Fix approach:**
- Implement exponential backoff reconnection
- Validate connections before use
- Add circuit breaker pattern

---

## No Audit Log for Sensitive Operations

**Issue:** Settings changes, user management, permission changes not logged comprehensively.

**Files:**
- `app/api/routers/settings.py`
- `app/api/routers/users.py`

**Problem:**
- Regulatory/compliance issue; cannot trace who changed what and when
- No way to detect unauthorized changes

**Fix approach:**
- Log all mutations: {user, timestamp, operation, before, after}
- Store audit log in database (immutable)
- Provide audit log query endpoint

---

Summary Statistics:
- **High Risk:** 2 (unsafe exit, large file upload)
- **Medium Risk:** 4 (SQL injection, missing CSRF, rate limit leak, restore validation)
- **Low Risk:** 8+ (various improvements and observability gaps)

**Recommendation Priority:**
1. Fix unsafe process termination (data corruption risk)
2. Implement large file upload limits
3. Add CSRF protection
4. Refactor SQL queries to use parameterized identifiers
5. Expand test coverage for critical paths

---

*Concerns audit: 2026-09-18*
