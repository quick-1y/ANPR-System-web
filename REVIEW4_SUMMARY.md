# REVIEW #4 — Executive Summary

**Date:** 2026-03-28 | **Review scope:** Full architecture, naming, unused code, performance, pipeline

---

## Overall Quality: Good (7/10)

The codebase has improved significantly since R3 (2026-03-24). Key R3 issues are fixed:
- DB connection pooling implemented (psycopg_pool)
- Auth timing attack fixed (secrets.compare_digest)
- Reconnect config caching added (30s TTL)
- Overlay polling conditionally started

## Top 5 Findings

| # | Finding | Severity | Impact |
|---|---------|----------|--------|
| 1 | ~~YOLO model duplicated per channel (50-200MB each)~~ ✅ Fixed | High | Memory waste, potential GPU VRAM exhaustion |
| 2 | Monolithic app.js (3138 lines, no modules) ⏳ In progress since 2026-03-30 (step 1: API/auth extracted to `app/web/js/api.js`; step 2: state extracted to `app/web/js/state.js`) | High | Maintenance bottleneck, untestable |
| 3 | ~~Blocking .result() on screenshot I/O in processing loop~~ ✅ Fixed | Medium | Adds 5-10ms latency per event |
| 4 | ~~Direction computed for finalized tracks (wasted CPU)~~ ✅ Fixed | Medium | Unnecessary numpy ops every frame |
| 5 | ~~SettingsManager has 14 pass-through delegation methods~~ ✅ Fixed | Medium | Code confusion, doubled API surface |

## Statistics

- **Architecture issues:** 6
- **Naming issues:** 2
- **Unused code items:** 5 safe to remove, 4 need verification
- **Refactoring candidates:** 8
- **Performance risks:** 6
- **CPU optimization opportunities:** 5
- **Independent tasks:** 15

## Reports

| File | Content |
|------|---------|
| `REVIEW4_FULL.md` | Complete report with all sections, evidence, and recommendations |
| `REVIEW4_TASKS.md` | 15 independent implementation tasks with risk levels |
| `REVIEW4_CLEANUP.md` | Cleanup candidate tables (safe/verify/refactor) |
| `REVIEW4_SUMMARY.md` | This file |


## Task 15 update (2026-03-30)

- Status: **in progress**.
- Completed incremental sub-steps:
  - Step 1: extracted API layer (fetch wrapper + auth helpers) from `app/web/app.js` into `app/web/js/api.js`.
  - Step 2: extracted shared state object into `app/web/js/state.js` and wired import in `app/web/app.js`.
- `app/web/index.html` uses module script loading; full split into feature modules is not done yet.
