import io
from zipfile import ZipFile

from config.settings_normalizer import SettingsNormalizer
from config.settings_schema import build_default_settings
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

    def test_normalizer_removes_obsolete_ocr_section(self):
        normalizer = SettingsNormalizer()
        raw = {
            "ocr": {
                "img_height": 32,
                "img_width": 128,
                "alphabet": "0123456789ABCEHKMOPTXY",
            }
        }

        normalized, changed = normalizer.normalize_with_meta(raw)

        assert changed is True
        assert "ocr" not in normalized

    def test_normalizer_removes_obsolete_detector_section(self):
        normalizer = SettingsNormalizer()
        raw = {
            "detector": {
                "confidence_threshold": 0.5,
                "bbox_padding_ratio": 0.08,
                "min_padding_pixels": 2,
            }
        }

        normalized, changed = normalizer.normalize_with_meta(raw)

        assert changed is True
        assert "detector" not in normalized

    def test_default_settings_do_not_include_detector_contract(self):
        defaults = build_default_settings()

        assert "detector" not in defaults

    def test_default_settings_do_not_include_ocr_contract(self):
        defaults = build_default_settings()

        assert "ocr" not in defaults

    def test_normalizer_removes_obsolete_inference_section(self):
        normalizer = SettingsNormalizer()
        raw = {
            "inference": {
                "workers": 2,
                "shared_memory": True,
            }
        }

        normalized, changed = normalizer.normalize_with_meta(raw)

        assert changed is True
        assert "inference" not in normalized


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


class TestUiSettingsNormalization:
    def test_default_settings_include_graphite_ui_style(self):
        defaults = build_default_settings()

        assert defaults["ui"] == {
            "style": "graphite",
            "theme": "light",
            "grid": "2x2",
            "sidebar_locked": False,
        }

    def test_normalizer_fills_missing_ui_defaults(self):
        normalizer = SettingsNormalizer()
        raw = {}

        normalized, changed = normalizer.normalize_with_meta(raw)

        assert changed is True
        assert normalized["ui"]["style"] == "graphite"
        assert normalized["ui"]["theme"] == "light"
        assert normalized["ui"]["grid"] == "2x2"
        assert normalized["ui"]["sidebar_locked"] is False

    def test_normalizer_preserves_valid_modern_ui_style(self):
        normalizer = SettingsNormalizer()
        raw = {"ui": {"style": "modern", "theme": "dark", "grid": "3x3", "sidebar_locked": True}}

        normalized, changed = normalizer.normalize_with_meta(raw)

        assert changed is True
        assert normalized["ui"]["style"] == "modern"
        assert normalized["ui"]["theme"] == "dark"
        assert normalized["ui"]["grid"] == "3x3"
        assert normalized["ui"]["sidebar_locked"] is True

    def test_normalizer_resets_invalid_ui_values(self):
        normalizer = SettingsNormalizer()
        raw = {"ui": {"style": "unknown", "theme": "blue", "grid": "4x4", "sidebar_locked": ""}}

        normalized, changed = normalizer.normalize_with_meta(raw)

        assert changed is True
        assert normalized["ui"]["style"] == "graphite"
        assert normalized["ui"]["theme"] == "light"
        assert normalized["ui"]["grid"] == "2x2"
        assert normalized["ui"]["sidebar_locked"] is False
