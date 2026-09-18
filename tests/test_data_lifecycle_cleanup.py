"""Tests for DataLifecycleService's media cleanup (app/shared/data_lifecycle.py).

Covers the symlink guard added to cleanup_old_media() and
enforce_storage_limit() (finding #9). Screenshots are written by this app
itself, so a symlink shouldn't ever legitimately appear under
screenshots_dir — the guard is defense-in-depth against rglob() following
one into (or counting the size of) something outside that directory.

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
