import io
from zipfile import ZipFile

from app.shared.data_lifecycle import DataLifecycleService, RetentionPolicy


class TestStorageCleanup:
    def test_retention_policy_does_not_persist_export_dir(self):
        from config.settings_service import SettingsService
        from tests.test_settings_service import _Clock, _Repo

        service = SettingsService(
            _Repo(
                {
                    "retention.auto_cleanup_enabled": True,
                    "retention.cleanup_interval_minutes": 60,
                    "retention.events_retention_days": 10,
                    "retention.media_retention_days": 5,
                    "retention.max_screenshots_mb": 2048,
                }
            ),
            clock=_Clock(),
        )
        policy = RetentionPolicy.from_settings(service)

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
                    "frame_path_entry": str(media_file),
                    "plate_path_entry": "",
                    "frame_path_exit": "",
                    "plate_path_exit": "",
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
