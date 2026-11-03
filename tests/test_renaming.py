from __future__ import annotations

import json
import os
import struct
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from mutagen.flac import FLAC

from discography_analyzer import renaming
from discography_analyzer.models import Track
from discography_analyzer.rename_panel import RenamePanel
from discography_analyzer.renaming import (
    FILE_TEMPLATES,
    FOLDER_TEMPLATES,
    RELEASE_FIELDS,
    TRACK_FIELDS,
    NamingScheme,
    RenameItem,
    RenamePlan,
    TemplateError,
    apply_renames,
    clean_component,
    detect_source,
    latest_journal,
    load_scheme,
    parse_template,
    plan_renames,
    read_tracks,
    rename_entry,
    render_name,
    save_scheme,
    source_from_folder,
    undo_journal,
)
from discography_analyzer.utilities_dialog import FOLDER_ACTIONS, UTILITY_PANELS

FILE_FIELDS = {*RELEASE_FIELDS, *TRACK_FIELDS}


def _flac_bytes(seconds: float = 1.0) -> bytes:
    samples = int(seconds * 44100)
    info = (44100 << 44) | (1 << 41) | (15 << 36) | samples
    streaminfo = (
        struct.pack(">HH", 4096, 4096)
        + b"\x00" * 6
        + info.to_bytes(8, "big")
        + b"\x00" * 16
    )
    return b"fLaC" + bytes([0x80]) + len(streaminfo).to_bytes(3, "big") + streaminfo


def write_flac(path: Path, **tags) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_flac_bytes())
    audio = FLAC(path)
    for key, value in tags.items():
        audio[key.upper()] = value if isinstance(value, list) else [str(value)]
    audio.save()
    return path


def box(
    root: Path, folder: str = "Moog Vol 3", disc_folders=("Disc 1", "Disc 2")
) -> Path:
    """A two-disc Qobuz release in «Disc N» folders with untidy file names."""
    release = root / "Klaus Schulze" / folder
    for disc, disc_folder in enumerate(disc_folders, start=1):
        for number in (1, 2):
            write_flac(
                release / disc_folder / f"{number} - part {disc}.{number}.flac",
                title=f"Part {disc}.{number}: Moog",
                artist="Klaus Schulze",
                albumartist="Klaus Schulze",
                album="The Dark Side of the Moog, Vol. 3",
                date="1996",
                label="Synthetic Symphony",
                barcode="0885513014023",
                url="https://open.qobuz.com/track/1",
                tracknumber=str(number),
                tracktotal="4",
                discnumber=str(disc),
                disctotal="2",
            )
    return release


def scan(root: Path) -> list[Track]:
    return read_tracks(root, extensions={".flac"})


def fake(folder: str, number: int, **values) -> Track:
    root = Path("/music")
    path = root / folder / f"{number:02d} - x.flac"
    values.setdefault("track_number", str(number))
    return Track(
        id=f"{folder}/{number}",
        path=path,
        root=root,
        filename=path.name,
        relative_path=f"{folder}/{path.name}",
        relative_folder=folder,
        format="FLAC",
        size_bytes=1,
        **values,
    )


class TemplateTests(unittest.TestCase):
    def test_the_archive_folder_scheme_and_its_optional_parts(self) -> None:
        parts = parse_template(FOLDER_TEMPLATES[0], RELEASE_FIELDS)
        values = {
            "year": "1972",
            "album": "Irrlicht",
            "source": "Qobuz",
            "label": "Brain",
            "barcode": "0004228331272",
        }

        self.assertEqual(
            render_name(parts, values),
            ("1972 Irrlicht (Qobuz, Brain, 0004228331272)", []),
        )
        duo = dict(
            values,
            album="Farscape",
            duo="Klaus Schulze, Lisa Gerrard",
            **{"24bit": "24Bit"},
        )
        self.assertEqual(
            render_name(parts, duo)[0],
            "1972 Farscape [Klaus Schulze, Lisa Gerrard] (Qobuz, Brain, 0004228331272) 24Bit",
        )
        # An empty field inside <…> drops that part only…
        self.assertEqual(render_name(parts, dict(values, label=""))[0], "1972 Irrlicht")
        # …an empty field outside <…> means no name at all.
        self.assertEqual(render_name(parts, dict(values, year="")), ("", ["year"]))

    def test_track_numbers_get_two_digits_and_guests_their_suffix(self) -> None:
        parts = parse_template(FILE_TEMPLATES[0], FILE_FIELDS)
        values = {"track": "3", "title": "Bang Bang", "albumartist": "Ariana Grande"}

        self.assertEqual(
            render_name(parts, values, suffix=".flac")[0], "03. Bang Bang.flac"
        )
        self.assertEqual(
            render_name(
                parts, dict(values, guests="Jessie J, Nicki Minaj"), suffix=".flac"
            )[0],
            "03. Bang Bang (Jessie J, Nicki Minaj feat. Ariana Grande).flac",
        )

    def test_template_mistakes_are_explained(self) -> None:
        cases = {
            "{year": "Нет закрывающей скобки «}»",
            "{year}}": "Лишняя скобка «}»",
            "{nope}": "Неизвестное поле {nope}",
            "<{year}": "Нет закрывающей скобки «>»",
            "{year}>": "Лишняя скобка «>»",
            "{track} {album}": "Поле {track} есть только в имени файла",
            "Album": "В шаблоне нет ни одного поля",
        }
        for template, message in cases.items():
            with (
                self.subTest(template=template),
                self.assertRaises(TemplateError) as raised,
            ):
                parse_template(template, RELEASE_FIELDS)
            self.assertEqual(str(raised.exception), message)

    def test_names_are_cleaned_like_the_normalizer_did(self) -> None:
        cases = {
            "Title: Part": "Title - Part",
            "Intro: (Live)": "Intro (Live)",
            "AC/DC": "AC - DC",
            "Why?": "Why",
            'The "Hit"': "The 'Hit'",
            "P:T:O": "P-T-O",
            "a   b": "a b",
            "Song...": "Song",
            "X- Y": "X - Y",
            "( x )": "(x)",
            "Inter*Face": "Inter Face",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(clean_component(value), expected)

    def test_template_text_cannot_make_a_subfolder_or_a_reserved_name(self) -> None:
        self.assertEqual(
            render_name(
                parse_template("{year}/{album}", RELEASE_FIELDS),
                {"year": "1972", "album": "A"},
            )[0],
            "1972 - A",
        )
        self.assertEqual(
            render_name(parse_template("{album}", RELEASE_FIELDS), {"album": "CON"})[0],
            "CON_",
        )

    def test_the_source_comes_from_a_url_tag_or_the_folder_name(self) -> None:
        vorbis = fake(
            "A", 1, all_tags={"url": ["https://open.qobuz.com/track/45973622"]}
        )
        id3 = fake("A", 2, all_tags={"WXXX:": ["https://www.deezer.com/album/1"]})
        unrelated = fake("A", 3, all_tags={"comment": ["bought on qobuz.com"]})

        self.assertEqual(detect_source([vorbis]), "Qobuz")
        self.assertEqual(detect_source([id3]), "Deezer")
        self.assertEqual(detect_source([unrelated]), "")
        name = "1972 Irrlicht (Qobuz, Brain, 0004228331272)"
        self.assertEqual(source_from_folder(name, "0004228331272"), "Qobuz")
        self.assertEqual(source_from_folder(name, "0602557892826"), "")
        self.assertEqual(source_from_folder(name, ""), "")


class PlanTests(unittest.TestCase):
    def test_files_disc_folders_and_the_release_folder(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            release = box(root)

            plan = plan_renames(root, scan(root), NamingScheme(), protected=root)

            renames = {
                (item.kind, item.source.name, item.target.name) for item in plan.items
            }
            self.assertIn(("disc", "Disc 1", "CD1"), renames)
            self.assertIn(("disc", "Disc 2", "CD2"), renames)
            self.assertIn(
                ("file", "1 - part 1.1.flac", "01. Part 1.1 - Moog.flac"), renames
            )
            self.assertIn(
                (
                    "folder",
                    "Moog Vol 3",
                    "1996 The Dark Side of the Moog, Vol. 3 (Qobuz, Synthetic Symphony, 0885513014023)",
                ),
                renames,
            )
            self.assertEqual(plan.problems, 0)
            self.assertEqual({item.folder for item in plan.items}, {release})
            self.assertEqual(
                (plan.count("file"), plan.count("disc"), plan.count("folder")),
                (4, 2, 1),
            )

    def test_a_library_named_by_the_scheme_needs_nothing(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            box(root)
            apply_renames(
                plan_renames(root, scan(root), NamingScheme(), protected=root),
                journal_dir=root.parent / f"{root.name}-journal",
            )

            again = plan_renames(root, scan(root), NamingScheme(), protected=root)

            self.assertEqual(again.items, [])
            self.assertEqual(again.unchanged, 4 + 2 + 1)

    def test_the_source_survives_files_without_url_tags(self) -> None:
        # A folder already named by the scheme keeps «Qobuz» from its own name.
        tracks = [
            fake(
                "Klaus Schulze/1972 Irrlicht (Qobuz, Brain, 0004228331272)",
                number,
                title=f"Satz {number}",
                album="Irrlicht",
                year="1972",
                track_number=f"{number}/3",
                all_tags={"label": ["Brain"], "barcode": ["0004228331272"]},
            )
            for number in (1, 2, 3)
        ]

        plan = plan_renames(
            Path("/music"),
            tracks,
            NamingScheme(rename_files=False),
            protected=Path("/music"),
        )

        self.assertEqual(plan.items, [])
        self.assertEqual(plan.unchanged, 1)

    def test_problems_are_listed_and_left_unchecked(self) -> None:
        tracks = [
            fake("Same", 1, album="A", title="Song"),
            fake("Same", 2, album="A", title="Song", track_number="1"),
            fake("Untitled", 1, album="B"),
            fake("Two", 1, album="C", title="x"),
            fake("Two", 2, album="D", title="y"),
        ]

        plan = plan_renames(Path("/music"), tracks, NamingScheme(rename_folders=True))

        # A file by its folder, a release folder by its own name.
        problems = {
            (
                item.source.parent.name if item.kind == "file" else item.source.name,
                item.kind,
            ): item.problem
            for item in plan.items
            if item.problem
        }
        self.assertEqual(problems[("Same", "file")], "у другого файла то же новое имя")
        self.assertEqual(problems[("Untitled", "file")], "нет тега Title")
        self.assertEqual(problems[("Two", "folder")], "в папке не один релиз")
        self.assertEqual(problems[("Same", "folder")], "нет года")
        self.assertTrue(all(not item.selected for item in plan.items if item.problem))
        self.assertEqual(
            plan.chosen(), [item for item in plan.items if not item.problem]
        )

    def test_a_folder_without_a_year_keeps_its_name(self) -> None:
        tracks = [fake("NoYear", 1, album="A", title="t")]

        plan = plan_renames(Path("/music"), tracks, NamingScheme(rename_files=False))

        self.assertEqual([item.problem for item in plan.items], ["нет года"])

    def test_the_protected_folder_and_a_lone_disc_folder_keep_their_names(self) -> None:
        tracks = [fake("Album", 1, album="A", year="2000", title="t")]
        tracks[0].relative_folder = str(Path("/music"))
        tracks[0].path = Path("/music/01 - x.flac")

        self.assertEqual(
            plan_renames(
                Path("/music"),
                tracks,
                NamingScheme(rename_files=False),
                protected=Path("/music"),
            ).items,
            [],
        )
        disc = [fake("CD2", 1, album="A", year="2000", title="t")]
        disc[0].relative_folder = str(Path("/music/CD2"))
        disc[0].root = Path("/music/CD2")
        disc[0].path = Path("/music/CD2/01 - x.flac")
        self.assertEqual(
            plan_renames(
                Path("/music/CD2"), disc, NamingScheme(rename_files=False)
            ).items,
            [],
        )

    def test_a_name_that_makes_a_path_too_long_is_refused(self) -> None:
        # 121 characters now; the 255-character folder name makes it 276.
        deep = "D/" + "x" * 100
        tracks = [fake(deep, 1, album="A" * 250, year="2000", title="Song")]

        plan = plan_renames(Path("/music"), tracks, NamingScheme(rename_files=False))

        self.assertEqual(len(plan.items), 1)
        self.assertRegex(plan.items[0].problem, r"^путь файла станет \d+ > 259$")
        self.assertFalse(plan.items[0].selected)

    def test_an_existing_name_is_reported(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_flac(
                root / "A" / "1 - song.flac", title="Song", album="A", tracknumber="1"
            )
            # Something else already has the name (a folder, so it is not scanned).
            (root / "A" / "01. Song.flac").mkdir()

            plan = plan_renames(root, scan(root), NamingScheme(rename_folders=False))

        self.assertEqual(
            [item.problem for item in plan.items], ["«01. Song.flac» уже есть"]
        )


class ApplyTests(unittest.TestCase):
    def test_apply_and_undo_give_every_name_back(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "music"
            journals = base / "journals"
            box(root)
            before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))

            result = apply_renames(
                plan_renames(root, scan(root), NamingScheme(), protected=root),
                journal_dir=journals,
            )

            self.assertEqual((result.renamed, result.failures), (7, []))
            after = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
            self.assertIn(
                str(
                    Path(
                        "Klaus Schulze",
                        "1996 The Dark Side of the Moog, Vol. 3 (Qobuz, Synthetic Symphony, 0885513014023)",
                        "CD2",
                        "02. Part 2.2 - Moog.flac",
                    )
                ),
                after,
            )
            lines = result.journal.read_text(encoding="utf-8").splitlines()
            self.assertEqual(json.loads(lines[0])["root"], str(root))
            self.assertEqual(
                [json.loads(line)["kind"] for line in lines[1:]],
                ["file"] * 4 + ["disc"] * 2 + ["folder"],
            )

            journal = latest_journal(journals)
            undone = undo_journal(journal)

            self.assertEqual((undone.renamed, undone.failures), (7, []))
            self.assertEqual(
                sorted(str(path.relative_to(root)) for path in root.rglob("*")), before
            )
            self.assertTrue(undone.journal.name.endswith(".undone.jsonl"))
            self.assertIsNone(latest_journal(journals))

    def test_what_cannot_be_undone_stays_in_the_journal(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "music"
            write_flac(root / "A" / "1 - a.flac", title="A", album="X", tracknumber="1")
            write_flac(root / "A" / "2 - b.flac", title="B", album="X", tracknumber="2")
            result = apply_renames(
                plan_renames(root, scan(root), NamingScheme(rename_folders=False)),
                journal_dir=base / "journals",
            )
            (root / "A" / "02. B.flac").rename(root / "A" / "moved away.flac")

            undone = undo_journal(latest_journal(base / "journals"))

            self.assertEqual(undone.renamed, 1)
            self.assertEqual(len(undone.failures), 1)
            self.assertTrue((root / "A" / "1 - a.flac").exists())
            remaining = latest_journal(base / "journals")
            self.assertEqual(remaining.path, result.journal)
            self.assertEqual(
                [new.name for _kind, _old, new in remaining.entries], ["02. B.flac"]
            )

    def test_the_chosen_folder_itself_can_get_its_name(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "Irrlicht"
            for number in (1, 2):
                write_flac(
                    root / f"0{number}. Satz {number}.flac",
                    title=f"Satz {number}",
                    album="Irrlicht",
                    date="1972",
                    tracknumber=str(number),
                )

            result = apply_renames(
                plan_renames(
                    root, scan(root), NamingScheme(folder_template="{year} {album}")
                ),
                journal_dir=base / "journals",
            )

            self.assertEqual(result.root, base / "1972 Irrlicht")
            self.assertTrue((base / "1972 Irrlicht" / "01. Satz 1.flac").exists())

    def test_a_stopped_run_leaves_no_empty_journal(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "music"
            write_flac(root / "A" / "1 - a.flac", title="A", album="X", tracknumber="1")
            stop = threading.Event()
            stop.set()

            result = apply_renames(
                plan_renames(root, scan(root), NamingScheme()),
                journal_dir=base / "journals",
                stop_event=stop,
            )

            self.assertTrue(result.stopped)
            self.assertEqual(result.renamed, 0)
            self.assertIsNone(result.journal)
            self.assertEqual(list((base / "journals").iterdir()), [])

    def test_a_rename_never_overwrites_and_handles_letter_case(self) -> None:
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "a.flac").write_bytes(b"a")
            (folder / "b.flac").write_bytes(b"b")

            with self.assertRaises(FileExistsError):
                rename_entry(folder / "a.flac", folder / "b.flac")
            self.assertEqual((folder / "b.flac").read_bytes(), b"b")

            (folder / "cd1").mkdir()
            rename_entry(folder / "cd1", folder / "CD1")
            self.assertEqual(
                sorted(path.name for path in folder.iterdir()),
                ["CD1", "a.flac", "b.flac"],
            )
            with self.assertRaises(FileNotFoundError):
                rename_entry(folder / "missing.flac", folder / "c.flac")

    def test_a_folder_held_for_a_moment_on_windows_is_renamed_on_retry(self) -> None:
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "Disc 1").mkdir()
            real_rename = os.rename
            calls: list[str] = []

            def busy_once(source, target):
                calls.append(source)
                if len(calls) == 1:
                    raise PermissionError("используется другим процессом")
                real_rename(source, target)

            with (
                mock.patch.object(renaming.sys, "platform", "win32"),
                mock.patch.object(renaming.os, "rename", busy_once),
                mock.patch.object(renaming.time, "sleep") as sleep,
            ):
                rename_entry(folder / "Disc 1", folder / "CD1")

            self.assertTrue((folder / "CD1").is_dir())
            self.assertEqual(len(calls), 2)
            sleep.assert_called_once_with(renaming.RENAME_RETRY_DELAY)

            # On Linux and macOS a permission error is final at once.
            with (
                mock.patch.object(renaming.sys, "platform", "linux"),
                mock.patch.object(
                    renaming.os, "rename", side_effect=PermissionError("нет прав")
                ),
                mock.patch.object(renaming.time, "sleep") as sleep,
                self.assertRaises(PermissionError),
            ):
                rename_entry(folder / "CD1", folder / "CD2")
            sleep.assert_not_called()

    def test_the_scheme_is_remembered(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "renaming.json"
            scheme = NamingScheme(
                file_template="{track:02} - {title}", source="Qobuz", disc_folders=False
            )

            save_scheme(scheme, path)

            self.assertEqual(load_scheme(path), scheme)
            path.write_text("[1, 2]", encoding="utf-8")
            self.assertEqual(load_scheme(path), NamingScheme())
            path.write_text('{"source": 5, "rename_files": false}', encoding="utf-8")
            self.assertEqual(load_scheme(path), NamingScheme(rename_files=False))


class Var:
    def __init__(self, value=None) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class FakeTree:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.children: dict[str, list[str]] = {"": []}
        self.focused = ""

    def insert(self, parent: str, _index, *, iid: str | None = None, **values) -> str:
        iid = iid or f"row{len(self.rows)}"
        self.rows[iid] = dict(values)
        self.children.setdefault(parent, []).append(iid)
        self.children.setdefault(iid, [])
        return iid

    def delete(self, *_items) -> None:
        self.rows.clear()
        self.children = {"": []}

    def get_children(self, item: str = "") -> list[str]:
        return list(self.children.get(item, []))

    def set(self, item: str, column: str, value) -> None:
        self.rows[item][column] = value

    def focus(self) -> str:
        return self.focused


class RenamePanelTests(unittest.TestCase):
    def test_the_utility_and_its_folder_action_are_registered(self) -> None:
        self.assertIn(RenamePanel, UTILITY_PANELS)
        self.assertIn(("Переименовать по тегам…", RenamePanel), FOLDER_ACTIONS)

    def panel(self) -> RenamePanel:
        panel = RenamePanel.__new__(RenamePanel)
        panel.tree = FakeTree()
        panel.item_rows = {}
        panel.plan = None
        panel.busy = False
        panel.summary_var = Var("")
        panel.status_var = Var("")
        panel.apply_button = SimpleNamespace(configure=lambda **_options: None)
        return panel

    def test_the_preview_groups_by_release_folder_and_toggles_rows(self) -> None:
        root = Path("/music")

        def item(folder: str, name: str, problem: str = "") -> RenameItem:
            source = root / folder / name
            return RenameItem(
                "file",
                source,
                source.with_name(f"01. {name}"),
                "Irrlicht (1972)",
                problem,
                not problem,
                root / folder,
            )

        first = item("A/Irrlicht", "a.flac")
        second = item("B/Irrlicht", "b.flac")
        blocked = item("B/Irrlicht", "c.flac", "нет тега Title")
        panel = self.panel()

        panel.show_plan(
            RenamePlan(root=root, items=[first, second, blocked], unchanged=3)
        )

        parents = panel.tree.get_children("")
        self.assertEqual(len(parents), 2)  # two releases with one title
        self.assertEqual(
            panel.tree.rows[parents[0]]["values"][1], str(Path("A/Irrlicht"))
        )
        self.assertEqual(panel.tree.rows[parents[1]]["mark"], "–")
        self.assertIn("файлов 2", panel.summary_var.value)
        self.assertIn("не переименовать: 1", panel.summary_var.value)

        panel.tree.focused = parents[1]
        panel._toggle()
        self.assertFalse(second.selected)
        self.assertFalse(blocked.selected)
        self.assertEqual(panel.tree.rows[parents[1]]["mark"], "")
        panel.tree.focused = parents[1]
        panel._toggle()
        self.assertTrue(second.selected)
        # A row that cannot be renamed never gets checked.
        self.assertFalse(blocked.selected)

    def test_template_mistakes_stop_the_preview_with_a_reason(self) -> None:
        panel = self.panel()

        self.assertEqual(
            panel._template_problem(NamingScheme(folder_template="{year")),
            "Шаблон папок: Нет закрывающей скобки «}»",
        )
        self.assertEqual(
            panel._template_problem(NamingScheme(file_template="{titel}")),
            "Шаблон файлов: Неизвестное поле {titel}",
        )
        self.assertEqual(
            panel._template_problem(
                NamingScheme(
                    rename_folders=False, rename_files=False, disc_folders=False
                )
            ),
            "Отметьте, что переименовывать: папки релизов, файлы или папки дисков",
        )
        self.assertEqual(panel._template_problem(NamingScheme()), "")


if __name__ == "__main__":
    unittest.main()
