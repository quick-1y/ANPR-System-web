import io
from zipfile import ZipFile

from config.settings_normalizer import SettingsNormalizer
from app.shared.data_lifecycle import DataLifecycleService, RetentionPolicy


class TestLoggingSettingsNormalization:

    def test_normalizer_removes_offset_minutes_from_time(self):
        normalizer = SettingsNormalizer()
        raw = {
            "time": {
                "timezone": "UTC+03:00",
                "offset_minutes": 120,
            }
        }

        normalized, changed = normalizer.normalize_with_meta(raw)

        assert changed is True
        assert "offset_minutes" not in normalized["time"]

    def test_normalizer_removes_allowed_levels_from_logging(self):
        normalizer = SettingsNormalizer()
        raw = {
            "logging": {
                "level": "INFO",
                "retention_days": 30,
                "allowed_levels": ["INFO", "ERROR"],
            }
        }

        normalized, changed = normalizer.normalize_with_meta(raw)

        assert changed is True
        assert "allowed_levels" not in normalized["logging"]



    def test_normalizer_removes_shared_memory_from_inference(self):
        normalizer = SettingsNormalizer()
        raw = {
            "inference": {
                "workers": 2,
                "shared_memory": True,
            }
        }

        normalized, changed = normalizer.normalize_with_meta(raw)

        assert changed is True
        assert "shared_memory" not in normalized["inference"]

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


class _StubEventsDb:
    def __init__(self, rows):
        self._rows = rows

    def fetch_for_export(self, **kwargs):
        return list(self._rows)


class TestInMemoryExports:
    def test_export_events_csv_returns_bytes_without_export_directory(self, tmp_path):
        service = DataLifecycleService(
            screenshots_dir=str(tmp_path / "screens"),
            policy=RetentionPolicy(),
            postgres_dsn="postgresql://user:pass@localhost:5432/db",
        )
        service.pg_events = _StubEventsDb(
            [
                {
                    "id": 1,
                    "timestamp": "2026-01-01T10:00:00Z",
                    "channel_id": 1,
                    "channel": "Cam 1",
                    "plate": "A123AA77",
                    "plate_display": "A 123 AA 77",
                    "country": "RU",
                    "confidence": 0.9,
                    "source": "rtsp",
                    "frame_path": "",
                    "plate_path": "",
                    "direction": "in",
                }
            ]
        )

        filename, payload = service.export_events_csv()

        assert filename.endswith(".csv")
        assert isinstance(payload, bytes)
        assert b"plate" in payload
        assert not hasattr(service, "_export_dir")

    def test_export_bundle_returns_zip_bytes(self, tmp_path):
        media_file = tmp_path / "frame.jpg"
        media_file.write_bytes(b"fake-image")

        service = DataLifecycleService(
            screenshots_dir=str(tmp_path / "screens"),
            policy=RetentionPolicy(),
            postgres_dsn="postgresql://user:pass@localhost:5432/db",
        )
        service.pg_events = _StubEventsDb(
            [
                {
                    "id": 1,
                    "timestamp": "2026-01-01T10:00:00Z",
                    "channel_id": 1,
                    "channel": "Cam 1",
                    "plate": "A123AA77",
                    "plate_display": "A 123 AA 77",
                    "country": "RU",
                    "confidence": 0.9,
                    "source": "rtsp",
                    "frame_path": str(media_file),
                    "plate_path": "",
                    "direction": "in",
                }
            ]
        )

        filename, payload = service.export_events_bundle(include_media=True)

        assert filename.endswith(".zip")
        with ZipFile(io.BytesIO(payload), "r") as archive:
            names = set(archive.namelist())
            assert any(name.endswith(".csv") for name in names)
            assert "media/frame.jpg" in names
