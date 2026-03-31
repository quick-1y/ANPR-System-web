# REVIEW #4 — Independent Implementation Tasks

**Date:** 2026-03-28

---

## Task 1: Share YOLO Model Across Channels ✅ COMPLETED (2026-03-29)

**Problem:** Each channel loads its own `YOLO(model_path)` instance, duplicating model weights in memory (50-200MB per channel).

**What to change:** Implement a singleton for the YOLO model (not the detector) similar to the existing `_get_shared_recognizer()` pattern. Each channel gets its own `YOLODetector` wrapper with independent tracker state but shares the underlying model.

**Files affected:** `anpr/pipeline/factory.py`, `anpr/detection/yolo_detector.py`

**Expected result:** N channels use 1 YOLO model in memory instead of N copies. RAM savings ~50-200MB per additional channel.

**Risk level:** Medium — YOLO's `track()` maintains internal state per-source. Need to verify that sharing the model object doesn't corrupt tracker state between channels. May require separate predictor instances.

**Resolution:** Added `_get_shared_yolo()` singleton in `factory.py` using double-checked locking + `copy.copy()`. The cached YOLO instance holds the heavy nn.Module weights; each channel gets a shallow clone with `predictor=None` so ultralytics lazily creates independent predictor/tracker state per channel. `YOLODetector.__init__` now accepts optional `yolo_model` parameter to skip redundant disk load. Also removed dead `import os` from TYPE_CHECKING block.

---

## Task 2: Fire-and-Forget Screenshot I/O ✅ COMPLETED (2026-03-29)

**Problem:** `channel_runtime.py:583-584` blocks the processing thread with `.result(timeout=5.0)` waiting for JPEG writes to complete.

**What to change:** Pre-compute deterministic file paths before submitting to the IO pool. Pass pre-computed paths to the event dict immediately. Let writes complete asynchronously with error-only callbacks.

**Files affected:** `runtime/channel_runtime.py`

**Expected result:** Channel processing loop no longer blocks on disk I/O. Reduces per-event latency by 5-10ms.

**Risk level:** Low — file paths are deterministic. Worst case: event references a path that failed to write, resulting in 404 on media endpoint (already handled).

**Resolution:** Replaced `.result(timeout=5.0)` blocking calls with pre-computed `str(path.resolve())` paths. JPEG writes are now fully fire-and-forget via `_io_pool.submit()`. `_save_jpeg` already logs errors internally. If plate_crop is None, the plate write is skipped and `plate_path` is set to None.

---

## Task 3: Move Direction Check After should_process Gate ✅ COMPLETED (2026-03-29)

**Problem:** `anpr_pipeline.py:419-423` computes direction for every detection, including finalized tracks that will be skipped at line 429. Direction computation involves numpy operations.

**What to change:** Move the `should_process()` check (lines 429-437) to before the direction update (lines 419-423). Only compute direction for tracks that will actually be processed.

**Files affected:** `anpr/pipeline/anpr_pipeline.py`

**Expected result:** Eliminates numpy direction computation for finalized tracks. Saves ~0.1ms per finalized detection per frame.

**Risk level:** Low — direction is only used in events, and finalized tracks don't produce new events.

**Resolution:** Moved `should_process()` gate before direction computation. Direction is still computed for the unreadable-emit case (which generates an event needing direction info). Plain finalized tracks (the common case) skip direction entirely.

---

## Task 4: Lazy ROI Copy ✅ COMPLETED (2026-03-29)

**Problem:** `anpr_pipeline.py:444` does `roi.copy()` for every detection, even though most detections don't produce events. The copy is only needed when saving screenshots.

**What to change:** Don't copy the ROI in the pipeline. Instead, store only the bbox in the detection dict. In `channel_runtime.py`, crop from the original frame only when an event is actually generated.

**Files affected:** `anpr/pipeline/anpr_pipeline.py`, `runtime/channel_runtime.py`

**Expected result:** Eliminates unnecessary numpy array copies for non-event detections. Saves memory allocation + memcpy per detection.

**Risk level:** Low — `_extract_plate_crop()` already has a fallback path that crops from frame using bbox (line 300-307).

**Resolution:** Removed `roi.copy()` assignment to `detection["plate_image"]` in `process_frame()`. `plate_image` stays None; `_extract_plate_crop()` in channel_runtime already falls back to bbox cropping from the current frame. No changes needed in channel_runtime.py.

---

## Task 5: Cache PostProcessor / Country Configs ✅ COMPLETED (2026-03-29)

**Problem:** `factory.py:76-82` creates a new `CountryConfigLoader` and reads/parses all YAML files from disk on every `build_components()` call (i.e., per channel start/restart).

**What to change:** Cache the `PlatePostProcessor` singleton (or the parsed `CountryConfig` list) at module level, similar to the recognizer singleton. Invalidate only when plate settings change.

**Files affected:** `anpr/pipeline/factory.py`, `anpr/postprocessing/country_config.py`

**Expected result:** YAML files read once at startup instead of per-channel. Eliminates repeated disk I/O and regex compilation.

**Risk level:** Low — country configs are static. Only need to invalidate when `enabled_countries` setting changes.

**Resolution:** Added `_POSTPROCESSOR_LOCK`/`_POSTPROCESSOR_CACHE` in `factory.py` with double-checked locking. Cache key is `(config_dir, sorted_enabled_countries)`. PlatePostProcessor is stateless after init, safe to share. Different `enabled_countries` settings get separate cached instances. No changes needed in `country_config.py`.

---

## Task 6: Remove SettingsManager Delegation Methods ✅ COMPLETED (2026-03-29)

**Problem:** `settings_manager.py:111-151` contains 14 methods that do nothing but call `self._normalizer._method()`. This creates confusion about where normalization logic lives.

**What to change:** Remove all `_fill_*` and `_normalize_*` forwarding methods. Update internal callers to use `self._normalizer` directly.

**Files affected:** `config/settings_manager.py`

**Expected result:** SettingsManager reduced by ~40 lines. Clearer ownership of normalization logic.

**Risk level:** Low — purely internal refactoring, no API changes.

**Resolution:** Removed all 14 delegation methods (`_normalize_hotkey`, `_normalize_relay`, 12 `_fill_*` methods). All internal callers were already using `self._normalizer._*` directly — the delegation methods had zero callers.

---

## Task 7: Remove Unused Exports ✅ COMPLETED (2026-03-29)

**Problem:** `RELAY_MODES`, `CONTROLLER_TYPES`, `normalize_region_config` wrapper, and `os` import in factory TYPE_CHECKING are dead code.

**What to change:**
- Remove `RELAY_MODES` from `controllers/service.py` and `controllers/__init__.py`
- Remove `CONTROLLER_TYPES` dict (keep `SUPPORTED_CONTROLLER_TYPES` as standalone tuple)
- Remove `normalize_region_config` function from `settings_manager.py:31-32`
- Remove `import os` from `anpr/pipeline/factory.py:14`
- Remove `favicon` endpoint from `app/worker/main.py:123-125`

**Files affected:** `controllers/service.py`, `controllers/__init__.py`, `config/settings_manager.py`, `anpr/pipeline/factory.py`, `app/worker/main.py`

**Expected result:** Dead code removed. Cleaner exports.

**Risk level:** Low — all items verified as unused by grep across project.

**Resolution:** Removed `RELAY_MODES`, `CONTROLLER_TYPES` (replaced with standalone `SUPPORTED_CONTROLLER_TYPES` tuple), `OrderedDict` import from `service.py`. Removed re-exports from `__init__.py`. Removed `normalize_region_config` wrapper + its `schema_normalize_region_config` import from `settings_manager.py`. Removed `favicon` endpoint from `worker/main.py`. The `import os` from factory TYPE_CHECKING was already removed in Task 1.

---

## Task 8: Migrate Worker to Lifespan Pattern ✅ COMPLETED (2026-03-29)

**Problem:** `app/worker/main.py:75,83` uses deprecated `@app.on_event("startup"/"shutdown")` while the main API uses the modern `lifespan` context manager.

**What to change:** Replace `on_event` decorators with an `@asynccontextmanager async def lifespan(app)` function, matching the pattern in `app/api/main.py:37-42`.

**Files affected:** `app/worker/main.py`

**Expected result:** Worker uses modern FastAPI lifecycle pattern. Consistent with main API. Eliminates deprecation warnings.

**Risk level:** Low — straightforward migration with established pattern in the same codebase.

**Resolution:** Replaced `@app.on_event("startup"/"shutdown")` with `@asynccontextmanager async def lifespan(app)` context manager, matching `app/api/main.py` pattern. Passed `lifespan=lifespan` to `FastAPI()` constructor.

---

## Task 9: Break Circular Dependency config -> controllers ✅ COMPLETED (2026-03-29)

**Problem:** `config/settings_normalizer.py:17` imports `SUPPORTED_CONTROLLER_TYPES` from `controllers`. This makes `config` depend on `controllers`, while `controllers` also depends on `config` through settings.

**What to change:** Move `SUPPORTED_CONTROLLER_TYPES` into `config/settings_schema.py` as a constant. Update `controllers/service.py` to import it from there. Update `app/api/schemas.py` to import from `config` instead of `controllers`.

**Files affected:** `config/settings_schema.py`, `config/settings_normalizer.py`, `controllers/service.py`, `app/api/schemas.py`

**Expected result:** Clean dependency direction: `controllers` -> `config`, not bidirectional.

**Risk level:** Low — moving a constant between modules.

**Resolution:** Moved `SUPPORTED_CONTROLLER_TYPES` to `config/settings_schema.py`. Updated imports in `settings_normalizer.py`, `controllers/service.py`, `controllers/__init__.py`, and `app/api/schemas.py`. Removed stale docstring note about the circular dependency from `settings_normalizer.py`.

---

## Task 10: Extract Shared Database Pool Base Class ✅ COMPLETED (2026-03-29)

**Problem:** `PostgresEventDatabase` and `ListDatabase` have identical lazy pool initialization patterns (`_get_pool`, `_connect`, `_ensure_schema`, `_init_lock`, `_initialized`, `_pool`).

**What to change:** Create a `database/base.py` with a `PooledDatabase` base class containing the shared pool logic. Both repositories inherit from it.

**Files affected:** `database/base.py` (new), `database/postgres_event_repository.py`, `database/plate_lists_repository.py`

**Expected result:** ~30 lines of duplicated code eliminated. Consistent pool configuration.

**Risk level:** Low — pure refactoring of internal plumbing.

**Resolution:** Created `database/base.py` with `PooledDatabase` ABC containing `__init__` (DSN validation, lock/pool init), `_get_pool()` (lazy ConnectionPool), `_connect()`, and `_ensure_schema()` (double-checked locking). Subclasses implement `_schema_sql()` — `PostgresEventDatabase` reads from SQL file, `ListDatabase` returns inline DDL. Removed `threading` import and ~30 lines of duplicated code from both repositories.

---

## Task 11: Pause Frontend Polling When Tab Hidden ✅ COMPLETED (2026-03-29)

**Problem:** `setInterval` timers for `refreshChannels` (8s), `refreshSystemResources` (10s), and `checkServerHealth` (10s) run unconditionally, making HTTP requests even when the browser tab is hidden.

**What to change:** Wrap polling callbacks with a `document.hidden` check. The `visibilitychange` listener already exists at line 670 — extend it to pause/resume all polling intervals.

**Files affected:** `app/web/app.js`

**Expected result:** No API requests made when the tab is in background. Reduces server load for users who leave the tab open.

**Risk level:** Low — existing visibilitychange handler proves the pattern is already in use.

**Resolution:** Added `if (document.hidden) return;` guard to `refreshChannels`, `refreshSystemResources`, `checkServerHealth`, and `refreshOverlayStates`. Extended the existing `visibilitychange` listener to call all three network-polling functions immediately when the tab becomes visible, so data refreshes without waiting for the next interval tick. `updateTopbarDateTime` (pure DOM, no network) left unchanged.

---

## Task 12: Replace "Нечитаемо" String Sentinel ✅ COMPLETED (2026-03-29)

**Problem:** The Russian string `"Нечитаемо"` is used as both a display value and a logic sentinel in `anpr_pipeline.py:432,482,541`. The `debug.py:231` also checks for it. Mixing display strings with business logic prevents i18n.

**What to change:** Always use `detection["unreadable"] = True` (already exists) as the only sentinel. Set `detection["text"] = ""` for unreadable detections. Move the `"Нечитаемо"` string assignment to the event emission layer in `channel_runtime.py` where the event dict is built.

**Files affected:** `anpr/pipeline/anpr_pipeline.py`, `runtime/debug.py`, `runtime/channel_runtime.py`

**Expected result:** Clean separation between detection logic (boolean flag) and display logic (localized string). Enables future i18n.

**Risk level:** Low-Medium — need to verify all consumers of `detection["text"]` handle the empty string + boolean flag correctly.

**Resolution:** Replaced all 4 `detection["text"] = "Нечитаемо"` assignments in `anpr_pipeline.py` with `detection["text"] = ""` (the `detection["unreadable"] = True` flag was already set alongside each). In `debug.py`, replaced the `text_raw.upper() != "НЕЧИТАЕМО"` string check with `not det.get("unreadable")` boolean flag check. In `channel_runtime.py`, added `is_unreadable` check at the event emission point — unreadable detections now get the display string `"Нечитаемо"` assigned only at the event layer. The string no longer appears in any business logic path.

---

## Task 13: Duplicate DSN Resolution Cleanup ✅ COMPLETED (2026-03-29)

**Problem:** `str(storage.get("postgres_dsn", "")).strip()` appears 3+ times in `container.py` and is passed separately to each database client.

**What to change:** Resolve DSN once in `AppContainer.build()`, store as `self._dsn`, pass to all consumers. Same in `refresh_storage_clients()`.

**Files affected:** `app/api/container.py`

**Expected result:** Single source of truth for DSN. Less repetitive code.

**Risk level:** Low — trivial refactoring.

**Resolution:** Extracted `_resolve_dsn()` helper method on `AppContainer`. In `build()`, DSN is resolved once into a local `dsn` variable and passed to both `PostgresEventDatabase` and `ListDatabase`. In `refresh_storage_clients()`, same pattern — single `dsn` local reused. `_build_lifecycle()` calls `_resolve_dsn()` directly. Eliminated 5 duplicate `str(storage.get("postgres_dsn", "")).strip()` expressions.

---

## Task 14: Consistent Error Handling in ListDatabase.update_entry ✅ COMPLETED (2026-03-29)

**Problem:** `plate_lists_repository.py:156` catches all exceptions and returns `False`, while every other method wraps exceptions in `StorageUnavailableError`. This hides real database errors.

**What to change:** Replace the bare `except Exception: return False` with the `StorageUnavailableError` pattern used by all other methods in both repositories.

**Files affected:** `database/plate_lists_repository.py`

**Expected result:** Database errors in `update_entry` are reported to the API layer like all other operations.

**Risk level:** Low — makes error handling consistent.

**Resolution:** Replaced `except Exception: return False` with `except Exception as exc: raise StorageUnavailableError(...)`. Added `StorageUnavailableError` import (was removed during Task 10 base class extraction). The router at `lists.py:99` already catches `StorageUnavailableError` for this endpoint, so DB errors now correctly surface as 503.

---

## Task 15: Split app.js Into ES Modules 🚧 IN PROGRESS (2026-03-30)

**Problem:** `app/web/app.js` is 3138 lines — the largest single file and the main maintenance bottleneck. All UI features are interleaved.

**What to change:** Split into ES modules with `<script type="module">`:
- `api.js` — fetch wrapper, auth (~80 lines)
- `state.js` — global state object (~10 lines)
- `channels.js` — channel CRUD, preview, ROI (~600 lines)
- `journal.js` — event journal, infinite scroll (~300 lines)
- `lists.js` — plate lists management (~200 lines)
- `settings.js` — global settings panel (~400 lines)
- `controllers.js` — controller CRUD (~200 lines)
- `debug.js` — debug panels, log stream (~200 lines)
- `ui.js` — tabs, sidebar, toast, modals, datetime (~300 lines)
- `app.js` — initialization, wiring (~100 lines)

**Files affected:** `app/web/app.js`, `app/web/index.html`

**Expected result:** Each feature is isolated in its own file. Easier to navigate, modify, and eventually test.

**Risk level:** Medium — large refactoring. Requires careful extraction of shared state and function references. Should be done incrementally.

**Progress update (2026-03-30, step 1 completed):**
- Created `app/web/js/` directory.
- Extracted API/auth layer from `app/web/app.js` into `app/web/js/api.js`:
  - `api(path)`
  - `getApiKey()`
  - `apiUrl(path)`
  - `showAuthOverlay(onSuccess)`
  - `jfetch(url, method, body)`
- Updated `app/web/app.js` to import and use these functions from `./js/api.js`.
- Switched `app/web/index.html` script tag to `<script type="module" src="/web/app.js"></script>`.
- Task 15 remains in progress; only the first extraction sub-step is done.

**Progress update (2026-03-30, step 2 completed):**
- Extracted application state container/defaults from `app/web/app.js` into `app/web/js/state.js`.
- `state.js` now owns the shared mutable `state` object initial values (`channels`, `lists`, `selectedListId`, `allEvents`, `lastPlatesByChannelId`, `plateLookup`, `currentEntries`).
- Updated `app/web/app.js` to import `state` from `./js/state.js` and continue using it without behavior changes.
- Task 15 remains in progress; API/auth extraction (step 1) and state extraction (step 2) are completed, remaining modules are pending.

**Progress update (2026-03-30, step 3 completed):**
- Extracted debug/logging frontend logic from `app/web/app.js` into `app/web/js/debug.js`.
- Moved debug panel behavior, debug log history loading, SSE live log stream, reconnect handling, and debug log rendering helpers to `debug.js`.
- Updated `app/web/app.js` to use `debug.js` APIs (`initDebugModule`, `applyDebugPanelVisibility`, `loadDebugLogHistory`, `setupDebugLogStream`, `cleanupDebugLogStream`) while preserving startup order.
- Task 15 remains in progress; steps 1-3 are completed, remaining module extractions are pending.

**Progress update (2026-03-30, step 4 completed):**
- Extracted journal/event history frontend logic from `app/web/app.js` into `app/web/js/journal.js`.
- Moved journal loading/filter/infinite-scroll logic, journal row rendering, event detail modal logic, and journal-specific bindings/handlers into `journal.js`.
- Updated `app/web/app.js` to use `journal.js` APIs (`initJournalModule`, `initJournalBindings`, `loadJournal`, `initJournalScroll`, `loadEventFeedHistory`, `fillChannelFilter`, `openEventDetails`, `formatDirection`, `normalizePlate`, `handleLiveEventForJournal`) while preserving current startup and interaction order.
- Task 15 remains in progress; steps 1-4 are completed, remaining module extractions are pending.

**Progress update (2026-03-31, step 5 completed):**
- Extracted plate lists frontend logic from `app/web/app.js` into `app/web/js/lists.js`.
- Moved lists loading/selection/rendering, entries loading/editing, create/rename/delete list flows, CSV import/export, and lists-specific modal/binding handlers to `lists.js`.
- Updated `app/web/app.js` to use `lists.js` APIs (`initListsModule`, `initListsBindings`, `loadLists`) while preserving initialization order and existing UX flows.
- Task 15 remains in progress; steps 1-5 are completed, remaining module extractions are pending.

**Progress update (2026-03-31, step 6 completed):**
- Extracted settings frontend logic from `app/web/app.js` into `app/web/js/settings.js`.
- Moved settings loading/population/saving flows and settings-specific country/debug controls handling to `settings.js`.
- Updated `app/web/app.js` to use `settings.js` APIs (`initSettingsModule`, `loadGlobalSettings`, `saveGeneral`) with dependency wiring to preserve behavior and initialization order.
- Task 15 remains in progress; steps 1-6 are completed, remaining module extractions are pending.

**Progress update (2026-03-31, step 7 completed):**
- Extracted controllers frontend logic from `app/web/app.js` into `app/web/js/controllers.js`.
- Moved controllers list/selection/rendering, CRUD flows, test relay actions, controller form handling, controller-specific modal/binding handlers, and controller hotkey map handling to `controllers.js`.
- Updated `app/web/app.js` to use `controllers.js` APIs (`initControllersModule`, `initControllersBindings`, `loadControllers`, `renderChannelControllerOptions`, `updateChannelControllerBindingState`, `triggerHotkey`, `hasHotkeyBinding`, `hasSelectedController`) while preserving current initialization and UX behavior.
- Task 15 remains in progress; steps 1-7 are completed, remaining module extractions are pending.

**Progress update (2026-03-31, step 8 completed):**
- Extracted shared UI infrastructure logic from `app/web/app.js` into `app/web/js/ui.js`.
- Moved shared tab switching/title update helpers, shared modal open/close helpers, and shared toast notification helper to `ui.js`.
- Updated `app/web/app.js` to use `ui.js` APIs (`initUI`, `switchTab`, `switchSettings`, `updateTopbarTitle`, `openModal`, `closeModal`, `showToast`) while preserving current behavior and initialization order.
- Task 15 remains in progress; steps 1-8 are completed, remaining module extractions are pending.

**Progress update (2026-03-31, step 9 completed):**
- Extracted shared contextual help/tooltip popover logic from `app/web/app.js` into `app/web/js/help.js`.
- Moved help content map, help popover open/close/positioning helpers, and shared help interaction handlers (click toggle, outside click close, ESC close) to `help.js`.
- Updated `app/web/app.js` to initialize `help.js` via `initHelpModule()` while preserving existing help UX and initialization order.
- Task 15 remains in progress; steps 1-9 are completed, remaining module extractions are pending.

**Progress update (2026-03-31, step 10 completed):**
- Extracted live events/event feed frontend logic from `app/web/app.js` into `app/web/js/events.js`.
- Moved live event feed rendering/incremental prepend logic, channel last-plate hydration/update helpers, event feed layout guards, and event stream lifecycle/reconnect logic to `events.js`.
- Updated `app/web/app.js` to initialize `events.js` via `initEventsModule()` and to use `events.js` APIs (`hydrateChannelLastPlates`, `loadInitialEventFeed`, `renderEventFeed`, `setupEventFeedLayoutGuards`, `setupEventStream`, `cleanupEventRuntime`, `updateChannelLastPlate`) while preserving behavior.
- Task 15 remains in progress; steps 1-10 are completed, remaining module extractions are pending.

**Progress update (2026-03-31, step 11 completed):**
- Extracted backup/restore system-data frontend logic from `app/web/app.js` into `app/web/js/backup.js`.
- Moved DB/settings export handlers, DB/settings restore file-pick/confirm/upload flows, backup busy-state handling, and restore success/error/reload behaviors to `backup.js`.
- Updated `app/web/app.js` to initialize `backup.js` via `initBackupModule()` with dependency wiring (`api`, `getApiKey`, `showAuthOverlay`, `showToast`, `openModal`, `closeModal`, `loadGlobalSettings`) while preserving behavior.
- Task 15 remains in progress; steps 1-11 are completed, remaining module extractions are pending.
