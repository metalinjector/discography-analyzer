import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from discography_analyzer.constants import DEFAULT_REPORT_COLORS
from discography_analyzer.settings import AppSettings


class SettingsTests(unittest.TestCase):
    def test_settings_round_trip(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            settings = AppSettings(
                last_folder="/music",
                dark_theme=False,
                check_track_gaps=False,
                folder_tree_mode=True,
            )
            settings.save(path)
            restored = AppSettings.load(path)
            self.assertEqual(restored.last_folder, "/music")
            self.assertFalse(restored.dark_theme)
            self.assertFalse(restored.check_track_gaps)
            self.assertTrue(restored.folder_tree_mode)

    def test_folder_tree_is_enabled_by_default(self) -> None:
        self.assertTrue(AppSettings().folder_tree_mode)

    def test_disabled_remember_folder_does_not_persist_path(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            settings = AppSettings(
                last_folder="/private/music", remember_folder=False
            )
            settings.save(path)
            restored = AppSettings.load(path)
            self.assertEqual(restored.last_folder, "")

    def test_invalid_nested_values_are_safely_normalized(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "dark_theme": 0,
                        "folder_tree_mode": 1,
                        "variation_markers": [123, None, " Live ", "live", ""],
                        "excluded_folders": [" Temp ", 1, "temp"],
                        "formats": {"MP3": "false", "FLAC": False},
                        "report_colors": {
                            "Дубликат": 123,
                            "Вариация": "#abcdef",
                        },
                    }
                ),
                encoding="utf-8",
            )

            restored = AppSettings.load(path)

            self.assertTrue(restored.dark_theme)
            # An invalid value falls back to the default, which is now the tree.
            self.assertTrue(restored.folder_tree_mode)
            self.assertEqual(restored.variation_markers, ["Live"])
            self.assertEqual(restored.excluded_folders, ["Temp"])
            self.assertTrue(restored.formats["MP3"])
            self.assertFalse(restored.formats["FLAC"])
            self.assertEqual(
                restored.report_colors["Дубликат"],
                DEFAULT_REPORT_COLORS["Дубликат"],
            )
            self.assertEqual(restored.report_colors["Вариация"], "ABCDEF")


if __name__ == "__main__":
    unittest.main()
