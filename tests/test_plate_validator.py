"""Tests for PlatePostProcessor in anpr/postprocessing/validator.py

These tests build CountryConfig objects in-memory so no YAML files are required.
"""
import re
import pytest
from anpr.postprocessing.country_config import (
    CountryConfig,
    CountryConfigLoader,
    CorrectionRules,
    PlateFormat,
)
from anpr.postprocessing.validator import PlatePostProcessor


# ---------------------------------------------------------------------------
# Helpers: build minimal in-memory configs
# ---------------------------------------------------------------------------

def _ru_format(name: str, regex: str) -> PlateFormat:
    return PlateFormat(name=name, regex=regex, pattern=re.compile(regex))


def _ru_country() -> CountryConfig:
    """Minimal Russia-like config with one standard format А000АА77."""
    return CountryConfig(
        name="Russia",
        code="RU",
        priority=1,
        formats=[_ru_format("standard", r"[АВЕКМНОРСТУХ]\d{3}[АВЕКМНОРСТУХ]{2}\d{2,3}")],
        valid_letters="АВЕКМНОРСТУХ",
        valid_digits="0123456789",
        corrections=CorrectionRules(
            digit_to_letter={"0": "О"},
            letter_to_digit={},
            common_mistakes=[{"from": "I", "to": "1"}],
        ),
        stop_words=["СТОП"],
        invalid_sequences=["000"],
    )


def _processor_with_ru() -> PlatePostProcessor:
    class _InlineLoader(CountryConfigLoader):
        def __init__(self, configs):
            self._configs = configs

        def load(self, enabled_codes=None):
            return self._configs

    loader = _InlineLoader([_ru_country()])
    return PlatePostProcessor(loader)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_strips_non_alphanumeric(self):
        result = PlatePostProcessor._normalize("А-123 ВС 77")
        assert result == "А123ВС77"

    def test_uppercase(self):
        assert PlatePostProcessor._normalize("а123вс77") == "А123ВС77"

    def test_yo_to_ye(self):
        assert "Ё" not in PlatePostProcessor._normalize("ЁABCЁ")

    def test_empty_string(self):
        assert PlatePostProcessor._normalize("") == ""


# ---------------------------------------------------------------------------
# No countries configured → always valid
# ---------------------------------------------------------------------------

class TestNoCountries:
    def test_always_valid_when_no_countries(self):
        class _EmptyLoader(CountryConfigLoader):
            def __init__(self):
                pass
            def load(self, enabled_codes=None):
                return []

        proc = PlatePostProcessor(_EmptyLoader())
        result = proc.process("ANYTHING123")
        assert result.is_valid is True
        assert result.country is None


# ---------------------------------------------------------------------------
# Russia config
# ---------------------------------------------------------------------------

class TestRussiaConfig:
    def setup_method(self):
        self.proc = _processor_with_ru()

    def test_valid_standard_plate(self):
        result = self.proc.process("А123ВС77")
        assert result.is_valid is True
        assert result.country == "RU"
        assert result.plate == "А123ВС77"

    def test_valid_plate_three_digit_region(self):
        result = self.proc.process("В456КМ199")
        assert result.is_valid is True

    def test_invalid_format(self):
        result = self.proc.process("123456")
        assert result.is_valid is False

    def test_stop_word_rejected(self):
        result = self.proc.process("СТОП")
        assert result.is_valid is False

    def test_invalid_sequence_rejected(self):
        # "000" in the plate triggers the invalid sequence check
        result = self.proc.process("А000ВС77")
        # After normalization "А000ВС77" contains "000"
        assert result.is_valid is False

    def test_digit_to_letter_correction(self):
        # "0" should be corrected to "О" before matching
        raw = "А1230ВС77".replace("0", "0")  # contains literal digit 0 in letter position
        # Build a plate where the region has a 0 that should become О: А123ВС770 → correction turns trailing 0 to О for letter positions
        # Use a simpler case: "0" at start should be corrected to "О"
        result = self.proc.process("0123ВС77")
        # After correction: "О123ВС77" — should match standard format
        assert result.is_valid is True
        assert result.plate == "О123ВС77"

    def test_normalization_applied_before_validation(self):
        # Input with spaces and lowercase
        result = self.proc.process("а 123 вс 77")
        assert result.is_valid is True
        assert result.plate == "А123ВС77"

    def test_original_preserved_in_result(self):
        raw = "  А123ВС77  "
        result = self.proc.process(raw)
        assert result.original == raw

    def test_invalid_chars_rejected(self):
        # Plate with characters not in valid_letters
        result = self.proc.process("Z123ВС77")
        assert result.is_valid is False
