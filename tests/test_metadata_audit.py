from __future__ import annotations

import dataclasses
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
    disc_number: str = "1/1",
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
        disc_number=disc_number,
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

    def test_declared_total_below_highest_number_is_reported_per_file(self) -> None:
        # Real «Christmas & Chill» case: six files keep TRACKTOTAL=6 from the
        # 6-track edition, the seventh declares 7/7.
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "Album"
            folder.mkdir()
            tracks = [
                make_track(
                    str(number),
                    folder,
                    track_number=f"{number}/6" if number < 7 else "7/7",
                )
                for number in range(1, 8)
            ]
            issues = audit_metadata(tracks)

        total_issues = [
            issue for issue in issues if issue.message.startswith("Итог Track #")
        ]
        self.assertEqual(len(total_issues), 6)
        self.assertEqual(
            {issue.track_id for issue in total_issues},
            {str(number) for number in range(1, 7)},
        )
        self.assertTrue(
            all(issue.severity == AuditSeverity.WARNING for issue in total_issues)
        )
        self.assertTrue(all(not issue.fixable for issue in total_issues))
        self.assertEqual(total_issues[0].current_value, "1/6")
        self.assertEqual(total_issues[0].suggested_value, "1/7")
        self.assertIn("на диске (7)", total_issues[0].message)

    def test_equal_totals_produce_no_total_warning(self) -> None:
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "Album"
            folder.mkdir()
            tracks = [
                make_track(str(number), folder, track_number=f"{number}/7")
                for number in range(1, 8)
            ]
            issues = audit_metadata(tracks)

        self.assertFalse(
            any(issue.message.startswith("Итог Track #") for issue in issues)
        )

    def test_multi_disc_totals_are_checked_per_disc(self) -> None:
        # Disc 1 declares 10 tracks, disc 2 declares 12: two different totals in
        # one album are normal for a multi-disc set and must not be flagged.
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "Album"
            folder.mkdir()
            tracks = [
                make_track(f"d1-{number}", folder, track_number=f"{number}/10")
                for number in (1, 2, 3)
            ] + [
                make_track(
                    f"d2-{number}",
                    folder,
                    track_number=f"{number}/12",
                    disc_number="2/2",
                )
                for number in (1, 2)
            ]
            issues = audit_metadata(tracks)

        self.assertFalse(
            any(issue.message.startswith("Итог Track #") for issue in issues)
        )

    def test_cover_suggestion_names_the_file_the_utility_embeds(self) -> None:
        # The audit picked the first file alphabetically (AlbumArt.jpg) while
        # the cover utility embeds cover.jpg: the suggestion named a different
        # picture than the one the fix would write.
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "Album"
            folder.mkdir()
            (folder / "AlbumArt.jpg").write_bytes(b"jpeg")
            (folder / "cover.jpg").write_bytes(b"jpeg")
            item = make_track("one", folder)
            item.cover_hash = ""
            issues = audit_metadata([item])

        suggestions = [
            issue.suggested_value for issue in issues if issue.field == "cover"
        ]
        self.assertEqual(suggestions, ["Встроить файл cover.jpg"])

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


def quality_track(
    identifier: str,
    folder: Path,
    *,
    fmt: str = "FLAC",
    bitrate: int = 0,
    sample_rate: int = 44100,
    bit_depth: int = 16,
    codec: str = "",
) -> Track:
    return dataclasses.replace(
        make_track(identifier, folder, track_number=f"{identifier}/10"),
        format=fmt,
        bitrate=bitrate,
        sample_rate=sample_rate,
        bit_depth=bit_depth,
        codec=codec,
    )


class QualityAuditTests(unittest.TestCase):
    """The album was assembled from different sources: mixed formats,
    a falling bitrate, a different resolution."""

    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.folder = Path(self._temp.name) / "Album"
        self.folder.mkdir(parents=True)
        self.addCleanup(self._temp.cleanup)

    def quality(self, tracks: list[Track]):
        return [
            issue
            for issue in audit_metadata(tracks)
            if issue.category is AuditCategory.QUALITY
        ]

    def test_foreign_format_is_a_warning_on_that_file(self) -> None:
        tracks = [
            quality_track("1", self.folder),
            quality_track("2", self.folder),
            quality_track("3", self.folder),
            quality_track("4", self.folder),
            quality_track("5", self.folder, fmt="MP3", bitrate=320_000, codec=""),
        ]

        issues = self.quality(tracks)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].track_id, "5")
        self.assertIs(issues[0].severity, AuditSeverity.WARNING)
        self.assertEqual(issues[0].field, "format")
        self.assertIn("Формат MP3", issues[0].message)
        self.assertIn("FLAC", issues[0].message)

    def test_a_falling_bitrate_is_a_warning(self) -> None:
        tracks = [
            quality_track("1", self.folder, fmt="MP3", bitrate=320_000),
            quality_track("2", self.folder, fmt="MP3", bitrate=320_000),
            quality_track("3", self.folder, fmt="MP3", bitrate=320_000),
            quality_track("4", self.folder, fmt="MP3", bitrate=128_000),
        ]

        issues = self.quality(tracks)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].track_id, "4")
        self.assertEqual(issues[0].field, "bitrate")
        self.assertIn("128 kbps", issues[0].message)
        self.assertIn("320 kbps", issues[0].message)

    def test_a_vbr_album_is_not_flagged(self) -> None:
        tracks = [
            quality_track(str(index), self.folder, fmt="MP3", bitrate=rate * 1000)
            for index, rate in enumerate((190, 210, 235, 260), start=1)
        ]

        self.assertEqual(self.quality(tracks), [])

    def test_a_different_lossless_resolution_is_a_recommendation(self) -> None:
        tracks = [
            quality_track("1", self.folder),
            quality_track("2", self.folder),
            quality_track("3", self.folder),
            quality_track(
                "4", self.folder, sample_rate=96000, bit_depth=24
            ),
        ]

        issues = self.quality(tracks)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].track_id, "4")
        self.assertIs(issues[0].severity, AuditSeverity.INFO)
        self.assertEqual(
            issues[0].message,
            "96 kHz/24 bit при 44.1 kHz/16 bit у большинства треков альбома",
        )

    def test_a_single_track_and_unknown_bitrates_stay_silent(self) -> None:
        self.assertEqual(self.quality([quality_track("1", self.folder)]), [])
        self.assertEqual(
            self.quality(
                [
                    quality_track("1", self.folder, fmt="MP3"),
                    quality_track("2", self.folder, fmt="MP3"),
                ]
            ),
            [],
        )

    def test_a_tie_between_formats_is_a_recommendation_for_every_file(self) -> None:
        tracks = [
            quality_track("1", self.folder),
            quality_track("2", self.folder),
            quality_track("3", self.folder, fmt="MP3", bitrate=320_000),
            quality_track("4", self.folder, fmt="MP3", bitrate=320_000),
        ]

        issues = self.quality(tracks)

        self.assertEqual(len(issues), 4)
        self.assertTrue(
            all(issue.severity is AuditSeverity.INFO for issue in issues)
        )
        self.assertTrue(all(issue.fix_kind is None for issue in issues))
