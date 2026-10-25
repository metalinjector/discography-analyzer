import unittest
from pathlib import Path

from discography_analyzer.completeness import (
    analyze_track_completeness,
    parse_position,
)
from discography_analyzer.models import (
    AlbumCompletenessIssue,
    Track,
    album_completeness_text,
)


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

    def test_complete_album_with_conflicting_totals_says_so(self) -> None:
        # Real case: 1/6 … 6/6 from a 6-track edition plus 7/7 for an added
        # bonus track. Nothing is missing, so «ожидается 7» would be wrong.
        tracks = [
            make_track(str(number), f"{number}/6")
            for number in range(1, 7)
        ] + [make_track("7", "7/7")]

        issues = analyze_track_completeness(tracks)

        self.assertEqual(len(issues), 1)
        issue = issues[0]
        self.assertEqual(issue.missing_numbers, ())
        self.assertEqual(issue.inconsistent_totals, (6, 7))
        self.assertEqual(issue.total_counts, ((6, 6), (7, 1)))
        self.assertEqual(
            issue.short_text,
            "⚠ комплект полный; итоги в тегах: 6, 7",
        )
        # The detailed card keeps the per-file breakdown.
        self.assertEqual(issue.total_breakdown_text, "6 (6 файлов), 7 (1 файл)")
        self.assertNotIn("ожидается", issue.short_text)
        self.assertTrue(
            all(track.collection_warning == issue.short_text for track in tracks)
        )

    def test_panel_shows_tag_total_instead_of_missing_expectation(self) -> None:
        tracks = [
            make_track(str(number), f"{number}/6") for number in range(1, 7)
        ] + [make_track("7", "7/7")]
        issue = analyze_track_completeness(tracks)[0]

        text = album_completeness_text(issue)

        self.assertIn("Найдены номера: 1, 2, 3, 4, 5, 6, 7", text)
        self.assertIn("Итог в тегах: 6 (6 файлов), 7 (1 файл)", text)
        self.assertNotIn("Ожидаемое количество", text)
        self.assertNotIn("Источник ожидаемого количества", text)

    def test_total_below_highest_number_is_reported_once(self) -> None:
        tracks = [
            make_track("one", "1/2"),
            make_track("two", "2/2"),
            make_track("three", "3/2"),
        ]

        issues = analyze_track_completeness(tracks)

        self.assertEqual(len(issues), 1)
        issue = issues[0]
        self.assertEqual(issue.missing_numbers, ())
        self.assertEqual(issue.inconsistent_totals, (2,))
        self.assertEqual(issue.total_counts, ((2, 3),))
        self.assertEqual(
            issue.short_text,
            "⚠ комплект полный; итог в теге меньше номера: 2 < 3",
        )

    def test_panel_keeps_expectation_when_tracks_are_missing(self) -> None:
        tracks = [make_track(str(number), f"{number}/10") for number in (1, 2, 4)]
        issue = analyze_track_completeness(tracks)[0]

        text = album_completeness_text(issue)

        self.assertIn("Ожидаемое количество: 10", text)
        self.assertIn("Источник ожидаемого количества: теги Track #", text)
        self.assertIn("пропущены № 3, 5, 6, 7, 8, 9, 10", text)
        self.assertIn("ожидается 10", text)

    def test_unnumbered_files_keep_the_expectation_and_list_names(self) -> None:
        issue = AlbumCompletenessIssue(
            id="one",
            relative_folder="Artist/Album",
            album="Album",
            disc=1,
            present_numbers=(1, 2),
            missing_numbers=(),
            expected_total=2,
            total_from_tags=True,
            unnumbered_files=("bonus.flac",),
            total_counts=((2, 2),),
        )

        self.assertEqual(issue.short_text, "⚠ без Track #: 1; ожидается 2")
        text = album_completeness_text(issue)
        self.assertIn("Ожидаемое количество: 2", text)
        self.assertIn("• bonus.flac", text)


if __name__ == "__main__":
    unittest.main()
