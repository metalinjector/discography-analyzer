from __future__ import annotations

import unittest
from pathlib import Path

from discography_analyzer.online.panel import OnlineTagsPanel
from discography_analyzer.utilities_dialog import UTILITY_PANELS, UtilityContext
from discography_analyzer.utility_panel import BackgroundUtilityPanel, UtilityPanel


class UtilityRegistryTests(unittest.TestCase):
    def test_every_panel_is_listed_with_a_title_and_a_description(self) -> None:
        self.assertIn(OnlineTagsPanel, UTILITY_PANELS)
        self.assertTrue(issubclass(OnlineTagsPanel, BackgroundUtilityPanel))
        for panel in UTILITY_PANELS:
            with self.subTest(panel=panel.__name__):
                self.assertTrue(issubclass(panel, UtilityPanel))
                self.assertTrue(panel.title)
                self.assertTrue(panel.description)
        self.assertEqual(len({panel.title for panel in UTILITY_PANELS}), len(UTILITY_PANELS))

    def test_the_selected_folder_is_optional(self) -> None:
        context = UtilityContext(
            root_folder=Path("/music"),
            include_subfolders=True,
            excluded_folders=(),
            extensions=frozenset({".flac"}),
            backup_enabled=True,
            on_backup_changed=lambda _enabled: None,
            on_completed=lambda _root: None,
        )

        self.assertIsNone(context.selected_folder)


if __name__ == "__main__":
    unittest.main()
