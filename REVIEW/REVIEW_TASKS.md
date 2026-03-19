# ANPR-System-v0.8_web — Implementation Task List

**Source:** REVIEW_FULL.md (review date 2026-03-18)
**Status tracking updated:** 2026-03-19

---

## Table 1 — Safe Removals (5 tasks)

| # | Task | File | Status |
|---|------|------|--------|
| TASK-01 | Remove `CRNNRecognizer.recognize()` dead method | `anpr/recognition/crnn_recognizer.py:77-82` | ✅ DONE |
| TASK-02 | Remove `list(plate_images)` copy in `recognize_batch`; change type hint to `List` | `anpr/recognition/crnn_recognizer.py:69` | ✅ DONE |
| TASK-03 | Remove `TrackAggregator.clear_last()` dead method | `anpr/pipeline/anpr_pipeline.py:65-66` | ✅ DONE |
| TASK-04 | Remove second `mkdir` call in `_save_jpeg` | `runtime/channel_runtime.py:253` | ✅ DONE |
| TASK-05 | Remove redundant `cleanup_stale` call at line 498; move to non-processing branch | `runtime/channel_runtime.py:498` | ✅ DONE |

---

## Table 2 — Refactors (10 tasks)

| # | Task | File | Status |
|---|------|------|--------|
| TASK-06 | Replace `track_texts` `List` with `deque(maxlen=best_shots)` + TTL eviction for `track_texts`, `last_emitted` | `anpr/pipeline/anpr_pipeline.py` | ✅ DONE |
| TASK-07 | Add TTL eviction for `TrackDirectionEstimator._history` | `anpr/pipeline/anpr_pipeline.py` | ✅ DONE |
| TASK-08 | Prune `ANPRPipeline._last_seen` entries older than `cooldown_seconds * 2` in `_on_cooldown` | `anpr/pipeline/anpr_pipeline.py` | ✅ DONE |
| TASK-09 | Compute ROI polygon once; eliminate `_apply_roi_mask` from hot path | `runtime/channel_runtime.py:494` | ✅ DONE |
| TASK-10 | Move CLAHE and kernel to `__init__` in `PlatePreprocessor` | `anpr/preprocessing/plate_preprocessor.py` | ✅ DONE |
| TASK-11 | Vectorize `CRNNRecognizer._decode_batch` (argmax + exp on full batch×time tensor) | `anpr/recognition/crnn_recognizer.py:84-114` | ✅ DONE |
| TASK-12 | Only restart processor on pipeline-relevant settings changes in `put_global_settings` | `app/api/routers/settings.py:67` | ✅ DONE |
| TASK-13 | Merge `dispatch_event` + `handle_event` into single method in `ControllerAutomationService` | `controllers/service.py:165-220` | ✅ DONE |
| TASK-14 | Replace `DebugLogBus.wait_for_entries` / `asyncio.to_thread` with `asyncio.Queue` subscriber pattern | `runtime/debug.py`, `app/api/routers/debug.py` | ✅ DONE |
| TASK-15 | Split `app/api/routers/settings.py` into `settings.py` (settings routes) + `data.py` (retention/export routes) | `app/api/routers/` | ✅ DONE |

---

## Notes

- All 15 tasks implemented on 2026-03-19.
- TASK-09 also eliminates double polygon computation (AW-2) and full-frame mask allocation (AW-3).
- TASK-06 also fixes PM-1 (O(n) pop(0) → O(1) deque).
- TASK-12 also addresses CI-3 (settings restart interrupts live feeds on UI-only changes).
- `_apply_roi_mask` method kept in `ChannelProcessor` but no longer called in the frame loop.
