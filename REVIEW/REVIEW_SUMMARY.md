# ANPR-System-v0.8_web — Review Summary

**Date:** 2026-03-18
**Full report:** `REVIEW_FULL.md`
**Cleanup candidates:** `REVIEW_CLEANUP_CANDIDATES.md`
**Implementation tasks:** `REVIEW_TASKS.md`

---

## Overall Assessment

The project is well-structured and production-ready in its core design. Architecture is clean: clear module boundaries, PostgreSQL-only persistence, single YAML config source, isolated channel threads, async SSE for events. No dead imports, no legacy code, no commented-out blocks.

**However, there are 3 confirmed memory leaks and several significant CPU inefficiencies in the recognition pipeline hot path that must be addressed.**

---

## Top Risks (Ordered by Priority)

### CRITICAL — Memory Leaks

| # | Issue | File | Evidence |
|---|-------|------|----------|
| 1 | ~~`TrackAggregator.track_texts` and `last_emitted` grow unbounded~~ | `anpr/pipeline/anpr_pipeline.py` | **FIXED 2026-03-19** — deque + TTL eviction |
| 2 | ~~`TrackDirectionEstimator._history` grows unbounded~~ | `anpr/pipeline/anpr_pipeline.py` | **FIXED 2026-03-19** — TTL eviction added |
| 3 | ~~`ANPRPipeline._last_seen` grows unbounded~~ | `anpr/pipeline/anpr_pipeline.py` | **FIXED 2026-03-19** — 60s scheduled TTL pruning in `_touch_plate` |

All three dicts live inside `ANPRPipeline`/`TrackAggregator`/`TrackDirectionEstimator`, which are created per channel. After days/weeks of continuous operation these grow significantly.

---

### HIGH — CPU Waste in Hot Path

| # | Issue | File | CPU Cost |
|---|-------|------|----------|
| 4 | ~~ROI polygon computed twice per frame~~ | `channel_runtime.py` | **FIXED 2026-03-19** — polygon computed once, passed to `_filter_detections_by_roi` |
| 5 | ~~Full-frame mask array allocated when ROI enabled~~ | `channel_runtime.py` | **FIXED 2026-03-19** — `_apply_roi_mask` call removed; filtering via point-in-polygon only |
| 6 | ~~CLAHE + morphology kernel recreated each `preprocess()`~~ | `plate_preprocessor.py` | **FIXED 2026-03-19** — both objects created once in `__init__` |
| 7 | ~~`_decode_batch` uses Python loop per CTC timestep~~ | `crnn_recognizer.py` | **FIXED 2026-03-19** — vectorized argmax/exp over full batch+time, single `.cpu().numpy()` transfer |
| 8 | ~~`TrackAggregator` uses `list.pop(0)` (O(n))~~ | `anpr_pipeline.py` | **FIXED 2026-03-19** — already done in TASK-01: `deque(maxlen=best_shots)` with O(1) append |

---

### HIGH — Architecture

| # | Issue | File | Impact |
|---|-------|------|--------|
| 9 | ~~Controller plate-list DB query blocks channel thread~~ | `container.py` | **FIXED 2026-03-19** — `dispatch_event` scheduled via `asyncio.to_thread` in `publish_event_sync`; channel thread no longer waits for DB |
| 10 | ~~`PUT /api/settings` restarts all channels incl. model reload~~ | `routers/settings.py` | **FIXED 2026-03-19** — restart only when `plates` changed; DSN change calls `refresh_storage_clients()` only; UI-only saves (grid, theme, logging, time, debug) apply in-place with no interruption |

---

### MEDIUM

| # | Issue |
|---|-------|
| 11 | `reconnect_config` fetched under lock on every frame iteration |
| 12 | ~~JPEG preview encoded every frame even with no active viewers~~ | **FIXED 2026-03-19** — `active_preview_clients` counter in `ChannelContext`; encoding skipped when 0; snapshot encodes on-demand from `latest_raw_frame` |
| 13 | ~~`ChannelConfigPayload.detection_mode` default `"motion"` vs runtime default `"always"`~~ | **FIXED 2026-03-19** — schema default changed to `"always"`; `POST /api/channels` now stores full config defaults |
| 14 | ~~`PlatePreprocessor` runs full pipeline on tiny crops (no minimum size guard)~~ | **FIXED 2026-03-19** — early return for `w < 20 or h < 8` added to `preprocess()` |
| 15 | ~~`settings.py` router file also handles data export/retention routes (naming mismatch)~~ | **FIXED 2026-03-19** — data routes moved to `app/api/routers/data.py`; registered in `main.py` |

---

### LOW / Safe to Remove

| # | Issue |
|---|-------|
| 16 | ~~`CRNNRecognizer.recognize()` — dead code, never called~~ | **FIXED 2026-03-19** — deleted |
| 17 | ~~`TrackAggregator.clear_last()` — dead code, never called~~ | **FIXED 2026-03-19** — deleted; test removed too |
| 18 | Second `mkdir` call in `_save_jpeg` — directory already created |
| 19 | Redundant `cleanup_stale` call at `channel_runtime.py:498` |
| 20 | `log_perf_stage` in `common/logging.py` — likely unused |

---

## Highest-Priority Actions

```
1. Fix memory leaks in ANPRPipeline (track dicts + _last_seen)
2. Eliminate double ROI polygon + remove full-frame masking
3. Move controller DB query off channel thread
4. Make settings save non-destructive (don't restart on UI-only changes)
5. Vectorize _decode_batch in CRNNRecognizer
6. Move CLAHE/kernel to PlatePreprocessor.__init__
7. Replace list.pop(0) with deque in TrackAggregator
8. Remove confirmed dead code (recognize, clear_last)
```
