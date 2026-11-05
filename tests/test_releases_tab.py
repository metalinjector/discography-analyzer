from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from discography_analyzer.constants import TABLE_COLUMNS
from discography_analyzer.models import AnalysisResult, Track
from discography_analyzer.releases import build_releases
from discography_analyzer.ui import DiscographyAnalyzerApp

ROOT = Path("/music")
COLUMN_IDS = [item[0] for item in TABLE_COLUMNS]
# A release folder is the track folder as scanned; for «CD1» it is its parent
# as the OS spells it.
IRRLICHT = "release::Klaus Schulze/Irrlicht::irrlicht"
MOOG = f"release::{Path('Klaus Schulze/Moog')}::moog"


def make(folder: str, number: int, total: int, disc: str = "", **values) -> Track:
    path = ROOT / folder / f"{number:02d}.flac"
    return Track(
        id=f"{folder}/{disc}/{number}",
        path=path,
        root=ROOT,
        filename=path.name,
        relative_path=f"{folder}/{path.name}",
        relative_folder=folder,
        format="FLAC",
        size_bytes=1024 * 1024,
        track_number=f"{number}/{total}",
        disc_number=disc,
        **values,
    )


def collection() -> list[Track]:
    box = [
        make("Klaus Schulze/Moog/CD1", number, 18, "1/4", album="Moog", year="1996")
        for number in range(1, 7)
    ] + [
        make("Klaus Schulze/Moog/CD2", number, 18, "2/4", album="Moog", year="1996")
        for number in range(1, 7)
    ]
    # Three tracks of 17.5 minutes: an album by length, not a single.
    irrlicht = [
        make(
            "Klaus Schulze/Irrlicht",
            number,
            3,
            album="Irrlicht",
            year="1972",
            duration_exact=1050.0,
            duration_seconds=1050,
        )
        for number in (2, 1, 3)
    ]
    for track in irrlicht:
        track.all_tags = {"label": ["Brain"]}
    return box + irrlicht


class Var:
    def __init__(self, value) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class Widget:
    def configure(self, **_options) -> None:
        pass


class FakeTree:
    def __init__(self, focused: str = "") -> None:
        self.rows: dict[str, dict] = {}
        self.children: dict[str, list[str]] = {"": []}
        self.headings: dict[str, str] = {}
        self.focused = focused

    def configure(self, **_values) -> None:
        pass

    def column(self, *_args, **_values) -> None:
        pass

    def heading(self, column: str, **values) -> None:
        self.headings[column] = values.get("text", "")

    def insert(self, parent: str, _index, *, iid: str, **values) -> str:
        self.rows[iid] = dict(values, parent=parent)
        self.children.setdefault(parent, []).append(iid)
        self.children.setdefault(iid, [])
        return iid

    def get_children(self, item_id: str = "") -> tuple[str, ...]:
        return tuple(self.children.get(item_id, ()))

    def delete(self, *_items) -> None:
        self.rows.clear()
        self.children = {"": []}

    def selection(self) -> tuple[str, ...]:
        return (self.focused,) if self.focused else ()

    def selection_set(self, item_id: str) -> None:
        self.focused = item_id

    def focus(self, item_id: str | None = None) -> str:
        if item_id is not None:
            self.focused = item_id
        return self.focused

    def exists(self, item_id: str) -> bool:
        return item_id in self.rows

    def item(self, item_id: str, option: str | None = None, **values):
        if values:
            self.rows[item_id].update(values)
            return None
        return self.rows[item_id].get(option) if option else self.rows[item_id]

    def winfo_width(self) -> int:
        return 1200


def releases_app(focused: str = "") -> DiscographyAnalyzerApp:
    tracks = collection()
    app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
    app.result = AnalysisResult(
        tracks=tracks,
        folders_scanned=3,
        root=ROOT,
        releases=build_releases(tracks, ROOT),
    )
    app.track_by_id = {track.id: track for track in tracks}
    app.release_by_id = {release.id: release for release in app.result.releases}
    app.tree = FakeTree(focused)
    app.current_tab = Var("releases")
    app.filter_var = Var("")
    app.folder_tree_mode_var = Var(True)
    for name in (
        "folder_tree_check",
        "expand_tree_button",
        "collapse_tree_button",
        "audit_fix_button",
    ):
        setattr(app, name, Widget())
    app.shown_count_var = Var("")
    app.group_labels = {}
    app.group_members = {}
    app.audit_item_track_ids = {}
    app.sort_column = "track_number"
    app.sort_reverse = False
    app.release_sort_column = None
    app.release_sort_reverse = False
    app._group_column_width = 300
    app._refresh_numbering_button = lambda: None
    return app


def cell(app: DiscographyAnalyzerApp, item_id: str, column: str):
    return app.tree.rows[item_id]["values"][COLUMN_IDS.index(column)]


class ReleasesTabTests(unittest.TestCase):
    def test_release_rows_hold_their_tracks_in_disc_and_number_order(self) -> None:
        app = releases_app()

        app.refresh_table()

        rows = app.tree.get_children("")
        self.assertEqual(rows, (IRRLICHT, MOOG))
        self.assertEqual(app.tree.rows[IRRLICHT]["text"], "[+] Irrlicht (1972)")
        self.assertEqual(app.tree.rows[IRRLICHT]["tags"], ("ReleaseComplete",))
        self.assertEqual(cell(app, IRRLICHT, "status"), "● Полный")
        self.assertEqual(cell(app, IRRLICHT, "title"), "Brain")
        self.assertEqual(cell(app, IRRLICHT, "variation"), "Album *")
        self.assertEqual(app.tree.rows[MOOG]["tags"], ("ReleaseIncomplete",))
        self.assertEqual(cell(app, MOOG, "track_number"), "12/18 · 4 CD")
        self.assertEqual(cell(app, MOOG, "status"), "● Не хватает 6")
        children = app.tree.get_children(IRRLICHT)
        self.assertEqual(
            [app.tree.rows[item]["text"] for item in children],
            ["01 · 01.flac", "02 · 02.flac", "03 · 03.flac"],
        )
        self.assertTrue(
            app.tree.rows[app.tree.get_children(MOOG)[6]]["text"].startswith("CD2 · 01")
        )
        self.assertEqual(app.shown_count_var.value, "2 из 2 релизов")
        self.assertEqual(app.tree.headings["status"], "Комплект")
        self.assertEqual(app.tree.headings["#0"], "Релизы и треки")
        # Track tabs keep their own sort: the release tab sorts on its own.
        self.assertEqual(app.sort_column, "track_number")

    def test_sorting_and_filtering_release_rows(self) -> None:
        app = releases_app()

        app.sort_by("status")

        self.assertEqual(app.release_sort_column, "status")
        self.assertEqual(app.sort_column, "track_number")
        # Incomplete releases first.
        self.assertEqual(app.tree.get_children(""), (MOOG, IRRLICHT))
        self.assertEqual(app.tree.headings["status"], "Комплект ▲")

        app.filter_var.set("brain")
        app.refresh_table()

        self.assertEqual(app.tree.get_children(""), (IRRLICHT,))
        self.assertEqual(app.shown_count_var.value, "1 из 2 релизов")

    def test_selecting_a_release_shows_its_card(self) -> None:
        class FakeText:
            def __init__(self) -> None:
                self.text = ""

            def configure(self, **_values) -> None:
                pass

            def delete(self, *_args) -> None:
                self.text = ""

            def insert(self, _index, text: str) -> None:
                self.text += text

        app = releases_app(focused=MOOG)
        app.info_text = FakeText()
        app.cover_label = Widget()

        app._selection_changed()

        self.assertTrue(app.info_text.text.startswith("РЕЛИЗ\nMoog (1996)\n"))
        self.assertIn("• нет дисков 3, 4", app.info_text.text)

    def test_a_release_row_opens_the_menu_of_its_folder(self) -> None:
        class Menu:
            def __init__(self) -> None:
                self.popped = False

            def tk_popup(self, *_args) -> None:
                self.popped = True

        app = releases_app()
        app.refresh_table()
        app.tree.identify_row = lambda _y: MOOG
        app.folder_menu = Menu()
        app.context_menu = Menu()

        app._show_context_menu(SimpleNamespace(x_root=1, y_root=2, y=3))

        self.assertTrue(app.folder_menu.popped)
        self.assertFalse(app.context_menu.popped)
        self.assertEqual(app.menu_folder, ROOT / "Klaus Schulze" / "Moog")
        self.assertEqual(app._selected_folder(), ROOT / "Klaus Schulze" / "Moog")
        self.assertEqual(len(app._playlist_tracks()), 12)

    def test_expand_and_collapse_all_releases(self) -> None:
        app = releases_app()
        app.refresh_table()
        app.root = SimpleNamespace(after_idle=lambda callback: callback())

        app._set_folder_tree_open(True)

        self.assertTrue(all(app.tree.rows[row]["open"] for row in app.tree.get_children("")))
        self.assertEqual(app.tree.rows[IRRLICHT]["text"], "[-] Irrlicht (1972)")
        app._set_folder_tree_open(False)
        self.assertEqual(app.tree.rows[MOOG]["text"], "[+] Moog (1996)")

    def test_a_release_short_of_discs_marks_its_folder_in_the_tree(self) -> None:
        app = releases_app()

        self.assertIn(("Klaus Schulze", "Moog"), app._folders_with_missing_numbers())
        self.assertNotIn(
            ("Klaus Schulze", "Moog", "CD1"), app._folders_with_missing_numbers()
        )
        # Gap checking switched off for the run: no marking from releases either.
        app.result.gaps_checked = False
        self.assertEqual(app._folders_with_missing_numbers(), set())

    def test_statistics_count_releases(self) -> None:
        app = releases_app()
        app.statistics_var = Var("")

        app._update_statistics()

        self.assertIn("релизов 2, неполных 1", app.statistics_var.value)

    def test_the_folder_summary_includes_the_releases_inside(self) -> None:
        class FakeText:
            def __init__(self) -> None:
                self.text = ""

            def configure(self, **_values) -> None:
                pass

            def delete(self, *_args) -> None:
                self.text = ""

            def insert(self, _index, text: str) -> None:
                self.text += text

        app = releases_app(focused="folder-path::Klaus Schulze")
        app.info_text = FakeText()
        app.cover_label = Widget()
        app.audit_issue_by_id = {}

        with patch("discography_analyzer.ui.find_folder_cover", return_value=None):
            app._selection_changed()

        self.assertIn("РЕЛИЗЫ\nВсего 2: полных 1 · неполных 1", app.info_text.text)


if __name__ == "__main__":
    unittest.main()
