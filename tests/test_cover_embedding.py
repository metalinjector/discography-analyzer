from __future__ import annotations

import hashlib
import io
import os
import struct
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from discography_analyzer.cover_embedding import (
    ArtState,
    CoverImage,
    embed_covers,
    find_folder_cover,
    inspect_art,
    plan_cover_embedding,
    read_cover_image,
)
from discography_analyzer.metadata import read_embedded_cover

# MPEG-1 Layer III, 128 kbps, 44.1 kHz: 417-byte frames.
MP3_FRAMES = (b"\xff\xfb\x90\x00" + b"\x00" * 413) * 40


def flac_header() -> bytes:
    """Minimal FLAC: "fLaC" + STREAMINFO (44.1 kHz, stereo, 16 bit, 1 s)."""
    streaminfo = struct.pack(">HH", 4096, 4096) + b"\x00" * 6
    bits = (44100 << 44) | (1 << 41) | (15 << 36) | 44100
    streaminfo += bits.to_bytes(8, "big") + b"\x00" * 16
    return b"fLaC" + bytes([0x80]) + len(streaminfo).to_bytes(3, "big") + streaminfo


def ape_header() -> bytes:
    """Minimal Monkey's Audio header: 76 bytes starting with "MAC "."""
    header = bytearray(76)
    header[0:4] = b"MAC "
    struct.pack_into("<H", header, 4, 3990)
    struct.pack_into("<IIIHHI", header, 56, 73728 * 4, 73728, 1, 16, 2, 44100)
    return bytes(header) + b"\x00" * 256


def make_flac(path: Path, with_cover: bool = False) -> None:
    from mutagen.flac import FLAC, Picture

    path.write_bytes(flac_header())
    if with_cover:
        picture = Picture()
        picture.type, picture.mime, picture.data = 3, "image/png", image_bytes("PNG")
        audio = FLAC(path)
        audio.add_picture(picture)
        audio.save()


def make_mp3(path: Path, with_cover: bool = False) -> None:
    from mutagen.id3 import APIC, ID3, TIT2

    path.write_bytes(MP3_FRAMES)
    tags = ID3()
    tags.add(TIT2(encoding=3, text="Song"))
    if with_cover:
        tags.add(
            APIC(
                encoding=3,
                mime="image/png",
                type=3,
                desc="",
                data=image_bytes("PNG"),
            )
        )
    tags.save(path, v2_version=3)


def image_bytes(image_format: str = "JPEG", color: str = "#e97824") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buffer, format=image_format)
    return buffer.getvalue()


class CoverPlanTests(unittest.TestCase):
    def test_only_files_without_art_in_folders_with_cover_are_targets(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Album").mkdir()
            (root / "Album" / "cover.jpeg").write_bytes(image_bytes())
            make_flac(root / "Album" / "one.flac")
            make_flac(root / "Album" / "two.flac", with_cover=True)
            # A folder without any cover image must be ignored entirely.
            (root / "Other").mkdir()
            make_flac(root / "Other" / "three.flac")

            plan = plan_cover_embedding(root, extensions={".flac"})

        self.assertEqual(plan.folder_count, 1)
        self.assertEqual(plan.target_count, 1)
        self.assertEqual(plan.folders[0].targets[0].path.name, "one.flac")
        self.assertEqual(plan.folders[0].targets[0].reason, ArtState.MISSING)
        self.assertEqual(plan.files_with_cover, 1)
        self.assertEqual(plan.folders_without_cover, 1)
        self.assertEqual(plan.problems, ())

    def test_cover_prefers_cover_over_other_art_names(self) -> None:
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "folder.jpg").write_bytes(image_bytes())
            (folder / "Cover.JPEG").write_bytes(image_bytes("PNG"))
            (folder / "back.png").write_bytes(image_bytes("PNG"))

            chosen = find_folder_cover(folder)

        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.name, "Cover.JPEG")

    def test_hidden_and_excluded_folders_are_not_scanned(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("Keep", "_skip", ".hidden"):
                (root / name).mkdir()
                (root / name / "cover.jpg").write_bytes(image_bytes())
                make_flac(root / name / "one.flac")

            plan = plan_cover_embedding(
                root,
                extensions={".flac"},
                excluded_folders=["_skip"],
            )

        self.assertEqual([folder.relative_folder for folder in plan.folders], ["Keep"])

    def test_hidden_audio_files_are_ignored(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cover.jpg").write_bytes(image_bytes())
            make_flac(root / "one.flac")
            # AppleDouble companion written by macOS: not audio at all.
            (root / "._one.flac").write_bytes(b"\x00\x05\x16\x07" + b"\x00" * 80)

            plan = plan_cover_embedding(root, extensions={".flac"})

        self.assertEqual(plan.files_scanned, 1)
        self.assertEqual(plan.problems, ())
        self.assertEqual(
            [target.path.name for target in plan.folders[0].targets],
            ["one.flac"],
        )

    def test_broken_art_is_replaced_only_on_request(self) -> None:
        from mutagen.id3 import APIC, ID3

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cover.jpg").write_bytes(image_bytes())
            make_mp3(root / "broken.mp3")
            tags = ID3(root / "broken.mp3")
            tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=b"nope"))
            tags.save(root / "broken.mp3")

            kept = plan_cover_embedding(root, extensions={".mp3"})
            replaced = plan_cover_embedding(
                root, extensions={".mp3"}, replace_broken=True
            )

        self.assertEqual(kept.target_count, 0)
        self.assertEqual(kept.files_with_broken_cover, 1)
        self.assertEqual(replaced.target_count, 1)
        self.assertEqual(replaced.folders[0].targets[0].reason, ArtState.BROKEN)

    def test_broken_cover_file_is_reported_not_embedded(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cover.jpg").write_bytes(b"this is not an image")
            make_flac(root / "one.flac")

            plan = plan_cover_embedding(root, extensions={".flac"})
            with self.assertRaisesRegex(ValueError, "не является изображением"):
                read_cover_image(root / "cover.jpg")

        self.assertEqual(plan.folder_count, 0)
        self.assertEqual(len(plan.problems), 1)
        self.assertIn("cover.jpg", plan.problems[0].relative_path)

    def test_unreadable_audio_file_is_reported_not_targeted(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cover.jpg").write_bytes(image_bytes())
            (root / "broken.mp3").write_bytes(b"not audio at all")

            plan = plan_cover_embedding(root, extensions={".mp3"})

        self.assertEqual(plan.target_count, 0)
        self.assertEqual(len(plan.problems), 1)
        self.assertEqual(inspect_art(root / "broken.mp3")[0], ArtState.UNREADABLE)


class CoverEmbedTests(unittest.TestCase):
    def test_flac_receives_cover_backup_and_keeps_mtime(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / "backup"
            album = root / "Album"
            album.mkdir()
            cover_bytes = image_bytes()
            (album / "cover.jpeg").write_bytes(cover_bytes)
            make_flac(album / "one.flac")
            os.utime(album / "one.flac", (1_600_000_000, 1_600_000_000))

            plan = plan_cover_embedding(root, extensions={".flac"})
            result = embed_covers(plan, backup_root=backup)
            second = plan_cover_embedding(root, extensions={".flac"})
            data, mime, error = read_embedded_cover(album / "one.flac")
            saved_backup = (backup / "Album" / "one.flac").read_bytes()
            saved_mtime = (album / "one.flac").stat().st_mtime

        self.assertEqual(result.updated_files, 1)
        self.assertEqual(result.backup_files, 1)
        self.assertEqual(result.failures, ())
        self.assertEqual(data, cover_bytes)
        self.assertEqual(mime, "image/jpeg")
        self.assertEqual(error, "")
        self.assertEqual(saved_backup, flac_header())
        self.assertEqual(second.target_count, 0)
        self.assertEqual(second.files_with_cover, 1)
        self.assertEqual(saved_mtime, 1_600_000_000)

    def test_flac_picture_metadata_matches_the_image(self) -> None:
        from mutagen.flac import FLAC

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cover.png").write_bytes(image_bytes("PNG"))
            make_flac(root / "one.flac")

            embed_covers(plan_cover_embedding(root, extensions={".flac"}))
            pictures = FLAC(root / "one.flac").pictures

        self.assertEqual(len(pictures), 1)
        self.assertEqual(pictures[0].type, 3)
        self.assertEqual(pictures[0].mime, "image/png")
        self.assertEqual((pictures[0].width, pictures[0].height), (64, 64))
        self.assertEqual(pictures[0].depth, 24)

    def test_mp3_keeps_id3v23_and_stores_the_cover(self) -> None:
        from mutagen.id3 import ID3

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cover.png").write_bytes(image_bytes("PNG"))
            make_mp3(root / "one.mp3")

            result = embed_covers(plan_cover_embedding(root, extensions={".mp3"}))
            tags = ID3(root / "one.mp3")

        self.assertEqual(result.updated_files, 1)
        self.assertEqual(tags.version[:2], (2, 3))
        self.assertEqual(tags["TIT2"].text, ["Song"])
        self.assertEqual(tags.getall("APIC")[0].mime, "image/png")
        self.assertEqual(tags.getall("APIC")[0].data, image_bytes("PNG"))

    def test_replacing_a_broken_flac_cover_keeps_other_pictures(self) -> None:
        # «Заменять повреждённые обложки» used to wipe every embedded picture:
        # a valid back cover or booklet scan was lost with the broken front.
        from mutagen.flac import FLAC, Picture

        back_bytes = image_bytes(color="#2f75b5")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cover.jpg").write_bytes(image_bytes())
            make_flac(root / "one.flac")
            audio = FLAC(root / "one.flac")
            for kind, data in ((3, b"broken front"), (4, back_bytes)):
                picture = Picture()
                picture.type, picture.mime, picture.data = kind, "image/jpeg", data
                audio.add_picture(picture)
            audio.save()

            plan = plan_cover_embedding(
                root, extensions={".flac"}, replace_broken=True
            )
            result = embed_covers(plan)
            pictures = FLAC(root / "one.flac").pictures

        self.assertEqual(result.updated_files, 1)
        self.assertEqual(
            [(picture.type, picture.data) for picture in pictures],
            [(3, image_bytes()), (4, back_bytes)],
        )

    def test_replacing_a_broken_mp3_cover_keeps_other_pictures(self) -> None:
        from mutagen.id3 import APIC, ID3

        back_bytes = image_bytes("PNG", color="#2f75b5")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cover.jpg").write_bytes(image_bytes())
            make_mp3(root / "one.mp3")
            tags = ID3(root / "one.mp3")
            # The kept picture is named like the new one on purpose: adding
            # the new frame must not overwrite it.
            for kind, desc, data in ((3, "", b"nope"), (4, "Cover", back_bytes)):
                tags.add(
                    APIC(encoding=3, mime="image/png", type=kind, desc=desc, data=data)
                )
            tags.save(root / "one.mp3", v2_version=3)

            plan = plan_cover_embedding(
                root, extensions={".mp3"}, replace_broken=True
            )
            result = embed_covers(plan)
            frames = ID3(root / "one.mp3").getall("APIC")

        self.assertEqual(result.updated_files, 1)
        self.assertEqual(
            sorted((frame.type, frame.data) for frame in frames),
            [(3, image_bytes()), (4, back_bytes)],
        )

    def test_ape_cover_is_stored_as_apev2_binary(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cover_bytes = image_bytes()
            (root / "cover.jpeg").write_bytes(cover_bytes)
            (root / "one.ape").write_bytes(ape_header())

            result = embed_covers(plan_cover_embedding(root, extensions={".ape"}))
            data, _mime, error = read_embedded_cover(root / "one.ape")
            second = plan_cover_embedding(root, extensions={".ape"})

        self.assertEqual(result.updated_files, 1)
        self.assertFalse(result.failures)
        self.assertEqual(data, cover_bytes)
        self.assertEqual(error, "")
        self.assertEqual(second.target_count, 0)

    def test_failed_verification_keeps_the_original_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            album = root / "Album"
            album.mkdir()
            (album / "cover.jpeg").write_bytes(image_bytes())
            make_flac(album / "one.flac")
            original = (album / "one.flac").read_bytes()

            plan = plan_cover_embedding(root, extensions={".flac"})
            with patch(
                "discography_analyzer.cover_embedding.verify_cover",
                side_effect=ValueError("проверка обложки после записи не пройдена"),
            ):
                result = embed_covers(plan, backup_root=root / "backup")

            self.assertEqual(result.updated_files, 0)
            self.assertEqual(len(result.failures), 1)
            self.assertIn("проверка обложки", result.failures[0].reason)
            self.assertEqual((album / "one.flac").read_bytes(), original)
            self.assertEqual(list(album.glob(".one-cover-*.flac")), [])
            self.assertFalse((root / "backup").exists())

    def test_stop_event_stops_before_any_write(self) -> None:
        import threading

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cover.jpeg").write_bytes(image_bytes())
            make_flac(root / "one.flac")
            plan = plan_cover_embedding(root, extensions={".flac"})
            stop = threading.Event()
            stop.set()

            result = embed_covers(plan, stop_event=stop)

        self.assertTrue(result.stopped)
        self.assertEqual(result.updated_files, 0)

    def test_cover_image_reads_mime_from_content_not_suffix(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "cover.jpg"
            path.write_bytes(image_bytes("PNG"))

            cover = read_cover_image(path)

        self.assertIsInstance(cover, CoverImage)
        self.assertEqual(cover.mime, "image/png")
        self.assertEqual(cover.size, len(image_bytes("PNG")))
        self.assertEqual(
            cover.digest, hashlib.sha256(image_bytes("PNG")).hexdigest()
        )


if __name__ == "__main__":
    unittest.main()
