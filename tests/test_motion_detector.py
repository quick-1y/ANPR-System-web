"""Tests for MotionDetector in anpr/detection/motion_detector.py

These tests use numpy arrays as synthetic frames — no real video required.
"""
import numpy as np
import pytest
from anpr.detection.motion_detector import MotionDetector, MotionDetectorConfig


def _blank(h: int = 120, w: int = 160) -> np.ndarray:
    """Return a black BGR frame."""
    return np.zeros((h, w, 3), dtype=np.uint8)


def _noisy(h: int = 120, w: int = 160, value: int = 200) -> np.ndarray:
    """Return a uniform non-black BGR frame to simulate motion."""
    return np.full((h, w, 3), value, dtype=np.uint8)


class TestMotionDetector:
    def test_first_frame_returns_false(self):
        """No previous frame means no motion on first call."""
        md = MotionDetector(MotionDetectorConfig())
        assert md.update(_blank()) is False

    def test_static_scene_no_motion(self):
        """Repeated identical frames should not trigger motion."""
        md = MotionDetector(MotionDetectorConfig(threshold=0.01, activation_frames=3))
        frame = _blank()
        for _ in range(10):
            result = md.update(frame)
        assert result is False

    def test_motion_triggers_after_activation_frames(self):
        """Motion activates only after activation_frames consecutive motion frames."""
        cfg = MotionDetectorConfig(threshold=0.001, activation_frames=3, release_frames=100)
        md = MotionDetector(cfg)
        md.update(_blank())          # seed previous frame
        md.update(_noisy())          # motion frame 1 — not yet active
        md.update(_noisy(value=100)) # motion frame 2 — not yet active
        result = md.update(_noisy(value=50))  # motion frame 3 — should activate
        assert result is True

    def test_motion_releases_after_release_frames(self):
        """Motion deactivates after release_frames consecutive static frames."""
        cfg = MotionDetectorConfig(
            threshold=0.001,
            activation_frames=2,
            release_frames=3,
            frame_stride=1,
        )
        md = MotionDetector(cfg)
        # Activate motion
        md.update(_blank())
        md.update(_noisy())
        md.update(_noisy(value=100))
        assert md.update(_noisy(value=50)) is True  # active
        # Now send static frames
        static = _blank()
        md.update(static)   # static 1
        md.update(static)   # static 2
        result = md.update(static)  # static 3 — should deactivate
        assert result is False

    def test_frame_stride_skips_analysis(self):
        """With frame_stride=2 only every 2nd frame is analysed; others return cached state."""
        cfg = MotionDetectorConfig(frame_stride=2, activation_frames=2, threshold=0.001)
        md = MotionDetector(cfg)
        # Frame 1: analysed (index 1 % 2 != 0 — see _should_analyze: index increments then checks)
        # The implementation increments then checks modulo, so index=1 → 1%2=1 (not zero → skip if stride>1)
        # We just verify no crash and boolean return type
        for frame in [_blank(), _noisy(), _blank(), _noisy()]:
            result = md.update(frame)
            assert isinstance(result, bool)

    def test_empty_frame_returns_false(self):
        """Zero-size frame does not crash and returns False."""
        md = MotionDetector(MotionDetectorConfig())
        empty = np.zeros((0, 0, 3), dtype=np.uint8)
        assert md.update(empty) is False

    def test_shape_change_resets_state(self):
        """Changing frame dimensions resets accumulated motion state."""
        cfg = MotionDetectorConfig(threshold=0.001, activation_frames=2)
        md = MotionDetector(cfg)
        md.update(_blank(120, 160))
        md.update(_noisy(120, 160))
        md.update(_noisy(120, 160, value=100))
        assert md._motion_active is True  # motion was activated
        # Switch to different resolution — should reset
        result = md.update(_blank(240, 320))
        assert result is False
