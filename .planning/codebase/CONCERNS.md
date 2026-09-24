---
last_mapped_commit: 9cfd79b3a864f23127a46c35300f838c212d0007
last_mapped_at: 2026-09-24
---
# Codebase Concerns

**Analysis Date:** 2026-09-24

## Tech Debt

### Settings Normalizer Imports Controllers

**Issue:** `config/settings_schema.py` imports `SUPPORTED_CONTROLLER_TYPES` from `controllers/` module, creating a unidirectional coupling from configuration to domain logic.

**Files:** `config/settings_schema.py`, `config/registry.py`, `controllers/__init__.py`

**Impact:** Configuration layer should be independent. Adding a new controller type requires changes in both `controllers/` and `config/`. Cross-domain imports violate layering rules documented in AGENTS.md.

**Fix approach:** Move `SUPPORTED_CONTROLLER_TYPES` definition to a shared location (`common/` or dedicated types module) that both `config/` and `controllers/` can import without creating coupling.

### Dead Environment Variables

**Issue:** Three environment variables are declared in `.env.example` and read by Docker/docker-compose, but never consumed by Python code.

**Files:** `.env.example`, `docker-compose.yml`, `Dockerfile`

- `APP_ENV`: Passed to container, used nowhere in code
- `DEBUG`: formerly duplicated the `debug` section of `config/settings.yaml`; that file has been removed — verify whether this is still a concern
- `LOG_LEVEL`: Duplicates `logging.level` in settings (now removed)

**Impact:** Operator confusion about whether setting these env vars has any effect. Dead code blocks future refactoring clarity.

**Fix approach:** Remove these three variables from `.env.example`, `docker-compose.yml`, and `Dockerfile` ENV declarations.

### Environment Variable Drift

**Issue:** `.env.example` does not list all environment variables actually read by code.

**Files:** `.env.example`, `config/env_settings.py`, `app/api/main.py`

- `CORS_ALLOWED_ORIGINS`: Documented in schema but missing from `.env.example`
- `POSTGRES_PORT`: Used in docker-compose.yml but not documented anywhere
- `TZ`: Timezone is not exposed as an environment variable, but container behavior depends on it implicitly

**Impact:** Deployment documentation incomplete. Operators cannot reliably understand what env vars they must configure.

**Fix approach:** Audit all env var reads in `config/env_settings.py`, `app/api/main.py`, and list every one in `.env.example` with explanatory comments.

### Validation Missing on Channel Update Endpoint

**Issue:** `PUT /api/channels/{channel_id}` at `app/api/routers/channels.py:144` accepts a raw `Dict[str, Any]` payload without Pydantic validation.

**Files:** `app/api/routers/channels.py:144-150`

```python
def update_channel(channel_id: int, payload: Dict[str, Any], ...):
    updated = container.channel_db.update_channel(channel_id, payload)
```

**Impact:** Any invalid field name or type passed in the dict is silently accepted or causes a database error. Inconsistent with other endpoints that use `ChannelPayload` or other Pydantic models. Schema contract is undefined for clients.

**Fix approach:** Create a `ChannelUpdatePayload` Pydantic model, validate input against it. Reference AGENTS.md "Patterns To Avoid Copying" which flags this pattern.

---

## Known Bugs

### Theme and Style Persist Inconsistently

**Issue:** Personal UI settings (theme, style, sidebar state, grid size) have conflicting sources of truth.

**Files:** `app/web/js/app.js:297-299`, `app/web/js/settings.js:50-54`, `app/web/index.html:93`, `config/settings_schema.py`

**Symptoms:**

- Before login: theme/style read from `localStorage` (defaults: `graphite-minimal`, `light`)
- After login: theme/style fetched from API `/api/settings`, overwriting localStorage with server values (defaults: `aurora`, `dark`)
- Theme toggle in topbar writes to localStorage but not to server
- Next page reload ignores user's toggle choice and reverts to server value

**Trigger:** (1) Open app before login, set theme in topbar. (2) Log in. (3) Observe theme resets to server default. (4) Toggle theme. (5) Reload page. (6) Observe toggle is lost.

**Workaround:** None. User must accept the configured server theme or repeatedly toggle after each reload.

**Root cause:** Three independent sources (localStorage before auth, server config after auth, frontend toggle) without a reconciliation strategy. See roadmap P1 for full analysis.

### Timezone Model Inexpressible for DST Zones

**Issue:** The `interface.display_timezone` setting (formerly `time.timezone`) stores timezone as a fixed UTC offset (e.g., `UTC+03:00`), which cannot represent daylight-saving-time transitions.

**Files:** `config/registry.py`, `config/settings_schema.py`, roadmap section 2.6

**Impact:** For countries with DST (Ukraine, Belarus) that are in the plate recognition whitelist, time display is offset by 1 hour for half the year.

**Fix approach:** Change `interface.display_timezone` domain from fixed offsets to IANA timezone identifiers (`Europe/Kyiv`, `Europe/Minsk`, etc.). Default to `UTC`. Per project policy, no settings migration: change the registry domain directly and re-enter the value through the UI.

### Inconsistent CSV Export Timezone Labels

**Issue:** Data exported as CSV includes timestamps in UTC but does not label them as UTC in the file.

**Files:** `app/shared/data_lifecycle.py:127-136`

**Impact:** Operator importing exported data into a spreadsheet cannot determine which timezone the times are in. If importing multiple exports from different systems (e.g., another ANPR installation in a different timezone), times appear to overlap or be out of order.

**Fix approach:** (1) Add a header row or comment in CSV file stating "All times in UTC". (2) Or: include timezone offset in each timestamp column (`2026-09-24T14:30:00+00:00`).

---

## Security Considerations

### Authorization Model Undecided and Partially Broken

**Risk:** The authorization model is documented as "pending redesign" (AGENTS.md section "Authorization Model — UNDECIDED"). Current implementation has known defects documented in roadmap section 2.7 (problems P2, P18, P19).

**Files:** `app/api/deps.py`, `app/api/routers/auth.py`, `app/api/routers/users.py:147`, roadmap section 2.7

**Current state:**

- `tab:settings` permission guards 18 unrelated operations (export, backup, database restore, retention runs, user management, settings read) that have nothing to do with "Настройки tab visibility"
- 46 endpoints are protected only by `get_current_user()` with no authorization check
- Four tab permissions (`tab:obs`, `tab:journal`, `tab:clients`, `tab:zones`) are checked only on frontend; backend endpoints are unprotected
- Destructive operations (`DELETE /api/channels/{id}`, `DELETE /api/zones/{id}`, `DELETE /api/lists/{id}`) have no permission guard beyond "you must be logged in"

**Recommendations:**

1. **Do not extend `tab:*` permission guards** to new endpoints. The tab permission system is known to be incorrect and will be redesigned in phase 11.
2. **Do not add new permission names** without consulting phase 11 roadmap. All new authorization decisions should route through the adapter layer in `app/api/deps.py`.
3. **Do not rely on current permission names** as the final authority model. Code defensively with the assumption that the model will change.

See roadmap section 4.11 for the access-level adapter pattern (`public`, `self`, `admin-*`) that phase 11 will use to point permissions to a proper model, once chosen.

### Destructive Operations Unprotected

**Risk:** Resource-destroying endpoints (`DELETE /api/channels/{channel_id}`, `DELETE /api/zones/{zone_id}`, `DELETE /api/lists/{list_id}`, `DELETE /api/clients/{client_id}`) are guarded only by `get_current_user`, with no additional authorization.

**Files:** `app/api/routers/channels.py`, `app/api/routers/zones.py`, `app/api/routers/lists.py`, `app/api/routers/clients.py`, `app/api/routers/users.py`

**Impact:** An operator with only `tab:obs` (observation/monitoring) permission can delete channels by calling the API directly (`curl -H "Authorization: Bearer $TOKEN" -X DELETE http://host/api/channels/1`). There is no server-side check preventing this.

**Current mitigation:** Frontend UI does not expose delete buttons to non-superadmin users. But this is a UI-level control, not a server-level enforcement.

**Recommendations:** Pause adding new destructive endpoints until phase 11 redesigns authorization. For existing destructive endpoints, implement server-side guards (either `require_role("superadmin")` or a dedicated `admin-data` access level per section 4.11 of the roadmap).

### Frontend XSS Risk in innerHTML Assignments

**Risk:** 46 uses of `innerHTML =` in frontend modules, some of which interpolate untrusted content.

**Files:** `app/web/js/*.js` (app.js, channels.js, clients.js, controllers.js, debug.js, events.js, journal.js, lists.js, users.js, zones.js, video-grid.js, ui.js, roi-editor.js)

**Examples of risk:**

- `app/web/js/debug.js`: Log messages interpolated into HTML: `line.innerHTML = ``<span>${ts}</span>${meta} ${text}```
- `app/web/js/events.js`: Dynamic flag HTML: `flagContainer.innerHTML = flagHtml(item.country)`

**Mitigation:** Most uses are safe (setting static control structure or known-safe enum values like country codes). But audit needed to identify if any user input or external data is interpolated without escaping.

**Fix approach:** For any dynamic content, use `textContent` instead of `innerHTML`, or use `createElement` and `appendChild` to construct elements programmatically. See AGENTS.md "Patterns To Avoid Copying" note on `innerHTML` XSS risks.

### Credential Exposure in Logs

**Risk:** Channel source URLs (RTSP credentials embedded in `channels.source`) and controller passwords (in `controllers.password`) must not be logged in full.

**Files:** Any logging in pipeline that references channel or controller objects

**Current state:** Code does not appear to log full credentials intentionally, but breadth of logging in `anpr/pipeline/anpr_pipeline.py` with channel context should be audited.

**Recommendation:** Before logging any channel or controller object, redact sensitive fields:

- `channels.source`: Redact credentials in RTSP URL
- `controllers.password`: Never log this field
- API responses: Never return full `channels.source` or `controllers.password` in responses (document in API schema)

---

## Performance Bottlenecks

### YOLO Detector Depends on Internal Ultralytics API

**Problem:** License plate detection uses internal attributes of the ultralytics YOLO library that are not part of the public API and may change without notice.

**Files:** `anpr/detection/yolo_detector.py:55-68`

```python
predictor = getattr(self.model, "predictor", None)  # Internal API
trackers = getattr(predictor, "trackers", None)     # Internal API
predictor.vid_path = [None] * len(trackers)         # Internal API
```

**Cause:** The ultralytics library does not expose a public tracker reset interface. To reset tracking state on frame size change, the code accesses `model.predictor.trackers` and `predictor.vid_path` directly.

**Impact:** Upgrading `ultralytics` beyond 8.3.20 (currently pinned in `pyproject.toml`) may break frame resizing or tracking state management silently — detection will still work, but tracking IDs may become inconsistent.

**Improvement path:**

1. Do not upgrade `ultralytics` version without testing frame-size transitions in a multi-resolution RTSP source scenario
2. Monitor ultralytics releases for public tracker reset API
3. If API is added, refactor to use it instead of internal attributes

---

## Fragile Areas

### Connection Pool Not Updated in refresh_storage_clients()

**Files:** `app/api/container.py:264-284`

**Why fragile:** When the DSN (PostgreSQL connection string) changes, `refresh_storage_clients()` recreates most database instances but **does not update `self.settings_service._repository`**. 

**Current code:**

```python
def refresh_storage_clients(self) -> None:
    ...
    self.events_db = PostgresEventDatabase(dsn)
    self.lists_db = ListDatabase(dsn)
    ...
    # But NOT: self.settings_service._repository = AppSettingsRepository(dsn)
```

**What breaks:** If the DSN is changed at runtime and the new database has different settings values, `SettingsService` will continue to read from the old database's connection pool. The new pool is closed, but the settings service still references the old one.

**Safe modification:** Add `self.settings_service._repository = AppSettingsRepository(dsn)` after line 270 in `refresh_storage_clients()`. Verify that `SettingsService._refresh_if_stale()` will properly reload from the new repository on next access.

**Test coverage:** No test exists for `refresh_storage_clients()` behavior when the DSN changes. Current tests mock this method.

### Daemon Channel Threads with 3-Second Join Timeout

**Files:** `runtime/channel_runtime.py:213-222` (stop method)

**Why fragile:** Channel processing threads are daemon threads with a hard 3-second join timeout. If the thread is blocked in OpenCV's `cap.read()` call waiting for an RTSP frame, `stop()` returns immediately without waiting for the thread to exit. The thread continues running in the background.

```python
if thread and thread.is_alive():
    thread.join(timeout=3)  # Returns after 3 seconds even if thread still running
```

**Impact:** Rapid stop-start cycles on a channel can leave orphaned threads consuming resources and hogging the video stream. Shutdown during an RTSP timeout may not cleanly release the TCP connection.

**Safe modification:** Consider a longer timeout or a more sophisticated shutdown protocol (e.g., event-driven wait with exponential backoff). Alternatively, use a non-daemon thread and ensure graceful shutdown before process exit.

### Settings Changes Require Channel Restart

**Files:** `app/api/routers/settings.py` (PUT endpoint), `runtime/channel_runtime.py`

**Why fragile:** Changing most operational settings (plate countries, detection confidence, motion thresholds) does not automatically update running channels. The setting is stored and applied to newly-created channels, but existing channels ignore it until manually restarted.

**Current state:** This is by design (documented in AGENTS.md "Known Pitfalls"). But it creates a support burden: operators must remember to restart channels after changing settings, or see inconsistent behavior across channels.

**Safe modification:** None needed — behavior is intentional. Document clearly in UI and API responses which settings require channel restart.

---

## Scaling Limits

### Single Shared OCR Recognizer

**Current capacity:** One CRNN OCR model instance is shared across all channel threads. OCR inference runs sequentially on one GPU or CPU core.

**Limit:** If multiple channels have plates to recognize simultaneously, only one can process at a time. The other threads block waiting for the recognizer lock (`anpr/pipeline/factory.py:18`).

**Scaling path:** For systems with 20+ channels running in parallel:

1. Profile OCR latency under concurrent load to identify bottleneck
2. Consider multi-instance OCR pool with round-robin work distribution
3. Evaluate multi-GPU setup if available
4. Alternatively, offload OCR to a separate service and call via HTTP

### Connection Pool Size

**Current capacity:** PostgreSQL connection pool min=2, max=10 (hardcoded in `database/base.py:26`)

**Limit:** With 10 channels, each potentially holding a connection for screenshot upload or event logging, all 10 connections can be exhausted. A 11th concurrent DB operation waits for a connection to be released.

**Scaling path:** Make pool size configurable via environment variables or settings. Adjust min/max based on channel count and load testing.

---

## Dependencies at Risk

### PyTorch CPU Wheels from Non-Standard Source

**Risk:** PyTorch CPU wheels are installed from `download.pytorch.org/whl/cpu` (custom Poetry source), not PyPI.

**Files:** `pyproject.toml` (Poetry configuration with explicit source)

**Impact:** If `download.pytorch.org` becomes unavailable or is compromised, builds will fail or pull malicious wheels. The build is not reproducible from pypi.org alone.

**Migration plan:** Monitor PyTorch availability on PyPI. Once CPU wheels are available on standard PyPI (they may be now), remove the custom source and use `pip install torch==2.8.0` for CPU. Verify no security regression.

---

## Test Coverage Gaps

### Destructive Operations Not Tested for Authorization

**What's not tested:** Delete endpoints (`DELETE /api/channels`, `DELETE /api/zones`, `DELETE /api/lists`, `DELETE /api/users`) are not tested with different user roles/permissions. Tests do not verify that a non-admin user cannot delete resources.

**Files:** `tests/test_container_validation.py`, `tests/test_users_router.py`, `tests/test_permission_guards.py` (do not cover destructive operations on all resources)

**Risk:** Authorization bypass on delete endpoints would go undetected by test suite.

**Priority:** High

### Connection Pool Refresh Behavior Not Tested

**What's not tested:** `refresh_storage_clients()` method is mocked in tests but never actually exercised with a real pool and DSN change.

**Files:** `tests/test_data_router.py`, `tests/test_reconnect_settings.py` (mock the method)

**Risk:** Pool cleanup logic or settings repository update could silently fail.

**Priority:** Medium

### YOLO Detector Frame Size Transition Not Tested

**What's not tested:** Detector's tracker state reset behavior when frame resolution changes during playback.

**Files:** `anpr/detection/yolo_detector.py:_maybe_reset_tracker()` (method exists, no tests)

**Risk:** Frame size change (e.g., RTSP reconnect at different resolution) could corrupt tracking state.

**Priority:** Medium

### Frontend innerHTML Content Not Audited for XSS

**What's not tested:** No automated check for dynamic content in `innerHTML` assignments. Manual audit required to identify untrusted interpolations.

**Files:** `app/web/js/*.js` (46 uses of `innerHTML =`)

**Risk:** Unescaped user input or enum values could be injected into DOM.

**Priority:** Medium

### Superadmin Endpoint Not Tested with Invalid/Missing Password

**What's not tested:** `PUT /api/settings/superadmin-password` and login path do not test behavior when `SUPERADMIN_PASSWORD` env var is missing or unset.

**Files:** `tests/test_superadmin.py`, `app/api/routers/auth.py`, `app/api/superadmin.py`

**Risk:** If env var is not set, superadmin login either silently fails or accepts empty password.

**Priority:** Low

---

## Missing Critical Features

### No Audit Trail for Settings Changes

**Problem:** When an operator changes a setting (e.g., detection confidence, enabled countries), there is no permanent record of who changed what and when.

**Impact:** Compliance/forensics challenge. Cannot trace why detection behavior changed on a given date.

**Workaround:** None. Review PostgreSQL `app_settings` table revision history (if kept).

---

*Concerns audit: 2026-09-24*
