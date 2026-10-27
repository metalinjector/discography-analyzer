from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from discography_analyzer import ui as ui_module
from discography_analyzer.online.panel import OnlineTagsPanel
from discography_analyzer.ui import DiscographyAnalyzerApp
from discography_analyzer.utilities_dialog import FOLDER_ACTIONS, UTILITY_PANELS

RIGHT_CLICK = SimpleNamespace(x_root=10, y_root=20, y=5)


class FakeTree:
    def __init__(self, row: str) -> None:
        self.row = row
        self.selected = ""
        self.focused = ""

    def identify_row(self, _y: int) -> str:
        return self.row

    def selection_set(self, row: str) -> None:
        self.selected = row

    def focus(self, row: str | None = None) -> str:
        if row is not None:
            self.focused = row
        return self.focused


class FakeMenu:
    def __init__(self) -> None:
        self.popped_at: tuple[int, int] | None = None

    def tk_popup(self, x: int, y: int) -> None:
        self.popped_at = (x, y)

    def entryconfigure(self, _label: str, **_options) -> None:
        pass


def app_on(row: str, tracks=()) -> DiscographyAnalyzerApp:
    app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
    app.tree = FakeTree(row)
    app.result = SimpleNamespace(root=Path("/music"))
    app.track_by_id = {track.id: track for track in tracks}
    app.audit_item_track_ids = {}
    app.menu_folder = None
    app.context_menu = FakeMenu()
    app.folder_menu = FakeMenu()
    app._refresh_numbering_button = lambda: None
    return app


class FolderMenuTests(unittest.TestCase):
    def test_the_menu_has_the_fill_tags_action_of_the_online_utility(self) -> None:
        self.assertIn(("Заполнить теги из интернета…", OnlineTagsPanel), FOLDER_ACTIONS)
        for _label, panel in FOLDER_ACTIONS:
            self.assertIn(panel, UTILITY_PANELS)

    def test_a_release_folder_row_opens_the_folder_menu_for_that_folder(self) -> None:
        app = app_on("folder-path::Artist/2015 - Album")

        app._show_context_menu(RIGHT_CLICK)

        self.assertEqual(app.folder_menu.popped_at, (10, 20))
        self.assertIsNone(app.context_menu.popped_at)
        self.assertEqual(app.menu_folder, Path("/music", "Artist", "2015 - Album"))
        # The row the menu belongs to is the selected one.
        self.assertEqual(app.tree.selected, "folder-path::Artist/2015 - Album")

    def test_the_collection_folder_row_is_a_folder_too(self) -> None:
        app = app_on("folder-root::node")

        app._show_context_menu(RIGHT_CLICK)

        self.assertEqual(app.folder_menu.popped_at, (10, 20))
        self.assertEqual(app.menu_folder, Path("/music"))

    def test_a_track_row_keeps_its_menu_and_acts_on_the_track_folder(self) -> None:
        song = SimpleNamespace(
            id="t1", path=Path("/music/Artist/Album/01.flac"), source_track_id=""
        )
        app = app_on("t1", [song])

        app._show_context_menu(RIGHT_CLICK)

        self.assertEqual(app.context_menu.popped_at, (10, 20))
        self.assertIsNone(app.folder_menu.popped_at)
        self.assertEqual(app.menu_folder, Path("/music/Artist/Album"))

    def test_a_click_beside_the_rows_opens_nothing(self) -> None:
        app = app_on("")

        app._show_context_menu(RIGHT_CLICK)

        self.assertIsNone(app.folder_menu.popped_at)
        self.assertIsNone(app.context_menu.popped_at)

    def test_the_action_opens_that_utility_with_the_folder_already_chosen(self) -> None:
        app = app_on("folder-path::Artist/Album")
        app.root = None
        app.folder_var = SimpleNamespace(get=lambda: "/music")
        app.include_subfolders_var = SimpleNamespace(get=lambda: True)
        app.settings = SimpleNamespace(excluded_folders=[], backup_before_tag_writes=True)
        app._style_toplevel = lambda _window: None
        app._show_context_menu(RIGHT_CLICK)

        with mock.patch.object(ui_module, "UtilitiesDialog") as dialog:
            app._open_folder_utility(OnlineTagsPanel)

        (_parent, context), options = dialog.call_args
        self.assertEqual(options, {"first": OnlineTagsPanel})
        self.assertEqual(context.selected_folder, Path("/music/Artist/Album"))
        self.assertEqual(context.root_folder, Path("/music"))


if __name__ == "__main__":
    unittest.main()
