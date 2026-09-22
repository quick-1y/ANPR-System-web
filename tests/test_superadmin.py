"""Tests for app/api/superadmin.py — the technical, env-only superadmin
identity (roadmap section 14: no row in `users`)."""
from __future__ import annotations

from app.api.superadmin import (
    SUPERADMIN_ID,
    SUPERADMIN_LOGIN,
    audit_user_id,
    is_superadmin_id,
    synthetic_superadmin,
)


class TestSentinelId:
    def test_zero_is_the_sentinel(self):
        assert SUPERADMIN_ID == 0

    def test_is_superadmin_id_matches_only_the_sentinel(self):
        assert is_superadmin_id(0) is True
        assert is_superadmin_id(1) is False
        assert is_superadmin_id(-1) is False


class TestSyntheticSuperadmin:
    def test_shape_matches_a_db_row(self):
        user = synthetic_superadmin()
        assert user["id"] == SUPERADMIN_ID
        assert user["login"] == SUPERADMIN_LOGIN
        assert user["role"] == "superadmin"
        assert user["permissions"] == []
        assert user["is_active"] is True
        assert user["created_at"] is not None
        assert user["updated_at"] is not None

    def test_every_call_returns_the_same_timestamp(self):
        """Stable across calls within a process — nothing depends on this
        being "live", it only needs to satisfy UserOut's required fields."""
        a, b = synthetic_superadmin(), synthetic_superadmin()
        assert a["created_at"] == b["created_at"]


class TestAuditUserId:
    def test_a_real_user_id_passes_through(self):
        assert audit_user_id({"id": 7}) == 7

    def test_the_superadmin_sentinel_becomes_none(self):
        """app_settings.updated_by has a foreign key to users(id); the
        sentinel id is never a row there, so it must be written as NULL."""
        assert audit_user_id(synthetic_superadmin()) is None

    def test_a_missing_id_becomes_none(self):
        assert audit_user_id({}) is None
