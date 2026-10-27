import struct
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from discography_analyzer.audit_models import (
    AuditCategory,
    AuditSeverity,
    MetadataAuditIssue,
)
from discography_analyzer.constants import TABLE_COLUMNS
from discography_analyzer.models import AlbumCompletenessIssue, Track, TrackStatus
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

        expected = 100 + [
            column_id for column_id, _heading, _width in TABLE_COLUMNS
        ].index("base_title")
        self.assertEqual(app._column_widths["base_title"], expected)
        self.assertTrue(app.tree.stretch)
        self.assertTrue(all(not value for value in app.tree.stretch.values()))

    def test_russian_layout_shortcut_falls_back_to_the_key_code(self) -> None:
        # Real Windows/Tk 8.6 reports keysym "??" for every Cyrillic letter, so
        # the keysym bindings above cannot fire; the key code still identifies
        # the physical key and does not depend on the layout.
        event = SimpleNamespace(keysym="??", keycode=ord("O"))
        calls: list[str] = []
        result = DiscographyAnalyzerApp._shortcut_by_keycode(
            event, "o", lambda _event: calls.append("folder")
        )

        self.assertEqual(result, "break")
        self.assertEqual(calls, ["folder"])

        latin = SimpleNamespace(keysym="o", keycode=ord("O"))
        ignored = DiscographyAnalyzerApp._shortcut_by_keycode(
            latin, "o", lambda _event: calls.append("twice")
        )
        self.assertIsNone(ignored)
        self.assertEqual(calls, ["folder"])

        other_key = SimpleNamespace(keysym="??", keycode=ord("E"))
        self.assertIsNone(
            DiscographyAnalyzerApp._shortcut_by_keycode(
                other_key, "o", lambda _event: calls.append("wrong")
            )
        )
        self.assertEqual(calls, ["folder"])

    def test_text_fields_cut_copy_paste_from_key_codes(self) -> None:
        generated: list[str] = []

        class FakeEntry:
            def event_generate(self, virtual: str) -> None:
                generated.append(virtual)

        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        for keysym, keycode, expected in (
            ("??", ord("V"), "<<Paste>>"),
            ("??", ord("C"), "<<Copy>>"),
            ("??", ord("X"), "<<Cut>>"),
            ("??", ord("F"), None),
            ("v", ord("V"), None),
        ):
            generated.clear()
            result = app._text_shortcut_by_keycode(
                SimpleNamespace(keysym=keysym, keycode=keycode, widget=FakeEntry())
            )
            self.assertEqual(generated, [expected] if expected else [])
            self.assertEqual(result, "break" if expected else None)

    def test_named_keys_never_take_the_key_code_fallback(self) -> None:
        # On X11 the key code is the hardware code: F1, F3, F4 and keypad 7
        # are 67, 69, 70 and 79 - the ASCII codes of C, E, F and O - so
        # Ctrl+F3 opened the export and Ctrl+F1 copied. Only the unnamed "??"
        # of the Russian layout on Windows may fall back to the key code.
        calls: list[str] = []
        for keysym, keycode, letter in (
            ("F1", 67, "c"),
            ("F3", 69, "e"),
            ("F4", 70, "f"),
            ("KP_Home", 79, "o"),
        ):
            result = DiscographyAnalyzerApp._shortcut_by_keycode(
                SimpleNamespace(keysym=keysym, keycode=keycode),
                letter,
                lambda _event, keysym=keysym: calls.append(keysym),
            )
            self.assertIsNone(result)
        self.assertEqual(calls, [])

        generated: list[str] = []

        class FakeEntry:
            def event_generate(self, virtual: str) -> None:
                generated.append(virtual)

        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        result = app._text_shortcut_by_keycode(
            SimpleNamespace(keysym="F1", keycode=67, widget=FakeEntry())
        )
        self.assertIsNone(result)
        self.assertEqual(generated, [])

    def test_shortcuts_work_in_russian_layout_and_with_caps_lock(self) -> None:
        # Tk matches shortcuts by keysym: under the Russian layout the O key
        # reports "Cyrillic_shcha" and under Caps Lock "O", so a plain
        # <Control-o> binding silently did nothing in both cases.
        class FakeWidget:
            def __init__(self) -> None:
                self.bindings: dict[str, object] = {}
                self.virtual: dict[str, tuple[str, ...]] = {}

            def bind(self, sequence: str, callback, add=None) -> None:
                self.bindings[sequence] = callback

            def event_add(self, virtual: str, *sequences: str) -> None:
                self.virtual[virtual] = self.virtual.get(virtual, ()) + sequences

            def bind_class(self, *_args, **_kwargs) -> None:
                pass

        class FakeVar:
            def trace_add(self, *_args) -> None:
                pass

        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        app.root = FakeWidget()
        app.tree = FakeWidget()
        app.filter_entry = FakeWidget()
        app.filter_var = FakeVar()
        calls: list[str] = []
        app.choose_folder = lambda: calls.append("folder")
        app.open_export = lambda: calls.append("export")
        app.copy_selected = lambda: calls.append("copy")

        app._bind_actions()
        for keysym in ("o", "O", "Cyrillic_shcha", "Cyrillic_SHCHA"):
            app.root.bindings[f"<Control-{keysym}>"](None)
        app.root.bindings["<Control-Cyrillic_u>"](None)
        app.tree.bindings["<Control-Cyrillic_es>"](None)

        self.assertEqual(calls, ["folder"] * 4 + ["export", "copy"])
        self.assertIn("<Control-Cyrillic_a>", app.root.bindings)
        self.assertIn("<Escape>", app.filter_entry.bindings)
        # Text fields: Ctrl+V/C/X in the Russian layout reach Tk's own events.
        self.assertIn("<Control-Cyrillic_em>", app.root.virtual["<<Paste>>"])
        self.assertIn("<Control-Cyrillic_es>", app.root.virtual["<<Copy>>"])
        self.assertIn("<Control-Cyrillic_che>", app.root.virtual["<<Cut>>"])

    def test_utility_run_on_a_parent_folder_refreshes_the_analysis(self) -> None:
        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        app.result = SimpleNamespace(root=Path("/music/Artist"))
        app.worker = None
        runs: list[str] = []
        app.start_analysis = lambda: runs.append("analysis")

        # The parent of the analysed folder contains the analysed files too.
        app._utility_completed(Path("/music"))
        app._utility_completed(Path("/music/Artist/Album"))
        app._utility_completed(Path("/other"))

        self.assertEqual(runs, ["analysis", "analysis"])

    def test_utilities_get_the_folder_selected_in_the_main_window(self) -> None:
        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        app.result = None
        self.assertIsNone(app._selected_folder())

        app.result = SimpleNamespace(root=Path("/music"))
        focused = {"id": "folder-path::Metallica/1986 - Master of Puppets"}
        app.tree = SimpleNamespace(focus=lambda: focused["id"])
        selected = SimpleNamespace(path=Path("/music/Other/song.flac"))
        app._selected_track = lambda: selected

        self.assertEqual(
            app._selected_folder(), Path("/music/Metallica/1986 - Master of Puppets")
        )
        # A track row: the track's own folder.
        focused["id"] = "track-row"
        self.assertEqual(app._selected_folder(), Path("/music/Other"))
        # The root row names the whole collection, which is the default anyway.
        focused["id"] = "folder-root::node"
        self.assertEqual(app._selected_folder(), Path("/music/Other"))

    def test_cover_panel_never_keeps_the_previous_cover(self) -> None:
        # A cover above Pillow's pixel limit raised DecompressionBombError,
        # which escaped the handler and left the previous track's picture.
        class FakeLabel:
            def __init__(self) -> None:
                self.options = {"image": "previous track", "text": ""}

            def configure(self, **values) -> None:
                self.options.update(values)

        def chunk(kind: bytes, data: bytes) -> bytes:
            crc = struct.pack(">I", zlib.crc32(kind + data))
            return struct.pack(">I", len(data)) + kind + data + crc

        header = struct.pack(">IIBBBBB", 20000, 20000, 8, 2, 0, 0, 0)
        bomb = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(b"\x00" * 10))
            + chunk(b"IEND", b"")
        )
        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        app.cover_label = FakeLabel()

        with patch(
            "discography_analyzer.ui.read_embedded_cover",
            return_value=(bomb, "image/png", ""),
        ):
            app._load_cover(
                SimpleNamespace(path=Path("/music/x.flac")), app.cover_label, 190
            )

        self.assertEqual(
            app.cover_label.options,
            {"image": "", "text": "Обложка не распознана"},
        )

    def test_tree_labels_use_russian_plural_forms(self) -> None:
        class FakeTree:
            def __init__(self) -> None:
                self.rows: dict[str, dict] = {}

            def configure(self, **_values) -> None:
                pass

            def column(self, *_args, **_values) -> None:
                pass

            def heading(self, *_args, **_values) -> None:
                pass

            def insert(self, _parent, _index, *, iid: str, **values) -> str:
                self.rows[iid] = values
                return iid

        def cell(item_id: str, column: str) -> str:
            values = app.tree.rows[item_id]["values"]
            return values[[item[0] for item in TABLE_COLUMNS].index(column)]

        members = [
            track(f"t{number}", TrackStatus.DUPLICATE, related=[])
            for number in range(5)
        ]
        for number, member in enumerate(members):
            member.relative_folder = f"Folder {number}"
        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        app.result = SimpleNamespace(root=Path("/music"), completeness_issues=[])
        app.tree = FakeTree()
        app._folder_column_width = None
        app._group_column_width = 300
        app.group_labels = {}
        app.group_members = {}
        app.audit_item_track_ids = {}
        app.track_by_id = {member.id: member for member in members}
        app.variation_source_ids = set()
        app.sort_column = None

        app._insert_folder_tree(members[:2])
        app._insert_relation_groups([(members[0], members)])
        app._insert_audit_groups(
            [
                MetadataAuditIssue(
                    id=f"issue-{field}",
                    track_id="t0",
                    severity=AuditSeverity.WARNING,
                    category=AuditCategory.REQUIRED,
                    field=field,
                    message="Не заполнено",
                )
                for field in ("album_artist", "year")
            ]
        )

        self.assertEqual(cell("folder-root::node", "status"), "Папка · 2 файла")
        self.assertEqual(cell("group::t0", "relative_folder"), "5 папок")
        self.assertEqual(
            app.group_labels["audit-group::t0"], "t0.flac · замечаний: 2"
        )

    def test_selecting_a_folder_row_shows_its_summary(self) -> None:
        # Selecting a folder in the default «По папкам» tree used to leave the
        # panel on the previously selected track and its cover.
        class FakeTree:
            def focus(self) -> str:
                return "folder-path::Artist/Album"

            def selection(self) -> tuple[str, ...]:
                return ("folder-path::Artist/Album",)

        class FakeText:
            def __init__(self) -> None:
                self.text = "previous track"

            def configure(self, **_values) -> None:
                pass

            def delete(self, *_args) -> None:
                self.text = ""

            def insert(self, _index, text: str) -> None:
                self.text += text

        inside = track("inside", TrackStatus.UNIQUE, related=[])
        inside.relative_folder = str(Path("Artist", "Album"))
        inside.cover_hash = "front"
        outside = track("outside", TrackStatus.UNIQUE, related=[])
        outside.relative_folder = "Other"
        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        app.tree = FakeTree()
        app.info_text = FakeText()
        app.result = SimpleNamespace(
            root=Path("/music"),
            tracks=[inside, outside],
            completeness_issues=[],
            audit_issues=[],
        )
        app.track_by_id = {item.id: item for item in (inside, outside)}
        app.audit_issue_by_id = {}
        app.audit_item_track_ids = {}
        app.group_members = {}
        app._refresh_numbering_button = lambda: None
        loaded: list[str] = []
        app._load_cover = lambda item, _label, _size: loaded.append(item.id)
        app.cover_label = object()

        with patch("discography_analyzer.ui.find_folder_cover", return_value=None):
            app._selection_changed()

        self.assertTrue(app.info_text.text.startswith("ПАПКА\nAlbum\n"))
        self.assertIn("Файлов: 1", app.info_text.text.splitlines())
        self.assertEqual(loaded, ["inside"])

    def test_fresh_analysis_starts_with_track_number_order(self) -> None:
        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        app.sort_column = "title"
        app.sort_reverse = True

        app._reset_sort_to_track_number()

        self.assertEqual(app.sort_column, "track_number")
        self.assertFalse(app.sort_reverse)

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
                self.hidden = False

            def configure(self, **values) -> None:
                self.options.update(values)

            def grid_remove(self) -> None:
                self.hidden = True

            def entryconfigure(self, *_args, **_kwargs) -> None:
                pass

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
        app.playlist_button = FakeWidget()
        app.audit_fix_button = FakeWidget()
        app.numbering_fix_button = FakeWidget()
        app.context_menu = FakeWidget()
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
        self.assertEqual(app.playlist_button.options, {"state": "disabled"})
        self.assertEqual(app.audit_fix_button.options, {"state": "disabled"})
        self.assertEqual(app.info_text.text, "Выберите трек в таблице")
        self.assertIsNone(app.cover_photo)
        self.assertEqual(app.cover_label.options["text"], "Обложка не выбрана")

    def test_folders_with_missing_numbers_are_collected(self) -> None:
        def issue(folder: str, missing=(), unnumbered=()):
            return SimpleNamespace(
                relative_folder=folder,
                missing_numbers=missing,
                unnumbered_files=unnumbered,
            )

        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        app.result = SimpleNamespace(
            completeness_issues=[
                issue("A/B", missing=(2,)),
                issue("C", missing=()),
                issue("D", unnumbered=("x.flac",)),
                issue("(корень)", missing=(5,)),
            ]
        )

        self.assertEqual(
            app._folders_with_missing_numbers(),
            {("A", "B"), ()},
        )

    def test_gap_folder_rows_carry_only_the_gap_tag(self) -> None:
        # ttk resolves options of several tags by tag creation order, not by
        # the order in the row's list (ttkTagSet.c, Tk 8.6.13-8.6.15): with
        # ("Folder", "FolderGap") the earlier-created Folder background won
        # and the dark-red highlight of 1.8.4 never showed.
        class FakeTree:
            def __init__(self) -> None:
                self.tags: dict[str, tuple[str, ...]] = {}

            def configure(self, **_values) -> None:
                pass

            def column(self, *_args, **_values) -> None:
                pass

            def insert(self, _parent, _index, *, iid: str, **values) -> str:
                self.tags[iid] = tuple(values.get("tags", ()))
                return iid

        def gap(folder: str) -> AlbumCompletenessIssue:
            return AlbumCompletenessIssue(
                id=f"gap-{folder}",
                relative_folder=folder,
                album="Album",
                disc=1,
                present_numbers=(1, 2),
                missing_numbers=(3,),
                expected_total=3,
                total_from_tags=True,
            )

        in_album = track("album", TrackStatus.UNIQUE, related=[])
        in_album.relative_folder = str(Path("Artist", "Album"))
        in_root = track("root", TrackStatus.UNIQUE, related=[])
        in_root.relative_folder = "(корень)"
        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        app.result = SimpleNamespace(
            root=Path("/music"),
            completeness_issues=[gap(in_album.relative_folder), gap("(корень)")],
        )
        app.tree = FakeTree()
        app._folder_column_width = None

        app._insert_folder_tree([in_root, in_album])

        self.assertEqual(app.tree.tags["folder-root::node"], ("FolderGap",))
        self.assertEqual(app.tree.tags["folder-path::Artist/Album"], ("FolderGap",))
        self.assertEqual(app.tree.tags["folder-path::Artist"], ("Folder",))

    def test_track_number_is_second_column_and_sorts_numerically(self) -> None:
        self.assertEqual(TABLE_COLUMNS[1][0], "track_number")

        def make(identifier: str, number: str) -> Track:
            path = Path(f"/music/{identifier}.flac")
            return Track(
                id=identifier,
                path=path,
                root=Path("/music"),
                filename=path.name,
                relative_path=identifier,
                relative_folder="A",
                format="FLAC",
                size_bytes=1,
                track_number=number,
            )

        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        tracks = [
            make("ten", "10/10"),
            make("two", "2/10"),
            make("one", "1/10"),
            make("none", ""),
        ]

        ordered = [
            track.id
            for track in sorted(
                tracks, key=lambda track: app._sort_key(track, "track_number")
            )
        ]

        # 2 must come before 10 (string sorting would put 10 first), and a file
        # without a number must land at the end.
        self.assertEqual(ordered, ["one", "two", "ten", "none"])

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
