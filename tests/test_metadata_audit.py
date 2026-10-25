from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from discography_analyzer.audit_models import (
    AuditCategory,
    AuditConfidence,
    AuditSeverity,
)
from discography_analyzer.metadata_audit import (
    audit_metadata,
    normalize_artist_value,
)
from discography_analyzer.models import Track


def make_track(
    identifier: str,
    folder: Path,
    *,
    artist: str = "Moby",
    album_artist: str = "Moby",
    track_number: str = "1/1",
) -> Track:
    path = folder / f"{identifier}.flac"
    return Track(
        id=identifier,
        path=path,
        root=folder.parent,
        filename=path.name,
        relative_path=f"{folder.name}/{path.name}",
        relative_folder=folder.name,
        format="FLAC",
        size_bytes=1000,
        title=f"Track {identifier}",
        artist=artist,
        album="Album",
        album_artist=album_artist,
        year="2009",
        track_number=track_number,
        duration_exact=180.0,
        duration_seconds=180,
        cover_hash="cover-a",
        cover_width=1000,
        cover_height=1000,
        canonical_tags={
            "title": [f"Track {identifier}"],
            "artist": [artist] if artist else [],
            "album": ["Album"],
            "album_artist": [album_artist] if album_artist else [],
            "year": ["2009"],
        },
    )


class MetadataAuditTests(unittest.TestCase):
    def test_artist_separator_normalization(self) -> None:
        expected = "Riana, Moby"
        for value in ("Riana,Moby", "Riana;Moby", "Riana; Moby"):
            with self.subTest(value=value):
                self.assertEqual(normalize_artist_value(value), (expected, True))

    def test_malformed_artist_separator_is_safe_fix(self) -> None:
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "Album"
            folder.mkdir()
            item = make_track(
                "one",
                folder,
                artist="Riana;Moby",
                album_artist="Riana; Moby",
            )
            issues = audit_metadata([item])

        fixes = [
            issue
            for issue in issues
            if issue.field in {"artist", "album_artist"} and issue.fixable
        ]
        self.assertEqual(len(fixes), 2)
        self.assertTrue(all(issue.safe_fix for issue in fixes))
        self.assertEqual(
            {issue.suggested_value for issue in fixes},
            {"Riana, Moby"},
        )

    def test_native_multi_value_artists_are_not_flattened(self) -> None:
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "Album"
            folder.mkdir()
            item = make_track(
                "one",
                folder,
                artist="Riana; Moby",
                album_artist="Riana; Moby",
            )
            item.canonical_tags["artist"] = ["Riana", "Moby"]
            item.canonical_tags["album_artist"] = ["Riana", "Moby"]
            issues = audit_metadata([item])

        self.assertFalse(
            any(
                issue.category == AuditCategory.ARTISTS and issue.fixable
                for issue in issues
            )
        )

    def test_guest_artist_difference_is_only_low_confidence_info(self) -> None:
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "Album"
            folder.mkdir()
            item = make_track(
                "one",
                folder,
                artist="Moby, Riana",
                album_artist="Moby",
            )
            issues = audit_metadata([item])

        guest_issue = next(
            issue
            for issue in issues
            if "дополнительные исполнители" in issue.message
        )
        self.assertEqual(guest_issue.severity, AuditSeverity.INFO)
        self.assertEqual(guest_issue.confidence, AuditConfidence.LOW)
        self.assertFalse(guest_issue.fixable)

    def test_missing_required_data_cover_and_duration_are_errors(self) -> None:
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "Album"
            folder.mkdir()
            item = make_track("one", folder, artist="")
            item.title = ""
            item.album = ""
            item.duration_exact = None
            item.cover_hash = ""
            issues = audit_metadata([item])

        error_fields = {
            issue.field
            for issue in issues
            if issue.severity == AuditSeverity.ERROR
        }
        self.assertTrue(
            {"title", "artist", "album", "duration", "cover"}
            <= error_fields
        )

    def test_duplicate_and_invalid_track_numbers_are_reported(self) -> None:
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "Album"
            folder.mkdir()
            first = make_track("one", folder, track_number="1/10 trailing")
            second = make_track("two", folder, track_number="1/10")
            issues = audit_metadata([first, second])

        self.assertTrue(
            any(
                issue.track_id == first.id
                and issue.message == "Некорректный номер трека"
                for issue in issues
            )
        )
        self.assertTrue(
            any("повторяется" in issue.message for issue in issues)
        )

    def _cover_mismatch_track_ids(self, cover_hashes: list[str]) -> list[str]:
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "Album"
            folder.mkdir()
            tracks = []
            for number, cover_hash in enumerate(cover_hashes, start=1):
                item = make_track(
                    f"t{number}",
                    folder,
                    track_number=f"{number}/{len(cover_hashes)}",
                )
                item.cover_hash = cover_hash
                tracks.append(item)
            issues = audit_metadata(tracks)
        return [
            issue.track_id
            for issue in issues
            if issue.message.startswith("Обложка отличается")
        ]

    def test_cover_tie_has_no_dominant_cover_warning(self) -> None:
        self.assertEqual(
            self._cover_mismatch_track_ids(["a", "a", "b", "b"]),
            [],
        )

    def test_cover_unique_leader_still_warns(self) -> None:
        self.assertEqual(
            self._cover_mismatch_track_ids(["a", "a", "a", "b"]),
            ["t4"],
        )


if __name__ == "__main__":
    unittest.main()
