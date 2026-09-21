"""Channel defaults are declared once and every layer agrees with them
(roadmap task 3.1, problem P4, decisions 4.10 no. 1-3)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.api.schemas import (
    ChannelConfigPayload,
    ChannelFilterPayload,
    ChannelOCRPayload,
    InterfacePayload,
)
from config.registry import CHANNEL_PLATE_SIZES, CHANNEL_SPECS
from config.settings_schema import channel_defaults
from database import channel_repository
from database.channel_repository import ChannelDatabase, _normalize
from runtime.debug import DebugSettings

SCHEMA_SQL = Path(__file__).resolve().parent.parent / "database" / "postgres" / "schema.sql"
DEFAULTS = channel_defaults({})


def _ddl_defaults(sql: str) -> dict[str, str]:
    body = re.search(r"CREATE TABLE IF NOT EXISTS channels \((.*?)\n\s*\);", sql, re.DOTALL).group(1)
    result = {}
    for line in body.splitlines():
        m = re.match(r"\s*(\w+)\s+.*?DEFAULT\s+(.*?),?\s*$", line)
        if m:
            result[m.group(1)] = m.group(2)
    return result


def _ddl_value(raw: str):
    import json

    raw = raw.replace("::jsonb", "").strip()
    if raw.startswith("'"):
        text = raw[1:-1]
        try:
            return json.loads(text)
        except ValueError:
            return text
    if raw.upper() in ("TRUE", "FALSE"):
        return raw.upper() == "TRUE"
    return float(raw) if "." in raw else int(raw)


DDL = {k: _ddl_value(v) for k, v in _ddl_defaults(ChannelDatabase._SCHEMA).items()}
PAYLOAD = ChannelConfigPayload(name="c", source="rtsp://x")


@pytest.mark.parametrize("name", sorted(CHANNEL_SPECS))
def test_registry_pydantic_and_ddl_agree(name):
    expected = DEFAULTS[name]
    assert CHANNEL_SPECS[name].default == expected
    assert getattr(PAYLOAD, name) == expected
    assert DDL[name] == expected


@pytest.mark.parametrize("name", ["min_plate_size", "max_plate_size"])
def test_plate_sizes_agree_across_layers(name):
    expected = DEFAULTS[name]
    assert CHANNEL_PLATE_SIZES[name] == expected
    assert getattr(PAYLOAD, name).model_dump() == expected
    assert getattr(ChannelFilterPayload(list_filter_mode="all"), name) == expected
    assert DDL[name] == expected


def test_decision_values_from_section_4_10():
    assert DEFAULTS["motion_release_frames"] == 100
    assert DEFAULTS["max_plate_size"] == {"width": 400, "height": 100}


def test_channel_ddl_is_identical_in_schema_sql():
    assert _ddl_defaults(SCHEMA_SQL.read_text(encoding="utf-8")) == _ddl_defaults(ChannelDatabase._SCHEMA)


def test_row_fallbacks_use_the_shared_defaults():
    row = [None] * 31
    row[21] = None
    row[22] = None
    result = channel_repository._row_to_dict(row)
    assert result["max_plate_size"] == {"width": 400, "height": 100}
    assert result["min_plate_size"] == DEFAULTS["min_plate_size"]


def test_creating_a_channel_without_optional_fields_gives_registry_defaults():
    normalized = _normalize({"name": "gate", "source": "rtsp://x"})
    for name in CHANNEL_SPECS:
        assert normalized[name] == DEFAULTS[name], name
    assert normalized["max_plate_size"] == {"width": 400, "height": 100}


def test_ocr_payload_defaults_match():
    payload = ChannelOCRPayload()
    for name in ("best_shots", "cooldown_seconds", "ocr_min_confidence", "max_ocr_attempts", "max_consecutive_empty_ocr"):
        assert getattr(payload, name) == DEFAULTS[name]


def test_registry_bounds_are_enforced_by_pydantic():
    with pytest.raises(ValueError):
        ChannelConfigPayload(name="c", source="s", motion_release_frames=121)
    with pytest.raises(ValueError):
        ChannelConfigPayload(name="c", source="s", detection_mode="bogus")


def test_personal_debug_flags_default_to_off_and_are_not_server_settings():
    from app.api.schemas import DebugPayload
    from config.registry import get_spec

    assert get_spec("channel_metrics_visible").default is False
    assert get_spec("debug_panel_enabled").default is False
    assert set(DebugPayload.model_fields) == {"video_output_enabled"}
    assert set(DebugSettings.from_dict({}).to_dict()) == {"video_output_enabled"}
    assert DebugSettings().video_output_enabled is True


def test_interface_payload_defaults_follow_schema():
    from config.settings_schema import interface_defaults

    assert interface_defaults() == {"style": "graphite-minimal", "theme": "light"}
    payload = InterfacePayload()  # nothing is sent unless the admin changes it
    assert (payload.default_style, payload.default_theme, payload.display_timezone) == (None, None, None)


def test_registry_channel_keys_do_not_leak_into_app_settings():
    from config.registry import REGISTRY

    assert not [k for k in REGISTRY if k.startswith("channel.")]
