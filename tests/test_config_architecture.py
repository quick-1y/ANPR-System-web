"""Tests for the configuration registry (config/registry.py, roadmap task 1.1).

Covers completeness against the inventory (every key of the current settings
schema and every environment variable the code reads is either registered or
explicitly listed as removed), uniqueness, the resolved defaults of roadmap
section 4.10, the rule that a `reserved` key must state its reason, and the
validation behaviour `SettingsService` relies on.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from config.registry import (
    COUNTRIES,
    REGISTRY,
    REMOVED,
    ConfigClass,
    SettingSpec,
    SettingValidationError,
    defaults,
    get_spec,
    specs,
)
from tests.test_env_example_sync import _env_names_read_by_code


def _flatten(prefix: str, node: dict) -> list[str]:
    keys: list[str] = []
    for name, value in node.items():
        path = f"{prefix}.{name}" if prefix else name
        keys.extend(_flatten(path, value) if isinstance(value, dict) else [path])
    return keys


class TestCompleteness:

    def test_every_environment_variable_read_by_code_is_registered_or_removed(self):
        missing = [
            name
            for name in _env_names_read_by_code()
            if name not in REGISTRY and name not in REMOVED
        ]
        assert not missing, f"Environment variables absent from the registry: {missing}"

    def test_class_d_entries_are_environment_variable_names(self):
        for spec in specs(ConfigClass.D):
            assert spec.key == spec.key.upper(), spec.key

    def test_removed_keys_are_not_also_registered(self):
        assert not [key for key in REMOVED if key in REGISTRY]

    def test_every_class_a_and_u_key_has_a_default(self):
        for cls in (ConfigClass.A, ConfigClass.U):
            for spec in specs(cls):
                assert spec.default is not None, spec.key

    def test_every_entry_has_a_description_and_a_known_class(self):
        for spec in REGISTRY.values():
            assert spec.description.strip(), spec.key
            assert isinstance(spec.cls, ConfigClass), spec.key


class TestReservedKeys:
    def test_reserved_keys_are_exactly_the_locale_keys(self):
        reserved = sorted(spec.key for spec in REGISTRY.values() if spec.reserved)
        assert reserved == ["interface.default_locale", "locale"]

    def test_every_reserved_key_states_its_reason(self):
        for spec in REGISTRY.values():
            if spec.reserved:
                reason = spec.description.removeprefix("Зарезервирован:").strip()
                assert len(reason) > 10, spec.key

    def test_reserved_without_a_reason_is_rejected(self):
        with pytest.raises(ValueError):
            SettingSpec(
                key="x.y", cls=ConfigClass.A, type="str", default="a",
                owner="admin-config", description="Просто описание", reserved=True,
            )


class TestResolvedDefaults:
    """Roadmap 4.10: which of the conflicting defaults won."""

    def test_periodic_reconnect_is_off_by_default(self):
        assert get_spec("reconnect.periodic.enabled").default is False

    def test_enabled_countries_are_all_four(self):
        assert get_spec("plates.enabled_countries").default == ["RU", "UA", "BY", "KZ"]


    def test_display_timezone_default_is_static_utc(self):
        assert get_spec("interface.display_timezone").default == "UTC"

    def test_channel_metrics_are_hidden_by_default(self):
        assert get_spec("channel_metrics_visible").default is False

    def test_retention_defaults_are_unchanged(self):
        retention = {k: v for k, v in defaults(ConfigClass.A).items() if k.startswith("retention.")}
        assert retention == {
            "retention.auto_cleanup_enabled": True,
            "retention.cleanup_interval_minutes": 30,
            "retention.events_retention_days": 30,
            "retention.media_retention_days": 14,
            "retention.max_screenshots_mb": 4096,
        }

    def test_countries_domain_matches_the_country_configs_on_disk(self):
        directory = pathlib.Path(__file__).resolve().parent.parent / "anpr" / "countries"
        codes = {
            re.search(r'^code:\s*"?(\w+)"?', path.read_text(encoding="utf-8"), re.MULTILINE).group(1)
            for path in directory.glob("*.yaml")
        }
        assert set(COUNTRIES) == codes


class TestRestartFlags:
    def test_only_processor_bound_keys_require_restart_in_class_a(self):
        flagged = sorted(spec.key for spec in specs(ConfigClass.A) if spec.requires_restart)
        assert flagged == ["detection.confidence_threshold", "plates.enabled_countries"]


class TestValidation:
    def test_bool_is_not_accepted_as_an_integer(self):
        with pytest.raises(SettingValidationError):
            get_spec("retention.events_retention_days").validate(True)

    def test_integer_is_not_accepted_as_a_bool(self):
        with pytest.raises(SettingValidationError):
            get_spec("retention.auto_cleanup_enabled").validate(1)

    def test_numeric_string_is_rejected(self):
        with pytest.raises(SettingValidationError):
            get_spec("retention.events_retention_days").validate("30")

    def test_value_outside_choices_is_rejected(self):
        with pytest.raises(SettingValidationError):
            get_spec("theme").validate("purple")

    def test_value_below_minimum_is_rejected(self):
        with pytest.raises(SettingValidationError):
            get_spec("retention.max_screenshots_mb").validate(255)

    def test_float_range_is_enforced_and_ints_are_widened(self):
        spec = get_spec("detection.confidence_threshold")
        assert spec.validate(1) == 1.0
        with pytest.raises(SettingValidationError):
            spec.validate(1.5)

    def test_unknown_country_is_rejected_and_duplicates_collapse(self):
        spec = get_spec("plates.enabled_countries")
        with pytest.raises(SettingValidationError):
            spec.validate(["RU", "XX"])
        assert spec.validate(["RU", "BY", "RU"]) == ["RU", "BY"]

    def test_utc_is_a_valid_display_timezone_without_a_tz_database(self):
        assert get_spec("interface.display_timezone").validate("UTC") == "UTC"

    def test_garbage_timezone_is_rejected(self):
        with pytest.raises(SettingValidationError):
            get_spec("interface.display_timezone").validate("Not/AZone")


    def test_unknown_key_is_reported_clearly(self):
        with pytest.raises(KeyError):
            get_spec("no.such.key")


# ════════════════════════════════════════════════════════════════════════
# Architecture invariants (roadmap task 10.2): keep configuration from
# sprawling again. Each rule is a small checker over source text, and each
# checker is also run against a deliberately broken snippet to prove it can fail.
# ════════════════════════════════════════════════════════════════════════

import ast as _ast

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_PY_DIRS = ("anpr", "app", "common", "config", "controllers", "database", "runtime")


def _py_files():
    for directory in _PY_DIRS:
        yield from (_ROOT / directory).rglob("*.py")


def _rel(path):
    return path.relative_to(_ROOT).as_posix()


def env_reads(source: str) -> list[int]:
    """Lines that read the process environment directly."""
    lines = []
    for node in _ast.walk(_ast.parse(source)):
        if isinstance(node, _ast.Attribute) and node.attr in ("getenv", "environ") and isinstance(node.value, _ast.Name) and node.value.id == "os":
            lines.append(node.lineno)
        if isinstance(node, _ast.ImportFrom) and node.module == "os" and any(a.name in ("getenv", "environ") for a in node.names):
            lines.append(node.lineno)
    return lines


def naive_clock_reads(source: str) -> list[int]:
    lines = []
    for node in _ast.walk(_ast.parse(source)):
        if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute) and not node.args and not node.keywords:
            if node.func.attr in ("now", "astimezone", "utcnow", "today"):
                lines.append(node.lineno)
    return lines


def local_storage_uses(source: str) -> bool:
    return "localStorage" in source


def migration_or_yaml_settings(path: str, source: str) -> list[str]:
    problems = []
    name = path.rsplit("/", 1)[-1].lower()
    if "migrat" in name:
        problems.append("migration module")
    if "import yaml" in source and path != "anpr/postprocessing/country_config.py":
        problems.append("yaml import outside the country loader")
    return problems


class TestArchitectureInvariants:
    # (a) the environment is read in exactly one place
    def test_environment_is_read_only_in_env_settings(self):
        offenders = [f"{_rel(p)}:{n}" for p in _py_files() if _rel(p) != "config/env_settings.py" for n in env_reads(p.read_text(encoding="utf-8"))]
        assert not offenders, offenders

    def test_env_invariant_can_fail(self):
        assert env_reads('import os\nx = os.getenv("A")') and env_reads("from os import environ") and env_reads('import os\nos.environ["A"]')

    # (b) every registry key is fully described
    def test_every_registry_key_has_class_type_default_and_description(self):
        for spec in REGISTRY.values():
            assert isinstance(spec.cls, ConfigClass) and spec.type and spec.description.strip(), spec.key
            if spec.cls in (ConfigClass.A, ConfigClass.U):
                assert spec.default is not None, f"{spec.key}: class {spec.cls.value} needs a registry default"

    # (c) .env.example covers class D
    def test_env_example_lists_every_class_d_variable(self):
        template = (_ROOT / ".env.example").read_text(encoding="utf-8")
        listed = {line.split("=", 1)[0].strip() for line in template.splitlines() if line.strip() and not line.startswith("#") and "=" in line}
        missing = [s.key for s in specs(ConfigClass.D) if s.key not in listed and s.key != "TZ"]
        assert not missing, missing
        assert "TZ=UTC" in (_ROOT / "Dockerfile").read_text(encoding="utf-8")

    # (d) channel defaults agree across registry, pydantic and DDL (details: test_channel_defaults_sync.py)
    def test_channel_defaults_agree_between_registry_pydantic_and_ddl(self):
        from app.api.schemas import ChannelConfigPayload
        from config.registry import CHANNEL_SPECS
        from database.channel_repository import ChannelDatabase

        payload = ChannelConfigPayload(name="c", source="s")
        for name, spec in CHANNEL_SPECS.items():
            assert getattr(payload, name) == spec.default, name
            assert f" {name} " in ChannelDatabase._SCHEMA, f"{name} missing from the channels DDL"

    # (e) a key belongs to one class only
    def test_no_key_is_declared_in_two_classes(self):
        by_class = {c: {s.key for s in specs(c)} for c in ConfigClass}
        classes = list(by_class)
        for i, first in enumerate(classes):
            for second in classes[i + 1:]:
                assert not (by_class[first] & by_class[second]), (first, second)
        assert not (set(REMOVED) & set(REGISTRY)), "a key cannot be both removed and current"
        assert all("." in k for k in by_class[ConfigClass.A]) and not any("." in k for k in by_class[ConfigClass.U])
        assert not (by_class[ConfigClass.D] & (by_class[ConfigClass.A] | by_class[ConfigClass.U]))

    # (f) a class A key is consumed or reserved
    def test_every_class_a_key_has_a_consumer_or_is_reserved(self):
        haystack = "\n".join(p.read_text(encoding="utf-8") for p in _py_files() if _rel(p) != "config/registry.py")
        unconsumed = []
        for spec in specs(ConfigClass.A):
            if spec.reserved:
                continue
            section = spec.key.split(".")[0]
            consumed = (
                f'"{spec.key}"' in haystack
                or f'get_section("{section}")' in haystack
                or f'_flatten("{section}"' in haystack
            )
            if not consumed:
                unconsumed.append(spec.key)
        assert not unconsumed, f"dead settings (rule 5): {unconsumed}"

    # (g) no naive clock reads
    def test_no_naive_datetime_now_or_astimezone(self):
        offenders = [f"{_rel(p)}:{n}" for p in _py_files() for n in naive_clock_reads(p.read_text(encoding="utf-8"))]
        assert not offenders, offenders

    def test_clock_invariant_can_fail(self):
        assert naive_clock_reads("from datetime import datetime\ndatetime.now()") and naive_clock_reads("d.astimezone()")
        assert not naive_clock_reads("from datetime import datetime, timezone\ndatetime.now(timezone.utc)")

    # (h) localStorage only in the modules that own device or cache state
    LOCAL_STORAGE_OWNERS = {"api.js", "appearance.js", "appearance-core.js", "video-grid.js"}

    def test_local_storage_is_confined_to_its_owner_modules(self):
        offenders = [p.name for p in (_ROOT / "app" / "web" / "js").glob("*.js") if p.name not in self.LOCAL_STORAGE_OWNERS and local_storage_uses(p.read_text(encoding="utf-8"))]
        assert not offenders, offenders

    def test_local_storage_invariant_can_fail(self):
        assert local_storage_uses("localStorage.setItem('x','y')") and not local_storage_uses("storage.setItem('x','y')")

    # (i) no configuration migration modules and no YAML settings reading
    def test_no_migration_modules_and_yaml_only_for_country_configs(self):
        offenders = [(_rel(p), problem) for p in _py_files() for problem in migration_or_yaml_settings(_rel(p), p.read_text(encoding="utf-8"))]
        assert not offenders, offenders

    def test_migration_invariant_can_fail(self):
        assert migration_or_yaml_settings("config/migrate_settings.py", "") and migration_or_yaml_settings("config/x.py", "import yaml")
        assert not migration_or_yaml_settings("anpr/postprocessing/country_config.py", "import yaml")

    # (j) endpoints added by the configuration work declare their level through the adapter
    def test_access_adapter_maps_every_level(self):
        from app.api.deps import ACCESS_LEVELS, get_current_user, require_access

        for level in ACCESS_LEVELS:
            assert callable(require_access(level)), level
        assert require_access("self") is get_current_user and require_access("authenticated") is get_current_user
        with pytest.raises(ValueError):
            require_access("tab:settings")

    def test_new_endpoints_use_the_adapter_not_tab_settings(self):
        import inspect

        from app.api.routers import preferences, settings, system

        for function in (preferences.get_my_preferences, preferences.patch_my_preferences,
                         system.system_time, settings.get_settings_schema):
            source = inspect.getsource(function)
            assert "require_access(" in source, function.__name__
            assert "tab:settings" not in source and "require_permission(" not in source, function.__name__

    # (k) do not make it worse: direct use of the navigation permission as an access check
    TAB_SETTINGS_BASELINE = 18  # roadmap 2.7 audit

    def test_direct_tab_settings_checks_do_not_grow(self):
        count = sum(p.read_text(encoding="utf-8").count('require_permission("tab:settings")') for p in (_ROOT / "app" / "api").rglob("*.py"))
        assert count <= self.TAB_SETTINGS_BASELINE, f"{count} direct tab:settings checks (baseline {self.TAB_SETTINGS_BASELINE}); use require_access(level)"


class TestConfigurationDocumentation:
    """10.1: the documentation answers seven questions for every registry key."""

    DOC = _ROOT / "docs" / "technical" / "configuration.md"

    def _rows(self):
        rows = {}
        for line in self.DOC.read_text(encoding="utf-8").splitlines():
            if line.startswith("| `"):
                cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
                rows[cells[0].strip("`")] = cells
        return rows

    def test_every_registry_key_is_documented_with_seven_answers(self):
        rows = self._rows()
        missing = [key for key in REGISTRY if key not in rows]
        assert not missing, f"undocumented keys: {missing}"
        for key, cells in rows.items():
            assert len(cells) == 7 and all(cells), (key, cells)

    def test_documentation_lists_no_key_that_is_gone(self):
        assert not [key for key in self._rows() if key not in REGISTRY]

    def test_no_document_presents_yaml_as_the_settings_mechanism(self):
        offenders = []
        for path in list((_ROOT / "docs").rglob("*.md")) + [_ROOT / "README.md", _ROOT / "AGENTS.md"] + list((_ROOT / ".planning").rglob("*.md")):
            if path.name == "configuration-architecture.md" or path.as_posix().endswith("guides/setup.md"):
                continue  # the roadmap records history; setup.md explains the move away from the old file
            text = path.read_text(encoding="utf-8", errors="ignore")
            offenders += [(path.name, token) for token in ("settings.yaml", "SettingsManager", "SETTINGS_PATH") if token in text]
        assert not offenders, offenders
