"""Tests for DataLifecycleService's media cleanup (app/shared/data_lifecycle.py).

Covers the symlink guard added to cleanup_old_media() and
enforce_storage_limit() (finding #9). Screenshots are written by this app
itself, so a symlink shouldn't ever legitimately appear under
screenshots_dir — the guard is defense-in-depth against rglob() following
one into (or counting the size of) something outside that directory.

The scheduler tests at the bottom cover propagation of retention settings to
the worker (roadmap task 2.2): they drive RetentionScheduler.tick() with a
hand-held clock and a SettingsService over an in-memory repository.

DataLifecycleService's constructor only requires a non-empty postgres_dsn
string (PooledDatabase's connection pool is created lazily on first query —
see database/base.py); cleanup_old_media/enforce_storage_limit never touch
the DB, so a fake DSN and no live Postgres are fine here.
"""
from __future__ import annotations

import os
import time

import pytest

from app.shared.data_lifecycle import DataLifecycleService, RetentionPolicy
from app.worker.main import RetentionScheduler
from config.settings_service import SettingsService
from database.errors import StorageUnavailableError


def _make_service(tmp_path, **policy_kwargs):
    screenshots_dir = tmp_path / "screenshots"
    policy = RetentionPolicy(**policy_kwargs)
    return DataLifecycleService(
        screenshots_dir=str(screenshots_dir),
        policy=policy,
        postgres_dsn="postgresql://unused/unused",
    )


def _age_file(path, days_old: float) -> None:
    old_time = time.time() - days_old * 86400
    os.utime(path, (old_time, old_time))


class TestCleanupOldMediaSymlinkGuard:
    def test_old_real_file_is_deleted(self, tmp_path):
        service = _make_service(tmp_path, media_retention_days=1)
        real_file = service.screenshots_dir / "old.jpg"
        real_file.write_bytes(b"x")
        _age_file(real_file, days_old=5)

        result = service.cleanup_old_media()

        assert result["deleted_orphan_media"] == 1
        assert not real_file.exists()

    def test_recent_real_file_is_kept(self, tmp_path):
        service = _make_service(tmp_path, media_retention_days=30)
        real_file = service.screenshots_dir / "recent.jpg"
        real_file.write_bytes(b"x")

        result = service.cleanup_old_media()

        assert result["deleted_orphan_media"] == 0
        assert real_file.exists()

    def test_symlinked_file_is_left_untouched(self, tmp_path):
        service = _make_service(tmp_path, media_retention_days=1)
        outside_target = tmp_path / "outside.jpg"
        outside_target.write_bytes(b"x")
        _age_file(outside_target, days_old=5)
        link = service.screenshots_dir / "link.jpg"
        try:
            link.symlink_to(outside_target)
        except OSError:
            pytest.skip("symlink creation not permitted in this environment")

        result = service.cleanup_old_media()

        assert result["deleted_orphan_media"] == 0
        assert link.exists(), "guard should mean unlink() is never called on the symlink"
        assert outside_target.exists()


class TestEnforceStorageLimitSymlinkGuard:
    def test_real_oversized_files_are_deleted(self, tmp_path):
        service = _make_service(tmp_path, max_screenshots_mb=1)  # 1 MiB cap
        old_file = service.screenshots_dir / "big_old.jpg"
        old_file.write_bytes(b"x" * (2 * 1024 * 1024))  # 2 MiB, over cap
        _age_file(old_file, days_old=2)

        result = service.enforce_storage_limit()

        assert result["deleted_for_limit"] == 1
        assert not old_file.exists()

    def test_symlinked_file_excluded_from_total_and_untouched(self, tmp_path):
        """Without the guard, stat() follows the symlink and counts the
        target's size toward the total, which could push a within-budget
        directory over the cap and get the symlink unlinked."""
        service = _make_service(tmp_path, max_screenshots_mb=1)  # 1 MiB cap
        outside_target = tmp_path / "outside_big.jpg"
        outside_target.write_bytes(b"x" * (5 * 1024 * 1024))  # 5 MiB
        link = service.screenshots_dir / "link.jpg"
        try:
            link.symlink_to(outside_target)
        except OSError:
            pytest.skip("symlink creation not permitted in this environment")

        result = service.enforce_storage_limit()

        assert result["deleted_for_limit"] == 0
        assert link.exists()
        assert outside_target.exists()


# ---------------------------------------------------------------------------
# Propagation of retention settings to the worker (roadmap task 2.2)
# ---------------------------------------------------------------------------

class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Repo:
    """In-memory AppSettingsRepository stand-in; `down` simulates an outage."""

    def __init__(self, stored=None) -> None:
        self.stored = dict(stored or {})
        self.rev = 0
        self.down = False

    def revision(self) -> int:
        if self.down:
            raise StorageUnavailableError("PostgreSQL недоступен")
        return self.rev

    def get_all(self) -> dict:
        if self.down:
            raise StorageUnavailableError("PostgreSQL недоступен")
        return dict(self.stored)

    def change(self, values: dict) -> None:
        """Another process (the API) writes settings."""
        self.stored.update(values)
        self.rev += 1


class _StubLifecycle:
    def __init__(self, fail: bool = False) -> None:
        self.policy = RetentionPolicy()
        self.runs = 0
        self.fail = fail

    def update_policy(self, policy: RetentionPolicy) -> None:
        self.policy = policy

    def run_retention_cycle(self) -> dict:
        self.runs += 1
        if self.fail:
            raise StorageUnavailableError("PostgreSQL недоступен")
        return {"deleted_events": 0}


def _scheduler(stored=None, lifecycle=None):
    clock = _Clock()
    repo = _Repo(stored)
    service = SettingsService(repo, cache_ttl_seconds=5.0, clock=clock)
    lifecycle = lifecycle or _StubLifecycle()
    return RetentionScheduler(lifecycle, service, clock=clock), lifecycle, repo, clock


class TestRetentionSchedulerPropagation:
    def test_policy_comes_from_settings_not_from_the_startup_snapshot(self):
        scheduler, lifecycle, _, _ = _scheduler({"retention.events_retention_days": 90})
        scheduler.tick()
        assert lifecycle.policy.events_retention_days == 90

    def test_first_tick_runs_a_cycle_and_schedules_the_next(self):
        scheduler, lifecycle, _, _ = _scheduler()
        sleep = scheduler.tick()
        assert lifecycle.runs == 1
        assert scheduler.last_run == {"deleted_events": 0}
        assert 0 < sleep <= RetentionScheduler.POLICY_POLL_SECONDS

    def test_no_second_cycle_before_the_interval_elapses(self):
        scheduler, lifecycle, _, clock = _scheduler()
        scheduler.tick()
        clock.now += 29 * 60
        scheduler.tick()
        assert lifecycle.runs == 1

    def test_cycle_repeats_after_the_interval(self):
        scheduler, lifecycle, _, clock = _scheduler()
        scheduler.tick()
        clock.now += 30 * 60 + 1
        scheduler.tick()
        assert lifecycle.runs == 2

    def test_shortened_interval_takes_effect_within_one_poll(self):
        """With a fixed sleep computed before the change, a worker asleep for
        24 h would ignore an administrator setting 1 minute. Re-reading the
        policy every tick and computing the next run from the current interval
        makes the change effective at the next poll."""
        scheduler, lifecycle, repo, clock = _scheduler({"retention.cleanup_interval_minutes": 24 * 60})
        scheduler.tick()
        clock.now += 90  # far short of 24 h, past the cache window
        scheduler.tick()
        assert lifecycle.runs == 1

        repo.change({"retention.cleanup_interval_minutes": 1})
        clock.now += RetentionScheduler.POLICY_POLL_SECONDS + 6
        scheduler.tick()
        assert lifecycle.policy.cleanup_interval_minutes == 1
        assert lifecycle.runs == 2

    def test_lengthened_interval_postpones_the_next_cycle(self):
        scheduler, lifecycle, repo, clock = _scheduler({"retention.cleanup_interval_minutes": 1})
        scheduler.tick()
        repo.change({"retention.cleanup_interval_minutes": 24 * 60})
        clock.now += 120
        scheduler.tick()
        assert lifecycle.runs == 1

    def test_sleep_never_exceeds_the_poll_period(self):
        scheduler, _, _, _ = _scheduler({"retention.cleanup_interval_minutes": 24 * 60})
        assert scheduler.tick() <= RetentionScheduler.POLICY_POLL_SECONDS

    def test_disabling_cleanup_stops_cycles_and_enabling_resumes_them(self):
        scheduler, lifecycle, repo, clock = _scheduler({"retention.auto_cleanup_enabled": False})
        scheduler.tick()
        clock.now += 3600
        scheduler.tick()
        assert lifecycle.runs == 0

        repo.change({"retention.auto_cleanup_enabled": True})
        clock.now += 6
        scheduler.tick()
        assert lifecycle.runs == 1

    def test_cycle_error_is_recorded_and_the_loop_continues(self):
        scheduler, lifecycle, _, clock = _scheduler(lifecycle=_StubLifecycle(fail=True))
        scheduler.tick()
        assert scheduler.last_run == {"status": "error"}
        clock.now += 30 * 60 + 1
        scheduler.tick()
        assert lifecycle.runs == 2


class TestRetentionSchedulerUnavailableDatabase:
    def test_no_cleanup_runs_by_registry_defaults_while_settings_were_never_read(self):
        """Retention deletes data: with the database down from the start, the
        registry defaults are not the operator's policy, so no cycle runs."""
        scheduler, lifecycle, repo, clock = _scheduler({"retention.events_retention_days": 365})
        repo.down = True
        sleep = scheduler.tick()
        assert lifecycle.runs == 0
        assert sleep == RetentionScheduler.POLICY_POLL_SECONDS

        repo.down = False
        clock.now += 6
        scheduler.tick()
        assert lifecycle.runs == 1
        assert lifecycle.policy.events_retention_days == 365

    def test_outage_after_a_load_keeps_the_last_known_policy(self):
        scheduler, lifecycle, repo, clock = _scheduler({"retention.events_retention_days": 365})
        scheduler.tick()
        repo.down = True
        clock.now += 30 * 60 + 1
        scheduler.tick()
        assert lifecycle.policy.events_retention_days == 365
        assert lifecycle.runs == 2


class TestRetentionPolicyFromSettings:
    def test_builds_the_policy_from_the_retention_section(self):
        stored = {"retention.max_screenshots_mb": 512, "retention.auto_cleanup_enabled": False}
        service = SettingsService(_Repo(stored), clock=_Clock())
        policy = RetentionPolicy.from_settings(service)
        assert policy == RetentionPolicy(
            auto_cleanup_enabled=False,
            cleanup_interval_minutes=30,
            events_retention_days=30,
            media_retention_days=14,
            max_screenshots_mb=512,
        )
