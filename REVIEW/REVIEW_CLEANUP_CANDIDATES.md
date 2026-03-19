# ANPR-System-v0.8_web — Cleanup Candidates

**Date:** 2026-03-18
**Status updated:** 2026-03-19 — All 15 tasks from REVIEW_TASKS.md implemented.

---

## Table 1: Safe to Remove Now ✅ ALL DONE

These items are confirmed dead code with high confidence. Removing them carries no functional risk.

| Item | File | Line(s) | Evidence | Notes | Status |
|------|------|---------|----------|-------|--------|
| `CRNNRecognizer.recognize()` | `anpr/recognition/crnn_recognizer.py` | 78–82 | Never called in any `.py` file; all callers use `recognize_batch()` | Thin wrapper over `recognize_batch([img])[0]` | ✅ Removed |
| `TrackAggregator.clear_last()` | `anpr/pipeline/anpr_pipeline.py` | 65–66 | Never called in any `.py` file | Partial reset superseded by `reset()` | ✅ Removed |
| Second `mkdir` in `_save_jpeg` | `runtime/channel_runtime.py` | 253 | Directory already created by `_build_event_media_paths` at line 243 | No-op syscall on every event | ✅ Removed |
| Redundant `cleanup_stale` call | `runtime/channel_runtime.py` | 498 | Also called inside `update_from_detections` (line 520) which runs immediately after | Moved to non-processing branch only | ✅ Fixed |
| `list(plate_images)` copy | `anpr/recognition/crnn_recognizer.py` | 69 | Caller always passes a `List`; converting is a no-op | Removed; type changed to `List[np.ndarray]` | ✅ Removed |

---

## Table 2: Needs Verification Before Removal

These items appear unused but require manual verification (grep for usage outside Python, check templates, check JS bindings).

| Item | File | Line(s) | What to Verify | Reason for Uncertainty |
|------|------|---------|---------------|------------------------|
| `log_perf_stage` | `common/logging.py` | 277–288 | `grep -r "log_perf_stage"` across entire project | Defined but not called in any `.py` file reviewed; may be an intended API |
| `CONTROLLER_TYPES` dict | `controllers/service.py` | 14–16 | Check if `app/web/app.js` or any template references `CONTROLLER_TYPES` | Exported via `__all__`; may be consumed by front-end via API response |
| `RELAY_MODES` dict | `controllers/service.py` | 20–23 | Same as above — check `app.js` usage | Maps relay mode keys to Russian display names; may be used in UI settings |
| `TrackAggregator.reset()` | `anpr/pipeline/anpr_pipeline.py` | 68–71 | Called at `anpr_pipeline.py:260` — confirm no tests rely on `clear_last` distinction | Keep; only listing for completeness |

---

## Table 3: Should Be Refactored, Not Removed ✅ 10/10 DONE (from REVIEW_TASKS.md)

These items have real functional problems but removing them would break behavior. They need replacement/redesign.

| Item | File | Line(s) | Problem | Recommended Refactor | Status |
|------|------|---------|---------|----------------------|--------|
| `TrackAggregator.track_texts` and `last_emitted` | `anpr/pipeline/anpr_pipeline.py` | 30–31, 37–63 | Unbounded memory growth (memory leak) | Add TTL eviction; replace value list with `deque(maxlen=best_shots)` | ✅ Done |
| `TrackDirectionEstimator._history` | `anpr/pipeline/anpr_pipeline.py` | 96, 149 | Unbounded memory growth (memory leak) | Add TTL eviction using `time.monotonic()` per-track timestamp | ✅ Done |
| `ANPRPipeline._last_seen` | `anpr/pipeline/anpr_pipeline.py` | 193, 198–201 | Unbounded memory growth | Prune entries where `now - ts > cooldown_seconds * 2` in `_on_cooldown` | ✅ Done |
| `_apply_roi_mask` full-frame masking | `runtime/channel_runtime.py` | 274–281, 494 | Allocates 2+ MB mask per frame; polygon computed twice | Removed from hot path; detector now receives raw frame; ROI via `_filter_detections_by_roi` only | ✅ Done |
| `PlatePreprocessor.preprocess` | `anpr/preprocessing/plate_preprocessor.py` | 149, 155 | CLAHE and morphology kernel re-created on every call | Moved to `__init__` as instance attributes | ✅ Done |
| `CRNNRecognizer._decode_batch` | `anpr/recognition/crnn_recognizer.py` | 84–114 | Python loop per CTC timestep; separate `argmax` and `max` calls on same tensor | Vectorized: `argmax` and `exp(max)` over full batch × time tensor; single CPU transfer | ✅ Done |
| `put_global_settings` restart logic | `app/api/routers/settings.py` | 67 | Restarts all channels (incl. model reload) on every settings save | Only restarts when `plates` or `postgres_dsn`/`screenshots_dir` changes | ✅ Done |
| `dispatch_event` + `handle_event` split | `controllers/service.py` | 165–220 | Unnecessary indirection | Merged into single `dispatch_event` with inline try/except | ✅ Done |
| `DebugLogBus.wait_for_entries` in `asyncio.to_thread` | `runtime/debug.py:375`, `routers/debug.py:67` | Blocks thread pool thread for up to 15 s per SSE client | Replaced with `asyncio.Queue` subscriber pattern (`subscribe`/`unsubscribe`/`snapshot_after`) | ✅ Done |
| `settings.py` router file | `app/api/routers/settings.py` | entire file | File named "settings" but contains retention + export routes | Split: `settings.py` (GET/PUT /api/settings), `data.py` (retention + export routes) | ✅ Done |
| `ChannelFilterPayload` plate size types | `app/api/schemas.py` | 71–72 | Uses raw `Dict[str,int]` instead of `PlateSizePayload` | Change to `PlateSizePayload` for consistency and validation | ⏳ Not in 15-task scope |
| `ChannelConfigPayload.detection_mode` default | `app/api/schemas.py` | 36 | Default `"motion"` conflicts with runtime default `"always"` | Align to `"always"` or update runtime fallback to `"motion"` | ⏳ Not in 15-task scope |
| Per-frame JPEG encoding | `runtime/channel_runtime.py` | 576 | Runs on every frame regardless of viewer count | Track active MJPEG clients per channel; skip encoding when count = 0 | ⏳ Not in 15-task scope |
| `reconnect_config` lock acquisition per frame | `runtime/channel_runtime.py` | 417 | Acquires RLock on every frame iteration | Cache locally; re-read only when needed (e.g., after `_reopen_capture`) | ⏳ Not in 15-task scope |

---

## Summary Counts

| Category | Count |
|----------|-------|
| Safe to remove | 5 |
| Needs verification | 4 |
| Refactor (not remove) | 14 |
