import copy
import tempfile
import unittest
from pathlib import Path

import yaml

from anpr.infrastructure.settings_manager import SettingsManager
from anpr.infrastructure.settings_normalizer import SettingsNormalizer
from anpr.infrastructure.settings_schema import (
    SETTINGS_LINEAGE,
    SETTINGS_LINEAGE_KEY,
    SETTINGS_VERSION,
    build_default_settings,
)


class SettingsCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.normalizer = SettingsNormalizer()

    def test_legacy_config_is_upgraded(self) -> None:
        data = {
            "settings_version": 2,
            "tracking": {"best_shots": 3, "direction": {"history_size": 10}},
            "channels": [{"name": "legacy", "region": {"x": 5, "y": 10, "width": 20, "height": 30}}],
        }

        normalized, changed = self.normalizer.normalize_with_meta(data)

        self.assertTrue(changed)
        self.assertEqual(normalized["settings_version"], SETTINGS_VERSION)
        self.assertEqual(normalized[SETTINGS_LINEAGE_KEY], SETTINGS_LINEAGE)
        self.assertIn("confidence_threshold", normalized["tracking"]["direction"])
        self.assertEqual(normalized["channels"][0]["region"]["unit"], "percent")

    def test_config_without_settings_version_supported(self) -> None:
        data = {
            "channels": [{"name": "cam-1", "region": {"x": 10, "y": 20, "width": 30, "height": 40}}],
        }

        normalized, changed = self.normalizer.normalize_with_meta(data)

        self.assertTrue(changed)
        self.assertEqual(normalized["settings_version"], SETTINGS_VERSION)
        self.assertEqual(normalized[SETTINGS_LINEAGE_KEY], SETTINGS_LINEAGE)
        self.assertEqual(normalized["channels"][0]["region"]["unit"], "percent")

    def test_already_current_config_stays_stable(self) -> None:
        data = build_default_settings()

        normalized, changed = self.normalizer.normalize_with_meta(data)

        self.assertFalse(changed)
        self.assertEqual(normalized, data)

    def test_second_normalization_is_idempotent(self) -> None:
        data = {
            "settings_version": 2,
            "channels": [{"name": "cam-1", "region": {"x": 10, "y": 20, "width": 30, "height": 40}}],
        }

        first_normalized, first_changed = self.normalizer.normalize_with_meta(copy.deepcopy(data))
        second_normalized, second_changed = self.normalizer.normalize_with_meta(first_normalized)

        self.assertTrue(first_changed)
        self.assertFalse(second_changed)
        self.assertEqual(first_normalized, second_normalized)

    def test_manager_init_upgrades_and_persists_file(self) -> None:
        legacy_data = {
            "settings_version": 2,
            "channels": [{"name": "cam-1", "region": {"x": 1, "y": 2, "width": 3, "height": 4}}],
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "settings.yaml"
            settings_path.write_text(yaml.safe_dump(legacy_data, allow_unicode=True, sort_keys=False), encoding="utf-8")

            manager = SettingsManager(path=str(settings_path))
            self.assertEqual(manager.settings["settings_version"], SETTINGS_VERSION)
            self.assertEqual(manager.settings[SETTINGS_LINEAGE_KEY], SETTINGS_LINEAGE)

            stored = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["settings_version"], SETTINGS_VERSION)
            self.assertEqual(stored[SETTINGS_LINEAGE_KEY], SETTINGS_LINEAGE)
            self.assertEqual(stored["channels"][0]["region"]["unit"], "percent")


    def test_current_lineage_future_version_raises_and_does_not_downgrade_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "settings.yaml"
            future_data = build_default_settings()
            future_data["settings_version"] = SETTINGS_VERSION + 1
            original_text = yaml.safe_dump(future_data, allow_unicode=True, sort_keys=False)
            settings_path.write_text(original_text, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "будущая версия схемы"):
                SettingsManager(path=str(settings_path))

            self.assertEqual(settings_path.read_text(encoding="utf-8"), original_text)

    def test_unknown_lineage_raises_and_refresh_does_not_rewrite_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "settings.yaml"
            current = build_default_settings()
            settings_path.write_text(yaml.safe_dump(current, allow_unicode=True, sort_keys=False), encoding="utf-8")
            manager = SettingsManager(path=str(settings_path))

            unknown_lineage = {
                SETTINGS_LINEAGE_KEY: "experimental",
                "settings_version": 1,
                "channels": [],
            }
            original_text = yaml.safe_dump(unknown_lineage, allow_unicode=True, sort_keys=False)
            settings_path.write_text(original_text, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Неподдерживаемая линия схемы"):
                manager.refresh()

            self.assertEqual(settings_path.read_text(encoding="utf-8"), original_text)

    def test_manager_refresh_upgrades_and_persists_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "settings.yaml"
            current = build_default_settings()
            settings_path.write_text(yaml.safe_dump(current, allow_unicode=True, sort_keys=False), encoding="utf-8")
            manager = SettingsManager(path=str(settings_path))

            legacy_after_external_update = {
                "settings_version": 2,
                "channels": [{"name": "cam-2", "region": {"x": 7, "y": 8, "width": 9, "height": 10}}],
            }
            settings_path.write_text(
                yaml.safe_dump(legacy_after_external_update, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

            manager.refresh()

            self.assertEqual(manager.settings["settings_version"], SETTINGS_VERSION)
            self.assertEqual(manager.settings[SETTINGS_LINEAGE_KEY], SETTINGS_LINEAGE)
            persisted = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["settings_version"], SETTINGS_VERSION)
            self.assertEqual(persisted[SETTINGS_LINEAGE_KEY], SETTINGS_LINEAGE)
            self.assertEqual(persisted["channels"][0]["region"]["unit"], "percent")


if __name__ == "__main__":
    unittest.main()
