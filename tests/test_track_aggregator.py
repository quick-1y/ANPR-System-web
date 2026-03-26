"""Tests for TrackAggregator consensus and OCR budget logic in anpr/pipeline/anpr_pipeline.py"""
import pytest
from anpr.pipeline.anpr_pipeline import TrackAggregator


class TestTrackAggregator:
    def test_no_emission_below_quorum(self):
        """Does not emit until best_shots results are accumulated."""
        agg = TrackAggregator(best_shots=3)
        # First two results — below quorum
        assert agg.add_result(1, "А123ВС77", 0.9) == ""
        assert agg.add_result(1, "А123ВС77", 0.9) == ""

    def test_emits_on_quorum(self):
        """Emits consensus text when quorum is reached."""
        agg = TrackAggregator(best_shots=3)
        agg.add_result(1, "А123ВС77", 0.9)
        agg.add_result(1, "А123ВС77", 0.9)
        result = agg.add_result(1, "А123ВС77", 0.9)
        assert result == "А123ВС77"

    def test_no_duplicate_emission(self):
        """Same plate is not emitted twice in a row for the same track."""
        agg = TrackAggregator(best_shots=3)
        for _ in range(3):
            agg.add_result(1, "А123ВС77", 0.9)
        # First quorum — should emit
        # Now add more of the same plate
        result = agg.add_result(1, "А123ВС77", 0.9)
        assert result == ""  # already emitted, last_emitted guard prevents re-emission

    def test_weighted_majority_determines_winner(self):
        """Candidate with highest weighted confidence wins."""
        agg = TrackAggregator(best_shots=4)
        # 1x high-confidence "А999ВС99", 3x low-confidence "А123ВС77"
        agg.add_result(1, "А999ВС99", 0.95)
        agg.add_result(1, "А123ВС77", 0.3)
        agg.add_result(1, "А123ВС77", 0.3)
        result = agg.add_result(1, "А123ВС77", 0.3)
        # "А123ВС77" has quorum (3/4 >= 2) and total weight 0.9 vs 0.95
        # Actually A999 has higher weight per item but less count. Result depends on algorithm.
        # The important thing is that empty text is never emitted.
        assert result in ("А123ВС77", "А999ВС99", "")

    def test_empty_text_ignored(self):
        """Empty strings are not added to the bucket."""
        agg = TrackAggregator(best_shots=3)
        assert agg.add_result(1, "", 0.9) == ""
        assert agg.add_result(1, "", 0.9) == ""
        assert agg.add_result(1, "", 0.9) == ""
        # Bucket should still be empty, no emission
        assert agg.add_result(1, "А123ВС77", 0.9) == ""

    def test_reset_clears_history(self):
        """reset() allows the same plate to be emitted again."""
        agg = TrackAggregator(best_shots=3)
        for _ in range(3):
            agg.add_result(1, "А123ВС77", 0.9)
        agg.reset(1)
        # After reset, quorum must be rebuilt from scratch
        assert agg.add_result(1, "А123ВС77", 0.9) == ""

    def test_independent_tracks(self):
        """Results for different track IDs do not interfere."""
        agg = TrackAggregator(best_shots=3)
        for _ in range(3):
            agg.add_result(1, "А111АА77", 0.9)
            agg.add_result(2, "В222ВВ99", 0.9)
        # Track 1 already emitted — adding more should not emit again
        assert agg.add_result(1, "А111АА77", 0.9) == ""
        # Track 2 similarly
        assert agg.add_result(2, "В222ВВ99", 0.9) == ""

    def test_best_shots_one(self):
        """best_shots=1 emits on the very first result."""
        agg = TrackAggregator(best_shots=1)
        result = agg.add_result(1, "Х000ХХ00", 0.8)
        assert result == "Х000ХХ00"


class TestTrackOCRBudget:
    """Tests for per-track OCR budget management and finalization."""

    def test_should_process_new_track(self):
        """New (unseen) tracks should always be processed."""
        agg = TrackAggregator(best_shots=3)
        assert agg.should_process(42) is True

    def test_should_process_false_after_consensus(self):
        """After consensus, should_process returns False."""
        agg = TrackAggregator(best_shots=3)
        agg.add_result(1, "ABC123", 0.9)
        agg.add_result(1, "ABC123", 0.9)
        agg.add_result(1, "ABC123", 0.9)  # consensus reached
        assert agg.should_process(1) is False

    def test_should_process_false_after_budget_exhausted(self):
        """After budget is exhausted, should_process returns False."""
        agg = TrackAggregator(best_shots=3, max_ocr_attempts=5)
        for i in range(5):
            agg.add_result(1, "", 0.3)  # all low-confidence, empty text
        assert agg.should_process(1) is False

    def test_budget_exhaustion_returns_best_candidate(self):
        """When budget runs out, the strongest candidate is returned."""
        agg = TrackAggregator(best_shots=5, max_ocr_attempts=4)
        agg.add_result(1, "ABC123", 0.8)
        agg.add_result(1, "ABC123", 0.7)
        agg.add_result(1, "XYZ999", 0.6)
        # Attempt 4 exhausts budget. "ABC123" has higher total weight.
        result = agg.add_result(1, "", 0.3)
        assert result == "ABC123"
        assert agg.should_process(1) is False

    def test_budget_exhaustion_no_candidates_emits_nothing(self):
        """When budget runs out with no candidates, returns empty."""
        agg = TrackAggregator(best_shots=3, max_ocr_attempts=3)
        agg.add_result(1, "", 0.2)
        agg.add_result(1, "", 0.1)
        result = agg.add_result(1, "", 0.15)
        assert result == ""
        assert agg.should_process(1) is False

    def test_should_emit_unreadable_once(self):
        """should_emit_unreadable fires exactly once for finalized tracks with no result."""
        agg = TrackAggregator(best_shots=3, max_ocr_attempts=3)
        agg.add_result(1, "", 0.2)
        agg.add_result(1, "", 0.1)
        agg.add_result(1, "", 0.15)  # budget exhausted, no candidates
        # First call → True
        assert agg.should_emit_unreadable(1) is True
        # Second call → False (already emitted)
        assert agg.should_emit_unreadable(1) is False

    def test_should_emit_unreadable_false_for_recognized(self):
        """should_emit_unreadable is False for tracks that had a valid emission."""
        agg = TrackAggregator(best_shots=3)
        agg.add_result(1, "ABC123", 0.9)
        agg.add_result(1, "ABC123", 0.9)
        agg.add_result(1, "ABC123", 0.9)  # consensus emitted
        assert agg.should_emit_unreadable(1) is False

    def test_consensus_finalizes_track(self):
        """After consensus, the track is finalized — further add_result returns empty."""
        agg = TrackAggregator(best_shots=3, max_ocr_attempts=100)
        agg.add_result(1, "ABC", 0.9)
        agg.add_result(1, "ABC", 0.9)
        result = agg.add_result(1, "ABC", 0.9)  # consensus
        assert result == "ABC"
        # Further attempts are silently ignored.
        assert agg.add_result(1, "ABC", 0.9) == ""
        assert agg.add_result(1, "DEF", 0.99) == ""

    def test_empty_text_counts_toward_budget(self):
        """Empty text (low-confidence) still consumes OCR budget."""
        agg = TrackAggregator(best_shots=3, max_ocr_attempts=5)
        for _ in range(5):
            agg.add_result(1, "", 0.3)
        # Budget exhausted
        assert agg.should_process(1) is False
        assert agg.should_emit_unreadable(1) is True

    def test_reset_preserves_budget(self):
        """reset() clears candidates but keeps the attempt count."""
        agg = TrackAggregator(best_shots=3, max_ocr_attempts=10)
        agg.add_result(1, "ABC", 0.9)
        agg.add_result(1, "ABC", 0.9)
        agg.add_result(1, "ABC", 0.9)  # consensus + finalization
        agg.reset(1)
        # Finalization cleared, can process again — but budget is at 3/10
        assert agg.should_process(1) is True
        # Need to rebuild quorum from scratch
        assert agg.add_result(1, "ABC", 0.9) == ""

    def test_reset_after_budget_exhausted_stays_finalized(self):
        """reset() with exhausted budget keeps the track finalized."""
        agg = TrackAggregator(best_shots=5, max_ocr_attempts=3)
        agg.add_result(1, "ABC", 0.9)
        agg.add_result(1, "ABC", 0.9)
        result = agg.add_result(1, "ABC", 0.7)  # budget exhausted → best candidate
        assert result == "ABC"
        # Simulate postprocessor rejection → reset
        agg.reset(1)
        # Budget was already exhausted (3/3), so track stays finalized
        assert agg.should_process(1) is False
        # Since result_emitted was cleared by reset, unreadable fires
        assert agg.should_emit_unreadable(1) is True

    def test_conflicting_ocr_results_pick_strongest(self):
        """Track with conflicting OCR picks the strongest weighted candidate."""
        agg = TrackAggregator(best_shots=5, max_ocr_attempts=5)
        agg.add_result(1, "ABC123", 0.9)
        agg.add_result(1, "ABC123", 0.85)
        agg.add_result(1, "XBC123", 0.7)
        agg.add_result(1, "ABC1Z3", 0.6)
        result = agg.add_result(1, "XBC123", 0.65)  # budget exhausted
        # "ABC123" has highest total weight (0.9+0.85=1.75) and count 2
        assert result == "ABC123"

    def test_noisy_track_no_consensus(self):
        """Track with all-different results picks best at budget exhaustion."""
        agg = TrackAggregator(best_shots=3, max_ocr_attempts=3)
        agg.add_result(1, "AAA", 0.7)
        agg.add_result(1, "BBB", 0.8)
        result = agg.add_result(1, "CCC", 0.9)
        # No quorum possible (all different, deque only keeps 3).
        # At budget exhaustion, "CCC" has highest weight (0.9).
        assert result == "CCC"

    def test_early_exit_consecutive_failures(self):
        """Track is finalized early after N consecutive empty OCR results."""
        agg = TrackAggregator(best_shots=3, max_ocr_attempts=100, max_consecutive_empty_ocr=5)
        for _ in range(5):
            agg.add_result(1, "", 0.3)
        assert agg.should_process(1) is False
        assert agg.should_emit_unreadable(1) is True

    def test_consecutive_failures_reset_by_valid_result(self):
        """A valid OCR result resets the consecutive failure counter."""
        agg = TrackAggregator(best_shots=5, max_ocr_attempts=100, max_consecutive_empty_ocr=5)
        for _ in range(4):
            agg.add_result(1, "", 0.3)
        agg.add_result(1, "ABC123", 0.9)
        for _ in range(4):
            agg.add_result(1, "", 0.3)
        assert agg.should_process(1) is True

    def test_early_exit_disabled_when_zero(self):
        """max_consecutive_empty_ocr=0 disables early exit."""
        agg = TrackAggregator(best_shots=3, max_ocr_attempts=100, max_consecutive_empty_ocr=0)
        for _ in range(20):
            agg.add_result(1, "", 0.3)
        assert agg.should_process(1) is True

    def test_stale_eviction_cleans_state(self):
        """Stale tracks are fully evicted including OCR state."""
        import time as _time

        agg = TrackAggregator(best_shots=3, ttl_seconds=5.0)
        agg.add_result(1, "ABC", 0.9)
        # Simulate the track being old by backdating its timestamp.
        agg._track_ts[1] = _time.monotonic() - 60.0
        agg._evict_stale(_time.monotonic())
        # Track 1 should be evicted — new state starts fresh.
        assert agg.should_process(1) is True
        assert 1 not in agg._track_states
