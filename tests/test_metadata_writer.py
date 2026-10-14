from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from discography_analyzer.audit_models import (
    AuditCategory,
    AuditConfidence,
    AuditFixKind,
    AuditSeverity,
    MetadataAuditIssue,
)
from discography_analyzer.metadata_writer import (
    _write_verified_copy,
    apply_metadata_fixes,
)
from discography_analyzer.models import Track


def make_track(identifier: str) -> Track:
    path = Path(f"/music/Album/{identifier}.flac")
    return Track(
        id=identifier,
        path=path,
        root=Path("/music"),
        filename=path.name,
        relative_path=f"Album/{path.name}",
        relative_folder="Album",
        format="FLAC",
        size_bytes=100,
        artist="Riana;Moby",
    )


def make_issue(identifier: str, track_id: str) -> MetadataAuditIssue:
    return MetadataAuditIssue(
        id=identifier,
        track_id=track_id,
        severity=AuditSeverity.WARNING,
        category=AuditCategory.ARTISTS,
        field="artist",
        message="Разделитель",
        current_value="Riana;Moby",
        suggested_value="Riana, Moby",
        fix_kind=AuditFixKind.NORMALIZE_ARTISTS,
        confidence=AuditConfidence.HIGH,
    )


class MetadataWriterTests(unittest.TestCase):
    def test_failed_verification_leaves_original_file_unchanged(self) -> None:
        class FakeAudio:
            def __init__(self, artist: str) -> None:
                self.tags = {"artist": [artist]}

            def __setitem__(self, key, value) -> None:
                self.tags[key] = value

            def save(self) -> None:
                pass

        with TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Album"
            folder.mkdir()
            source = folder / "one.flac"
            source.write_bytes(b"original audio")
            item = make_track("one")
            item.root = root
            item.path = source
            item.filename = source.name
            fake_mutagen = SimpleNamespace(
                File=Mock(
                    side_effect=[
                        FakeAudio("Riana;Moby"),  # raw read for save options
                        FakeAudio("Riana;Moby"),  # easy view that gets edited
                        FakeAudio("wrong result"),  # verification re-read
                    ]
                )
            )
            with patch(
                "discography_analyzer.metadata_writer.mutagen",
                fake_mutagen,
            ), self.assertRaisesRegex(ValueError, "проверка тега"):
                _write_verified_copy(
                    item,
                    {"artist": "Riana, Moby"},
                    root.parent / "Backup",
                )

            self.assertEqual(source.read_bytes(), b"original audio")
            self.assertEqual(item.artist, "Riana;Moby")
            self.assertFalse((root.parent / "Backup").exists())
            self.assertEqual(
                list(folder.glob(".one-audit-*.flac")),
                [],
            )

    def test_id3v23_container_version_is_preserved(self) -> None:
        from mutagen.id3 import ID3, TIT2, TPE1

        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "Album" / "one.mp3"
            source.parent.mkdir()
            # MPEG-1 Layer III, 128 kbps, 44.1 kHz: 417-byte frames.
            source.write_bytes((b"\xff\xfb\x90\x00" + b"\x00" * 413) * 40)
            tags = ID3()
            tags.add(TIT2(encoding=3, text="Song"))
            tags.add(TPE1(encoding=3, text="Riana;Moby"))
            tags.save(source, v2_version=3)
            self.assertEqual(ID3(source).version[:2], (2, 3))

            item = make_track("one")
            item.root = root
            item.path = source
            item.filename = source.name

            _write_verified_copy(item, {"artist": "Riana, Moby"}, None)

            saved = ID3(source)
            self.assertEqual(saved.version[:2], (2, 3))
            self.assertEqual(saved["TPE1"].text, ["Riana, Moby"])
            self.assertEqual(saved["TIT2"].text, ["Song"])
            self.assertEqual(item.artist, "Riana, Moby")

    def test_issues_for_one_file_are_written_in_one_job(self) -> None:
        item = make_track("one")
        artist_issue = make_issue("artist", item.id)
        title_issue = MetadataAuditIssue(
            id="title",
            track_id=item.id,
            severity=AuditSeverity.WARNING,
            category=AuditCategory.FORMATTING,
            field="title",
            message="Пробелы",
            current_value="  Song ",
            suggested_value="Song",
            fix_kind=AuditFixKind.NORMALIZE_WHITESPACE,
            confidence=AuditConfidence.HIGH,
        )
        with patch(
            "discography_analyzer.metadata_writer._write_verified_copy",
            return_value=True,
        ) as writer:
            result = apply_metadata_fixes(
                {item.id: item},
                [artist_issue, title_issue],
                backup_root=Path("/backup"),
            )

        writer.assert_called_once_with(
            item,
            {"artist": "Riana, Moby", "title": "Song"},
            Path("/backup"),
        )
        self.assertEqual(result.updated_files, 1)
        self.assertEqual(result.backup_files, 1)
        self.assertFalse(result.failures)

    def test_failure_is_reported_without_counting_update(self) -> None:
        item = make_track("one")
        with patch(
            "discography_analyzer.metadata_writer._write_verified_copy",
            side_effect=ValueError("verification failed"),
        ):
            result = apply_metadata_fixes(
                {item.id: item},
                [make_issue("artist", item.id)],
            )

        self.assertEqual(result.updated_files, 0)
        self.assertEqual(len(result.failures), 1)
        self.assertIn("verification failed", result.failures[0].reason)


if __name__ == "__main__":
    unittest.main()
