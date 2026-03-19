# ANPR-System-v0.8_web — Independent Implementation Tasks

**Date:** 2026-03-18

Each task is self-contained, has a clear goal, and does not depend on the others.
Tasks are ordered by impact (highest first).

---

## TASK-01 — Fix memory leak: unbounded track dicts in recognition pipeline ✅ COMPLETED 2026-03-19

**Problem:**
`TrackAggregator.track_texts` and `last_emitted`, `TrackDirectionEstimator._history` — all keyed by `track_id` (int) — grow indefinitely. Track IDs are never removed. After days of operation the dicts hold thousands of stale entries, causing measurable RSS growth.

**What to change:**
1. In `TrackAggregator.__init__`: replace `self.track_texts: Dict[int, List[...]]` with `Dict[int, deque]` where each deque has `maxlen=best_shots`. Remove the manual `pop(0)` at line 39.
2. Add a `_track_last_seen: Dict[int, float]` tracking `time.monotonic()` per track, updated on each `add_result` call. In `add_result`, before returning, evict entries where `now - last_seen > STALE_TTL` (suggested: `max(30.0, best_shots * 2.0)` seconds).
3. In `TrackDirectionEstimator`: add `_track_last_seen: Dict[int, float]` updated in `update()`. Before returning result, evict `_history` entries older than `history_size * 2` seconds (or a configurable TTL).

**Files/modules affected:**
- `anpr/pipeline/anpr_pipeline.py` (`TrackAggregator`, `TrackDirectionEstimator`)

**Expected result:**
Memory usage of the recognition pipeline stabilizes after warmup. No unbounded dict growth during long-running operation.

**Risk level:** Low — behavior is unchanged for active tracks; only stale entries are removed.

---

## TASK-02 — Fix memory leak: unbounded cooldown dict in `ANPRPipeline` ✅ COMPLETED 2026-03-19

**Problem:**
`ANPRPipeline._last_seen: Dict[str, float]` accumulates one entry per unique plate string recognized. It is never pruned. Over months, thousands of unique plates accumulate.

**What to change:**
In `ANPRPipeline._on_cooldown()` or `_touch_plate()`: after updating `_last_seen[plate]`, scan the dict and remove entries where `now - ts > cooldown_seconds * 2`. To avoid O(n) scan on every plate, only scan if `len(_last_seen) > threshold` (e.g., 500) or on a time-based schedule (e.g., every 60 seconds using a `_last_pruned` timestamp).

**Files/modules affected:**
- `anpr/pipeline/anpr_pipeline.py` (`ANPRPipeline._on_cooldown`, `_touch_plate`)

**Expected result:**
`_last_seen` stays bounded at approximately `active_plates_count_in_recent_window` entries. Memory stabilizes.

**Risk level:** Low — only removes entries that are outside the cooldown window anyway (they would never trigger the cooldown branch).

---

## TASK-03 — Eliminate double ROI polygon computation per frame ✅ COMPLETED 2026-03-19

**Problem:**
`_get_roi_polygon` (parses channel dict, converts units, builds `np.ndarray`) is called twice per processed frame:
1. Inside `_apply_roi_mask` at `channel_runtime.py:275`
2. Inside `_filter_detections_by_roi` at `channel_runtime.py:326`

**What to change:**
1. Remove the `_apply_roi_mask` call at line 494. This eliminates the full-frame mask allocation and the first polygon computation.
2. In the `_run_channel` loop, compute the ROI polygon once before the detection call: `roi_polygon = self._get_roi_polygon(frame.shape, channel)`.
3. Pass `roi_polygon` directly to `_filter_detections_by_roi`, removing its internal `_get_roi_polygon` call.
4. Update `_filter_detections_by_roi` signature to accept an optional pre-computed `roi_polygon: Optional[np.ndarray]`.

**Files/modules affected:**
- `runtime/channel_runtime.py` (`_run_channel`, `_apply_roi_mask`, `_filter_detections_by_roi`)

**Expected result:**
One polygon computation per processed frame instead of two. No full-frame mask allocation. At 6 channels × 25 fps, saves ~150 polygon constructions/sec plus eliminates ~8 MB/frame allocation chain when ROI is enabled.

**Risk level:** Low — functional behavior is identical; ROI filtering still occurs via `_filter_detections_by_roi`.

---

## TASK-04 — Fix `PlatePreprocessor`: move reusable objects to `__init__` ✅ COMPLETED 2026-03-19

**Problem:**
`cv2.createCLAHE(...)` and `cv2.getStructuringElement(MORPH_RECT, (3,3))` are called on every `preprocess()` invocation. These objects are stateless and identical each time.

**What to change:**
In `PlatePreprocessor.__init__`, create:
```python
self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
self._kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
```
Replace the in-method creation calls with `self._clahe` and `self._kernel`.

**Files/modules affected:**
- `anpr/preprocessing/plate_preprocessor.py` (`PlatePreprocessor.__init__`, `preprocess`)

**Expected result:**
No C++ object allocation on each detection. Small but consistent CPU improvement in high-detection scenarios.

**Risk level:** Very low — CLAHE and the kernel are stateless.

---

## TASK-05 — Vectorize `CRNNRecognizer._decode_batch` (CTC greedy decoder) ✅ COMPLETED 2026-03-19

**Problem:**
The CTC greedy decoder uses a Python `for t in range(time_steps)` loop. Inside the loop, `torch.argmax` and `torch.exp(torch.max(...))` are called separately on each timestep tensor, causing ~time_steps device-to-host copies per batch item.

**What to change:**
Replace the per-timestep loop with vectorized operations:
```python
def _decode_batch(self, log_probs: torch.Tensor) -> List[Tuple[str, float]]:
    batch_probs = log_probs.permute(1, 0, 2)          # [batch, time, classes]
    char_indices = batch_probs.argmax(dim=-1)           # [batch, time]
    char_confs = batch_probs.exp().max(dim=-1).values   # [batch, time]
    # Move to numpy for CTC collapse (Python loop over batch only, not time)
    indices_np = char_indices.cpu().numpy()            # [batch, time]
    confs_np = char_confs.cpu().numpy()                # [batch, time]
    results = []
    for b in range(indices_np.shape[0]):
        chars, confidences = [], []
        prev = 0
        for t, idx in enumerate(indices_np[b]):
            if idx != 0 and idx != prev:
                chars.append(self.int_to_char.get(int(idx), ""))
                confidences.append(float(confs_np[b, t]))
            prev = idx
        text = "".join(chars)
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        results.append((text, avg_conf))
    return results
```
The key change: compute `argmax` and `exp(max)` in one vectorized pass, then do only one `.cpu().numpy()` call per batch (not per timestep), then loop over batch × time in numpy (much faster than calling `.item()` per step).

**Files/modules affected:**
- `anpr/recognition/crnn_recognizer.py` (`_decode_batch`)

**Expected result:**
Fewer Python-to-C boundary crossings. Reduced decode time especially for batch sizes > 1. Existing unit behavior is unchanged (same CTC greedy algorithm).

**Risk level:** Low — algorithm is identical, only execution path changes. Validate against existing tests.

---

## TASK-06 — Replace `list.pop(0)` with `deque` in `TrackAggregator` ✅ COMPLETED 2026-03-19 (implemented as part of TASK-01)

**Problem:**
`TrackAggregator.track_texts` stores per-track result lists. The list is capped with `list.pop(0)` which is O(n). This is part of the recognition hot path.

**What to change:**
Change `track_texts` value type from `List[tuple[str, float]]` to `deque[tuple[str, float]]` with `maxlen=self.best_shots`. Remove the manual length check and `pop(0)`. This is closely related to TASK-01 (do both together or either alone works).

**Files/modules affected:**
- `anpr/pipeline/anpr_pipeline.py` (`TrackAggregator.__init__`, `add_result`)

**Expected result:**
O(1) append + automatic eviction of oldest entry. No behavior change.

**Risk level:** Very low.

---

## TASK-07 — Move controller plate-list DB query off the channel thread ✅ COMPLETED 2026-03-19

**Problem:**
`ControllerAutomationService.dispatch_event` is called synchronously from the channel thread (via `publish_event_sync` at `container.py:131`). Inside `dispatch_event`, `plate_in_list_type(plate, "black")` and `plate_in_list_type(plate, "white")` execute PostgreSQL queries. These block the channel thread for 1–10 ms per event.

**What to change:**
In `AppContainer.publish_event_sync`, schedule `dispatch_event` asynchronously instead of calling it directly:
```python
def publish_event_sync(self, event: Dict[str, Any]) -> None:
    if self.main_loop and self.main_loop.is_running():
        self.main_loop.call_soon_threadsafe(asyncio.create_task, self.event_bus.publish(event))
        self.main_loop.call_soon_threadsafe(
            asyncio.create_task,
            asyncio.to_thread(self.controller_automation.dispatch_event, event)
        )
```
This moves the DB call to the thread pool without blocking the channel thread.

**Files/modules affected:**
- `app/api/container.py` (`publish_event_sync`)

**Expected result:**
Channel thread returns from `publish_event_sync` immediately after scheduling, without waiting for DB query. Frame processing continues without delay.

**Risk level:** Low — relay command is still triggered; just slightly delayed (by the event loop cycle). Order of plate events to relay commands is preserved.

---

## TASK-08 — Fix settings save to not restart channels on UI-only changes ✅ COMPLETED 2026-03-19

**Problem:**
`PUT /api/settings` always calls `restart_processor_for_settings()` which destroys and rebuilds the entire `ChannelProcessor` including reloading YOLO and CRNN models (~2–5 seconds). This interrupts all camera feeds when saving UI preferences like `grid` or `theme`.

**What to change:**
1. In `put_global_settings` (`routers/settings.py`), compare the incoming payload against current settings to determine which subsystems are affected.
2. Define what constitutes a "pipeline restart required" change: changes to `storage.postgres_dsn`, `plates`, any channel config, `reconnect`, detector/OCR settings.
3. Changes to `grid`, `theme`, `logging.level`, `time`, `debug` should NOT trigger `restart_processor_for_settings()`. They should apply in-place.
4. `storage.postgres_dsn` change should call `refresh_storage_clients()` only, not rebuild the processor.
5. `reconnect` changes should call `processor.update_reconnect_settings()` only.

**Files/modules affected:**
- `app/api/routers/settings.py` (`put_global_settings`)
- `app/api/container.py` (`restart_processor_for_settings`, `refresh_storage_clients`)

**Expected result:**
Saving UI preferences (grid, theme, log level) applies instantly without interrupting camera feeds. Full restart only occurs when actually necessary.

**Risk level:** Medium — must carefully identify which settings require restart. Test each settings category.

---

## TASK-09 — Remove dead code: `CRNNRecognizer.recognize` and `TrackAggregator.clear_last` ✅ COMPLETED 2026-03-19

**Problem:**
`CRNNRecognizer.recognize()` (line 78) and `TrackAggregator.clear_last()` (line 65) are never called anywhere in the codebase. They are dead code.

**What to change:**
1. Delete `CRNNRecognizer.recognize` method (`crnn_recognizer.py:78-82`).
2. Delete `TrackAggregator.clear_last` method (`anpr_pipeline.py:65-66`).
3. Run tests to confirm nothing breaks.

**Files/modules affected:**
- `anpr/recognition/crnn_recognizer.py`
- `anpr/pipeline/anpr_pipeline.py`

**Expected result:**
Slightly smaller codebase, no ambiguity about which method to call for single-image OCR.

**Risk level:** Very low — confirmed unused. Run `grep -r "clear_last\|\.recognize(" .` to double-check before deleting.

---

## TASK-10 — Add minimum crop size guard in `PlatePreprocessor.preprocess` ✅ COMPLETED 2026-03-19

**Problem:**
`PlatePreprocessor.preprocess` only guards against `plate_image.size == 0`. For very small crops (e.g., 30×8 pixels from a distant vehicle), it runs the full preprocessing pipeline (CLAHE, threshold, contour detection, Hough transform) producing meaningless output that wastes CPU.

**What to change:**
At the start of `preprocess()`, add:
```python
if plate_image.size == 0:
    return plate_image
h, w = plate_image.shape[:2]
if w < 20 or h < 8:
    return plate_image   # Too small for preprocessing; let CRNN resize handle it
```

**Files/modules affected:**
- `anpr/preprocessing/plate_preprocessor.py` (`preprocess`)

**Expected result:**
Tiny crops skip the expensive preprocessing steps. The CRNN's internal resize handles them. Slight CPU reduction for distant/small detections.

**Risk level:** Very low — the CRNN resize already handles any input size. Crops below this threshold produce poor OCR results regardless.

---

## TASK-11 — Align `detection_mode` defaults between schema and runtime ✅ COMPLETED 2026-03-19

**Problem:**
`ChannelConfigPayload.detection_mode` defaults to `"motion"` (schema default). `channel_runtime.py` line 366 falls back to `"always"` when the field is absent from the channel dict. A newly created channel (via `POST /api/channels`) has no `detection_mode` field stored, so the runtime uses `"always"` — but if saved via the config form, it stores `"motion"`. This is a hidden inconsistency.

**What to change:**
Option A (recommended): Change `ChannelConfigPayload.detection_mode` default from `"motion"` to `"always"` to match the runtime default.
Option B: Change the runtime fallback at `channel_runtime.py:366` from `"always"` to `"motion"`.

Pick one and apply consistently. Additionally, after `POST /api/channels` creates a channel, populate all config fields with their defaults (using `ChannelConfigPayload` defaults) so the stored dict is complete.

**Files/modules affected:**
- `app/api/schemas.py` (`ChannelConfigPayload.detection_mode`)
- `runtime/channel_runtime.py` (line 366, fallback value)

**Expected result:**
New channels always have consistent behavior regardless of whether their config was set explicitly or relies on defaults.

**Risk level:** Low — purely a default value alignment. Existing channels with an explicit `detection_mode` value are unaffected.

---

## TASK-12 — Skip JPEG preview encoding when no clients are watching ✅ COMPLETED 2026-03-19

**Problem:**
`cv2.imencode('.jpg', frame, ...)` runs on every frame for every channel, regardless of whether any browser is connected to the MJPEG stream. For 4 channels at 25 fps at 1080p, this consumes significant CPU (5–15 ms per encode).

**What to change:**
1. Add `active_preview_clients: int = 0` to `ChannelContext`.
2. In `channel_preview_stream` generator: increment `active_preview_clients` on connect, decrement in the `finally` block of the generator.
3. In `_run_channel` at line 575: check `if ctx.active_preview_clients > 0 or self._debug_registry.get_settings().disable_video_output == False` before encoding. Actually simplify: only encode if `active_preview_clients > 0`.
4. Update `get_preview_frame` to return `None` when `active_preview_clients == 0` (snapshot endpoint should still work on demand, so encode only for the snapshot case).

Note: `channel_snapshot` (single JPEG on demand) can encode on the fly when called, independently of the MJPEG stream.

**Files/modules affected:**
- `runtime/channel_runtime.py` (`ChannelContext`, `_run_channel`)
- `app/api/routers/channels.py` (`channel_preview_stream`)

**Expected result:**
Zero JPEG encoding CPU when no browser is viewing the preview. Full encoding resumes immediately when a client connects.

**Risk level:** Medium — requires coordination between API thread (client counter) and channel thread (encoding decision). Use atomic integer or lock-protected counter in `ChannelContext`.

---

## TASK-13 — Replace `DebugLogBus` polling with async subscriber queue ✅ COMPLETED 2026-03-19

**Problem:**
`stream_debug_logs` uses `asyncio.to_thread(debug_log_bus.wait_for_entries, cursor, 15.0)` which blocks a thread pool thread for up to 15 seconds per connected SSE client. With multiple debug panel clients, multiple threads are permanently blocked.

**What to change:**
Add an async subscriber mechanism to `DebugLogBus`, similar to `EventBus`:
1. Add `subscribe() -> asyncio.Queue` and `unsubscribe(queue)` methods.
2. In `publish()`, in addition to the ring buffer, push to all subscriber queues.
3. In `stream_debug_logs`, use `await queue.get()` with a timeout (like `EventBus` SSE stream).
4. Remove `wait_for_entries` (or keep for non-SSE snapshot use).

**Files/modules affected:**
- `runtime/debug.py` (`DebugLogBus`)
- `app/api/routers/debug.py` (`stream_debug_logs`)

**Expected result:**
No thread pool threads permanently blocked for debug log SSE. Better resource efficiency with multiple connected debug clients.

**Risk level:** Medium — changes the threading model of `DebugLogBus`. Ensure existing `snapshot()` and `wait_for_entries` callers (if any) still work.

---

## TASK-14 — Merge `dispatch_event` / `handle_event` in `ControllerAutomationService` ✅ COMPLETED 2026-03-19

**Problem:**
`dispatch_event` is a one-line wrapper over `handle_event` adding only exception logging. This indirection adds no semantic value and creates confusion about which method to call.

**What to change:**
Inline the body of `handle_event` into `dispatch_event`. Remove `handle_event` as a separate method. Ensure the try/except that was in `dispatch_event` wraps the entire former `handle_event` body.

**Files/modules affected:**
- `controllers/service.py` (`ControllerAutomationService`)

**Expected result:**
Single, clearly-named method `dispatch_event` with the complete logic inline.

**Risk level:** Very low — pure structural change, no behavior change.

---

## TASK-15 — Split `app/api/routers/settings.py` into `settings.py` and `data.py` ✅ COMPLETED 2026-03-19

**Problem:**
`settings.py` router contains routes for two distinct concerns: (1) global application settings (`/api/settings`) and (2) data lifecycle management (`/api/data/policy`, `/api/data/retention/run`, `/api/data/export/*`). The filename is misleading.

**What to change:**
1. Create `app/api/routers/data.py` containing:
   - `GET/PUT /api/data/policy`
   - `POST /api/data/retention/run`
   - `GET /api/data/export/events.csv`
   - `POST /api/data/export/bundle`
2. Keep `app/api/routers/settings.py` with only `GET/PUT /api/settings`.
3. Import and include `data_router` in `app/api/main.py`.

**Files/modules affected:**
- `app/api/routers/settings.py` (reduce)
- `app/api/routers/data.py` (create)
- `app/api/main.py` (add import)

**Expected result:**
Cleaner router organization. Easy to find data export/retention routes.

**Risk level:** Very low — URL paths do not change, only file organization.
