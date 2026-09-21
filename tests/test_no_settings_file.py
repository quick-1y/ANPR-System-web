"""The YAML settings layer is gone (roadmap task 9.2): the system runs from
`app_settings` and the environment alone."""
from __future__ import annotations

from pathlib import Path

import pytest

from config import settings_schema
from config.registry import ConfigClass, specs
from config.settings_service import SettingsService
from tests.test_settings_service import _Clock, _Repo

ROOT = Path(__file__).resolve().parent.parent

REMOVED_FILES = (
    "config/settings_manager.py",
    "config/settings_normalizer.py",
    "config/settings_repository.py",
    "config/settings.yaml.example",
)

#: What must not be mentioned anywhere in shipped code or deployment files.
FORBIDDEN = ("settings.yaml", "SETTINGS_PATH", "SettingsManager", "settings_manager", "settings_normalizer")

SCANNED_SUFFIXES = {".py", ".js", ".html", ".yml", ".yaml", ".toml", ".example", ".css"}
SKIPPED_DIRS = {"tests", "docs", ".planning", ".git", ".idea", ".pytest_cache", "__pycache__", "node_modules", "data", "logs"}
#: The registry's REMOVED inventory names the retired variable on purpose.
ALLOWED = {"config/registry.py"}


def _shipped_files():
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if not path.is_file() or any(part in SKIPPED_DIRS for part in rel.parts):
            continue
        if path.suffix in SCANNED_SUFFIXES or path.name in {"Dockerfile", ".gitignore", ".env.example", ".dockerignore"}:
            yield rel.as_posix(), path


def test_the_layer_files_are_deleted():
    for name in REMOVED_FILES:
        assert not (ROOT / name).exists(), name


def test_nothing_shipped_mentions_the_settings_file_or_its_classes():
    offenders = []
    for rel, path in _shipped_files():
        if rel in ALLOWED:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        offenders += [(rel, token) for token in FORBIDDEN if token in text]
    assert not offenders, offenders


def test_compose_no_longer_mounts_the_config_directory():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "./config" not in compose and "SETTINGS_PATH" not in compose


def test_the_schema_module_is_reduced_to_defaults_and_normalizers():
    assert not hasattr(settings_schema, "build_default_settings")
    for kept in ("channel_defaults", "direction_defaults", "normalize_region_config", "normalize_hotkey",
                 "SUPPORTED_CONTROLLER_TYPES", "relay_defaults"):
        assert hasattr(settings_schema, kept), kept


def test_pyyaml_stays_because_country_configs_are_yaml():
    assert "PyYAML" in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert list((ROOT / "anpr" / "countries").glob("*.yaml"))


def test_gitignore_no_longer_needs_a_rule_for_the_settings_file():
    assert "settings.yaml" not in (ROOT / ".gitignore").read_text(encoding="utf-8")


class TestFreshInstallOnAnEmptyTable:
    """A clean installation has no rows at all: every setting must resolve."""

    def test_every_operational_key_resolves_to_its_registry_default(self):
        service = SettingsService(_Repo(), clock=_Clock())
        for spec in specs(ConfigClass.A):
            assert service.get(spec.key) == spec.default, spec.key
        assert service.loaded and not service.degraded

    def test_nothing_is_reported_as_configured_on_a_fresh_install(self):
        service = SettingsService(_Repo(), clock=_Clock())
        assert service.stored_values() == {}
        assert service.is_configured("interface.display_timezone") is False

    def test_the_container_starts_without_any_settings_source_but_the_service(self):
        import inspect

        from app.api.container import AppContainer

        assert "settings" not in AppContainer.__dataclass_fields__
        source = inspect.getsource(AppContainer.build)
        assert "SettingsManager" not in source and "settings_service = SettingsService(" in source

    def test_the_worker_likewise(self):
        import inspect

        from app.worker.main import WorkerContainer

        assert "settings" not in WorkerContainer.__dataclass_fields__
        assert "SettingsManager" not in inspect.getsource(WorkerContainer.build)
