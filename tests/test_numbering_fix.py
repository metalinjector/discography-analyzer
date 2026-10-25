from __future__ import annotations

import os
import struct
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from discography_analyzer.completeness import analyze_track_completeness
from discography_analyzer.metadata import read_metadata
from discography_analyzer.models import Track
from discography_analyzer.numbering_fix import (
    apply_numbering_fix,
    plan_numbering_fix,
    verify_total,
    write_total,
)

# MPEG-1 Layer III, 128 kbps, 44.1 kHz: 417-byte frames.
MP3_FRAMES = (b"\xff\xfb\x90\x00" + b"\x00" * 413) * 40


def flac_header() -> bytes:
    streaminfo = struct.pack(">HH", 4096, 4096) + b"\x00" * 6
    bits = (44100 << 44) | (1 << 41) | (15 << 36) | 44100
    streaminfo += bits.to_bytes(8, "big") + b"\x00" * 16
    return b"fLaC" + bytes([0x80]) + len(streaminfo).to_bytes(3, "big") + streaminfo


def ape_header() -> bytes:
    header = bytearray(76)
    header[0:4] = b"MAC "
    struct.pack_into("<H", header, 4, 3990)
    struct.pack_into("<IIIHHI", header, 56, 73728 * 4, 73728, 1, 16, 2, 44100)
    return bytes(header) + b"\x00" * 256


def make_flac(path: Path, number: int, total: int) -> None:
    from mutagen.flac import FLAC

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(flac_header())
    audio = FLAC(path)
    audio["tracknumber"] = [str(number)]
    audio["tracktotal"] = [str(total)]
    audio.save()


def make_mp3(path: Path, number: int, total: int) -> None:
    from mutagen.id3 import ID3, TRCK

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(MP3_FRAMES)
    tags = ID3()
    tags.add(TRCK(encoding=3, text=f"{number}/{total}"))
    tags.save(path, v2_version=3)


def make_ape(path: Path, number: int, total: int) -> None:
    import mutagen
    from mutagen.apev2 import TEXT, APEValue

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ape_header())
    audio = mutagen.File(path)
    tags = audio.tags if audio.tags is not None else (audio.add_tags() or audio.tags)
    tags["Track"] = APEValue(f"{number}/{total}", TEXT)
    audio.save()


def make_track(path: Path, root: Path, album: str = "Album") -> Track:
    return Track(
        id=path.stem,
        path=path,
        root=root,
        filename=path.name,
        relative_path=str(path.relative_to(root)),
        relative_folder=str(path.parent.relative_to(root)),
        format=path.suffix[1:].upper(),
        size_bytes=path.stat().st_size,
        album=album,
    )


def read_tracks(paths: list[Path], root: Path) -> list[Track]:
    tracks = [make_track(path, root) for path in paths]
    for track in tracks:
        read_metadata(track)
    return tracks


class NumberingPlanTests(unittest.TestCase):
    def test_conflicting_totals_become_the_highest_number(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Album"
            for number in range(1, 7):
                make_flac(folder / f"{number}.flac", number, 6)
            make_flac(folder / "7.flac", 7, 7)
            tracks = read_tracks(sorted(folder.glob("*.flac")), root)
            issue = analyze_track_completeness(tracks)[0]

            plan = plan_numbering_fix(tracks, [issue])

        self.assertEqual(plan.count, 6)
        self.assertEqual(plan.totals, (7,))
        self.assertEqual(
            [change.new_value for change in plan.changes],
            [f"{number}/7" for number in range(1, 7)],
        )
        self.assertEqual(plan.changes[0].current, "1/6")
        self.assertEqual(plan.unnumbered, ())

    def test_target_never_lowers_a_declared_total(self) -> None:
        # Files 1…5 declare /6 and /7 although only five numbers exist: the fix
        # must reach 7, not drop the files that already say 7 down to 5.
        with TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Album"
            for number in range(1, 5):
                make_flac(folder / f"{number}.flac", number, 6)
            make_flac(folder / "5.flac", 5, 7)
            tracks = read_tracks(sorted(folder.glob("*.flac")), root)
            issue = analyze_track_completeness(tracks)[0]

            plan = plan_numbering_fix(tracks, [issue])

        self.assertEqual(plan.totals, (7,))
        self.assertEqual(plan.count, 4)
        self.assertEqual({change.new_value for change in plan.changes}, {"1/7", "2/7", "3/7", "4/7"})

    def test_consistent_album_needs_no_fix(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Album"
            for number in range(1, 4):
                make_flac(folder / f"{number}.flac", number, 3)
            tracks = read_tracks(sorted(folder.glob("*.flac")), root)

            plan = plan_numbering_fix(tracks, analyze_track_completeness(tracks))

        self.assertEqual(plan.count, 0)

    def test_files_without_track_number_are_listed_not_changed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Album"
            for number in range(1, 4):
                make_flac(folder / f"{number}.flac", number, 2)
            make_flac(folder / "bonus.flac", 0, 0)  # written as 0/0 → no number
            tracks = read_tracks(sorted(folder.glob("*.flac")), root)
            issue = analyze_track_completeness(tracks)[0]

            plan = plan_numbering_fix(tracks, [issue])

        self.assertEqual(plan.count, 3)
        self.assertEqual(
            plan.unnumbered,
            (str(Path("Album") / "bonus.flac"),),
        )


class NumberingApplyTests(unittest.TestCase):
    def test_flac_numbers_are_rewritten_with_backup_and_mtime(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Album"
            for number in range(1, 4):
                make_flac(folder / f"{number}.flac", number, 2)
            make_flac(folder / "4.flac", 4, 4)
            paths = sorted(folder.glob("*.flac"))
            tracks = read_tracks(paths, root)
            issue = analyze_track_completeness(tracks)[0]
            plan = plan_numbering_fix(tracks, [issue])
            os.utime(folder / "1.flac", (1_600_000_000, 1_600_000_000))

            result = apply_numbering_fix(plan.changes, root=root, backup_root=root / "backup")
            after = read_tracks(paths, root)
            again = plan_numbering_fix(after, analyze_track_completeness(after))
            saved_mtime = (folder / "1.flac").stat().st_mtime
            backup_exists = (root / "backup" / "Album" / "1.flac").exists()

        self.assertEqual(result.updated_files, 3)
        self.assertEqual(result.backup_files, 3)
        self.assertFalse(result.failures)
        self.assertEqual([track.track_number for track in after], ["1/4", "2/4", "3/4", "4/4"])
        self.assertTrue(backup_exists)
        self.assertEqual(again.count, 0)
        self.assertEqual(saved_mtime, 1_600_000_000)

    def test_mp3_keeps_id3v23_and_updates_trck(self) -> None:
        from mutagen.id3 import ID3

        with TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Album"
            make_mp3(folder / "1.mp3", 1, 6)
            make_mp3(folder / "2.mp3", 2, 7)
            paths = sorted(folder.glob("*.mp3"))
            tracks = read_tracks(paths, root)
            issue = analyze_track_completeness(tracks)[0]

            result = apply_numbering_fix(
                plan_numbering_fix(tracks, [issue]).changes, root=root
            )
            tags = ID3(folder / "1.mp3")
            second = ID3(folder / "2.mp3")

        self.assertEqual(result.updated_files, 1)
        self.assertEqual(tags.version[:2], (2, 3))
        self.assertEqual(str(tags["TRCK"]), "1/7")
        self.assertEqual(str(second["TRCK"]), "2/7")

    def test_ape_track_tag_is_rewritten(self) -> None:
        import mutagen

        with TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Album"
            make_ape(folder / "1.ape", 1, 6)
            make_ape(folder / "2.ape", 2, 7)
            paths = sorted(folder.glob("*.ape"))
            tracks = read_tracks(paths, root)
            issue = analyze_track_completeness(tracks)[0]

            result = apply_numbering_fix(
                plan_numbering_fix(tracks, [issue]).changes, root=root
            )
            tags = mutagen.File(folder / "1.ape").tags

        self.assertEqual(result.updated_files, 1)
        self.assertEqual(tags.get("Track"), "1/7")

    def test_failed_verification_leaves_the_original_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Album"
            make_flac(folder / "1.flac", 1, 6)
            make_flac(folder / "2.flac", 2, 7)
            paths = sorted(folder.glob("*.flac"))
            tracks = read_tracks(paths, root)
            issue = analyze_track_completeness(tracks)[0]
            plan = plan_numbering_fix(tracks, [issue])
            original = (folder / "1.flac").read_bytes()

            with patch(
                "discography_analyzer.numbering_fix.verify_total",
                side_effect=ValueError("проверка нумерации после записи не пройдена"),
            ):
                result = apply_numbering_fix(plan.changes, root=root, backup_root=root / "backup")

            self.assertEqual(result.updated_files, 0)
            self.assertEqual(len(result.failures), 1)
            self.assertEqual((folder / "1.flac").read_bytes(), original)
            self.assertEqual(list(folder.glob(".1-numbering-*.flac")), [])
            self.assertFalse((root / "backup").exists())

    def test_stop_event_stops_before_any_write(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Album"
            make_flac(folder / "1.flac", 1, 6)
            make_flac(folder / "2.flac", 2, 7)
            tracks = read_tracks(sorted(folder.glob("*.flac")), root)
            issue = analyze_track_completeness(tracks)[0]
            plan = plan_numbering_fix(tracks, [issue])
            stop = threading.Event()
            stop.set()

            result = apply_numbering_fix(plan.changes, root=root, stop_event=stop)

        self.assertTrue(result.stopped)
        self.assertEqual(result.updated_files, 0)

    def test_write_and_verify_reject_an_unsupported_value(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "1.flac"
            make_flac(path, 1, 6)

            write_total(path, 1, 7)
            verify_total(path, 1, 7)
            with self.assertRaisesRegex(ValueError, "не пройдена"):
                verify_total(path, 1, 9)


if __name__ == "__main__":
    unittest.main()
