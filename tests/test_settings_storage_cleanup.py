from config.settings_normalizer import SettingsNormalizer
from app.shared.data_lifecycle import RetentionPolicy


class TestStorageCleanup:
    def test_normalizer_removes_export_dir_from_storage(self):
        normalizer = SettingsNormalizer()
        raw = {
            "storage": {
                "screenshots_dir": "data/screenshots",
                "logs_dir": "logs",
                "auto_cleanup_enabled": True,
                "cleanup_interval_minutes": 30,
                "events_retention_days": 30,
                "media_retention_days": 14,
                "max_screenshots_mb": 4096,
                "export_dir": "data/exports",
            }
        }

        normalized, changed = normalizer.normalize_with_meta(raw)

        assert changed is True
        assert "export_dir" not in normalized["storage"]

    def test_retention_policy_does_not_persist_export_dir(self):
        policy = RetentionPolicy.from_storage(
            {
                "auto_cleanup_enabled": True,
                "cleanup_interval_minutes": 60,
                "events_retention_days": 10,
                "media_retention_days": 5,
                "max_screenshots_mb": 2048,
                "export_dir": "data/exports",
            }
        )

        storage = policy.to_storage()

        assert "export_dir" not in storage
        assert storage["cleanup_interval_minutes"] == 60
