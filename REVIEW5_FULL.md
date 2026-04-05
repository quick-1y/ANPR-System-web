# ANPR System v0.8 — Deep Architectural Review #5

**Date**: 2026-04-04
**Branch**: `dev_add_auth`
**Scope**: Architecture, naming, unused code, legacy code, consistency, recognition pipeline

---

## 1. Executive Summary

### Overall Assessment

The codebase is well-structured for a single-developer project of this scale (~10,900 lines Python, ~2,600 lines JS). The module separation has improved significantly since prior reviews (R1-R4). The recognition pipeline is efficiently designed with shared YOLO weights, singleton OCR, connection pooling, and adaptive frame striding. The auth system (JWT + RBAC) is properly layered.

**Main strengths:**
- Clean separation: `anpr/` (ML pipeline), `app/` (API + web), `runtime/` (channels), `config/`, `database/`, `controllers/`
- Shared model instances across channels (YOLO clone pattern, OCR singleton)
- Proper connection pooling via `psycopg_pool`
- Non-blocking screenshot I/O via ThreadPoolExecutor
- Well-tested auth layer with 13 test files

**Main risks:**
1. **Dual `hash_password` implementations** — `database/user_repository.py:_hash_password` and `app/api/auth_utils.py:hash_password` are identical but independent. Divergence risk.
2. **Dual hotkey normalization** — `config/settings_normalizer.py:_normalize_hotkey` and `app/api/schemas.py:_normalize_hotkey` have slightly different behavior (one logs warnings, the other raises ValueError).
3. **SettingsManager still has 14 pass-through static methods** — Each just delegates to `settings_schema.*_defaults()`. The normalizer has the same 14. That's 28 pass-through wrappers.
4. **Controller normalization duplicated** — `SettingsManager.get_controllers()` and `SettingsNormalizer._fill_controller_defaults()` contain nearly identical controller normalization logic (id assignment, type validation, relay normalization).
5. **`auth_roadmap_eng.txt`** — Planning artifact committed to repo root. Not code, not docs, no longer actionable.
6. **Frontend channels.js is 1,298 lines** — largest JS file by far; handles grid rendering, preview lifecycle, overlay, ROI editor, plate size editor, and full channel CRUD.

### Highest-Priority Cleanup Opportunities

| Priority | Issue | Effort |
|----------|-------|--------|
| 1 | Consolidate dual `hash_password` to one source | Small |
| 2 | Consolidate dual `_normalize_hotkey` to one source | Small |
| 3 | Eliminate 28 pass-through `_*_defaults()` wrappers | Medium |
| 4 | Deduplicate controller normalization in SettingsManager vs SettingsNormalizer | Medium |
| 5 | Split channels.js into focused modules | Medium-Large |
| 6 | Remove `auth_roadmap_eng.txt` | Trivial |

---

## 2. Architecture Weaknesses

### 2.1 EventSink Is a Trivial Proxy

**Severity**: Medium | **Confidence**: High

`runtime/event_sink.py` (42 lines) wraps `PostgresEventDatabase.insert_event()` with zero added logic. Every parameter is passed through identically. It was likely a multi-backend abstraction (SQLite+Postgres) that lost its second backend.

**Evidence**: `EventSink.__init__` takes either a DSN or an existing `events_db`. Its `insert_event()` just calls `self._postgres.insert_event(...)` with the same kwargs.

**Impact**: Extra indirection, extra constructor wiring in `ChannelProcessor.__init__`.

**Fix**: Remove `EventSink`, use `PostgresEventDatabase` directly in `ChannelProcessor`. The `_sink` field can become `_events_db`.

---

### 2.2 Settings Layer Has 3 Redundant Pass-Through Tiers

**Severity**: Medium | **Confidence**: High

The defaults-access chain is:

```
settings_schema.py  → (14 functions) → SettingsNormalizer._*_defaults()  (14 wrappers)
                                      → SettingsManager._*_defaults()    (14 wrappers)
```

Both `SettingsManager` and `SettingsNormalizer` have identical `@staticmethod` wrappers that just call `settings_schema.*_defaults()`. Only `SettingsNormalizer` uses them internally. `SettingsManager` uses them in `get_channels()` and `get_controllers()`.

**Evidence**: 
- `config/settings_manager.py:48-103` — 14 static methods
- `config/settings_normalizer.py:37-47, 108-146` — 14 static methods
- Both are identical pass-throughs to `settings_schema.*`

**Fix**: Import directly from `settings_schema` where needed. Remove the wrapper methods from both classes.

---

### 2.3 Controller Normalization Duplicated Between SettingsManager and SettingsNormalizer

**Severity**: Medium | **Confidence**: High

`SettingsManager.get_controllers()` (lines 140-186) performs controller normalization (id assignment, type validation, relay normalization, hotkey extraction) that is almost identical to `SettingsNormalizer._fill_controller_defaults()` (lines 260-312).

**Evidence**: Both methods:
- Iterate controllers, assign missing IDs
- Call `_validate_controller_type()`
- Set default name, address, password
- Normalize relay list to exactly 2
- Call `_normalize_relay()` on each relay
- Check hotkey duplicates

**Fix**: `get_controllers()` should call `_fill_controller_defaults()` per controller (same pattern as `get_channels()` calls `_fill_channel_defaults()`), then only handle the "save-if-changed" logic.

---

### 2.4 Dual `hash_password` Functions

**Severity**: High | **Confidence**: High

Two independent `hash_password` implementations exist:
- `database/user_repository.py:19` — `_hash_password(plain)` (private, used only for superadmin seeding)
- `app/api/auth_utils.py:20` — `hash_password(plain)` (public, used by routers and tests)

Both are identical: `bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")`.

**Impact**: If one is changed (e.g., to argon2id), the other won't be, causing password format mismatch.

**Fix**: Remove `_hash_password` from `user_repository.py`. Import `hash_password` from `auth_utils` for the superadmin seed.

---

### 2.5 `SettingsRepository._file_lock` Is a Class-Level Attribute Shared Across Instances

**Severity**: Low | **Confidence**: High

`config/settings_repository.py:11` defines `_file_lock = threading.RLock()` as a class attribute. This means all instances of `SettingsRepository` share the same lock, which is correct for this project (single-instance per process) but fragile as an API contract. `SettingsManager` reaches into `self._repo._file_lock` directly (line 35).

**Evidence**: `settings_repository.py:11`, `settings_manager.py:35`

**Fix**: Make the lock an instance attribute, or expose it as a proper public property.

---

## 3. Directory Structure Issues

### 3.1 `auth_roadmap_eng.txt` in Project Root

**Severity**: Low | **Confidence**: High

This is a planning document from the auth implementation phase. It describes the auth architecture that has already been implemented. It is not documentation — it's a snapshot of the plan.

**Fix**: Remove. The auth architecture is visible in the code and tests.

---

### 3.2 `app/shared/` Contains Only 2 Files

**Severity**: Low | **Confidence**: Medium

`app/shared/` holds `backup_service.py` (218 lines) and `data_lifecycle.py` (167 lines). These are domain services, not "shared utilities". They could live in `app/api/services/` or similar to better signal their role.

**Impact**: Minor naming confusion. "shared" implies reuse across api/worker, which is true for `data_lifecycle.py` (used by both worker and api) but not for `backup_service.py` (api-only).

**Fix**: Consider renaming to `app/services/` or leaving as-is (low priority).

---

### 3.3 `docs/` Directory May Be Stale

**Severity**: Low | **Confidence**: Medium

The `docs/` directory contains 6 markdown files that may not reflect the current codebase state (auth was added after initial docs were written). Specifically:
- `docs/endpoints.md` — may not cover auth endpoints
- `docs/modules.md` — may not cover `database/user_repository.py`, `app/api/auth*`

**Fix**: Verify and update, or remove if README is sufficient.

---

## 4. Naming Issues

### 4.1 `_NOOP_RECOGNIZER` vs `_FallbackRecognizer`

**Severity**: Low | **Confidence**: High

`anpr/pipeline/factory.py:37` creates `_NOOP_RECOGNIZER = _FallbackRecognizer()`. The class is named "Fallback" (suggests temporary until real one loads) but the instance is named "NOOP" (suggests it intentionally does nothing). The semantics are "fallback" — it returns `[]` while the real OCR initializes in a background thread.

**Fix**: Rename to `_FALLBACK_RECOGNIZER` for consistency.

---

### 4.2 Mixed Russian/English in Log Messages and Comments

**Severity**: Low | **Confidence**: High

Log messages are predominantly Russian, but some are English (e.g., `controllers/service.py:167` "channel %s relay skip: channel not found"). This is intentional (user-facing logs in Russian, debug/internal in English), but some messages inconsistently mix languages within the same flow.

**Impact**: Minor readability issue for log analysis.

---

## 5. Unused Modules / Files / Code

### 5.1 Definitely Unused — Safe to Remove

| Item | Evidence | Risk |
|------|----------|------|
| `auth_roadmap_eng.txt` | Planning artifact, not imported/referenced anywhere | None |
| `SettingsManager._channel_defaults()` (line 48) | Only `SettingsNormalizer._channel_defaults()` is called; `SettingsManager`'s wrapper is unused | None |
| `SettingsManager._debug_defaults()` (line 52) | Same pattern — all `get_*` methods use `self._normalizer._fill_*_defaults()` instead | None |
| `SettingsManager._relay_defaults()` (line 56) | Only called from `get_controllers()` which duplicates normalizer logic | Low (fix duplication first) |
| `SettingsManager._model_defaults()` through `._logging_defaults()` (lines 72-103) | All 10 remaining static methods — unused, normalizer has identical copies | None |

### 5.2 Probably Unused — Needs Verification

| Item | Evidence | Action Needed |
|------|----------|---------------|
| `docs/` markdown files | May be stale, unclear if referenced externally | Check if linked from README or external docs |
| `AGENTS.md` in project root | GSD tooling artifact | Check if `.claude/` tooling reads it at runtime |

### 5.3 Legacy But Still Referenced

| Item | Evidence | Status |
|------|----------|--------|
| `APIKeyMiddleware` in `app/api/auth.py` | Legacy static API key middleware. Still present but middleware is not registered in `main.py` — JWT is the primary auth. The `API_KEY` env var path may be dead. | Verify if `API_KEY` env var is still used in deployment. If not, remove `auth.py` entirely. |
| ~~`EventSink` in `runtime/event_sink.py`~~ | ✅ Removed — `ChannelProcessor` uses `PostgresEventDatabase` directly | Done |
| ~~`_hash_password` in `database/user_repository.py`~~ | ✅ Consolidated — now imports from `auth_utils` | Done |

---

## 6. Consistency Issues

### 6.1 Hotkey Normalization Has Two Divergent Implementations

**Severity**: Medium | **Confidence**: High

`config/settings_normalizer.py:_normalize_hotkey()` — logs a warning and returns the raw value for invalid hotkeys.
`app/api/schemas.py:_normalize_hotkey()` — raises `ValueError` for invalid hotkeys.

Both perform the same CTRL+ALT+SHIFT ordering, but the error handling diverges. This means:
- API validation rejects bad hotkeys at the endpoint level
- Settings normalization silently accepts bad hotkeys during startup/migration

**Fix**: Extract to a shared utility function with a `strict: bool` parameter, or have the API schema call the normalizer version.

---

### 6.2 `get_controllers()` Duplicates `_fill_controller_defaults()`

**Severity**: Medium | **Confidence**: High

See section 2.3 above. The duplication means:
- Changes to controller normalization must be applied in two places
- One path (normalizer) is called during settings load; the other (manager) during `get_controllers()`
- They can silently diverge

---

### 6.3 `_RECONNECT_CACHE_TTL` Defined in Two Ways

**Severity**: Low | **Confidence**: High

`ChannelProcessor._RECONNECT_CACHE_TTL = 30.0` is a class attribute (line 111), but the cache logic references it directly. The `get_reconnect_config()` method uses `self._RECONNECT_CACHE_TTL` (implicitly). This is fine, but the `30.0` default is also baked into the `ReconnectConfig` dataclass semantics.

**Impact**: Negligible.

---

## 7. Recognition Pipeline Analysis

### 7.1 Full Processing Flow

```
Camera Source (RTSP/file)
  │
  ├─ cap.read() — OpenCV VideoCapture
  │
  ├─ Motion Detector (optional, mode="motion")
  │   └─ If no motion → skip frame (metrics.motion_skipped_frames++)
  │
  ├─ Adaptive Stride Check
  │   └─ If no active tracks → stride × 3 (saves YOLO calls during idle)
  │   └─ If stride not met → skip frame (metrics.detector_skipped_frames++)
  │
  ├─ YOLO Detection + Tracking
  │   └─ model.track(frame, persist=True) → bboxes + track_ids
  │   └─ Size filter → ROI polygon filter
  │
  ├─ ANPRPipeline.process_frame()
  │   ├─ For each detection:
  │   │   ├─ Skip finalized tracks (main CPU-saving path)
  │   │   ├─ Direction estimation (update center_y + area history)
  │   │   ├─ Plate preprocessor (perspective correction, skew correction)
  │   │   └─ Batch collect preprocessed plate images
  │   │
  │   ├─ CRNNRecognizer.recognize_batch() — single batch inference
  │   │
  │   ├─ TrackAggregator.add_result() per detection
  │   │   ├─ Consensus check (quorum + weighted majority)
  │   │   ├─ Budget exhaustion (max_ocr_attempts)
  │   │   └─ Consecutive failure early-exit
  │   │
  │   └─ PlatePostProcessor.process() — country format validation
  │
  ├─ Event Emission
  │   ├─ Screenshot I/O (async via ThreadPoolExecutor)
  │   ├─ PostgreSQL insert via EventSink
  │   ├─ EventBus publish (async, for SSE subscribers)
  │   └─ ControllerAutomation dispatch (list matching, relay command)
  │
  └─ Preview JPEG encode (if consumers exist, rate-limited)
```

### 7.2 Pipeline Efficiency Assessment

**Well-optimized areas:**
- Finalized track skip (no OCR, no direction computation) — `anpr_pipeline.py:424`
- Adaptive stride (3x multiplier when no active tracks) — `channel_runtime.py:546-552`
- Motion detector gate — skips YOLO entirely during no-motion periods
- Shared YOLO weights via `copy.copy()` clone pattern — `factory.py:99`
- Singleton OCR recognizer — `factory.py:40-79`
- Batch OCR inference — single `model(batch)` call per frame
- Non-blocking screenshot I/O — `channel_runtime.py:588`
- Preview rate limiting — `channel_runtime.py:634`

**Remaining inefficiencies:**

#### 7.2.1 Direction Computed for Non-Finalized Tracks Even When Result is Empty

**Severity**: Low | **Confidence**: High

`anpr_pipeline.py:438-441` — Direction estimation runs for every non-finalized detection, including those where OCR hasn't produced a result yet. The direction is only useful when a plate event is emitted. For tracks still accumulating OCR attempts, direction computation is wasted.

**Impact**: ~0.01ms per detection per frame (numpy operations on small arrays). Negligible for low detection counts, but adds up with many simultaneous tracks.

**Potential fix**: Defer direction computation to the emission point (when `result` or `unreadable` triggers an event). Store bbox in detection dict, compute direction only when needed.

#### 7.2.2 `_evict_stale` in TrackAggregator and TrackDirectionEstimator Run on Timer-Based Intervals

**Severity**: Low | **Confidence**: High

Both classes check `now - self._last_evict > self._EVICT_INTERVAL` every time their main methods are called. This is O(n) scan over all track dicts. With the 10-second interval, this is fine.

**Impact**: Negligible.

#### 7.2.3 `PlatePreprocessor` Recreates No Objects Per Call (Stateless)

**Severity**: None (positive observation) | **Confidence**: High

The preprocessor caches CLAHE and morphology kernel in `__init__`. Each `preprocess()` call only operates on the input image. This is correct.

#### 7.2.4 `reconnect_config` Re-read Every Frame Iteration

**Severity**: Low | **Confidence**: High

`channel_runtime.py:452` calls `self.get_reconnect_config()` at the top of every frame loop. The 30-second cache TTL means this is almost always a cache hit (just a monotonic time comparison). But the call is inside the hot loop.

**Impact**: ~0.001ms per frame. Negligible.

#### 7.2.5 Preview JPEG Encoding Allocates New Buffer Each Frame

**Severity**: Low | **Confidence**: Medium

`cv2.imencode('.jpg', frame, ...)` at line 635 allocates a new numpy buffer each time. The `.tobytes()` call at line 641 copies it again. For 5 FPS preview, this is ~5 allocations/second per channel with consumers.

**Impact**: Minor GC pressure. Not worth optimizing unless memory profiling shows it as a hotspot.

---

## 8. Cleanup Candidate Tables

### Safe to Remove Now

| Item | File | Lines | Evidence |
|------|------|-------|----------|
| `auth_roadmap_eng.txt` | project root | entire file | Planning artifact, auth is implemented |
| `SettingsManager._channel_defaults` | `config/settings_manager.py` | 48-50 | Never called; normalizer version is used |
| `SettingsManager._debug_defaults` | `config/settings_manager.py` | 52-54 | Never called |
| `SettingsManager._relay_defaults` | `config/settings_manager.py` | 56-58 | Only called from duplicated normalization code |
| `SettingsManager._reconnect_defaults` | `config/settings_manager.py` | 60-62 | Never called externally; normalizer version used |
| `SettingsManager._storage_defaults` | `config/settings_manager.py` | 64-66 | Same |
| `SettingsManager._plate_defaults` | `config/settings_manager.py` | 68-70 | Same |
| `SettingsManager._model_defaults` | `config/settings_manager.py` | 72-74 | Same |
| `SettingsManager._inference_defaults` | `config/settings_manager.py` | 76-78 | Same |
| `SettingsManager._plate_size_defaults` | `config/settings_manager.py` | 80-82 | Same |
| `SettingsManager._direction_defaults` | `config/settings_manager.py` | 84-86 | Same |
| `SettingsManager._ocr_defaults` | `config/settings_manager.py` | 88-90 | Same |
| `SettingsManager._detector_defaults` | `config/settings_manager.py` | 92-94 | Same |
| `SettingsManager._time_defaults` | `config/settings_manager.py` | 96-98 | Same |
| `SettingsManager._logging_defaults` | `config/settings_manager.py` | 100-102 | Same |

### Needs Verification Before Removal

| Item | File | Risk | What to Check |
|------|------|------|---------------|
| `APIKeyMiddleware` class | `app/api/auth.py` | Medium | Is `API_KEY` env var still used in Docker/deployment? If middleware is not registered in `main.py`, the whole file may be dead. |
| `docs/` directory (6 files) | `docs/*` | Low | Are these linked from README or external tools? |
| `AGENTS.md` | project root | Low | Is this read by `.claude/` tooling? |

### Should Be Refactored, Not Removed

| Item | File | What to Do |
|------|------|------------|
| ~~`EventSink`~~ | ~~`runtime/event_sink.py`~~ | ✅ Removed — inlined `PostgresEventDatabase` into `ChannelProcessor` |
| ~~`_hash_password`~~ | ~~`database/user_repository.py:19`~~ | ✅ Consolidated into `app.api.auth_utils.hash_password` |
| ~~`_normalize_hotkey` (duplicate)~~ | ~~`app/api/schemas.py` + `config/settings_normalizer.py`~~ | ✅ Consolidated into `config.settings_schema.normalize_hotkey` |
| Controller normalization (duplicate) | `config/settings_manager.py:140-186` | Delegate to normalizer's `_fill_controller_defaults()` |
| `channels.js` (1,298 lines) | `app/web/js/channels.js` | Split into grid, preview, roi-editor, plate-size-editor, channel-crud modules |
| 14 pass-through `_*_defaults()` methods | `config/settings_normalizer.py` | Import `settings_schema` directly where needed |

---

## 9. Independent Implementation Tasks

### Task 1: Consolidate Duplicate `hash_password` ✅ COMPLETED

**Problem**: Two identical `hash_password` functions exist — one in `database/user_repository.py` (private `_hash_password`) and one in `app/api/auth_utils.py` (public `hash_password`). If hashing strategy changes, one will be missed.

**What was done**:
- Removed `_hash_password` from `database/user_repository.py`
- Replaced `import bcrypt` with `from app.api.auth_utils import hash_password`
- Updated `_seed_default_superadmin()` to call `hash_password()`
- Updated `tests/test_user_repository.py` to import `hash_password` from `app.api.auth_utils`
- All 31 tests pass.

**Files changed**: `database/user_repository.py`, `tests/test_user_repository.py`

**Result**: Single source of truth for password hashing in `app/api/auth_utils.py`.

---

### Task 2: Consolidate Duplicate `_normalize_hotkey` ✅ COMPLETED

**Problem**: Two divergent hotkey normalization functions — `config/settings_normalizer.py:49` (warns on error, returns raw value) and `app/api/schemas.py:160` (raises ValueError).

**What was done**:
- Added shared `normalize_hotkey(value, *, strict=False)` to `config/settings_schema.py`
- `strict=True` raises `ValueError` (API validation behavior)
- `strict=False` logs warning and returns raw value (settings normalization behavior)
- Updated `config/settings_normalizer.py` — `_normalize_hotkey` now delegates to `normalize_hotkey(value, strict=False)`
- Updated `app/api/schemas.py` — `_normalize_hotkey` now delegates to `normalize_hotkey(value, strict=True)`
- All 10 hotkey/controller/settings tests pass.

**Files changed**: `config/settings_schema.py`, `config/settings_normalizer.py`, `app/api/schemas.py`

**Result**: Single normalization algorithm with two error-handling modes.

---

### Task 3: Remove `EventSink` Proxy Layer ✅ COMPLETED

**Problem**: `runtime/event_sink.py` is a 42-line class that wraps `PostgresEventDatabase.insert_event()` with zero added logic. It was a multi-backend abstraction that now has only one backend.

**What was done**:
- Replaced `EventSink` import with `PostgresEventDatabase` in `channel_runtime.py`
- Replaced `self._sink = EventSink(...)` with `self._events_db = events_db or PostgresEventDatabase(...)`
- Replaced `self._sink.insert_event(...)` with `self._events_db.insert_event(...)`
- Deleted `runtime/event_sink.py`
- `EventSink` was not exported from `runtime/__init__.py` — no changes needed there

**Files changed**: `runtime/channel_runtime.py`, `runtime/event_sink.py` (deleted)

**Result**: One less indirection layer. `ChannelProcessor` uses `PostgresEventDatabase` directly.

---

### Task 4: Remove 14 Pass-Through `_*_defaults()` from SettingsManager

**Problem**: `SettingsManager` has 14 `@staticmethod` methods (lines 48-103) that each call the identically-named function from `settings_schema`. The `SettingsNormalizer` also has 14 identical wrappers. The manager's wrappers are never called (the normalizer's versions are used instead).

**What to change**:
- Remove all 14 static methods from `SettingsManager` (lines 48-103)
- In `get_controllers()`, replace `self._relay_defaults()` with `relay_defaults()` (already imported at top of file from `settings_schema`)
- In `get_reconnect()`, `get_storage_settings()`, etc. — these already use `self._normalizer._fill_*()`, so no changes needed there

**Files affected**: `config/settings_manager.py`

**Expected result**: ~55 lines removed. Cleaner class with only real responsibilities.

**Risk**: Low — grep confirms these methods have no external callers.

---

### Task 5: Deduplicate Controller Normalization

**Problem**: `SettingsManager.get_controllers()` (lines 140-186) contains controller normalization logic that is nearly identical to `SettingsNormalizer._fill_controller_defaults()` (lines 260-312). Changes must be made in two places.

**What to change**:
- Refactor `get_controllers()` to loop over controllers and call `self._normalizer._fill_controller_defaults(data)` per controller (a new small method), similar to how `get_channels()` calls `self._normalizer._fill_channel_defaults()`
- Keep the "save if changed" wrapper logic in `get_controllers()`
- Remove the duplicated normalization code from `get_controllers()`

**Files affected**: `config/settings_manager.py`, `config/settings_normalizer.py` (may need a small public method)

**Expected result**: Single source of truth for controller normalization.

**Risk**: Low-Medium — need to verify test coverage for controller settings flow.

---

### Task 6: Remove `auth_roadmap_eng.txt`

**Problem**: Planning artifact from the auth implementation phase. Not code, not documentation, not actionable.

**What to change**: Delete the file.

**Files affected**: `auth_roadmap_eng.txt`

**Expected result**: Cleaner project root.

**Risk**: None.

---

### Task 7: Verify and Clean Up `APIKeyMiddleware`

**Problem**: `app/api/auth.py` contains `APIKeyMiddleware` — the legacy static API key authentication. It is NOT registered as middleware in `app/api/main.py` (JWT is the primary auth). The class may be entirely dead code.

**What to change**:
- Check if `API_KEY` environment variable is referenced in Docker, CI, or deployment configs
- If not used: delete `app/api/auth.py` entirely
- If used as a backwards-compatibility path: add a comment explaining the intentional retention, or register it conditionally

**Files affected**: `app/api/auth.py`, possibly `Dockerfile`, `docker-compose.yml`, `.env.example`

**Expected result**: Either clean removal of dead code, or documented intentional retention.

**Risk**: Medium — need to verify deployment configuration.

---

### Task 8: Split `channels.js` Into Focused Modules

**Problem**: `app/web/js/channels.js` is 1,298 lines — the largest frontend file by far. It handles 6+ distinct responsibilities: video grid rendering, preview/MJPEG lifecycle, overlay polling, ROI polygon editor, plate size editor, channel CRUD, and controller binding UI.

**What to change**:
- Extract ROI editor logic into `roi-editor.js`
- Extract plate size editor logic into `plate-size-editor.js`
- Extract video grid rendering into `video-grid.js`
- Keep channel CRUD and state management in `channels.js`

**Files affected**: `app/web/js/channels.js` (split), `app/web/js/app.js` (update imports)

**Expected result**: Each file under ~400 lines, focused on one responsibility.

**Risk**: Medium — many cross-references between functions. Need to carefully manage module exports.

---

### Task 9: Remove Pass-Through Wrappers from SettingsNormalizer

**Problem**: `SettingsNormalizer` has 14 `@staticmethod` wrappers (identical to SettingsManager's) that just call `settings_schema.*_defaults()`. These are used internally by `_fill_*_defaults()` methods, but the indirection adds no value.

**What to change**:
- In each `_fill_*_defaults()` method, call `settings_schema.*_defaults()` directly instead of `self._*_defaults()`
- Remove the 14 wrapper methods from `SettingsNormalizer`

**Files affected**: `config/settings_normalizer.py`

**Expected result**: ~50 lines removed. The class methods that actually do work (`_fill_*_defaults`, `normalize_with_meta`, etc.) become the only methods.

**Risk**: Low — purely internal refactor, no API change.

---

### Task 10: Verify and Update `docs/` Directory

**Problem**: The `docs/` directory contains 6 markdown files (`anpr-pipeline.md`, `diagrams.md`, `endpoints.md`, `modules.md`, `project-structure.md`, `technology-stack.md`) written before the auth system, user management, and backup features were added.

**What to change**:
- Review each doc against current codebase
- Update `endpoints.md` to include auth, users, backup/restore endpoints
- Update `modules.md` to include `database/user_repository.py`, `app/api/auth*`, `app/shared/backup_service.py`
- Update `project-structure.md` to reflect current directory layout
- If docs are not maintained, consider removing them and relying on code + README

**Files affected**: `docs/*.md`

**Expected result**: Documentation matches codebase, or is removed if not maintained.

**Risk**: Low.

---

### Task 11: Make `SettingsRepository._file_lock` an Instance Attribute

**Problem**: `SettingsRepository._file_lock` is a class-level `threading.RLock()`, meaning all instances share the same lock. `SettingsManager` accesses it directly via `self._repo._file_lock`.

**What to change**:
- Move `_file_lock` to `__init__` as `self._file_lock = threading.RLock()`
- Expose it via a property or keep as a public attribute
- Update `SettingsManager.__init__` to access `self._repo._file_lock` (already does, but semantics change)

**Files affected**: `config/settings_repository.py`, `config/settings_manager.py`

**Expected result**: Each repository instance has its own lock. Safer if multiple instances are ever created.

**Risk**: Low — currently only one instance exists.

---

### Task 12: Extract `DebugLogBus` from `runtime/debug.py`

**Problem**: `runtime/debug.py` is 398 lines and contains two unrelated subsystems:
1. `DebugRegistry` + `ChannelDebugState` (overlay state management) — ~280 lines
2. `DebugLogBus` + `DebugLogEntry` (live log pub/sub) — ~70 lines

These are imported separately: `DebugRegistry` by `ChannelProcessor` and `AppContainer`, `DebugLogBus` by `common/logging.py`.

**What to change**:
- Move `DebugLogBus` and `DebugLogEntry` to `runtime/debug_log_bus.py`
- Update imports in `common/logging.py`

**Files affected**: `runtime/debug.py`, new `runtime/debug_log_bus.py`, `common/logging.py`

**Expected result**: Each file has a single responsibility. ~70 lines extracted.

**Risk**: Low.

---

### Task 13: Add Index on `events.timestamp` for Retention Queries

**Problem**: `PostgresEventDatabase.delete_before(cutoff_iso)` runs `DELETE FROM events WHERE timestamp < %s`. Without an index on `timestamp`, this is a sequential scan on potentially millions of rows.

**What to change**:
- Add `CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);` to `database/postgres/schema.sql`
- This will be picked up by `_ensure_schema()` on next startup

**Files affected**: `database/postgres/schema.sql`

**Expected result**: Faster retention cleanup, faster journal queries with date filters.

**Risk**: Low — additive schema change, no data migration.

---

### Task 14: Remove Unused `hotkeys` Variable in Controller Normalization

**Problem**: In both `SettingsManager.get_controllers()` (line 183) and `SettingsNormalizer._fill_controller_defaults()` (line 305), there is a `hotkeys` variable that is computed but never used for duplicate detection in the manager version (only the normalizer version checks duplicates).

**Evidence**: `settings_manager.py:183` — `hotkeys = [relay.get("hotkey", "") for relay in normalized_relays if relay.get("hotkey")]` — computed but not used afterward.

**What to change**: Remove the dead `hotkeys` line from `get_controllers()`.

**Files affected**: `config/settings_manager.py`

**Expected result**: Dead code removed.

**Risk**: None.

---

### Task 15: Consider Connection Pool per Database Class (Not per Instance)

**Problem**: Each `PooledDatabase` subclass creates its own `ConnectionPool(min_size=2, max_size=10)`. With 3 database classes (`PostgresEventDatabase`, `ListDatabase`, `UserDatabase`) plus `DataLifecycleService`'s own `PostgresEventDatabase`, the app maintains 4+ connection pools to the same PostgreSQL instance.

**Evidence**: 
- `AppContainer.build()` creates `events_db`, `lists_db`, `user_db` — 3 pools
- `DataLifecycleService.__init__` creates another `PostgresEventDatabase` — 4th pool
- `EventSink` may share `events_db` or create its own (depends on wiring)

**What to change**:
- Share a single `ConnectionPool` across all database classes via a pool factory keyed by DSN
- Each `PooledDatabase` subclass receives the shared pool instead of creating its own

**Files affected**: `database/base.py`, `database/postgres_event_repository.py`, `database/lists_repository.py`, `database/user_repository.py`, `app/shared/data_lifecycle.py`

**Expected result**: 1 pool (min=2, max=10) instead of 4 pools (min=8, max=40 total connections).

**Risk**: Medium — need to ensure pool lifecycle management is correct when classes are recreated (e.g., `refresh_storage_clients()`).

---

*End of Review #5*
