from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from discography_analyzer.online import panel as panel_module
from discography_analyzer.online.lookup import AlbumLookup, Candidate
from discography_analyzer.online.panel import OnlineTagsPanel
from discography_analyzer.online.release import AlbumQuery, Release, ReleaseTrack
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


class VariantTrackListTests(unittest.TestCase):
    """Moving through the variants while a track list loads (Apple: one request in 3 s)."""

    class Status:
        def __init__(self) -> None:
            self.text = ""

        def set(self, text: str) -> None:
            self.text = text

    def setUp(self) -> None:
        self.loaded: list[Candidate] = []
        self.started: list = []
        self.events: list[tuple] = []
        panel = OnlineTagsPanel.__new__(OnlineTagsPanel)
        panel.lookups = {}
        panel.current = None
        panel.details_loading = None
        panel.busy = False
        panel.cache = None
        panel.frame = None
        panel.status_var = self.Status()
        panel._provider = lambda _key: None
        panel._refresh_album = lambda _row: None
        panel._refresh_summary = lambda: None
        panel.post = lambda *event: self.events.append(event)
        self.panel = panel
        self.lookup = AlbumLookup(
            album=None,
            query=AlbumQuery("Artist", "Album"),
            candidates=[
                Candidate(Release("apple", str(number), f"Variant {number}", "Artist"), 0)
                for number in range(3)
            ],
        )
        panel.lookups["album-0"] = self.lookup
        panel.current = "album-0"

        def load_details(_provider, candidate, _album, _cache):
            self.loaded.append(candidate)
            candidate.release = replace(candidate.release, tracks=(ReleaseTrack(1, 1, "Song"),))

        started = self.started

        class Thread:
            """Holds the loading thread's work until the test runs it."""

            def __init__(self, target, daemon) -> None:
                self.target = target

            def start(self) -> None:
                started.append(self.target)

        patches = [
            mock.patch.object(panel_module, "load_details", load_details),
            mock.patch.object(panel_module.threading, "Thread", Thread),
            mock.patch.object(panel_module.messagebox, "showerror"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.showerror = panel_module.messagebox.showerror

    def choose(self, index: int) -> None:
        self.lookup.chosen = index
        self.panel._load_chosen_details()

    def finish(self) -> None:
        """The loading thread runs; its event reaches the Tk thread."""
        self.started.pop(0)()
        self.panel._details_done(*self.events.pop(0)[1:])

    def test_only_one_list_loads_and_the_last_choice_comes_next(self) -> None:
        candidates = self.lookup.candidates
        self.choose(0)
        self.choose(1)  # passed over while the first list loads
        self.choose(2)

        self.assertEqual(len(self.started), 1)
        self.finish()
        self.finish()

        self.assertEqual(self.loaded, [candidates[0], candidates[2]])
        self.assertIsNone(self.panel.details_loading)
        self.assertEqual(self.panel.status_var.text, "Готово")

    def test_a_failed_list_of_a_variant_passed_over_stays_quiet(self) -> None:
        candidates = self.lookup.candidates
        self.choose(0)
        self.choose(1)
        self.started.pop(0)
        self.panel._details_done("album-0", self.lookup, candidates[0], "timed out")

        self.assertEqual(self.lookup.chosen, 1)
        self.showerror.assert_not_called()
        self.assertIs(self.panel.details_loading, candidates[1])

    def test_a_failed_list_of_the_chosen_variant_unselects_it(self) -> None:
        candidates = self.lookup.candidates
        self.choose(0)
        self.started.pop(0)
        self.panel._details_done("album-0", self.lookup, candidates[0], "timed out")

        self.assertIsNone(self.lookup.chosen)
        self.showerror.assert_called_once()
        self.assertEqual(self.panel.status_var.text, "Не удалось загрузить трек-лист")

    def test_an_answer_for_an_album_a_new_search_replaced_is_ignored(self) -> None:
        old = self.lookup
        self.choose(0)
        self.panel.lookups["album-0"] = replace(old, candidates=list(old.candidates), chosen=None)
        self.started.pop(0)
        self.panel._details_done("album-0", old, old.candidates[0], "timed out")

        self.showerror.assert_not_called()
        self.assertIsNone(self.panel.details_loading)


if __name__ == "__main__":
    unittest.main()
