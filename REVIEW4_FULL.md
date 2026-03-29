# ANPR System v0.8 — Deep Architectural Review #4

**Date:** 2026-03-28
**Scope:** Full codebase review — architecture, naming, unused code, performance, pipeline analysis
**Codebase:** ~35 Python files, 1 monolithic JS file, PostgreSQL storage

---

## 1. Executive Summary

### Overall Assessment

The codebase is **well-structured for a mid-size project**. Compared to prior reviews (R1–R3), significant improvements have been made: database connection pooling is implemented (`psycopg_pool`), auth uses `secrets.compare_digest`, and reconnect config caching eliminates per-frame RLock acquisitions. The recognition pipeline has a proper budget system with early exits. The architecture follows a reasonable separation of concerns with clear module boundaries.

### Main Risks

1. **Monolithic frontend** — `app.js` at 3138 lines is the single largest maintenance risk. All UI logic, state management, API calls, and DOM manipulation live in one file with no module system.
2. ~~**`SettingsManager` delegation layer**~~ ✅ Fixed (2026-03-29) — 14 dead delegation methods removed.
3. ~~**New YOLODetector instance per channel**~~ ✅ Fixed (2026-03-29) — shared YOLO singleton with `copy.copy()` clones per channel.
4. ~~**Blocking I/O in the processing loop**~~ ✅ Fixed (2026-03-29) — screenshot writes are now fire-and-forget with pre-computed paths.
5. ~~**Worker uses deprecated `@app.on_event`**~~ ✅ Fixed (2026-03-29) — migrated to `lifespan` context manager.

### Highest-Priority Cleanup Opportunities

1. ~~Extract `SettingsManager` delegation methods~~ ✅ Done
2. Split `app.js` into modules (high effort, high maintainability gain)
3. ~~Share YOLODetector across channels~~ ✅ Done
4. ~~Make screenshot I/O fire-and-forget~~ ✅ Done

---

## 2. Architecture Weaknesses

### 2.1 SettingsManager Is a Pass-Through Proxy ✅ Fixed (2026-03-29)

**Severity:** Medium | **Confidence:** High

**Evidence:** `config/settings_manager.py` lines 111–151 contain 14 methods like `_fill_channel_defaults`, `_fill_reconnect_defaults`, etc. Each simply delegates to `self._normalizer._fill_*()`. The same pattern appears for `_normalize_hotkey`, `_normalize_relay`.

**Why it's a problem:** The class has two responsibilities: settings persistence (legitimate) and normalization delegation (unnecessary). This creates confusion about where normalization logic lives and doubles the API surface.

**Recommended fix:** Remove all `_fill_*` and `_normalize_*` forwarding methods from `SettingsManager`. Call `self._normalizer` directly where needed, or have getters internally call the normalizer without exposing its methods.

**Resolution:** All 14 delegation methods removed. All internal callers were already using `self._normalizer._*` directly — the methods had zero callers.

---

### 2.2 YOLODetector Created Per Channel — No Sharing ✅ Fixed (2026-03-29)

**Severity:** High | **Confidence:** High

**Evidence:** `anpr/pipeline/factory.py:108-117` — `build_components()` creates a new `YOLODetector` per call. `runtime/channel_runtime.py:382` calls `build_components()` in `_run_channel()`, which runs per channel.

The CRNN recognizer is shared via `_get_shared_recognizer()` singleton (factory.py:34-73), but the YOLO detector has no equivalent sharing.

**Why it's a problem:** Each `YOLO(model_path)` call loads the model weights into memory and potentially GPU. With 4 channels, this means 4 copies of the YOLO model. On GPU, this can exhaust VRAM. On CPU, it wastes RAM and prevents weight sharing between channels.

**Recommended fix:** Implement a singleton pattern for YOLODetector similar to the recognizer singleton. Since YOLO's `track()` maintains per-source state, create one YOLODetector per channel but share the underlying `YOLO` model instance across all detectors, passing it in rather than loading it each time.

**Resolution:** `_get_shared_yolo()` added in `factory.py` — caches YOLO per `(model_path, device)` key with double-checked locking. `copy.copy()` produces lightweight clones sharing nn.Module weights; `predictor=None` ensures each channel gets independent tracker state.

---

### 2.3 Blocking `.result()` After Thread Pool Submit ✅ Fixed (2026-03-29)

**Severity:** Medium | **Confidence:** High

**Evidence:** `runtime/channel_runtime.py:581-584`:
```python
frame_future = self._io_pool.submit(self._save_jpeg, frame_file, frame)
plate_future = self._io_pool.submit(self._save_jpeg, plate_file, plate_crop)
frame_path = frame_future.result(timeout=5.0)
plate_path = plate_future.result(timeout=5.0)
```

**Why it's a problem:** The channel thread blocks waiting for both JPEG writes to complete before proceeding. The thread pool submit offloads the work to a different thread (good for parallelism of frame + plate), but the calling thread still waits up to 10 seconds total. The event insertion and callback also depend on the paths, but the frame_path/plate_path could be pre-computed (they're deterministic) and the actual write could be fire-and-forget.

**Recommended fix:** Pre-compute the file paths (they don't depend on write success), insert the event with the expected paths, and let the I/O pool writes complete asynchronously. Add a callback that logs errors if writes fail.

**Resolution:** Replaced `.result(timeout=5.0)` calls with pre-computed `str(path.resolve())` paths. JPEG writes are now fully fire-and-forget. `_save_jpeg` already handles errors internally (logs + returns None). If a write fails, the event references a path that doesn't exist → 404 on media endpoint (already handled).

---

### 2.4 `config` Package Imports `controllers` Package

**Severity:** Medium | **Confidence:** High

**Evidence:** `config/settings_normalizer.py:17` — `from controllers import SUPPORTED_CONTROLLER_TYPES`. Similarly, `app/api/schemas.py:7` imports the same.

**Why it's a problem:** The `config` package should be a lower-level module that other packages depend on, not the other way around. This creates a circular dependency risk: `controllers` depends on `config` (for settings), and `config` depends on `controllers` (for type validation). Currently works because the import is deferred in some paths, but it's architecturally fragile.

**Recommended fix:** Move `SUPPORTED_CONTROLLER_TYPES` into `config/settings_schema.py` as a constant, or accept it as a parameter to the normalizer rather than importing it.

---

### 2.5 AppContainer Is a God Object

**Severity:** Low | **Confidence:** High

**Evidence:** `app/api/container.py` — `AppContainer` holds references to settings, events_db, lists_db, controller_service, controller_automation, event_bus, debug_registry, debug_log_bus, processor, lifecycle, main_loop, and stream_shutdown. It also contains business logic for validation (`validate_channel_controller_binding`, `validate_global_hotkeys`) and runtime orchestration (`restart_processor_for_settings`, `sync_channel_runtime`, `refresh_storage_clients`).

**Why it's a problem:** For a v0.8 project this is acceptable, but as the system grows this becomes a maintenance bottleneck. Every new feature must touch this class.

**Recommended fix:** No immediate action needed. When the next major feature is added, consider splitting AppContainer into focused service facades.

---

### 2.6 Worker Uses Deprecated Lifecycle Events

**Severity:** Low | **Confidence:** High

**Evidence:** `app/worker/main.py:75,83` — `@app.on_event("startup")` and `@app.on_event("shutdown")`.

**Why it's a problem:** FastAPI has deprecated `on_event` in favor of the `lifespan` context manager. The main API (`app/api/main.py:37`) already uses `lifespan` correctly, creating inconsistency.

**Recommended fix:** Migrate worker to use the `lifespan` pattern matching the main API.

---

## 3. Directory Structure and Naming

### 3.1 `runtime/` Package Naming

**Severity:** Low | **Confidence:** Medium

The `runtime/` package contains `channel_runtime.py`, `debug.py`, `event_bus.py`, and `event_sink.py`. The name "runtime" is generic. The package really contains "channel processing infrastructure" — the live video processing loop, debug state, and event distribution.

**Recommended:** No change needed currently, but if the package grows, consider renaming to `processing/` or `engine/`.

---

### 3.2 `app/shared/` Contains Only Two Files

**Severity:** Low | **Confidence:** High

**Evidence:** `app/shared/backup_service.py` and `app/shared/data_lifecycle.py`.

These are application-level services that could live directly in `app/` or in a more specific directory. The "shared" name suggests they're shared between API and worker, which is true for `data_lifecycle.py` but `backup_service.py` is only used in `app/api/routers/data.py`.

**Recommended:** No change needed. If more shared services appear, the package name is fine. If not, the files could be moved closer to their consumers.

---

### 3.3 `anpr/preprocessing/` Has Only One File

**Severity:** Low | **Confidence:** High

**Evidence:** `anpr/preprocessing/plate_preprocessor.py` is the only file in the package.

A single-file package adds an unnecessary directory level. However, it follows the convention of `anpr/detection/`, `anpr/recognition/`, etc., so it's consistent.

**Recommended:** Keep for consistency.

---

## 4. Naming Issues

### 4.1 Mixed Language in Logs and Variable Names

**Severity:** Low | **Confidence:** High

**Evidence:** Log messages are in Russian (e.g., "Канал %s: reconnect"), while code identifiers are in English. Channel labels are generated in Russian: `channel_runtime.py:384` — `"Канал {} (id={})"`. The `detection.get("text")` value `"Нечитаемо"` (unreadable) was a hardcoded Russian string used as a sentinel value in `anpr_pipeline.py:432,482,541`.

**Why it's a problem:** Using a Russian string as a business logic sentinel means the string cannot be changed for i18n without breaking logic. Any comparison with this value is fragile.

**Recommended fix:** Replace the `"Нечитаемо"` sentinel with the existing `detection["unreadable"] = True` boolean flag (which already exists). The string representation should only be assigned at the UI/event layer.

**Resolution (2026-03-29):** All 4 sentinel assignments in `anpr_pipeline.py` replaced with `detection["text"] = ""`. `debug.py` now checks the boolean flag instead of the string. Display string `"Нечитаемо"` is assigned only in `channel_runtime.py` at the event emission point.

---

### 4.2 `_build_event_media_paths` Returns a Tuple

**Severity:** Low | **Confidence:** High

**Evidence:** `channel_runtime.py:277` returns `tuple[Path, Path]` — `(frame_path, plate_path)`. The caller must remember the order.

**Recommended fix:** Return a named tuple or dataclass for clarity.

---

## 5. Unused and Legacy Code

### 5.1 Definitely Unused / Safe to Remove ✅ All removed (Tasks 1, 7)

| Item | Location | Status |
|------|----------|--------|
| ~~`RELAY_MODES` dict~~ | `controllers/service.py` | ✅ Removed (Task 7) |
| ~~`CONTROLLER_TYPES` dict~~ | `controllers/service.py` | ✅ Removed; standalone tuple kept (Task 7) |
| `_FallbackRecognizer._noop` usage path | `anpr/pipeline/factory.py:24-31` | Kept — safety fallback during init race |
| `build_command_url` as standalone function | `controllers/service.py` | Kept — in `__all__`, may be public API |
| ~~`normalize_region_config` wrapper~~ | `config/settings_manager.py` | ✅ Removed (Task 7) |
| ~~`os` import in TYPE_CHECKING~~ | `anpr/pipeline/factory.py` | ✅ Removed (Task 1) |
| ~~`favicon` endpoint~~ | `app/worker/main.py` | ✅ Removed (Task 7) |

### 5.2 Probably Unused / Needs Manual Verification

| Item | Location | Evidence |
|------|----------|----------|
| `SettingsManager._default()` | `settings_manager.py:50-51` | Only called by `SettingsRepository._load()` when the settings file doesn't exist. If settings.yaml always exists in production, this code path is never reached at runtime. |
| `SettingsManager.get_inference_settings()` | `settings_manager.py:417-422` | Returns inference settings but no code calls this method. Check if it's used by external tools or scripts. |
| `inference_defaults()` in schema | `settings_schema.py:92-94` | Only referenced by `build_default_settings()` and `_fill_inference_defaults`. The inference settings (`workers`, `shared_memory`) are not read by any runtime component. |

### 5.3 Legacy But Still Referenced

| Item | Location | Notes |
|------|----------|-------|
| `@app.on_event("startup"/"shutdown")` | `app/worker/main.py:75,83` | Deprecated FastAPI pattern, still functional. Should migrate to `lifespan`. |
| `SETTINGS_LINEAGE_KEY` / `SETTINGS_LINEAGE` | `config/settings_schema.py:10-11` | Used by `settings_migrations/runner.py` for upgrade detection. Functional but belongs to an older migration system. |
| ~~`SettingsManager` delegation methods (14 methods)~~ ✅ Removed | `settings_manager.py:111-151` | Dead code — all callers already used `self._normalizer` directly. |

---

## 6. Consistency Issues

### 6.1 Duplicate Pool Initialization Pattern ✅ Fixed (2026-03-29)

**Severity:** Low | **Confidence:** High

**Evidence:** Both `PostgresEventDatabase._get_pool()` (line 47) and `ListDatabase._get_pool()` (line 31) have identical lazy pool initialization logic with `_init_lock`, `_initialized`, and `_pool` fields. Both use `ConnectionPool(dsn, min_size=2, max_size=10, open=True)`.

**Recommended fix:** Extract a base class or shared pool factory to eliminate duplication.

**Resolution:** Created `database/base.py` with `PooledDatabase` ABC. Both repositories now inherit shared pool logic (`_get_pool`, `_connect`, `_ensure_schema`) and only implement `_schema_sql()` for their specific schema.

---

### 6.2 Duplicate DSN Resolution ✅ Fixed (2026-03-29)

**Severity:** Low | **Confidence:** High

**Evidence:** The PostgreSQL DSN is resolved from `os.getenv("POSTGRES_DSN", ...)` in `settings_manager.py:309`, then passed separately to `PostgresEventDatabase`, `ListDatabase`, and `DataLifecycleService`. The `container.py:46-47` calls `str(storage.get("postgres_dsn", "")).strip()` in 3 different places.

**Recommended fix:** Resolve DSN once in `AppContainer.build()` and pass it to all consumers.

**Resolution:** Extracted `_resolve_dsn()` method. `build()` and `refresh_storage_clients()` resolve DSN once into a local, `_build_lifecycle()` calls the helper. 5 duplicate expressions eliminated.

---

### 6.3 Inconsistent Error Handling in Database Methods ✅ Fixed (2026-03-29)

**Severity:** Low | **Confidence:** High

**Evidence:** `ListDatabase.update_entry()` catches all exceptions and returns `False` (line 156), while other methods like `add_entry()` let exceptions propagate to be caught by the router as `StorageUnavailableError`. `PostgresEventDatabase` wraps all exceptions into `StorageUnavailableError`.

**Recommended fix:** Make `ListDatabase.update_entry()` consistent with the rest — wrap exceptions in `StorageUnavailableError`.

**Resolution:** Replaced `except Exception: return False` with `raise StorageUnavailableError(...)`. Router already catches this at `lists.py:99`.

---

## 7. Performance and Memory Risks

### 7.1 PlatePreprocessor Performs Heavy CV Operations Per Frame Per Detection

**Severity:** Medium | **Confidence:** High

**Evidence:** `anpr/preprocessing/plate_preprocessor.py:149-187` — For each plate detection, `preprocess()` runs: CLAHE, GaussianBlur, adaptiveThreshold, morphologyEx (close + open), findContours, approxPolyDP, getPerspectiveTransform/warpPerspective **or** Canny + HoughLinesP + rotation. This is ~10 OpenCV operations per plate crop.

**Why it's a problem:** At 25 FPS with 2 detections per frame, that's 50 preprocess calls/second per channel. The quadrilateral detection + perspective transform is CPU-heavy. The small-plate early exit (line 156-159) helps for tiny crops but most real detections will go through the full path.

**CPU cost:** Estimated 2-5ms per call depending on plate crop size. With 2 channels and 2 detections: up to 20ms/frame spent in preprocessing alone.

**Recommended fix:**
- Skip preprocessing when the track is already finalized (the budget system already does this for OCR, but preprocessing still runs before the OCR check).
- Cache preprocessing results for the same track if the bbox hasn't changed significantly.
- The `_detect_plate_quadrilateral` iterates up to 10 contours with approxPolyDP — could be limited to 5.

---

### 7.2 PostProcessor Reloads Country Configs Per Pipeline Instance ✅ Fixed (2026-03-29)

**Severity:** Medium | **Confidence:** High

**Evidence:** `anpr/pipeline/factory.py:76-82` — `_build_postprocessor()` creates a new `CountryConfigLoader` and calls `loader.load()` which reads and parses all YAML files from disk. This is called per `build_components()` invocation, i.e., per channel start or restart.

**Why it's a problem:** Reading 4 YAML files from disk on every channel start is wasteful. If channels are restarted frequently (e.g., due to reconnections), this creates unnecessary I/O.

**Recommended fix:** Cache the loaded `PlatePostProcessor` or the parsed `CountryConfig` list, similar to how the OCR recognizer is shared via a singleton.

**Resolution:** `_build_postprocessor()` now caches by `(config_dir, enabled_countries)` with double-checked locking. YAML parsed once; different country sets get separate cached instances.

---

### 7.3 `_last_seen` Dict in ANPRPipeline Grows Unbounded

**Severity:** Low | **Confidence:** High

**Evidence:** `anpr/pipeline/anpr_pipeline.py:394-409` — `_last_seen` is a dict mapping plate strings to timestamps. Stale entries are cleaned up in `_on_cooldown()` using a threshold of `cooldown_seconds * 2`, but cleanup only runs when cooldown is enabled (`cooldown_seconds > 0`) and a specific plate is checked.

**Why it's a problem:** In a high-traffic scenario with many unique plates and cooldown enabled, the dict is cleaned up per-plate-check. This is adequate but the cleanup iterates all entries on every cooldown check (line 402-404), creating O(N) overhead per detection.

**Recommended fix:** Move cleanup to a time-based eviction like `TrackAggregator._evict_stale()` with an interval check.

---

### 7.4 DebugLogBus Subscriber List Iteration Under Lock

**Severity:** Low | **Confidence:** Medium

**Evidence:** `runtime/debug.py:380-387` — `DebugLogBus.publish()` iterates all subscribers under `self._lock`, calling `loop.call_soon_threadsafe()` for each. Dead subscribers are removed in-place.

**Why it's a problem:** If multiple SSE clients are connected, every log line acquires the lock and iterates all subscribers. With high log volume (DEBUG level), this creates lock contention between the logging thread and the debug log SSE endpoints.

**Recommended:** Acceptable for current scale. Monitor if log volume increases.

---

### 7.5 `app.js` — No Cleanup of Global Event Listeners

**Severity:** Low | **Confidence:** High

**Evidence:** `app/web/app.js:669` — `window.addEventListener("resize", scheduleVideoGridLayout)` is called once. Lines 2806-2808 add `beforeunload`, `pagehide`, and `resize` listeners. Lines 2822-2827 add mouseenter/mouseleave on the sidebar rail. None of these are ever removed.

**Why it's a problem:** For a single-page app that never navigates away, this is fine. The `cleanupStreamsAndTimers()` function handles stream cleanup on page unload. No real leak here.

**Recommended:** No action needed.

---

### 7.6 Multiple `setInterval` Timers Run Unconditionally ✅ Fixed (2026-03-29)

**Severity:** Low | **Confidence:** High

**Evidence:**
- `setInterval(updateTopbarDateTime, 1000)` — line 2777
- `setInterval(refreshSystemResources, 10000)` — line 2780
- `setInterval(checkServerHealth, 10000)` — line 2782
- `setInterval(refreshChannels, 8000)` — line 2860
- `setInterval(refreshOverlayStates, 700)` — line 394 (conditional on debug)

All run regardless of which tab is active.

**Why it's a problem:** 3 of these make HTTP requests every 8-10 seconds even when the user is on a different tab. The overlay refresh at 700ms is the most aggressive (was flagged in R3 — now it's conditionally started via `syncOverlayPolling`).

**Recommended fix:** Pause polling when `document.hidden === true` (the visibility change handler exists at line 670 but only controls video grid layout, not API polling).

**Resolution:** Added `if (document.hidden) return;` guard to all 4 network-polling callbacks. Extended `visibilitychange` listener to trigger immediate refresh on tab focus. `updateTopbarDateTime` (no network) unchanged.

---

## 8. CPU Optimization Opportunities

### 8.1 Share YOLO Model Weights Across Channels

**CPU/Memory impact:** High
**Evidence:** See section 2.2. Each channel loads a separate YOLO model instance.
**Saving:** ~50-200MB RAM per additional channel on CPU; significant GPU VRAM savings.
**How:** Load YOLO model once, create per-channel tracker state wrappers.

---

### 8.2 Skip Preprocessing for Budget-Exhausted Tracks ✅ Fixed (2026-03-29)

**CPU impact:** Medium
**Evidence:** The `should_process()` check in `anpr_pipeline.py:429` prevents OCR for finalized tracks, but the pipeline's process_frame loop at line 418 still iterates all detections and computes direction. For finalized tracks, the direction update (line 419-423) is unnecessary CPU work.

**Saving:** Eliminates direction computation (numpy operations) for finalized tracks — ~0.1ms per finalized detection per frame.
**How:** Move the `should_process()` check before the direction update.

**Resolution:** `should_process()` gate moved before direction computation. Direction is still computed for the rare unreadable-emit case (which produces an event). Plain finalized tracks skip direction entirely.

---

### 8.3 Reduce `roi.copy()` in Process Frame ✅ Fixed (2026-03-29)

**CPU impact:** Low-Medium
**Evidence:** `anpr_pipeline.py:444` — `detection["plate_image"] = roi.copy()` creates a copy of the plate ROI for every detection that passes through OCR. This copy is used later for saving screenshots.

**Saving:** Avoid copy if no event is generated (most frames). Only copy when an event will be emitted.
**How:** Defer the copy. Store the bbox coordinates instead and crop from the original frame only when an event is actually generated in the channel runtime.

**Resolution:** Removed `roi.copy()` from `process_frame()`. `plate_image` stays None; `_extract_plate_crop()` already crops from frame using bbox on demand.

---

### 8.4 Batch PlatePreprocessor Operations

**CPU impact:** Medium
**Evidence:** `plate_preprocessor.py` processes plates one at a time. Each call to `preprocess()` runs independent OpenCV operations.
**Saving:** Batching `cv2.cvtColor` and `cv2.resize` for multiple plates would leverage SIMD better and reduce function call overhead.
**How:** Requires pipeline restructuring. Lower priority.

---

### 8.5 Fire-and-Forget Screenshot Writes

**CPU impact:** Medium (latency, not raw CPU)
**Evidence:** See section 2.3. The channel thread blocks up to 10 seconds waiting for JPEG writes.
**Saving:** Removes up to 5-10ms of blocking per event from the processing loop.
**How:** Pre-compute paths, submit writes to pool, don't wait for results. Use a callback for error logging.

---

## 9. Recognition Pipeline — Runtime Flow Analysis

### 9.1 Step-by-Step Processing Flow

```
1. cap.read() → raw BGR frame
2. [Optional] MotionDetector.update(frame) → motion_active boolean
   - Downscales to 320px width
   - cvtColor → GaussianBlur → absdiff → threshold → countNonZero
3. [Stride gate] Skip frames based on detector_frame_stride × adaptive multiplier
4. YOLODetector.track(frame) → list of {bbox, confidence, track_id}
   - YOLO model inference (GPU or CPU)
   - Size filtering (min/max plate size)
   - Bbox padding expansion
5. ROI filtering → keep only detections with center inside polygon
6. ANPRPipeline.process_frame(frame, detections):
   a. For each detection:
      - TrackDirectionEstimator.update() → direction
      - TrackAggregator.should_process() → skip if finalized
      - Crop ROI from frame → roi.copy()
      - PlatePreprocessor.preprocess(roi) → corrected grayscale
   b. CRNNRecognizer.recognize_batch(plate_images) → [(text, confidence)]
   c. For each result:
      - TrackAggregator.add_result() → consensus/budget logic
      - PlatePostProcessor.process() → validation, country matching
      - Cooldown check
7. For each event-worthy detection:
   - Build media paths
   - Submit JPEG writes to IO pool (BLOCKING wait)
   - EventSink.insert_event() → PostgreSQL INSERT
   - event_callback → EventBus.publish() + ControllerAutomation
8. Preview JPEG encode (throttled by fps limit + consumer check)
9. FPS/latency metrics update
```

### 9.2 Redundant Operations

1. ~~**Direction computed for finalized tracks**~~ ✅ Fixed (2026-03-29) — `should_process()` gate now runs before direction computation.

2. ~~**`roi.copy()` for every detection**~~ ✅ Fixed (2026-03-29) — removed from pipeline; `_extract_plate_crop()` crops from frame via bbox on demand.

3. ~~**PlatePostProcessor created per channel**~~ ✅ Fixed (2026-03-29) — cached by `(config_dir, enabled_countries)` key.

### 9.3 Opportunities for Improvement

1. **Early exit before direction computation** — Move the `should_process()` check to before the direction update.
2. **Lazy ROI copy** — Store bbox only; crop from the original frame in the channel runtime event path when an event is actually produced.
3. ~~**Shared postprocessor**~~ ✅ Done — cached by config key.
4. **Adaptive OCR batching** — Currently, `recognize_batch` receives all plates from one frame. With multiple detections, this is already batched. No change needed.

---

## 10. Frontend Specific Issues

### 10.1 Monolithic `app.js` (3138 lines)

**Severity:** High | **Confidence:** High

**Evidence:** A single file contains all application logic: state management, API calls, DOM rendering, event handling, tab switching, forms, modals, video grid, journal, lists management, settings, ROI editor, backup/restore, controller management, debug panels, and help popovers.

**Why it's a problem:** Any change to any feature requires navigating a 3000+ line file. No encapsulation between features means changes can have unintended side effects. No testing is possible.

**Recommended fix:** Split into ES modules:
- `state.js` — global state management
- `api.js` — HTTP client, auth
- `channels.js` — channel list, preview, ROI
- `journal.js` — event journal
- `lists.js` — plate lists management
- `settings.js` — global settings
- `controllers.js` — controller management
- `debug.js` — debug panels
- `ui.js` — shared UI utilities (toast, modals, tabs)

---

### 10.2 Hard-Coded Polling Intervals ✅ Partially fixed (2026-03-29)

**Severity:** Low | **Confidence:** High

**Evidence:**
- Channel refresh: 8000ms (line 2860)
- System resources: 10000ms (line 2780)
- Health check: 10000ms (line 2782)
- Overlay refresh: 700ms (line 394)
- DateTime update: 1000ms (line 2777)

**Recommended:** Add visibility-based throttling. When `document.hidden`, increase intervals or pause entirely.

**Resolution:** Visibility-based pausing added — all network-polling callbacks now skip when tab is hidden. Intervals themselves remain hard-coded (acceptable for current scale).

---

## 11. Cleanup Candidates

### Safe to Remove Now ✅ All removed (Tasks 1, 7)

| Item | File | Status |
|------|------|--------|
| ~~`RELAY_MODES` dict~~ | `controllers/service.py` | ✅ Removed |
| ~~`CONTROLLER_TYPES` dict~~ | `controllers/service.py` | ✅ Removed |
| ~~`normalize_region_config` wrapper~~ | `config/settings_manager.py` | ✅ Removed |
| ~~`os` import in TYPE_CHECKING~~ | `anpr/pipeline/factory.py` | ✅ Removed |
| ~~`favicon` endpoint~~ | `app/worker/main.py` | ✅ Removed |

### Needs Verification Before Removal

| Item | File | Reason for caution |
|------|------|--------------------|
| `SettingsManager.get_inference_settings()` | `settings_manager.py:417` | No internal callers found. May be used by external scripts/tools. |
| `inference_defaults()` | `settings_schema.py:92` | Referenced in `build_default_settings()`. Removing would change settings file structure. |
| `build_command_url` standalone function | `controllers/service.py:26` | Exported in `__all__`. May be used by external code. |
| `_FallbackRecognizer` / `_NOOP_RECOGNIZER` | `anpr/pipeline/factory.py:24-31` | Safety fallback. May be needed during race conditions at startup. |

### Should Be Refactored, Not Removed

| Item | File | What to do |
|------|------|------------|
| `SettingsManager` delegation methods (14) | `settings_manager.py:111-151` | Remove forwarding, call normalizer directly |
| Worker lifecycle events | `app/worker/main.py:75,83` | Migrate to `lifespan` pattern |
| `config` → `controllers` import | `settings_normalizer.py:17` | Move constant to config package |
| ~~Duplicate pool init pattern~~ ✅ Done | `postgres_event_repository.py` + `plate_lists_repository.py` | Extracted `PooledDatabase` base in `database/base.py` |
| ~~`"Нечитаемо"` string sentinel~~ ✅ Done | `anpr_pipeline.py:432,482,541` | Boolean flag only; display string at event layer |

---

## 12. Independent Implementation Tasks

See `REVIEW4_TASKS.md` for the complete task list.
