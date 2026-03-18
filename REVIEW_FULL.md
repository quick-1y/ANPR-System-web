# ANPR-System-v0.8_web — Full Architectural & Maintenance Review

**Date:** 2026-03-18
**Scope:** Complete codebase review — architecture, naming, unused/legacy code, memory leaks, CPU performance, recognition pipeline.

---

## 1. Executive Summary

### Overall Architecture Quality

The project is well-structured for its purpose. Separation of concerns is clear: ANPR pipeline, channel runtime, API layer, database, and configuration are all isolated modules with defined interfaces. The main architectural pattern (one blocking thread per channel, async SSE for events, single YAML config, PostgreSQL-only persistence) is sound and appropriate for a local deployment.

The codebase is free of legacy cruft, dead imports, or commented-out code blocks. Naming is mostly good. The pipeline design (YOLO → preprocessor → CRNN batch OCR → aggregator → validator → cooldown → event) is sensible.

**However**, there are three confirmed memory leaks in the recognition pipeline that will cause the process to grow indefinitely under continuous operation. There are also several CPU inefficiencies in the per-frame hot path that compound across channels and frame rates.

### Main Risks

| Risk | Location | Impact |
|------|----------|--------|
| Memory leak — unbounded track dicts | `anpr_pipeline.py` | Process grows indefinitely |
| Memory leak — unbounded direction history | `anpr_pipeline.py:149` | Process grows indefinitely |
| Memory leak — unbounded cooldown dict | `anpr_pipeline.py:193` | Slow growth over days |
| ROI polygon computed twice per frame | `channel_runtime.py:275, 326` | Wasted CPU on every frame |
| Full-frame mask array created every frame | `channel_runtime.py:274-281` | Unnecessary allocation + bitwise AND |
| O(n) `pop(0)` in aggregation hot path | `anpr_pipeline.py:39` | Degrades with `best_shots > 3` |
| CRNN decode: Python loop per timestep | `crnn_recognizer.py:95-104` | Prevents vectorization benefit |
| DB query blocks channel thread on every event | `container.py:131`, `service.py:150` | Stalls frame processing |
| Lock contention on every frame | `channel_runtime.py:417, 579` | Serializes threads |

### Highest-Priority Cleanup

1. Fix three unbounded dicts in `ANPRPipeline` — confirmed memory leaks.
2. Eliminate double ROI polygon computation and redundant full-frame masking.
3. Replace `list.pop(0)` with `deque(maxlen=N)` in `TrackAggregator`.
4. Vectorize `_decode_batch` in `CRNNRecognizer`.
5. Move controller list-check DB call off the channel thread.

---

## 2. Full Report

---

### 2.1 Architecture Weaknesses

---

#### AW-1 — Unbounded dicts in `ANPRPipeline` and `TrackAggregator`

**Severity:** Critical
**Confidence:** High
**Evidence:**

```python
# anpr_pipeline.py:30-31
self.track_texts: Dict[int, List[tuple[str, float]]] = {}
self.last_emitted: Dict[int, str] = {}

# anpr_pipeline.py:149
history = self._history.setdefault(track_id, deque(maxlen=self.history_size))

# anpr_pipeline.py:193
self._last_seen: Dict[str, float] = {}
```

`TrackAggregator.track_texts` and `last_emitted` are keyed by `track_id` (integer assigned by YOLO ByteTrack). Track IDs are never removed from these dicts. Every new vehicle that passes the camera adds a permanent entry. After days of operation, this dict contains thousands of stale track IDs.

`TrackDirectionEstimator._history` is keyed by `track_id`. Same problem — every new track adds a `deque` and it is never evicted.

`ANPRPipeline._last_seen` is keyed by plate string. Every unique plate ever recognized adds an entry. The cooldown logic reads it but never cleans it. Over months this accumulates thousands of entries.

`TrackAggregator.reset(track_id)` and `clear_last(track_id)` exist but are not called on track disappearance. `reset` is called only when plate validation fails (`anpr_pipeline.py:260`). `clear_last` is never called anywhere in the codebase.

**Why it is a problem:**
In a production environment processing hundreds of vehicles per day, these dicts grow continuously. After 30 days, `_last_seen` may have 10,000+ entries; `track_texts` and `_history` may have millions of entries if YOLO re-issues IDs after reconnects (ByteTrack starts ID counter from 1 after model reload). The process RSS will increase measurably over time.

**Recommended fix:**
- Replace `track_texts` dict value `List[...]` with `deque(maxlen=best_shots)` to cap per-track storage.
- Add TTL-based or LRU eviction for `track_texts`, `last_emitted`, and `_history` using `time.monotonic()` timestamps, or evict tracks not seen within `N * frame_time` seconds.
- For `_last_seen`: prune entries older than `cooldown_seconds * 2` on every call to `_on_cooldown`.

---

#### AW-2 — Double ROI polygon computation per frame

**Severity:** High
**Confidence:** High
**Evidence:**

```python
# channel_runtime.py:494
detector_frame = self._apply_roi_mask(frame, channel)

# channel_runtime.py:275-281 (_apply_roi_mask)
def _apply_roi_mask(self, frame, channel):
    roi_polygon = self._get_roi_polygon(frame.shape, channel)  # ← parse + compute #1
    ...

# channel_runtime.py:518
detections = self._filter_detections_by_roi(detections, frame.shape, channel)

# channel_runtime.py:326 (_filter_detections_by_roi)
def _filter_detections_by_roi(self, detections, frame_shape, channel):
    roi_polygon = self._get_roi_polygon(frame_shape, channel)  # ← parse + compute #2
    ...
```

`_get_roi_polygon` parses the `channel` dict, reads `roi_enabled`, `region`, `points`, converts units from percent to pixels, and constructs an `np.array`. This is called twice per frame when detection runs.

**Why it is a problem:**
Redundant computation on every processed frame. On a 6-channel system at 25 fps with `detector_frame_stride=1`, this is ~150 extra polygon constructions per second.

**Recommended fix:**
Compute `roi_polygon` once, pass it to both `_apply_roi_mask` and `_filter_detections_by_roi`. Or, cache the polygon per channel and invalidate on channel config change.

---

#### AW-3 — Full-frame mask array created for ROI on every frame

**Severity:** High
**Confidence:** High
**Evidence:**

```python
# channel_runtime.py:279-281
mask = np.zeros(frame.shape[:2], dtype=np.uint8)
cv2.fillPoly(mask, [roi_polygon], 255)
return cv2.bitwise_and(frame, frame, mask=mask)
```

When ROI is enabled, this allocates a full-resolution grayscale array, fills a polygon, and performs a bitwise AND on the full BGR frame. For a 1080p frame (1920×1080×3 bytes = 6.2 MB), this allocates 2 MB for the mask and processes 6.2 MB per frame.

This masking approach was intended to restrict the YOLO input to the ROI region. However, `_filter_detections_by_roi` already filters detections by center point inside the polygon. The frame masking is therefore redundant if the only purpose is restricting which detections are processed.

**Why it is a problem:**
On a 4-channel system at 25 fps: 4 × 25 × (2 MB mask alloc + 6 MB bitwise AND) = 800 MB/s of unnecessary memory bandwidth.

**Recommended fix:**
Remove `_apply_roi_mask` from the hot path. Rely entirely on `_filter_detections_by_roi` for ROI filtering. The masking approach only helps if YOLO itself benefits from a blacked-out frame (minor NMS benefit); if that's the goal, document it explicitly.

---

#### AW-4 — Controller list-check (DB query) blocks channel thread on every event

**Severity:** High
**Confidence:** High
**Evidence:**

```python
# container.py:128-131
def publish_event_sync(self, event) -> None:
    if self.main_loop and self.main_loop.is_running():
        self.main_loop.call_soon_threadsafe(asyncio.create_task, self.event_bus.publish(event))
    self.controller_automation.dispatch_event(event)  # ← synchronous DB call

# service.py:150
def _resolve_channel_controller_action(self, channel, plate):
    if self._plate_in_list_type(plate, "black"):   # ← psycopg query
        return False, "blacklisted"
    ...
    if self._plate_in_list_type(plate, "white"):   # ← psycopg query
```

`dispatch_event` is called synchronously from `publish_event_sync`, which is the `event_callback` in `ChannelProcessor`. It is called from within `_run_channel` (the channel thread) at `channel_runtime.py:565`. The `plate_in_list_type` function is a direct PostgreSQL query executed on the channel thread.

**Why it is a problem:**
Plate list DB queries have latency (typically 1–10 ms). This stalls the channel thread from reading the next frame. Under load (PostgreSQL busy) or if the DB is remote, this can cause frame drops and increased latency.

**Recommended fix:**
Move `dispatch_event` to a background thread or async task. The simplest fix: call `dispatch_event` via `loop.call_soon_threadsafe` just like the event bus publish, so it runs in the async event loop on a thread pool.

---

#### AW-5 — `reconnect_config` fetched under lock on every frame iteration

**Severity:** Medium
**Confidence:** High
**Evidence:**

```python
# channel_runtime.py:417
while not stop_event.is_set():
    reconnect_config = self.get_reconnect_config()  # acquires RLock on every frame
```

```python
# channel_runtime.py:102-104
def get_reconnect_config(self) -> ReconnectConfig:
    with self._lock:
        return self._reconnect_config
```

Reconnect settings change only when the user explicitly saves them. But the config is re-fetched under a lock on every single frame iteration, at potentially 25–30 fps per channel.

**Why it is a problem:**
Unnecessary lock acquisition on every frame. On a 4-channel system at 25 fps: 100 lock operations/second. While cheap individually, this also means the API thread contends with all channel threads on `_lock` for every single config read/write.

**Recommended fix:**
Use a local variable for `reconnect_config` and only re-read it when `stop_event` fires or after a `reconnect` operation. Alternatively, use `threading.local` or an atomic reference.

---

#### AW-6 — `_run_channel` acquires `_lock` for every JPEG write

**Severity:** Medium
**Confidence:** High
**Evidence:**

```python
# channel_runtime.py:579-583
with self._lock:
    channel_ctx = self._contexts.get(channel_id)
    if channel_ctx:
        channel_ctx.latest_jpeg = preview_buf.tobytes()
        channel_ctx.latest_frame_ts = now_ts
```

The same `_lock` (RLock) is used for three purposes: context management, reconnect config reads, and JPEG writes. All channel threads plus any API thread reading a preview contend on this single lock.

**Recommended fix:**
Use `threading.Lock` (not RLock) per channel context for the JPEG buffer, separate from the global context dict lock. Or use a separate dedicated per-channel `threading.Event` + atomic replace with `bytes` object. A simple `threading.Lock` per `ChannelContext` for `latest_jpeg` updates would eliminate cross-channel contention.

---

#### AW-7 — `dispatch_event` vs `handle_event` — unnecessary indirection

**Severity:** Low
**Confidence:** High
**Evidence:**

```python
# service.py:216-220
def dispatch_event(self, event):
    try:
        self.handle_event(event)
    except Exception as exc:
        logger.error("controller binding processing failed: %s", exc)
```

`dispatch_event` is a thin wrapper that adds only exception logging. This two-method split adds indirection without semantic value. Both methods do exactly one thing.

**Recommended fix:**
Merge into a single `dispatch_event` method with the try/except inline.

---

### 2.2 Directory Structure Issues

---

#### DS-1 — `app/api/routers/settings.py` mixes settings and data lifecycle routes

**Severity:** Medium
**Confidence:** High
**Evidence:**

`app/api/routers/settings.py` contains:
- `GET /api/settings`, `PUT /api/settings` — global settings
- `GET /api/data/policy`, `PUT /api/data/policy` — retention policy
- `POST /api/data/retention/run` — manual retention trigger
- `GET /api/data/export/events.csv` — event export
- `POST /api/data/export/bundle` — bundle export

The file is named `settings.py` but 5 of its 8 routes are about data lifecycle and export, not settings. Anyone looking for data export routes would not look in `settings.py`.

**Recommended fix:**
Split into `settings.py` (settings routes only) and `data.py` (retention + export routes), each imported as their own router in `main.py`.

---

#### DS-2 — `app/shared/` contains only one file

**Severity:** Low
**Confidence:** High
**Evidence:**

`app/shared/__init__.py` and `app/shared/data_lifecycle.py` are the only files in `app/shared/`. The `shared` directory implies a collection of shared utilities, but there's only one module. This directory exists to serve a purpose that a simpler import path would serve equally well.

**Recommended fix:**
Move `data_lifecycle.py` to `app/` directly, or rename the directory to something more specific like `app/lifecycle/`. Not urgent.

---

### 2.3 Naming Issues

---

#### NI-1 — `ChannelConfigPayload.detection_mode` default vs. runtime default mismatch

**Severity:** Medium
**Confidence:** High
**Evidence:**

```python
# schemas.py:36
detection_mode: str = Field(default="motion", pattern="^(always|motion)$")

# channel_runtime.py:366
detection_mode_raw = str(channel.get("detection_mode", "always")).strip().lower()
```

The API schema defaults new configs to `"motion"`, but the runtime falls back to `"always"` if the field is absent from the channel dict. A newly created channel (via `POST /api/channels`) does not include `detection_mode` in its payload (`ChannelPayload` has no such field), so the runtime will use `"always"`. But if the user saves via the config form, it will be stored as `"motion"`. This is a behavioral inconsistency.

**Recommended fix:**
Align both defaults to the same value. Prefer `"always"` as the safer default and update `ChannelConfigPayload`.

---

#### NI-2 — `ChannelFilterPayload` uses raw `Dict[str, int]` for plate sizes

**Severity:** Low
**Confidence:** High
**Evidence:**

```python
# schemas.py:71-72
min_plate_size: Dict[str, int] = {"width": 80, "height": 20}
max_plate_size: Dict[str, int] = {"width": 600, "height": 240}
```

`ChannelConfigPayload` uses `PlateSizePayload` (a proper Pydantic model with validation), but `ChannelFilterPayload` uses raw `Dict[str, int]` without validation. They represent the same data.

**Recommended fix:**
Change `ChannelFilterPayload` to use `PlateSizePayload`.

---

#### NI-3 — `ControllerAutomationService` method names `handle_event` / `dispatch_event`

**Severity:** Low
**Confidence:** High
**Evidence:** `service.py:165, 216`. `handle_event` does the real work; `dispatch_event` wraps it with a try/except. External callers use `dispatch_event`. The indirection adds no semantic clarity — one method with a clear name would be better.

---

#### NI-4 — `TrackAggregator.clear_last` — misleading name, never used

**Severity:** Low
**Confidence:** High
**Evidence:**

Searching all Python files: `clear_last` is defined at `anpr_pipeline.py:65` but is never called anywhere in the codebase. It only clears `last_emitted` without clearing `track_texts`, making it a partial reset with an ambiguous name.

**Recommended fix:**
Remove `clear_last`. The `reset` method already does a full reset including both dicts.

---

### 2.4 Unused Modules/Files/Code

---

#### UN-1 — `CRNNRecognizer.recognize` (single-image method) — dead code

**Severity:** Low
**Confidence:** High
**Evidence:**

```python
# crnn_recognizer.py:78-82
@torch.no_grad()
def recognize(self, plate_image) -> Tuple[str, float]:
    batch_result = self.recognize_batch([plate_image])
    if not batch_result:
        return "", 0.0
    return batch_result[0]
```

`recognize_batch` is called at `anpr_pipeline.py:230`. The single-image `recognize` method is never called in the codebase. It is a thin wrapper over `recognize_batch`.

**Recommended fix:**
Remove `recognize`. If single-image recognition is ever needed, callers can use `recognize_batch([img])[0]`.

---

#### UN-2 — `TrackAggregator.clear_last` — dead code

**Severity:** Low
**Confidence:** High
**Evidence:** Defined at `anpr_pipeline.py:65-66`, never called anywhere in the codebase. See NI-4.

---

#### UN-3 — `log_perf_stage` in `common/logging.py` — likely unused

**Severity:** Low
**Confidence:** Medium
**Evidence:**

```python
# common/logging.py:277-288
def log_perf_stage(logger, channel, stage, duration_ms, level=logging.DEBUG, **extra):
    ...
```

This utility function is defined but searching the codebase shows it is not called from any other module. Performance timing is captured via `DebugRegistry.update_stage_timings` instead.

**Recommended fix:**
Verify by grep, then remove if unused.

---

#### UN-4 — `CONTROLLER_TYPES` dict in `controllers/service.py`

**Severity:** Low
**Confidence:** High
**Evidence:**

```python
# service.py:14-16
CONTROLLER_TYPES = OrderedDict([
    ("DTWONDER2CH", "DTWONDER2CH"),
])
SUPPORTED_CONTROLLER_TYPES = tuple(CONTROLLER_TYPES.keys())
```

This dict has a single entry that maps a string to itself. Its only use is to produce `SUPPORTED_CONTROLLER_TYPES`. The `CONTROLLER_ADAPTERS` registry in `controllers/registry.py` already holds the canonical list of supported types. `CONTROLLER_TYPES` is an unnecessary parallel structure.

**Recommended fix:**
Derive `SUPPORTED_CONTROLLER_TYPES` from `CONTROLLER_ADAPTERS.keys()` in `registry.py`, eliminating `CONTROLLER_TYPES`.

---

### 2.5 Legacy Code

No legacy code found. The codebase has no commented-out blocks, deprecated compatibility shims, or import shadows. The settings migration runner has a single migration path for version 1, which is correct and not legacy.

---

### 2.6 Performance and Memory Risks

---

#### PM-1 — `TrackAggregator` uses `list.pop(0)` — O(n) in hot path

**Severity:** High
**Confidence:** High
**Evidence:**

```python
# anpr_pipeline.py:37-40
bucket = self.track_texts.setdefault(track_id, [])
bucket.append((text, max(0.0, float(confidence))))
if len(bucket) > self.best_shots:
    bucket.pop(0)   # ← O(n) list shift
```

Python's `list.pop(0)` is O(n) because all remaining elements are shifted. For `best_shots=3` this is trivial, but for larger values (up to 20 per schema) and high detection rates (multiple detections per frame, multiple channels), this adds up.

**Recommended fix:**
Replace `bucket: List[...]` with `deque(maxlen=self.best_shots)`. No manual pop needed.

---

#### PM-2 — `PlatePreprocessor` creates CLAHE and kernel objects on every call

**Severity:** Medium
**Confidence:** High
**Evidence:**

```python
# plate_preprocessor.py:149-156 (called on every detection)
clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
enhanced = clahe.apply(gray)
blurred = cv2.GaussianBlur(enhanced, (5, 5), 0)
thresh = cv2.adaptiveThreshold(...)
kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
cleaned = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=1)
```

`cv2.createCLAHE` allocates a C++ OpenCV object. `cv2.getStructuringElement` creates a new numpy array. Both are created freshly on every call to `preprocess()`. Since `preprocess` is called once per YOLO detection per frame, this is ~25×N allocations per second (N = detections per frame per channel).

**Recommended fix:**
Create `_clahe` and `_kernel` as class attributes in `__init__`. They are stateless and can be reused across calls.

---

#### PM-3 — `CRNNRecognizer._decode_batch` — per-timestep Python loop

**Severity:** High
**Confidence:** High
**Evidence:**

```python
# crnn_recognizer.py:95-104
for t in range(time_steps):
    timestep_log_probs = probs[t]
    char_idx = int(torch.argmax(timestep_log_probs).item())
    char_conf = float(torch.exp(torch.max(timestep_log_probs)).item())
    if char_idx != 0 and char_idx != last_char_idx:
        decoded_chars.append(self.int_to_char.get(char_idx, ""))
        char_confidences.append(char_conf)
    last_char_idx = char_idx
```

For each timestep, `.item()` forces a device-to-host copy. `torch.argmax` and `torch.max` are called separately on the same tensor, wasting computation. The CTC decoding loop runs in pure Python, defeating PyTorch's batch processing advantage.

The `time_steps` value for the CRNN model (input 32×128 → CNN downsampling → LSTM) is typically 31 (128 / 4 = 32 minus pooling). With 3 detections per frame × 6 channels × 25 fps = 450 batch elements per second, this is ~14,000 Python loop iterations per second just for decoding.

**Recommended fix:**
Vectorize the CTC greedy decoder:
```python
# Vectorized equivalent (pseudo-code):
indices = probs.argmax(dim=-1)  # shape: [batch, time]
max_probs = probs.exp().max(dim=-1).values  # shape: [batch, time]
# Then iterate over batch dimension only, using numpy on .cpu().numpy()
```

---

#### PM-4 — `recognize_batch` materializes full list for empty check

**Severity:** Low
**Confidence:** High
**Evidence:**

```python
# crnn_recognizer.py:69-71
plate_images = list(plate_images)
if not plate_images:
    return []
```

`plate_images` is already a `List[np.ndarray]` at the call site (`anpr_pipeline.py:208-228`). Converting it to a list again is a no-op copy. The `list()` call exists to support `Iterable` input, which is declared in the type annotation but not actually used — the caller always passes a list.

**Recommended fix:**
Either change the parameter type to `List[np.ndarray]` and remove the `list()` call, or keep the `Iterable` signature but only materialize if empty check is needed (check first item without full materialization).

---

#### PM-5 — `cleanup_stale` called redundantly per frame

**Severity:** Low
**Confidence:** High
**Evidence:**

```python
# channel_runtime.py:456 — on failed read
self._debug_registry.cleanup_stale(channel_id)

# channel_runtime.py:491 — on empty frame
self._debug_registry.cleanup_stale(channel_id)

# channel_runtime.py:498 — on every good frame (unconditional)
self._debug_registry.cleanup_stale(channel_id)

# channel_runtime.py:520 — inside update_from_detections (also calls _cleanup_stale_locked)
self._debug_registry.update_from_detections(...)  # calls _cleanup_stale_locked internally
```

On a successful processed frame, `cleanup_stale` is called once explicitly (line 498) AND again inside `update_from_detections` (line 520) which calls `_cleanup_stale_locked`. Each `cleanup_stale` acquires the RLock and iterates the `_track_last_seen` dict.

**Recommended fix:**
Remove the explicit `cleanup_stale(channel_id)` call at line 498 when `should_process=True`, since `update_from_detections` already does it. Only keep the explicit call for the cases when detection is skipped.

---

#### PM-6 — Double `mkdir` call per event

**Severity:** Low
**Confidence:** High
**Evidence:**

```python
# channel_runtime.py:242-247 (_build_event_media_paths)
day_dir = self._screenshots_dir / event_ts.strftime("%Y-%m-%d") / f"channel_{channel_id}"
day_dir.mkdir(parents=True, exist_ok=True)    # ← mkdir #1
...

# channel_runtime.py:252-253 (_save_jpeg)
def _save_jpeg(self, path, image):
    ...
    path.parent.mkdir(parents=True, exist_ok=True)  # ← mkdir #2 (same dir)
```

`path.parent` in `_save_jpeg` is the same `day_dir` created in `_build_event_media_paths`. The directory was just created, so the second call is always a no-op syscall.

**Recommended fix:**
Remove the `mkdir` call from `_save_jpeg` since the directory is guaranteed to exist after `_build_event_media_paths`. Or remove it from `_build_event_media_paths` and keep it only in `_save_jpeg` (called twice per event for frame and plate).

---

#### PM-7 — `ControllerService.send_command` spawns a new thread per command

**Severity:** Low
**Confidence:** High
**Evidence:**

```python
# service.py:111-113
thread = threading.Thread(target=_dispatch, name=f"controller-{controller_name}", daemon=True)
thread.start()
return url
```

Every relay command creates a new `Thread`. Thread creation has overhead (~1 ms). Under high-rate plate recognition (e.g., busy intersection), this could create threads faster than they complete.

**Recommended fix:**
Use a single daemon thread with a queue per controller, or use `concurrent.futures.ThreadPoolExecutor` with a pool of 1–2 workers. This bounds thread count and adds backpressure.

---

#### PM-8 — `HourlyFileHandler._open_stream` called on every log record

**Severity:** Low
**Confidence:** High
**Evidence:**

```python
# common/logging.py:81-88 (emit)
def emit(self, record):
    try:
        message = self.format(record)
        with self._lock:
            self._open_stream(datetime.now().astimezone())   # ← called every record
```

`_open_stream` checks if `_current_period_start == period_start` and returns early if unchanged. The early return is cheap, but `datetime.now().astimezone()` and the lock acquisition happen on every record. Since logging runs in a background `QueueListener` thread, this is not in the critical path, but it adds unnecessary work.

**Recommended fix:**
Cache the next rotation time as a `datetime` field and only call `_open_stream` when `datetime.now() >= _next_rotation_at`. This avoids the lock acquisition entirely on most records.

---

#### PM-9 — `DebugLogBus.wait_for_entries` blocks a thread pool thread for 15 seconds

**Severity:** Low
**Confidence:** High
**Evidence:**

```python
# debug.py:375-379
def wait_for_entries(self, last_id, timeout=15.0):
    with self._condition:
        if self._seq <= last_id:
            self._condition.wait(timeout=timeout)    # ← blocks for up to 15s

# app/api/routers/debug.py:67
items = await asyncio.to_thread(container.debug_log_bus.wait_for_entries, cursor, 15.0)
```

`asyncio.to_thread` moves `wait_for_entries` to a thread pool thread. That thread is blocked for up to 15 seconds per SSE client connection that has no new log entries. With N active debug log SSE clients, N threads are perpetually blocked. The default `asyncio.to_thread` thread pool (128 threads) can accommodate many clients, but this is an unnecessary resource waste.

**Recommended fix:**
Replace the polling-with-condition-variable approach with proper async: use an `asyncio.Queue` in `DebugLogBus` for SSE subscribers, similar to `EventBus`. This eliminates the thread pool usage entirely.

---

### 2.7 CPU Optimization Opportunities

---

#### CO-1 — Per-frame JPEG encoding regardless of viewer count

**Severity:** Medium
**Confidence:** High
**Evidence:**

```python
# channel_runtime.py:576
ok_enc, preview_buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
```

JPEG encoding runs on every frame for every channel, even if no browser is connected and watching the preview. The `disable_video_output` flag can disable this, but it requires manual user action. There is no automatic detection of viewer count.

For a 1080p frame at 80% quality, JPEG encoding typically takes 5–15 ms per frame. At 25 fps × 4 channels = 100 encodings/second = 500 ms–1500 ms of CPU per second dedicated solely to preview encoding when nobody is watching.

**Recommended fix:**
Track `active_preview_clients` per channel as a counter. Only run JPEG encoding when `active_preview_clients > 0`. Increment/decrement in the MJPEG streaming generator's connect/disconnect lifecycle. This requires adding a counter to `ChannelContext` and passing it through the `get_preview_frame` API.

---

#### CO-2 — YOLO runs on every frame when `detector_frame_stride=1` (default)

**Severity:** Medium
**Confidence:** High
**Evidence:**

```python
# channel_runtime.py:511
if detector_input_frames % detector_frame_stride != 0:
    metrics.detector_skipped_frames += 1
    should_process = False
```

With `detector_frame_stride=1` (default in `ChannelConfigPayload`), YOLO runs on every single frame. YOLO inference typically takes 20–100 ms on CPU. For 4 channels at 25 fps with `stride=1`, YOLO consumes the entire channel thread CPU.

The default should be `2` or `3` for real-time RTSP cameras. The schema defaults to `2` (`ChannelConfigPayload:41` — `detector_frame_stride: int = Field(default=2, ...)`), but the runtime default at `channel_runtime.py:377` is `1`.

**Recommended fix:**
Align the runtime fallback default to `2` to match the schema: `channel.get("detector_frame_stride", 2)`.

---

#### CO-3 — Motion detector processes every frame even at `motion_frame_stride=1`

**Severity:** Medium
**Confidence:** High
**Evidence:**

```python
# channel_runtime.py:503
motion_active = bool(motion_detector.update(detector_frame))
```

When `detection_mode="motion"`, the motion detector processes `detector_frame` (which may be the ROI-masked frame) on every single frame. The motion detector itself uses Gaussian blur and frame differencing. For 1080p frames, `GaussianBlur` is ~1–3 ms and differencing is ~2 ms. This runs even when there is clearly no motion to save.

The `motion_frame_stride` config controls how often the motion detector runs (default 1 = every frame per `MotionDetectorConfig`). But looking at `channel_runtime.py:381-382`, the motion config's `frame_stride` is only applied inside `MotionDetector.update()` — let me verify. Actually, the `motion_frame_stride` from the channel config is used as `frame_stride` in `MotionDetectorConfig`, so this may already be handled inside the motion detector.

**Note:** This is an observation rather than a confirmed bug. Verify that `MotionDetector.update()` internally skips frames based on `frame_stride`.

---

#### CO-4 — No early exit in `process_frame` when detections list is empty

**Severity:** Low
**Confidence:** High
**Evidence:**

```python
# anpr_pipeline.py:207-230
def process_frame(self, frame, detections):
    plate_inputs = []
    detection_indices = []
    for idx, detection in enumerate(detections):
        if self.direction_estimator and detection.get("track_id") is not None:
            direction_info = self.direction_estimator.update(...)  # ← runs even if empty
        ...
    batch_results = self.recognizer.recognize_batch(plate_inputs)  # ← called even if empty list
```

When `detections` is empty (no plates in frame), `process_frame` still initializes two lists, iterates (zero iterations), then calls `recognize_batch([])` which checks `if not plate_images: return []`. There is an early exit in `recognize_batch`, but the function call overhead itself is unnecessary.

**Recommended fix:**
Add `if not detections: return []` at the start of `process_frame`.

---

### 2.8 Recognition Pipeline Observations

---

#### RP-1 — Processing flow, step by step

```
Frame read (cv2.VideoCapture.read)
  │
  ├─ FAIL/EMPTY → reconnect logic, skip frame
  │
  ├─ ROI masking (_apply_roi_mask) [if roi_enabled]
  │    └─ Computes polygon #1, allocates mask array, runs bitwise_and
  │
  ├─ Motion detection (MotionDetector.update) [if detection_mode="motion"]
  │    └─ Grayscale, GaussianBlur, frame diff, threshold
  │         → motion_active = True/False
  │
  ├─ Frame stride skip [detector_input_frames % detector_frame_stride != 0]
  │
  ├─ YOLO detection/tracking (YOLODetector.track)
  │    └─ model.track(frame) → ByteTrack IDs + bboxes
  │    └─ _filter_by_size → size-filtered detections
  │    └─ _expand_detections → padding applied to bboxes
  │
  ├─ ROI detection filter (_filter_detections_by_roi)
  │    └─ Computes polygon #2 (DUPLICATE of polygon #1)
  │    └─ Filters detections by center point inside polygon
  │
  ├─ Debug registry update (update_from_detections)
  │    └─ cleanup_stale (DUPLICATE cleanup, also done at line 498)
  │
  ├─ ANPRPipeline.process_frame
  │    ├─ For each detection:
  │    │    ├─ TrackDirectionEstimator.update (bbox history → APPROACHING/RECEDING)
  │    │    ├─ Frame crop (frame[y1:y2, x1:x2])
  │    │    └─ PlatePreprocessor.preprocess (creates CLAHE+kernel EVERY time)
  │    │         ├─ Grayscale, CLAHE, GaussianBlur, adaptiveThreshold, morphology
  │    │         ├─ _detect_plate_quadrilateral → perspective transform
  │    │         └─ OR _estimate_skew_angle → Canny, HoughLinesP, rotation
  │    │
  │    ├─ CRNNRecognizer.recognize_batch (batch of preprocessed crops)
  │    │    ├─ transform each image (PIL → grayscale → resize → normalize)
  │    │    ├─ torch.stack → batch tensor
  │    │    ├─ model(batch) → log-softmax output
  │    │    └─ _decode_batch (Python loop per timestep per item — not vectorized)
  │    │
  │    ├─ For each decoded result:
  │    │    ├─ Confidence threshold check (< min_confidence → "Нечитаемо")
  │    │    ├─ TrackAggregator.add_result (quorum consensus)
  │    │    │    └─ Rebuilds weights/counts dicts on every call
  │    │    ├─ PlatePostProcessor.process (country validation)
  │    │    │    └─ Normalizes text, tries each enabled country's regex patterns
  │    │    └─ Cooldown check (_on_cooldown)
  │    │
  │    └─ Returns detections (including unreadable / no-text ones)
  │
  ├─ Event formation and save (for non-empty plate results)
  │    ├─ _build_event_media_paths → mkdir (DUPLICATE mkdir)
  │    ├─ _save_jpeg(frame) → cv2.imwrite
  │    ├─ _save_jpeg(plate_crop) → cv2.imwrite + mkdir (DUPLICATE mkdir)
  │    ├─ EventSink.insert_event (PostgreSQL)
  │    └─ publish_event_sync
  │         ├─ asyncio.create_task(event_bus.publish) [async SSE delivery]
  │         └─ ControllerAutomationService.dispatch_event [SYNCHRONOUS DB query]
  │
  └─ JPEG preview encoding (cv2.imencode) [ALWAYS, regardless of viewers]
       └─ _lock acquisition for latest_jpeg update
```

**Key redundancies and waste identified:**
1. ROI polygon computed twice (lines 275 and 326)
2. `cleanup_stale` called 2x on processed frames (lines 498 and inside update_from_detections)
3. `mkdir` called twice for same directory on each event
4. CLAHE/kernel recreated on each `preprocess()` call
5. JPEG encoding on every frame regardless of viewer count
6. Controller DB query blocks channel thread after every event
7. Unbounded growth of `track_texts`, `_history`, `_last_seen`

---

#### RP-2 — `PlatePreprocessor` runs full pipeline even on very small crops

**Severity:** Medium
**Confidence:** High
**Evidence:**

`plate_preprocessor.py:145` checks `if plate_image.size == 0` but does not check minimum dimensions. A crop from a 40×10 pixel bbox will go through: grayscale → CLAHE → GaussianBlur → adaptiveThreshold → morphology → contour detection → HoughLinesP. This produces poor results and wastes CPU.

**Recommended fix:**
Add a minimum dimension check at the start of `preprocess()`: if width < 20 or height < 8, return the image unchanged (the CRNN resize will handle it).

---

#### RP-3 — `process_frame` mutates incoming `detections` dicts in-place

**Severity:** Low
**Confidence:** High
**Evidence:**

```python
# anpr_pipeline.py:214-215
detection.update(direction_info)
detection["plate_image"] = None
```

The detections list passed to `process_frame` is the same list returned by `YOLODetector.track`. The function mutates each detection dict in-place (adds `direction`, `plate_image`, `text`, `confidence`, `country`, etc.). This is safe in the current code since no other consumer reads the original detections after `process_frame` is called. But it creates hidden coupling.

**Recommended fix:**
Document this contract explicitly in the docstring, or create new dicts in `process_frame` rather than mutating inputs.

---

#### RP-4 — Direction estimation uses separate conceptual vocabulary in debug overlay

**Severity:** Low
**Confidence:** High
**Evidence:**

`TrackDirectionEstimator` emits: `"APPROACHING"`, `"RECEDING"`, `"UNKNOWN"`.
`DebugRegistry._estimate_direction` emits: `"IN"`, `"OUT"`, `None`.

These are two separate direction systems with different semantics and different string values. The debug overlay (`DebugRegistry`) does its own direction estimation from track history (pure geometric: dx/dy), while the pipeline uses `TrackDirectionEstimator` which uses bbox area and Y-center.

The stored event `direction` field uses `APPROACHING`/`RECEDING`/`UNKNOWN` (from the pipeline). The debug overlay shows `IN`/`OUT` which may disagree. This is confusing for debugging.

**Recommended fix:**
Use the pipeline's `direction` result in the debug overlay instead of recomputing it. Pass `det.get("direction")` through to `DebugRegistry` (already done via `_candidate_from_detection`'s `explicit_direction` path) but ensure the fallback `_estimate_direction` either uses the same vocabulary or is removed.

---

## 3. Consistency Issues

---

#### CI-1 — Two different `direction` vocabularies used in same system

Already covered in RP-4.

---

#### CI-2 — `ChannelPayload` (create) vs `ChannelConfigPayload` (update) are incompatible models

**Severity:** Medium
**Confidence:** High
**Evidence:**

```python
# schemas.py:10-15 (ChannelPayload — used for POST /api/channels)
class ChannelPayload(BaseModel):
    name: str
    source: str
    enabled: bool = True
    roi_enabled: bool = True
    region: Dict[str, Any] | None = None
```

`ChannelPayload` (create) has no `detection_mode`, `best_shots`, `cooldown_seconds`, `ocr_min_confidence`, etc. These are all given system defaults on create. But `ChannelConfigPayload` (update) has all of these fields.

After creation, a channel dict in YAML will be missing these fields until the user explicitly saves the config form. The runtime uses `channel.get("detection_mode", "always")` style fallbacks for all missing fields, so this works but creates channels with inconsistent field sets in the YAML file. Some channels will have 5 keys, others 20+ keys.

**Recommended fix:**
After creating a channel, immediately apply all defaults from `ChannelConfigPayload` to the stored dict. This ensures consistent YAML structure.

---

#### CI-3 — `put_global_settings` restarts the processor (stops all channels) on every settings save

**Severity:** Medium
**Confidence:** High
**Evidence:**

```python
# routers/settings.py:67
container.restart_processor_for_settings()
```

```python
# container.py:133-145
def restart_processor_for_settings(self):
    ...
    for channel in channels:
        self.processor.stop(int(channel["id"]))
    self.processor = self._create_processor()   # ← rebuilds YOLO + CRNN models
    for channel in channels:
        self.processor.ensure_channel(channel)
    for channel_id in enabled_ids:
        self.processor.start(channel_id)
```

Every call to `PUT /api/settings` (which includes changing grid layout or theme) destroys and rebuilds the entire `ChannelProcessor`, reloads YOLO and CRNN models from disk, and restarts all channels. Loading YOLO takes ~2–5 seconds. This means changing UI theme interrupts all live camera feeds for several seconds.

**Why it is a problem:**
This is a major user experience issue. Changing `grid` or `theme` (UI-only settings) triggers a full pipeline restart.

**Recommended fix:**
Separate the settings that require processor restart (ANPR params, storage DSN, plate countries, reconnect) from those that don't (grid, theme, logging level, time settings). Only call `restart_processor_for_settings()` when pipeline-affecting settings change.

---

## 4. Cleanup Candidates

---

### Table 1: Safe to Remove Now

| Item | File | Evidence | Why |
|------|------|----------|-----|
| `CRNNRecognizer.recognize()` | `anpr/recognition/crnn_recognizer.py:78-82` | Never called anywhere | Dead code, thin wrapper over `recognize_batch` |
| `TrackAggregator.clear_last()` | `anpr/pipeline/anpr_pipeline.py:65-66` | Never called anywhere | Dead code, superseded by `reset()` |
| Second `mkdir` in `_save_jpeg` | `runtime/channel_runtime.py:253` | Directory already created in `_build_event_media_paths` | Redundant filesystem syscall |
| Redundant `cleanup_stale` at line 498 | `runtime/channel_runtime.py:498` | Also called inside `update_from_detections` | Double cleanup per processed frame |
| `list(plate_images)` copy in `recognize_batch` | `anpr/recognition/crnn_recognizer.py:69` | Input is already a `List` at callsite | Unnecessary copy |

---

### Table 2: Needs Verification Before Removal

| Item | File | What to Check | Reason for Uncertainty |
|------|------|--------------|------------------------|
| `log_perf_stage` | `common/logging.py:277-288` | Grep for calls outside Python files (JS, config, docs) | Not called in Python but may be documented API |
| `CONTROLLER_TYPES` dict | `controllers/service.py:14-16` | Check if imported by frontend JS or external scripts | Exported via `__all__` |
| `ChannelFilterPayload.size_filter_enabled` | `app/api/schemas.py:70` | Check if this field is processed by `update_channel` | May be used in `update_channel` via `payload.model_dump()` |

---

### Table 3: Should Be Refactored, Not Removed

| Item | File | What to Refactor | Expected Result |
|------|------|-----------------|-----------------|
| `TrackAggregator.track_texts` (list) | `anpr/pipeline/anpr_pipeline.py:30` | Replace `List` with `deque(maxlen=best_shots)` + add TTL eviction | Bounded memory, O(1) pop |
| `TrackDirectionEstimator._history` | `anpr/pipeline/anpr_pipeline.py:96` | Add TTL eviction with `time.monotonic()` | Bounded memory |
| `ANPRPipeline._last_seen` | `anpr/pipeline/anpr_pipeline.py:193` | Prune entries older than `cooldown_seconds * 2` | Bounded memory |
| `_apply_roi_mask` + `_filter_detections_by_roi` | `runtime/channel_runtime.py:274, 321` | Compute polygon once, pass to both; remove full-frame mask | ~2 polygon computations saved per frame |
| `PlatePreprocessor.preprocess` | `anpr/preprocessing/plate_preprocessor.py:145-170` | Move CLAHE and kernel to `__init__` as instance attributes | Eliminates per-call allocation |
| `CRNNRecognizer._decode_batch` | `anpr/recognition/crnn_recognizer.py:84-114` | Vectorize using `argmax` + `exp` on full tensor | Faster decoding, especially for large batches |
| `put_global_settings` restart logic | `app/api/routers/settings.py:47-68` | Only restart processor on pipeline-relevant changes | Prevents interruption on UI-only changes |
| `dispatch_event` + `handle_event` | `controllers/service.py:165-220` | Merge into single method | Removes unnecessary indirection |
| `DebugLogBus.wait_for_entries` | `runtime/debug.py:375-379` | Replace with async queue like `EventBus` | Eliminates blocking thread usage |
| `settings.py` router file | `app/api/routers/settings.py` | Split into `settings.py` and `data.py` | Cleaner route organization |

---

## 5. Independent Implementation Tasks

See `REVIEW_TASKS.md` for the full task list.
