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

def _make_format(name: str, regex: str, display_format: str = "") -> PlateFormat:
    return PlateFormat(name=name, regex=regex, pattern=re.compile(regex), display_format=display_format)


def _ru_country() -> CountryConfig:
    """Minimal Russia-like config with one standard format А000АА77."""
    return CountryConfig(
        name="Russia",
        code="RU",
        priority=1,
        formats=[_make_format("standard", r"([АВЕКМНОРСТУХ])(\d{3})([АВЕКМНОРСТУХ]{2})(\d{2,3})", "{0} {1} {2} {3}")],
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


def _ua_country() -> CountryConfig:
    """Minimal Ukraine-like config."""
    return CountryConfig(
        name="Ukraine",
        code="UA",
        priority=2,
        formats=[_make_format("standard", r"([ABCEHIKMOPTX]{2})(\d{4})([ABCEHIKMOPTX]{2})", "{0} {1} {2}")],
        valid_letters="ABCEHIKMOPTX",
        valid_digits="0123456789",
        corrections=CorrectionRules(),
        stop_words=[],
        invalid_sequences=[],
    )


def _inline_loader(configs):
    class _InlineLoader(CountryConfigLoader):
        def __init__(self, cfgs):
            self._cfgs = cfgs

        def load(self, enabled_codes=None):
            return self._cfgs

    return _InlineLoader(configs)


def _processor_with_ru() -> PlatePostProcessor:
    return PlatePostProcessor(_inline_loader([_ru_country()]))


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


# ---------------------------------------------------------------------------
# Display formatting
# ---------------------------------------------------------------------------

class TestDisplayFormat:
    def test_russia_standard_display(self):
        proc = _processor_with_ru()
        result = proc.process("А123ВС77")
        assert result.is_valid is True
        assert result.plate == "А123ВС77"
        assert result.plate_display == "А 123 ВС 77"

    def test_russia_three_digit_region_display(self):
        proc = _processor_with_ru()
        result = proc.process("В456КМ199")
        assert result.is_valid is True
        assert result.plate_display == "В 456 КМ 199"

    def test_ukraine_standard_display(self):
        proc = PlatePostProcessor(_inline_loader([_ua_country()]))
        result = proc.process("AX1234BK")
        assert result.is_valid is True
        assert result.country == "UA"
        assert result.plate == "AX1234BK"
        assert result.plate_display == "AX 1234 BK"

    def test_no_display_format_returns_none(self):
        """When a format has no display_format, plate_display should be None."""
        country = CountryConfig(
            name="Test",
            code="XX",
            priority=1,
            formats=[_make_format("basic", r"([A-Z]{2})(\d{4})")],  # no display_format
            valid_letters="ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            valid_digits="0123456789",
            corrections=CorrectionRules(),
            stop_words=[],
            invalid_sequences=[],
        )
        proc = PlatePostProcessor(_inline_loader([country]))
        result = proc.process("AB1234")
        assert result.is_valid is True
        assert result.plate_display is None

    def test_invalid_plate_has_no_display(self):
        proc = _processor_with_ru()
        result = proc.process("INVALID")
        assert result.is_valid is False
        assert result.plate_display is None

    def test_corrected_plate_display(self):
        """Correction produces a new candidate; display_format should apply to it."""
        proc = _processor_with_ru()
        result = proc.process("0123ВС77")
        assert result.is_valid is True
        assert result.plate == "О123ВС77"
        assert result.plate_display == "О 123 ВС 77"

    def test_multi_country_display(self):
        """When multiple countries are loaded, the matched one provides formatting."""
        proc = PlatePostProcessor(_inline_loader([_ru_country(), _ua_country()]))
        # This should match Ukraine (not Russia) because the format is XX0000XX
        result = proc.process("AX1234BK")
        assert result.country == "UA"
        assert result.plate_display == "AX 1234 BK"


# ---------------------------------------------------------------------------
# YAML loading with display_format
# ---------------------------------------------------------------------------

class TestYAMLDisplayFormat:
    def test_loader_parses_display_format(self, tmp_path):
        yaml_content = (
            'name: "TestCountry"\n'
            'code: "TC"\n'
            'priority: 1\n'
            'license_plate_formats:\n'
            '  - name: "std"\n'
            '    regex: "^([A-Z]{2})(\\\\d{4})$"\n'
            '    display_format: "{0}-{1}"\n'
            'valid_characters:\n'
            '  letters: "ABCDEFGHIJKLMNOPQRSTUVWXYZ"\n'
            '  digits: "0123456789"\n'
        )
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")
        loader = CountryConfigLoader(str(tmp_path))
        configs = loader.load()
        assert len(configs) == 1
        assert configs[0].formats[0].display_format == "{0}-{1}"

    def test_loader_missing_display_format(self, tmp_path):
        yaml_content = (
            'name: "TestCountry"\n'
            'code: "TC"\n'
            'priority: 1\n'
            'license_plate_formats:\n'
            '  - name: "std"\n'
            '    regex: "^([A-Z]{2})(\\\\d{4})$"\n'
            'valid_characters:\n'
            '  letters: "ABCDEFGHIJKLMNOPQRSTUVWXYZ"\n'
            '  digits: "0123456789"\n'
        )
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")
        loader = CountryConfigLoader(str(tmp_path))
        configs = loader.load()
        assert configs[0].formats[0].display_format == ""
