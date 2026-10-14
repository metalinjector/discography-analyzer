import unittest
from pathlib import Path

from discography_analyzer.completeness import (
    analyze_track_completeness,
    parse_position,
)
from discography_analyzer.models import Track


def make_track(
    identifier: str,
    number: str,
    *,
    album: str = "Album",
    folder: str = "Artist/Album",
    disc: str = "1/1",
) -> Track:
    path = Path("/music") / folder / f"{identifier}.flac"
    return Track(
        id=identifier,
        path=path,
        root=Path("/music"),
        filename=path.name,
        relative_path=str(path.relative_to("/music")),
        relative_folder=folder,
        format="FLAC",
        size_bytes=100,
        filename_title=identifier,
        album=album,
        track_number=number,
        disc_number=disc,
    )


class CompletenessTests(unittest.TestCase):
    def test_position_variants(self) -> None:
        self.assertEqual(parse_position("4/10"), (4, 10))
        self.assertEqual(parse_position("4 of 10"), (4, 10))
        self.assertEqual(parse_position("4"), (4, None))
        self.assertEqual(parse_position(""), (None, None))

    def test_total_in_tags_finds_internal_and_trailing_gaps(self) -> None:
        tracks = [
            make_track(str(number), f"{number}/10")
            for number in (1, 2, 3, 4, 6, 7, 8)
        ]
        issues = analyze_track_completeness(tracks)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].missing_numbers, (5, 9, 10))
        self.assertTrue(issues[0].total_from_tags)
        self.assertTrue(all("пропущены № 5, 9, 10" in item.collection_warning for item in tracks))

    def test_plain_sequence_finds_internal_gap(self) -> None:
        tracks = [make_track(str(number), str(number)) for number in (1, 2, 4, 5)]
        issues = analyze_track_completeness(tracks)
        self.assertEqual(issues[0].missing_numbers, (3,))
        self.assertFalse(issues[0].total_from_tags)

    def test_complete_album_has_no_issue(self) -> None:
        tracks = [make_track("one", "1/2"), make_track("two", "2/2")]
        self.assertEqual(analyze_track_completeness(tracks), [])
        self.assertTrue(all(not track.collection_warning for track in tracks))

    def test_discs_are_checked_separately(self) -> None:
        tracks = [
            make_track("d1-1", "1/2", disc="1/2"),
            make_track("d1-2", "2/2", disc="1/2"),
            make_track("d2-1", "1/2", disc="2/2"),
        ]
        issues = analyze_track_completeness(tracks)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].disc, 2)
        self.assertEqual(issues[0].missing_numbers, (2,))


if __name__ == "__main__":
    unittest.main()
