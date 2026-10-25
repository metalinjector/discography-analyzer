import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from discography_analyzer.constants import TABLE_COLUMNS
from discography_analyzer.models import Track, TrackStatus
from discography_analyzer.parsing import files_word
from discography_analyzer.ui import (
    DiscographyAnalyzerApp,
    _responsive_group_width,
)


def track(
    identifier: str,
    status: TrackStatus,
    *,
    related: list[str],
    source: str | None = None,
    variation: str = "",
) -> Track:
    path = Path(f"/music/{identifier}.flac")
    return Track(
        id=identifier,
        path=path,
        root=Path("/music"),
        filename=path.name,
        relative_path=path.name,
        relative_folder="Album",
        format="FLAC",
        size_bytes=1024,
        base_title="Song",
        filename_title="Song",
        comparison_title="Song",
        status=status,
        related_track_ids=related,
        source_track_id=source,
        variation=variation,
    )


class UiGroupingTests(unittest.TestCase):
    def app_with(self, tracks: list[Track]) -> DiscographyAnalyzerApp:
        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        app.track_by_id = {item.id: item for item in tracks}
        app.variation_source_ids = {
            item.source_track_id for item in tracks if item.source_track_id
        }
        app.sort_column = None
        app.sort_reverse = False
        return app

    def test_variation_tab_includes_source_in_expandable_group(self) -> None:
        source = track(
            "source",
            TrackStatus.UNIQUE,
            related=["live", "remix"],
        )
        live = track(
            "live",
            TrackStatus.VARIATION,
            related=["source"],
            source="source",
            variation="Live",
        )
        remix = track(
            "remix",
            TrackStatus.VARIATION,
            related=["source"],
            source="source",
            variation="Remix",
        )
        app = self.app_with([source, live, remix])

        entries, visible = app._build_relation_groups([live, remix], "")

        self.assertEqual(len(entries), 1)
        representative, members = entries[0]
        self.assertIs(representative, source)
        self.assertEqual({item.id for item in members}, {"source", "live", "remix"})
        self.assertEqual({item.id for item in visible}, {"live", "remix"})

    def test_duplicate_tab_keeps_duplicates_together(self) -> None:
        first = track("first", TrackStatus.DUPLICATE, related=["second"])
        second = track("second", TrackStatus.DUPLICATE, related=["first"])
        app = self.app_with([first, second])

        entries, visible = app._build_relation_groups([first, second], "")

        self.assertEqual(len(entries), 1)
        self.assertEqual({item.id for item in entries[0][1]}, {"first", "second"})
        self.assertEqual({item.id for item in visible}, {"first", "second"})

    def test_file_count_uses_correct_russian_word_form(self) -> None:
        expected = {
            2: "файла",
            5: "файлов",
            11: "файлов",
            21: "файл",
            22: "файла",
            111: "файлов",
        }
        self.assertEqual(
            {count: files_word(count) for count in expected},
            expected,
        )

    def test_group_column_width_grows_with_viewport(self) -> None:
        self.assertEqual(_responsive_group_width(800), 335)
        self.assertEqual(_responsive_group_width(1000), 380)
        self.assertEqual(_responsive_group_width(2000), 620)

    def test_manual_group_column_width_is_retained(self) -> None:
        class FakeTab:
            def get(self) -> str:
                return "all"

        class FakeTree:
            def __init__(self) -> None:
                self.width = 510
                self.stretch = True

            def cget(self, _name: str):
                return ("tree", "headings")

            def column(self, _column: str, option: str | None = None, **values):
                if option == "width":
                    return self.width
                if "width" in values:
                    self.width = values["width"]
                if "stretch" in values:
                    self.stretch = values["stretch"]

        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        app.current_tab = FakeTab()
        app.tree = FakeTree()
        app._group_column_width = None

        app._capture_group_column_width()

        self.assertEqual(app._group_column_width, 510)
        self.assertEqual(app.tree.width, 510)
        self.assertFalse(app.tree.stretch)

    def test_relation_refresh_reuses_manual_group_width(self) -> None:
        class FakeTree:
            def __init__(self) -> None:
                self.width = 0
                self.stretch = True

            def configure(self, **_values) -> None:
                pass

            def heading(self, *_args, **_values) -> None:
                pass

            def winfo_width(self) -> int:
                return 1400

            def column(self, _column: str, **values) -> None:
                self.width = values["width"]
                self.stretch = values["stretch"]

        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        app.tree = FakeTree()
        app._group_column_width = 510

        app._insert_relation_groups([])

        self.assertEqual(app.tree.width, 510)
        self.assertFalse(app.tree.stretch)

    def test_manual_widths_disable_stretch_for_every_data_column(self) -> None:
        class FakeTab:
            def get(self) -> str:
                return "all"

        class FakeTree:
            def __init__(self) -> None:
                self.widths = {
                    column_id: 100 + index
                    for index, (column_id, _heading, _width) in enumerate(
                        TABLE_COLUMNS
                    )
                }
                self.stretch: dict[str, bool] = {}

            def column(self, column_id: str, option=None, **values):
                if option == "width":
                    return self.widths[column_id]
                if "width" in values:
                    self.widths[column_id] = values["width"]
                if "stretch" in values:
                    self.stretch[column_id] = values["stretch"]

            def cget(self, _name: str):
                return ("headings",)

        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        app.current_tab = FakeTab()
        app.tree = FakeTree()
        app._column_widths = {}
        app._folder_column_width = None
        app._group_column_width = None

        app._capture_column_widths()

        self.assertEqual(app._column_widths["base_title"], 101)
        self.assertTrue(app.tree.stretch)
        self.assertTrue(all(not value for value in app.tree.stretch.values()))

    def test_filter_typing_is_debounced(self) -> None:
        class FakeRoot:
            def __init__(self) -> None:
                self.callbacks: dict[str, object] = {}
                self.cancelled: list[str] = []
                self.counter = 0

            def after(self, delay: int, callback):
                self.assert_delay = delay
                self.counter += 1
                job_id = f"job-{self.counter}"
                self.callbacks[job_id] = callback
                return job_id

            def after_cancel(self, job_id: str) -> None:
                self.cancelled.append(job_id)
                self.callbacks.pop(job_id, None)

        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        app.root = FakeRoot()
        app._filter_job = None
        refreshes: list[bool] = []
        app.refresh_table = lambda: refreshes.append(True)

        app._schedule_filter()
        app._schedule_filter()
        callback = app.root.callbacks[app._filter_job]
        callback()

        self.assertEqual(app.root.assert_delay, 250)
        self.assertEqual(app.root.cancelled, ["job-1"])
        self.assertEqual(refreshes, [True])
        self.assertIsNone(app._filter_job)

    def test_folder_named_root_does_not_collide_with_tree_root(self) -> None:
        class FakeTree:
            def __init__(self) -> None:
                self.item_ids: set[str] = set()

            def configure(self, **_values) -> None:
                pass

            def column(self, *_args, **_values) -> None:
                pass

            def insert(self, _parent, _index, *, iid: str, **_values) -> str:
                if iid in self.item_ids:
                    raise AssertionError(f"duplicate iid: {iid}")
                self.item_ids.add(iid)
                return iid

        item = track("track", TrackStatus.UNIQUE, related=[])
        item.relative_folder = "ROOT"
        item.relative_path = "ROOT/track.flac"
        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        app.result = SimpleNamespace(
            root=Path("/music"),
            completeness_issues=[],
        )
        app.tree = FakeTree()
        app._folder_column_width = None

        app._insert_folder_tree([item])

        self.assertEqual(len(app.tree.item_ids), 3)

    def test_analysis_error_resets_results_and_widgets(self) -> None:
        class FakeValue:
            def __init__(self, value="") -> None:
                self.value = value

            def set(self, value) -> None:
                self.value = value

        class FakeTree:
            def __init__(self) -> None:
                self.deleted: tuple[str, ...] = ()

            def get_children(self):
                return ("old-row",)

            def delete(self, *items) -> None:
                self.deleted = items

        class FakeWidget:
            def __init__(self) -> None:
                self.options: dict[str, object] = {}
                self.text = "old info"

            def configure(self, **values) -> None:
                self.options.update(values)

            def delete(self, *_args) -> None:
                self.text = ""

            def insert(self, _index, text) -> None:
                self.text += text

        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        app._restore_buttons = lambda: None
        app.progress_state_var = FakeValue()
        app.result = object()
        app.track_by_id = {"old": object()}
        app.variation_source_ids = {"old"}
        app.issue_by_id = {"old": object()}
        app.audit_issue_by_id = {"old": object()}
        app.audit_item_track_ids = {"old": "old"}
        app.visible_tracks = [object()]
        app.tree = FakeTree()
        app.statistics_var = FakeValue()
        app.shown_count_var = FakeValue("12 из 12")
        app.unique_copy_button = FakeWidget()
        app.audit_fix_button = FakeWidget()
        app.info_text = FakeWidget()
        app.cover_label = FakeWidget()
        app.cover_photo = object()
        app.root = object()

        with patch("discography_analyzer.ui.messagebox.showerror"):
            app._analysis_failed("test", generic=True)

        self.assertIsNone(app.result)
        self.assertEqual(app.track_by_id, {})
        self.assertEqual(app.variation_source_ids, set())
        self.assertEqual(app.issue_by_id, {})
        self.assertEqual(app.audit_issue_by_id, {})
        self.assertEqual(app.audit_item_track_ids, {})
        self.assertEqual(app.visible_tracks, [])
        self.assertEqual(app.tree.deleted, ("old-row",))
        self.assertEqual(app.shown_count_var.value, "0 из 0")
        self.assertEqual(app.statistics_var.value, "Статистика: —")
        self.assertEqual(app.unique_copy_button.options, {"state": "disabled"})
        self.assertEqual(app.audit_fix_button.options, {"state": "disabled"})
        self.assertEqual(app.info_text.text, "Выберите трек в таблице")
        self.assertIsNone(app.cover_photo)
        self.assertEqual(app.cover_label.options["text"], "Обложка не выбрана")

    def test_folder_tree_can_expand_and_collapse_in_one_action(self) -> None:
        class FakeTab:
            def get(self) -> str:
                return "folders"

        class FakeBool:
            def get(self) -> bool:
                return True

        class FakeTree:
            def __init__(self) -> None:
                self.children = {
                    "": ("root",),
                    "root": ("artist",),
                    "artist": ("album",),
                    "album": ("track",),
                    "track": (),
                }
                self.opened: dict[str, bool] = {}

            def get_children(self, item_id=""):
                return self.children[item_id]

            def item(self, item_id: str, **values):
                if "open" in values:
                    self.opened[item_id] = values["open"]

        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        app.current_tab = FakeTab()
        app.folder_tree_mode_var = FakeBool()
        app.tree = FakeTree()

        app._set_folder_tree_open(False)
        self.assertTrue(app.tree.opened["root"])
        self.assertFalse(app.tree.opened["artist"])
        self.assertFalse(app.tree.opened["album"])

        app._set_folder_tree_open(True)
        self.assertTrue(all(app.tree.opened.values()))


if __name__ == "__main__":
    unittest.main()
