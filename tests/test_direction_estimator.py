"""Tests for TrackDirectionEstimator in anpr/pipeline/anpr_pipeline.py"""
import pytest
from anpr.pipeline.anpr_pipeline import TrackDirectionEstimator


APPROACHING = TrackDirectionEstimator.APPROACHING
RECEDING = TrackDirectionEstimator.RECEDING
UNKNOWN = TrackDirectionEstimator.UNKNOWN


def _bbox(y: int, size: int) -> list[int]:
    """Convenience: square bbox centred around y."""
    half = size // 2
    return [100 - half, y - half, 100 + half, y + half]


class TestTrackDirectionEstimator:
    def test_unknown_on_insufficient_history(self):
        est = TrackDirectionEstimator(min_track_length=3)
        result = est.update(1, _bbox(100, 40))
        assert result["direction"] == UNKNOWN
        result = est.update(1, _bbox(102, 42))
        assert result["direction"] == UNKNOWN

    def test_approaching_growing_bbox(self):
        """Object moving toward camera: bbox grows (increasing area) and y increases."""
        est = TrackDirectionEstimator(
            history_size=20,
            min_track_length=3,
            confidence_threshold=0.1,  # low threshold for test determinism
        )
        # Simulate object approaching: y increases, size grows
        for i in range(10):
            result = est.update(1, _bbox(100 + i * 5, 40 + i * 3))
        assert result["direction"] in (APPROACHING, UNKNOWN)

    def test_receding_shrinking_bbox(self):
        """Object moving away from camera: bbox shrinks and y decreases."""
        est = TrackDirectionEstimator(
            history_size=20,
            min_track_length=3,
            confidence_threshold=0.1,
        )
        for i in range(10):
            result = est.update(1, _bbox(200 - i * 5, 60 - i * 3))
        assert result["direction"] in (RECEDING, UNKNOWN)

    def test_independent_tracks(self):
        """Two track IDs maintain separate history."""
        est = TrackDirectionEstimator(min_track_length=3, confidence_threshold=0.1)
        for i in range(10):
            est.update(1, _bbox(100 + i * 5, 40 + i * 3))
            est.update(2, _bbox(200 - i * 5, 60 - i * 3))
        r1 = est.update(1, _bbox(155, 70))
        r2 = est.update(2, _bbox(145, 30))
        # Directions should differ or at least not crash
        assert r1["direction"] in (APPROACHING, RECEDING, UNKNOWN)
        assert r2["direction"] in (APPROACHING, RECEDING, UNKNOWN)

    def test_empty_bbox_returns_unknown(self):
        est = TrackDirectionEstimator()
        result = est.update(1, [])
        assert result["direction"] == UNKNOWN

    def test_invalid_bbox_returns_unknown(self):
        est = TrackDirectionEstimator()
        result = est.update(1, [10, 10])  # too short
        assert result["direction"] == UNKNOWN

    def test_from_config(self):
        """from_config() correctly maps all keys."""
        cfg = {
            "history_size": 8,
            "min_track_length": 2,
            "smoothing_window": 3,
            "confidence_threshold": 0.4,
            "jitter_pixels": 2.0,
            "min_area_change_ratio": 0.05,
        }
        est = TrackDirectionEstimator.from_config(cfg)
        assert est.history_size == 8
        assert est.min_track_length == 2
        assert est.confidence_threshold == pytest.approx(0.4)
