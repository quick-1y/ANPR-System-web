"""Enumerations have one owner (roadmap task 3.2, problem P14): the registry.
Every consumer — pydantic, normalizers, repositories, the API and the UI —
must derive its allowed values from it."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.api import schemas
from app.api.routers.settings import get_settings_schema
from config.registry import CHANNEL_SPECS, ENUMS, TIMEZONES, choices_pattern, schema_document, _valid_zone

WEB = Path(__file__).resolve().parent.parent / "app" / "web"


class TestSchemaDocument:
    def test_endpoint_returns_every_registry_enum(self):
        body = get_settings_schema(_user={"id": 1})
        assert set(body["enums"]) == set(ENUMS)
        for name, values in ENUMS.items():
            assert body["enums"][name] == list(values)

    def test_every_choices_of_the_registry_is_exposed(self):
        exposed = {tuple(v) for v in schema_document()["enums"].values()}
        for spec in CHANNEL_SPECS.values():
            if spec.choices is not None:
                assert tuple(spec.choices) in exposed, spec.key
        from config.registry import REGISTRY

        for spec in REGISTRY.values():
            if spec.choices is not None and not spec.reserved:
                assert tuple(spec.choices) in exposed, spec.key

    def test_timezones_are_valid_iana_identifiers(self):
        pytest.importorskip("tzdata")
        assert "UTC" in TIMEZONES
        for zone in TIMEZONES:
            assert _valid_zone(zone) == zone

    def test_endpoint_requires_authentication_only(self):
        import inspect

        from app.api.deps import get_current_user

        default = inspect.signature(get_settings_schema).parameters["_user"].default
        assert default.dependency is get_current_user


class TestPydanticFollowsRegistry:
    @pytest.mark.parametrize(
        "model, field, enum",
        [
            (schemas.LoggingPayload, "level", "log_level"),
            (schemas.RelayPayload, "mode", "relay_mode"),
            (schemas.ROIRegionPayload, "unit", "roi_unit"),
            (schemas.ChannelConfigPayload, "detection_mode", "detection_mode"),
            (schemas.ChannelConfigPayload, "controller_direction_filter", "controller_direction_filter"),
            (schemas.ChannelConfigPayload, "list_filter_mode", "list_filter_mode"),
            (schemas.ChannelConfigPayload, "zone_channel_type", "zone_channel_type"),
            (schemas.ChannelFilterPayload, "list_filter_mode", "list_filter_mode"),
        ],
    )
    def test_field_pattern_is_generated_from_the_enum(self, model, field, enum):
        info = model.model_fields[field]
        patterns = [m.pattern for m in info.metadata if hasattr(m, "pattern")]
        assert patterns == [choices_pattern(ENUMS[enum])]

    def test_unknown_value_is_rejected(self):
        with pytest.raises(ValidationError):
            schemas.LoggingPayload(level="LOUD", retention_days=1)


class TestNoHardcodedDomains:
    """A new theme/style/level must need a change in the registry only."""

    def test_python_sources_do_not_repeat_the_lists(self):
        root = WEB.parent.parent
        literals = [
            r'["\']graphite-minimal["\']\s*,\s*["\']aurora["\']',
            r'\|aurora\)',
            r'\(["\']light["\']\s*,\s*["\']dark["\']\)',
            r'ALL\|DEBUG',
            r'approaching["\']\s*,\s*["\']receding',
            r'pulse["\']\s*,\s*["\']pulse_timer',
        ]
        allowed = {"config/registry.py"}
        offenders = []
        for directory in ("app", "config", "database", "runtime", "controllers"):
            for path in (root / directory).rglob("*.py"):
                rel = path.relative_to(root).as_posix()
                if rel in allowed:
                    continue
                text = path.read_text(encoding="utf-8")
                for pattern in literals:
                    if re.search(pattern, text):
                        offenders.append((rel, pattern))
        assert not offenders, offenders

    def test_ui_selects_are_filled_from_the_schema_not_from_static_options(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        js = (WEB / "js" / "schema.js").read_text(encoding="utf-8")
        for select_id in re.findall(r'\["(\w+)",\s*"\w+"', js):
            match = re.search(r'<select[^>]*id="%s"[^>]*>(.*?)</select>' % select_id, html, re.DOTALL)
            assert match, f"{select_id} is not in index.html"
            static = re.findall(r'<option[^>]*>', match.group(1))
            allowed_static = [o for o in static if 'value=""' in o]
            assert static == allowed_static, f"{select_id} has hardcoded options: {static}"

    def test_schema_js_references_only_registry_enums(self):
        js = (WEB / "js" / "schema.js").read_text(encoding="utf-8")
        used = set(re.findall(r'\["\w+",\s*"(\w+)"', js))
        assert used, "schema.js binds no selects"
        assert used <= set(ENUMS), used - set(ENUMS)


def test_timezone_select_has_no_hardcoded_options_and_is_filled_from_the_schema():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    match = re.search(r'<select[^>]*id="g_timezone"[^>]*>(.*?)</select>', html, re.DOTALL)
    assert match and "<option" not in match.group(1)
    assert "schema.timezones" in (WEB / "js" / "schema.js").read_text(encoding="utf-8")
