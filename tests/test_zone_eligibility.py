"""Tests for ChannelProcessor._resolve_zone_eligibility

Covers all list_filter_mode branches and blacklist guard:
  - all mode: non-blacklisted is eligible
  - all mode: blacklisted is not eligible
  - whitelist mode: whitelisted plate is eligible
  - whitelist mode: plate not in whitelist is not eligible
  - custom mode: plate in specified lists is eligible
  - custom mode: plate not in specified lists is not eligible
  - no lists_db: always eligible (treat as "all")
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

# cv2 and numpy are heavy native deps not available in the unit-test env.
# Stub them before importing channel_runtime so the module-level imports succeed.
_cv2_stub = types.ModuleType("cv2")
_cv2_stub.VideoCapture = MagicMock
_cv2_stub.pointPolygonTest = MagicMock(return_value=1.0)
_cv2_stub.imencode = MagicMock(return_value=(True, b""))
_cv2_stub.imwrite = MagicMock(return_value=True)
_cv2_stub.CAP_PROP_OPEN_TIMEOUT_MSEC = 0
_cv2_stub.CAP_PROP_READ_TIMEOUT_MSEC = 0
_cv2_stub.IMWRITE_JPEG_QUALITY = 1
sys.modules.setdefault("cv2", _cv2_stub)

_np_stub = types.ModuleType("numpy")
_np_stub.array = MagicMock(return_value=[])
_np_stub.int32 = int
sys.modules.setdefault("numpy", _np_stub)

from runtime.channel_runtime import ChannelProcessor  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: build a minimal ChannelProcessor with controlled lists_db
# ---------------------------------------------------------------------------

def _make_processor(
    black: list[str] | None = None,
    white: list[str] | None = None,
    list_members: dict[int, list[str]] | None = None,
    lists_db=True,
) -> ChannelProcessor:
    """
    Create a ChannelProcessor bypassing __init__, with a mocked lists_db.

    black:        plates treated as blacklisted
    white:        plates treated as whitelisted
    list_members: {list_id: [plates]} for custom-mode membership
    lists_db:     if False, _lists_db is set to None (no-list-db path)
    """
    processor = object.__new__(ChannelProcessor)

    if not lists_db:
        processor._lists_db = None
        return processor

    mock_db = MagicMock()

    black_set = set(black or [])
    white_set = set(white or [])
    members: dict[int, set[str]] = {k: set(v) for k, v in (list_members or {}).items()}

    def plate_in_list_type(plate: str, list_type: str) -> bool:
        if list_type == "black":
            return plate in black_set
        if list_type == "white":
            return plate in white_set
        return False

    def plate_in_lists(plate: str, list_ids: list[int]) -> bool:
        for lid in list_ids:
            if plate in members.get(lid, set()):
                return True
        return False

    mock_db.plate_in_list_type.side_effect = plate_in_list_type
    mock_db.plate_in_lists.side_effect = plate_in_lists
    processor._lists_db = mock_db
    return processor


def _channel(mode: str = "all", list_ids: list | None = None) -> dict:
    return {
        "list_filter_mode": mode,
        "list_filter_list_ids": list_ids or [],
    }


# ---------------------------------------------------------------------------
# mode: all
# ---------------------------------------------------------------------------

class TestAllMode:
    def test_non_blacklisted_is_eligible(self):
        p = _make_processor(black=[])
        assert p._resolve_zone_eligibility(_channel("all"), "A123BC") is True

    def test_blacklisted_is_not_eligible(self):
        p = _make_processor(black=["A123BC"])
        assert p._resolve_zone_eligibility(_channel("all"), "A123BC") is False

    def test_unknown_plate_is_eligible_in_all_mode(self):
        p = _make_processor()
        assert p._resolve_zone_eligibility(_channel("all"), "UNKNOWN") is True


# ---------------------------------------------------------------------------
# mode: whitelist
# ---------------------------------------------------------------------------

class TestWhitelistMode:
    def test_whitelisted_is_eligible(self):
        p = _make_processor(white=["A123BC"])
        assert p._resolve_zone_eligibility(_channel("whitelist"), "A123BC") is True

    def test_not_in_whitelist_is_not_eligible(self):
        p = _make_processor(white=["X999YZ"])
        assert p._resolve_zone_eligibility(_channel("whitelist"), "A123BC") is False

    def test_blacklisted_is_not_eligible_even_if_whitelisted(self):
        # Blacklist check comes first
        p = _make_processor(black=["A123BC"], white=["A123BC"])
        assert p._resolve_zone_eligibility(_channel("whitelist"), "A123BC") is False


# ---------------------------------------------------------------------------
# mode: custom
# ---------------------------------------------------------------------------

class TestCustomMode:
    def test_in_custom_list_is_eligible(self):
        p = _make_processor(list_members={5: ["A123BC"], 6: ["X999YZ"]})
        assert p._resolve_zone_eligibility(_channel("custom", [5]), "A123BC") is True

    def test_not_in_custom_lists_is_not_eligible(self):
        p = _make_processor(list_members={5: ["X999YZ"]})
        assert p._resolve_zone_eligibility(_channel("custom", [5]), "A123BC") is False

    def test_in_one_of_multiple_lists_is_eligible(self):
        p = _make_processor(list_members={5: ["A123BC"], 6: ["B456DE"]})
        assert p._resolve_zone_eligibility(_channel("custom", [5, 6]), "B456DE") is True

    def test_empty_list_ids_not_eligible(self):
        p = _make_processor(list_members={5: ["A123BC"]})
        assert p._resolve_zone_eligibility(_channel("custom", []), "A123BC") is False

    def test_blacklisted_is_not_eligible_in_custom_mode(self):
        p = _make_processor(black=["A123BC"], list_members={5: ["A123BC"]})
        assert p._resolve_zone_eligibility(_channel("custom", [5]), "A123BC") is False


# ---------------------------------------------------------------------------
# no lists_db
# ---------------------------------------------------------------------------

class TestNoListsDb:
    def test_always_eligible_when_no_lists_db(self):
        p = _make_processor(lists_db=False)
        assert p._resolve_zone_eligibility(_channel("all"), "ANYONE") is True

    def test_always_eligible_in_whitelist_mode_with_no_lists_db(self):
        p = _make_processor(lists_db=False)
        assert p._resolve_zone_eligibility(_channel("whitelist"), "ANYONE") is True


# ---------------------------------------------------------------------------
# unknown / fallback mode
# ---------------------------------------------------------------------------

class TestFallbackMode:
    def test_unknown_mode_is_eligible(self):
        p = _make_processor()
        assert p._resolve_zone_eligibility(_channel("unknown_mode"), "A123BC") is True
