"""Tests for ANPRPipeline's plate cooldown observability (finding #10).

_on_cooldown() previously suppressed duplicate detections silently, with no
way to notice from logs whether the cooldown window was misconfigured (too
long/short) or firing unexpectedly. These tests exercise _on_cooldown/
_touch_plate directly rather than the full process_frame path — cooldown
logic only touches self.cooldown_seconds/self._last_seen, so a no-op
recognizer stub is enough to construct a pipeline without any real OCR work.
"""
from __future__ import annotations

import logging
import time

from anpr.pipeline.anpr_pipeline import ANPRPipeline

_LOGGER_NAME = "anpr.pipeline.anpr_pipeline"


class _NoOpRecognizer:
    def recognize_batch(self, plate_images):
        return []


def _make_pipeline(cooldown_seconds: int) -> ANPRPipeline:
    return ANPRPipeline(_NoOpRecognizer(), best_shots=1, cooldown_seconds=cooldown_seconds)


class TestCooldownSuppressionLogging:
    def test_suppressed_plate_is_logged_at_debug(self, caplog):
        pipeline = _make_pipeline(cooldown_seconds=5)
        pipeline._touch_plate("A123BC77")

        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            on_cooldown = pipeline._on_cooldown("A123BC77")

        assert on_cooldown is True
        assert any("cooldown" in r.message.lower() and "A123BC77" in r.message for r in caplog.records)

    def test_new_plate_is_not_logged(self, caplog):
        pipeline = _make_pipeline(cooldown_seconds=5)

        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            on_cooldown = pipeline._on_cooldown("NEVER_SEEN")

        assert on_cooldown is False
        assert not caplog.records

    def test_plate_seen_after_window_elapses_is_not_logged(self, caplog):
        pipeline = _make_pipeline(cooldown_seconds=5)
        pipeline._last_seen["A123BC77"] = time.monotonic() - 10  # older than the 5s window

        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            on_cooldown = pipeline._on_cooldown("A123BC77")

        assert on_cooldown is False
        assert not any("подавлен" in r.message for r in caplog.records)

    def test_stale_cooldown_entries_are_pruned_and_logged(self, caplog):
        pipeline = _make_pipeline(cooldown_seconds=5)
        # Stale threshold is cooldown_seconds * 2 = 10s.
        pipeline._last_seen["OLD_PLATE"] = time.monotonic() - 20

        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            pipeline._on_cooldown("SOME_OTHER_PLATE")

        assert "OLD_PLATE" not in pipeline._last_seen
        assert any("устаревших записей cooldown" in r.message for r in caplog.records)
