from __future__ import annotations

import hashlib
import io
import struct
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from discography_analyzer import cover_extraction
from discography_analyzer.cover_extraction import (
    CoverTaskStopped,
    plan_cover_extraction,
    write_covers,
)


def flac_header() -> bytes:
    """Minimal FLAC: "fLaC" + STREAMINFO (44.1 kHz, stereo, 16 bit, 1 s)."""
    streaminfo = struct.pack(">HH", 4096, 4096) + b"\x00" * 6
    bits = (44100 << 44) | (1 << 41) | (15 << 36) | 44100
    streaminfo += bits.to_bytes(8, "big") + b"\x00" * 16
    return b"fLaC" + bytes([0x80]) + len(streaminfo).to_bytes(3, "big") + streaminfo


def image_bytes(image_format: str = "JPEG", color: str = "#e97824") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buffer, format=image_format)
    return buffer.getvalue()


def make_flac(path: Path, cover: bytes | None = None) -> None:
    from mutagen.flac import FLAC, Picture

    path.write_bytes(flac_header())
    if cover is None:
        return
    picture = Picture()
    picture.type = 3
    picture.mime = "image/jpeg" if cover[:2] == b"\xff\xd8" else "image/png"
    picture.data = cover
    audio = FLAC(path)
    audio.add_picture(picture)
    audio.save()


class CoverExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.folder = self.root / "Album"
        self.folder.mkdir()
        self.addCleanup(self._temp.cleanup)

    def plan(self, **kwargs):
        return plan_cover_extraction(
            self.root, extensions=[".flac"], **kwargs
        )

    def test_three_flac_with_one_cover_plan_cover_jpg(self) -> None:
        cover = image_bytes("JPEG")
        for index in range(1, 4):
            make_flac(self.folder / f"{index}.flac", cover)

        plan = self.plan()

        self.assertEqual(plan.writable, 1)
        target = plan.targets[0]
        self.assertEqual(target.destination.name, "cover.jpg")
        self.assertEqual((target.matching, target.total), (3, 3))
        self.assertEqual(
            hashlib.sha256(target.data).hexdigest(),
            hashlib.sha256(cover).hexdigest(),
        )

        result = write_covers(plan)

        self.assertEqual(result.written, 1)
        written = (self.folder / "cover.jpg").read_bytes()
        self.assertEqual(
            hashlib.sha256(written).hexdigest(), hashlib.sha256(cover).hexdigest()
        )

    def test_folder_with_a_cover_file_is_not_a_candidate(self) -> None:
        cover = image_bytes("JPEG")
        make_flac(self.folder / "1.flac", cover)
        (self.folder / "cover.jpg").write_bytes(cover)

        plan = self.plan()

        self.assertEqual(plan.writable, 0)

    def test_two_different_covers_are_skipped(self) -> None:
        first = image_bytes("JPEG", "#111111")
        second = image_bytes("JPEG", "#eeeeee")
        make_flac(self.folder / "1.flac", first)
        make_flac(self.folder / "2.flac", first)
        make_flac(self.folder / "3.flac", second)
        make_flac(self.folder / "4.flac", second)

        plan = self.plan()

        self.assertEqual(plan.writable, 0)
        self.assertEqual(
            plan.skipped[0].reason, "у треков разные обложки, ни одна не преобладает"
        )

    def test_one_cover_among_files_without_art_is_still_the_album_cover(self) -> None:
        # Files without any embedded cover do not vote: foobar2000 and Kodi
        # should still find a cover.jpg next to the audio.
        make_flac(self.folder / "1.flac", image_bytes("JPEG"))
        make_flac(self.folder / "2.flac")
        make_flac(self.folder / "3.flac")

        plan = self.plan()

        self.assertEqual(plan.writable, 1)
        self.assertEqual((plan.targets[0].matching, plan.targets[0].total), (1, 3))

    def test_png_cover_gets_cover_png(self) -> None:
        cover = image_bytes("PNG")
        make_flac(self.folder / "1.flac", cover)
        make_flac(self.folder / "2.flac", cover)

        plan = self.plan()

        self.assertEqual(plan.targets[0].destination.name, "cover.png")

    def test_appledouble_files_are_ignored(self) -> None:
        cover = image_bytes("JPEG")
        make_flac(self.folder / "1.flac", cover)
        make_flac(self.folder / "2.flac", cover)
        (self.folder / "._1.flac").write_bytes(b"resource fork")

        plan = self.plan()

        self.assertEqual(plan.targets[0].total, 2)

    def test_an_unsupported_image_is_reported_without_transcoding(self) -> None:
        gif = image_bytes("GIF")
        make_flac(self.folder / "1.flac", gif)
        make_flac(self.folder / "2.flac", gif)

        plan = self.plan()

        self.assertEqual(plan.writable, 0)
        self.assertTrue(plan.problems)
        self.assertIn("не поддерживается", plan.problems[0].reason)

    def test_stop_event_stops_before_writing(self) -> None:
        cover = image_bytes("JPEG")
        make_flac(self.folder / "1.flac", cover)
        make_flac(self.folder / "2.flac", cover)
        stop = threading.Event()
        stop.set()

        result = write_covers(self.plan(), stop_event=stop)

        self.assertEqual(result.written, 0)
        self.assertTrue(result.stopped)
        self.assertFalse((self.folder / "cover.jpg").exists())

    def test_a_failed_write_leaves_no_temporary_file(self) -> None:
        cover = image_bytes("JPEG")
        make_flac(self.folder / "1.flac", cover)
        make_flac(self.folder / "2.flac", cover)
        plan = self.plan()

        with patch.object(cover_extraction.os, "replace", side_effect=OSError("нет места")):
            result = write_covers(plan)

        self.assertEqual(result.written, 0)
        self.assertTrue(result.failures)
        self.assertEqual(list(self.folder.glob(".cover-*.part")), [])
        self.assertFalse((self.folder / "cover.jpg").exists())
        self.assertEqual(
            sorted(path.name for path in self.folder.iterdir()),
            ["1.flac", "2.flac"],
        )

    def test_stop_event_interrupts_the_plan(self) -> None:
        make_flac(self.folder / "1.flac")
        stop = threading.Event()
        stop.set()

        with self.assertRaises(CoverTaskStopped):
            plan_cover_extraction(
                self.root, extensions=[".flac"], stop_event=stop
            )


if __name__ == "__main__":
    unittest.main()
