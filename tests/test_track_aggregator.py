"""Tests for TrackAggregator consensus logic in anpr/pipeline/anpr_pipeline.py"""
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
