"""Tests for config/settings_service.py (roadmap task 2.1).

The repository is replaced by an in-memory stub that counts database round
trips, and the clock by a hand-driven one, so cache windows and revision
invalidation are deterministic.
"""
from __future__ import annotations

import threading

import pytest

from config.registry import ConfigClass, SettingValidationError, defaults
from config.settings_service import SettingsService
from database.errors import StorageUnavailableError


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Repo:
    """In-memory stand-in for AppSettingsRepository."""

    def __init__(self, stored=None) -> None:
        self.stored = dict(stored or {})
        self.rev = 0
        self.down = False
        self.revision_calls = 0
        self.get_all_calls = 0
        self.writes: list[tuple[dict, object]] = []
        self.replaced: list[tuple[dict, object]] = []
        self.gate: threading.Event | None = None
        self.entered = threading.Event()

    def _check(self) -> None:
        if self.down:
            raise StorageUnavailableError("PostgreSQL недоступен")

    def revision(self) -> int:
        self.revision_calls += 1
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(timeout=5)
        self._check()
        return self.rev

    def get_all(self) -> dict:
        self.get_all_calls += 1
        self._check()
        return dict(self.stored)

    def set_many(self, values, updated_by=None) -> int:
        self._check()
        self.writes.append((dict(values), updated_by))
        self.stored.update(values)
        self.rev += 1
        return self.rev

    def replace_all(self, values, updated_by=None) -> int:
        self._check()
        self.replaced.append((dict(values), updated_by))
        self.stored = dict(values)
        self.rev += 1
        return self.rev

    # Simulates another process (e.g. the API) writing to the table.
    def external_write(self, values: dict) -> None:
        self.stored.update(values)
        self.rev += 1


def _service(repo=None, ttl=5.0):
    repo = repo or _Repo()
    clock = _Clock()
    return SettingsService(repo, cache_ttl_seconds=ttl, clock=clock), repo, clock


class TestDefaultsAndOverrides:
    def test_empty_table_yields_registry_defaults(self):
        service, _, _ = _service()
        assert service.get("retention.events_retention_days") == 30
        assert service.get("plates.enabled_countries") == ["RU", "UA", "BY", "KZ"]
        assert service.loaded is True

    def test_every_class_a_key_is_readable_on_an_empty_table(self):
        service, _, _ = _service()
        for key, default in defaults(ConfigClass.A).items():
            assert service.get(key) == default

    def test_database_value_overrides_the_default(self):
        service, _, _ = _service(_Repo({"retention.events_retention_days": 90}))
        assert service.get("retention.events_retention_days") == 90
        assert service.get("retention.media_retention_days") == 14

    def test_section_returns_names_relative_to_the_prefix(self):
        service, _, _ = _service(_Repo({"retention.events_retention_days": 90}))
        section = service.get_section("retention")
        assert section == {
            "auto_cleanup_enabled": True,
            "cleanup_interval_minutes": 30,
            "events_retention_days": 90,
            "media_retention_days": 14,
            "max_screenshots_mb": 4096,
        }

    def test_nested_section_keeps_the_remaining_path(self):
        service, _, _ = _service()
        assert service.get_section("reconnect")["signal_loss.enabled"] is True

    def test_unknown_prefix_is_an_error_not_an_empty_section(self):
        service, _, _ = _service()
        with pytest.raises(KeyError):
            service.get_section("retentoin")

    def test_only_class_a_keys_are_served(self):
        service, _, _ = _service()
        for key in ("theme", "JWT_SECRET_KEY", "anpr_token"):
            with pytest.raises(KeyError):
                service.get(key)

    def test_returned_lists_are_copies(self):
        service, _, _ = _service()
        service.get("plates.enabled_countries").append("XX")
        assert service.get("plates.enabled_countries") == ["RU", "UA", "BY", "KZ"]

    def test_invalid_stored_value_falls_back_to_the_default(self):
        service, _, _ = _service(_Repo({"logging.level": "LOUD", "retention.events_retention_days": "many"}))
        assert service.get("logging.level") == "ALL"
        assert service.get("retention.events_retention_days") == 30

    def test_stored_key_unknown_to_the_registry_is_ignored(self):
        service, _, _ = _service(_Repo({"storage.events_retention_days": 5}))
        assert service.get("retention.events_retention_days") == 30


class TestCacheAndRevision:
    def test_reads_inside_the_window_do_not_touch_the_database(self):
        service, repo, clock = _service()
        for _ in range(50):
            service.get("retention.events_retention_days")
            service.get_section("retention")
            clock.advance(0.05)
        assert repo.revision_calls == 1
        assert repo.get_all_calls == 1

    def test_external_revision_bump_invalidates_the_cache(self):
        service, repo, clock = _service()
        assert service.get("retention.events_retention_days") == 30

        repo.external_write({"retention.events_retention_days": 7})
        assert service.get("retention.events_retention_days") == 30  # still inside the window

        clock.advance(6)
        assert service.get("retention.events_retention_days") == 7
        assert repo.get_all_calls == 2

    def test_unchanged_revision_polls_but_does_not_reload_values(self):
        service, repo, clock = _service()
        service.get("retention.events_retention_days")
        clock.advance(6)
        service.get("retention.events_retention_days")
        assert repo.revision_calls == 2
        assert repo.get_all_calls == 1

    def test_a_change_without_a_revision_bump_is_not_noticed(self):
        """The revision counter is the only invalidation signal by design."""
        service, repo, clock = _service()
        service.get("retention.events_retention_days")
        repo.stored["retention.events_retention_days"] = 7
        clock.advance(6)
        assert service.get("retention.events_retention_days") == 30

    def test_own_write_is_visible_immediately_inside_the_window(self):
        service, _, _ = _service()
        assert service.get("retention.events_retention_days") == 30
        service.update({"retention.events_retention_days": 60})
        assert service.get("retention.events_retention_days") == 60

    def test_a_slow_refresh_does_not_block_other_readers(self):
        service, repo, clock = _service()
        service.get("retention.events_retention_days")  # populate the cache
        clock.advance(6)
        repo.gate = threading.Event()
        repo.entered.clear()

        slow = threading.Thread(target=service.get, args=("retention.events_retention_days",))
        slow.start()
        assert repo.entered.wait(timeout=5), "refresh never reached the database"
        results: list = []
        fast = threading.Thread(target=lambda: results.append(service.get("retention.events_retention_days")))
        fast.start()
        fast.join(timeout=2)
        try:
            assert not fast.is_alive(), "reader blocked behind a refresh in progress"
            assert results == [30]
        finally:
            repo.gate.set()
            slow.join(timeout=5)


class TestUnavailableDatabase:
    def test_cold_start_returns_defaults_without_raising(self):
        repo = _Repo({"retention.events_retention_days": 90})
        repo.down = True
        service, _, _ = _service(repo)
        assert service.get("retention.events_retention_days") == 30
        assert service.loaded is False
        assert service.degraded is True

    def test_outage_after_a_load_keeps_serving_the_last_cache(self):
        service, repo, clock = _service(_Repo({"retention.events_retention_days": 90}))
        assert service.get("retention.events_retention_days") == 90
        repo.down = True
        clock.advance(6)
        assert service.get("retention.events_retention_days") == 90
        assert service.get_section("retention")["events_retention_days"] == 90
        assert service.loaded is True
        assert service.degraded is True

    def test_service_recovers_when_the_database_returns(self):
        repo = _Repo({"retention.events_retention_days": 90})
        repo.down = True
        service, _, clock = _service(repo)
        service.get("retention.events_retention_days")

        repo.down = False
        clock.advance(6)
        assert service.get("retention.events_retention_days") == 90
        assert service.loaded is True
        assert service.degraded is False

    def test_outage_is_retried_once_per_window_not_on_every_read(self):
        repo = _Repo()
        repo.down = True
        service, _, clock = _service(repo)
        for _ in range(20):
            service.get("retention.events_retention_days")
        assert repo.revision_calls == 1
        clock.advance(6)
        service.get("retention.events_retention_days")
        assert repo.revision_calls == 2

    def test_write_failure_is_not_swallowed(self):
        service, repo, _ = _service()
        service.get("retention.events_retention_days")
        repo.down = True
        with pytest.raises(StorageUnavailableError):
            service.update({"retention.events_retention_days": 60})


class TestUpdateValidation:
    def test_value_outside_choices_is_rejected_and_nothing_is_written(self):
        service, repo, _ = _service()
        with pytest.raises(SettingValidationError):
            service.update({"logging.level": "LOUD"})
        assert repo.writes == []

    def test_one_invalid_value_rejects_the_whole_mapping(self):
        service, repo, _ = _service()
        with pytest.raises(SettingValidationError):
            service.update({"retention.events_retention_days": 60, "logging.level": "LOUD"})
        assert repo.writes == []

    def test_wrong_type_is_rejected(self):
        service, repo, _ = _service()
        with pytest.raises(SettingValidationError):
            service.update({"retention.events_retention_days": True})
        assert repo.writes == []

    def test_unknown_key_is_rejected(self):
        service, repo, _ = _service()
        with pytest.raises(KeyError):
            service.update({"retention.nope": 1})
        assert repo.writes == []

    @pytest.mark.parametrize("key", ["theme", "JWT_SECRET_KEY"])
    def test_keys_of_other_classes_are_rejected(self, key):
        service, repo, _ = _service()
        with pytest.raises(KeyError):
            service.update({key: "x"})
        assert repo.writes == []

    def test_reserved_key_is_rejected(self):
        service, repo, _ = _service()
        with pytest.raises(SettingValidationError):
            service.update({"interface.default_locale": "ru"})
        assert repo.writes == []

    def test_empty_mapping_is_a_noop(self):
        service, repo, _ = _service()
        assert service.update({}) == []
        assert repo.writes == []

    def test_values_are_normalised_before_they_are_stored(self):
        service, repo, _ = _service()
        service.update({"plates.enabled_countries": ["RU", "BY", "RU"], "detection.confidence_threshold": 1})
        written = repo.writes[0][0]
        assert written["plates.enabled_countries"] == ["RU", "BY"]
        assert written["detection.confidence_threshold"] == 1.0

    def test_writer_is_recorded(self):
        service, repo, _ = _service()
        service.update({"retention.events_retention_days": 60}, updated_by=42)
        assert repo.writes == [({"retention.events_retention_days": 60}, 42)]


class TestRestartRequired:
    def test_changed_restart_key_is_reported(self):
        service, _, _ = _service()
        restart = service.update({"plates.enabled_countries": ["RU"], "retention.events_retention_days": 60})
        assert restart == ["plates.enabled_countries"]

    def test_unchanged_restart_key_is_not_reported(self):
        service, _, _ = _service()
        assert service.update({"plates.enabled_countries": ["RU", "UA", "BY", "KZ"]}) == []

    def test_keys_are_returned_sorted(self):
        service, _, _ = _service()
        restart = service.update({"plates.enabled_countries": ["RU"], "detection.confidence_threshold": 0.7})
        assert restart == ["detection.confidence_threshold", "plates.enabled_countries"]

    def test_hot_keys_never_require_restart(self):
        service, _, _ = _service()
        assert service.update({"retention.events_retention_days": 60, "logging.level": "INFO"}) == []
