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
| 1 | `TrackAggregator.track_texts` and `last_emitted` grow unbounded | `anpr/pipeline/anpr_pipeline.py:30-31` | Track IDs added on every detection, never evicted |
| 2 | `TrackDirectionEstimator._history` grows unbounded | `anpr/pipeline/anpr_pipeline.py:96,149` | New `deque` per track ID, never removed |
| 3 | `ANPRPipeline._last_seen` grows unbounded | `anpr/pipeline/anpr_pipeline.py:193` | Plate strings added, never pruned |

All three dicts live inside `ANPRPipeline`/`TrackAggregator`/`TrackDirectionEstimator`, which are created per channel. After days/weeks of continuous operation these grow significantly.

---

### HIGH — CPU Waste in Hot Path

| # | Issue | File | CPU Cost |
|---|-------|------|----------|
| 4 | ROI polygon computed twice per frame | `channel_runtime.py:275, 326` | 2× dict parse + `np.array` per frame |
| 5 | Full-frame mask array allocated when ROI enabled | `channel_runtime.py:279-281` | ~8 MB alloc + bitwise AND per frame |
| 6 | CLAHE + morphology kernel recreated each `preprocess()` | `plate_preprocessor.py:149, 155` | C++ object alloc per detection |
| 7 | `_decode_batch` uses Python loop per CTC timestep | `crnn_recognizer.py:95-104` | ~14,000 Python iterations/sec at 6 channels × 25 fps |
| 8 | `TrackAggregator` uses `list.pop(0)` (O(n)) | `anpr_pipeline.py:39` | Shifts list on every OCR result |

---

### HIGH — Architecture

| # | Issue | File | Impact |
|---|-------|------|--------|
| 9 | Controller plate-list DB query blocks channel thread | `container.py:131`, `service.py:150` | Stalls frame reading by 1–10 ms per event |
| 10 | `PUT /api/settings` restarts all channels incl. model reload | `routers/settings.py:67` | 2–5 second outage per settings save (even for UI theme change) |

---

### MEDIUM

| # | Issue |
|---|-------|
| 11 | `reconnect_config` fetched under lock on every frame iteration |
| 12 | JPEG preview encoded every frame even with no active viewers |
| 13 | `ChannelConfigPayload.detection_mode` default `"motion"` vs runtime default `"always"` |
| 14 | `PlatePreprocessor` runs full pipeline on tiny crops (no minimum size guard) |
| 15 | `settings.py` router file also handles data export/retention routes (naming mismatch) |

---

### LOW / Safe to Remove

| # | Issue |
|---|-------|
| 16 | `CRNNRecognizer.recognize()` — dead code, never called |
| 17 | `TrackAggregator.clear_last()` — dead code, never called |
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
