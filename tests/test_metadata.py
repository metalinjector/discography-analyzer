from __future__ import annotations

import io
import struct
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from discography_analyzer.metadata import (
    _cover_details,
    _first,
    _values,
    read_embedded_cover,
    read_metadata,
)
from discography_analyzer.models import Track

# MPEG-1 Layer III, 128 kbps, 44.1 kHz: 417-byte frames, ~26 ms each.
MP3_FRAMES = (b"\xff\xfb\x90\x00" + b"\x00" * 413) * 40


def _flac_header() -> bytes:
    """Minimal FLAC: "fLaC" + STREAMINFO (44.1 kHz, stereo, 16 bit, 1 s)."""
    streaminfo = struct.pack(">HH", 4096, 4096) + b"\x00" * 6
    bits = (44100 << 44) | (1 << 41) | (15 << 36) | 44100
    streaminfo += bits.to_bytes(8, "big") + b"\x00" * 16
    return b"fLaC" + bytes([0x80]) + len(streaminfo).to_bytes(3, "big") + streaminfo


FLAC_HEADER = _flac_header()


def make_track(path: Path) -> Track:
    return Track(
        id="one",
        path=path,
        root=path.parent,
        filename=path.name,
        relative_path=path.name,
        relative_folder=str(path.parent),
        format=path.suffix[1:].upper(),
        size_bytes=path.stat().st_size,
    )


class _LazyTags:
    """Mimics mutagen's EasyID3: ``len()`` is a full key enumeration."""

    def __init__(self, data: dict[str, list[str]]) -> None:
        self._data = data
        self.length_calls = 0

    def __len__(self) -> int:
        self.length_calls += 1
        return len(self._data)

    def get(self, key: str, default=None):
        return self._data.get(key, default)


class MetadataTests(unittest.TestCase):
    def test_tag_helpers_do_not_enumerate_easy_tags(self) -> None:
        # ``bool(EasyID3)`` walks every registered easy key, which made tag
        # lookups the slowest part of the whole analysis.
        tags = _LazyTags({"title": ["Song"], "artist": ["A", "B"]})

        self.assertEqual(_first(tags, "title"), "Song")
        self.assertEqual(_values(tags, "artist"), ["A", "B"])
        self.assertEqual(_values(tags, "album"), [])
        self.assertEqual(_first(None, "title"), "")
        self.assertEqual(_values(None, "title"), [])
        self.assertEqual(tags.length_calls, 0)

    def test_formats_without_easy_wrapper_are_parsed_once(self) -> None:
        import mutagen
        from mutagen.id3 import ID3, TIT2

        import discography_analyzer.metadata as metadata

        with TemporaryDirectory() as directory:
            flac_path = Path(directory) / "song.flac"
            flac_path.write_bytes(FLAC_HEADER)
            mp3_path = Path(directory) / "song.mp3"
            mp3_path.write_bytes(MP3_FRAMES)
            tags = ID3()
            tags.add(TIT2(encoding=3, text="Song"))
            tags.save(mp3_path)
            flac_item, mp3_item = make_track(flac_path), make_track(mp3_path)

            with patch.object(
                metadata.mutagen, "File", wraps=mutagen.File
            ) as file_calls:
                read_metadata(flac_item)
                flac_parses = file_calls.call_count
                read_metadata(mp3_item)
                mp3_parses = file_calls.call_count - flac_parses

        self.assertEqual(flac_item.metadata_errors, [])
        self.assertEqual(flac_item.duration_seconds, 1)
        self.assertEqual(flac_parses, 1)
        # ID3 needs the distinct EasyID3 view, so two parses are expected.
        self.assertEqual(mp3_parses, 2)
        self.assertEqual(mp3_item.metadata_errors, [])

    def test_preview_and_audit_agree_on_front_cover(self) -> None:
        import hashlib

        from mutagen.flac import FLAC, Picture

        def png(color: str) -> bytes:
            buffer = io.BytesIO()
            Image.new("RGB", (8, 8), color).save(buffer, format="PNG")
            return buffer.getvalue()

        with TemporaryDirectory() as directory:
            path = Path(directory) / "song.flac"
            path.write_bytes(FLAC_HEADER)
            audio = FLAC(path)
            back, front = Picture(), Picture()
            back.type, back.mime, back.data = 4, "image/png", png("#2f75b5")
            front.type, front.mime, front.data = 3, "image/png", png("#e97824")
            audio.add_picture(back)  # back cover deliberately listed first
            audio.add_picture(front)
            audio.save()
            item = make_track(path)

            read_metadata(item)
            data, mime, error = read_embedded_cover(path)

        self.assertEqual(error, "")
        self.assertEqual(mime, "image/png")
        self.assertEqual(data, front.data)
        self.assertEqual(item.cover_hash, hashlib.sha256(front.data).hexdigest())
        self.assertEqual((item.cover_width, item.cover_height), (8, 8))

    def test_id3_comment_frame_is_mapped_but_technical_frames_are_not(self) -> None:
        from mutagen.id3 import COMM, ID3, TIT2

        with TemporaryDirectory() as directory:
            path = Path(directory) / "song.mp3"
            path.write_bytes(MP3_FRAMES)
            tags = ID3()
            tags.add(TIT2(encoding=3, text="Song"))
            tags.add(COMM(encoding=3, lang="eng", desc="iTunNORM", text=" 0000 "))
            tags.add(COMM(encoding=3, lang="eng", desc="", text="Remastered 2011"))
            tags.save(path)
            item = make_track(path)

            read_metadata(item)

        self.assertEqual(item.title, "Song")
        self.assertEqual(item.comment, "Remastered 2011")
        self.assertEqual(item.canonical_tags["comment"], ["Remastered 2011"])
        self.assertIn("COMM:iTunNORM:eng", item.all_tags)
        self.assertEqual(item.metadata_errors, [])

    def test_cover_details_validate_image_and_dimensions(self) -> None:
        buffer = io.BytesIO()
        Image.new("RGB", (32, 48), "#e97824").save(buffer, format="PNG")

        mime, size, digest, width, height, error = _cover_details(
            buffer.getvalue(),
            "image/png",
        )

        self.assertEqual(mime, "image/png")
        self.assertGreater(size, 0)
        self.assertEqual(len(digest), 64)
        self.assertEqual((width, height), (32, 48))
        self.assertEqual(error, "")

    def test_broken_cover_is_reported(self) -> None:
        _mime, _size, _digest, _width, _height, error = _cover_details(
            b"not an image",
            "image/jpeg",
        )
        self.assertTrue(error)

    def test_oversized_cover_is_a_cover_error_not_a_file_error(self) -> None:
        import zlib

        from mutagen.id3 import APIC, ID3, TIT2

        def chunk(kind: bytes, payload: bytes) -> bytes:
            crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
            return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

        # A PNG header claiming 30000x30000 pixels trips Pillow's
        # decompression-bomb guard, which is not an OSError/ValueError.
        bomb = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 30000, 30000, 8, 2, 0, 0, 0))
            + chunk(b"IEND", b"")
        )

        with TemporaryDirectory() as directory:
            path = Path(directory) / "song.mp3"
            path.write_bytes(MP3_FRAMES)
            tags = ID3()
            tags.add(TIT2(encoding=3, text="Song"))
            tags.add(APIC(encoding=3, mime="image/png", type=3, desc="", data=bomb))
            tags.save(path)
            item = make_track(path)

            read_metadata(item)

        self.assertEqual(item.title, "Song")
        self.assertEqual(item.metadata_errors, [])
        self.assertIn("exceeds limit", item.cover_error)
        self.assertEqual(item.cover_size, len(bomb))
        self.assertEqual((item.cover_width, item.cover_height), (0, 0))


if __name__ == "__main__":
    unittest.main()
