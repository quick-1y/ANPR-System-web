"""Tests for common/cors.py's CORS_ALLOWED_ORIGINS parsing (finding #5).

Kept separate from app/api/main.py (which wires this into CORSMiddleware)
so it's testable without importing the full API stack (torch/cv2/FastAPI).
"""
from __future__ import annotations

from common.cors import parse_cors_allowed_origins


class TestParseCorsAllowedOrigins:
    def test_none_yields_empty_list(self):
        """Unset CORS_ALLOWED_ORIGINS — the secure default — allows no
        cross-origin browser access."""
        assert parse_cors_allowed_origins(None) == []

    def test_empty_string_yields_empty_list(self):
        assert parse_cors_allowed_origins("") == []

    def test_single_origin(self):
        assert parse_cors_allowed_origins("https://dash.example.com") == ["https://dash.example.com"]

    def test_multiple_origins_comma_separated(self):
        result = parse_cors_allowed_origins("https://a.example.com,https://b.example.org")
        assert result == ["https://a.example.com", "https://b.example.org"]

    def test_whitespace_around_origins_is_stripped(self):
        result = parse_cors_allowed_origins(" https://a.example.com , https://b.example.org ")
        assert result == ["https://a.example.com", "https://b.example.org"]

    def test_trailing_comma_does_not_produce_empty_entry(self):
        assert parse_cors_allowed_origins("https://a.example.com,") == ["https://a.example.com"]

    def test_blank_and_whitespace_only_entries_are_dropped(self):
        result = parse_cors_allowed_origins("https://a.example.com,, ,https://b.example.com")
        assert result == ["https://a.example.com", "https://b.example.com"]

    def test_explicit_wildcard_is_passed_through(self):
        """An operator can still opt back into permissive CORS explicitly —
        this just isn't the default anymore."""
        assert parse_cors_allowed_origins("*") == ["*"]

    def test_whitespace_only_string_yields_empty_list(self):
        assert parse_cors_allowed_origins("   ") == []
