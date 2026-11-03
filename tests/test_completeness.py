import unittest
from pathlib import Path

from discography_analyzer.completeness import (
    CONTINUOUS,
    PER_DISC,
    RELEASE_TOTAL,
    analyze_track_completeness,
    parse_position,
    release_folder,
    release_numbering,
)
from discography_analyzer.models import (
    AlbumCompletenessIssue,
    Track,
    album_completeness_text,
)
from discography_analyzer.parsing import disc_number_of_folder


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


ROOT = Path("/music")


def make(folder: str, number: int, **values) -> Track:
    path = ROOT / folder / f"{number}.flac"
    return Track(
        id=f"{folder}/{number}/{values.get('disc_number', '')}",
        path=path,
        root=ROOT,
        filename=path.name,
        relative_path=f"{folder}/{path.name}",
        relative_folder=folder,
        format="FLAC",
        size_bytes=100,
        **values,
    )


def disc_tracks(folder, album, disc, numbers, total) -> list[Track]:
    return [
        make(
            folder,
            number,
            album=album,
            disc_number=disc,
            track_number=f"{number}/{total}" if total else str(number),
        )
        for number in numbers
    ]


def qobuz_box() -> list[Track]:
    """12 + 12 + 9 tracks, every disc from 1, TRACKTOTAL 33 in every file."""
    return [
        *disc_tracks("Box/CD1", "Vol. 13", "1/3", range(1, 13), 33),
        *disc_tracks("Box/CD2", "Vol. 13", "2/3", range(1, 13), 33),
        *disc_tracks("Box/CD3", "Vol. 13", "3/3", range(1, 10), 33),
    ]


class MultiDiscNumberingTests(unittest.TestCase):
    def test_a_qobuz_box_total_counts_the_whole_release(self) -> None:
        # The old check read TRACKTOTAL 33 as the size of every disc and
        # reported «пропущены № 13 … 33» on each disc of a complete box.
        tracks = qobuz_box()

        self.assertEqual(analyze_track_completeness(tracks), [])
        numbering = release_numbering(tracks)
        self.assertEqual(numbering.mode, RELEASE_TOTAL)
        self.assertEqual((numbering.expected, numbering.missing_count), (33, 0))
        self.assertEqual(tracks[0].collection_warning, "")

    def test_a_short_qobuz_box_reports_the_gaps_of_each_disc(self) -> None:
        # «Das Wagner Desaster»: tracks 3, 4 of disc 1 and 3 of disc 2, of 7.
        tracks = [
            *disc_tracks("Wagner", "Wagner", "1/2", (3, 4), 7),
            *disc_tracks("Wagner", "Wagner", "2/2", (3,), 7),
        ]

        issues = analyze_track_completeness(tracks)

        self.assertEqual(
            [(issue.disc, issue.missing_numbers) for issue in issues],
            [(1, (1, 2)), (2, (1, 2))],
        )
        self.assertFalse(any(issue.total_from_tags for issue in issues))
        numbering = release_numbering(tracks)
        self.assertEqual(numbering.missing_count, 4)
        self.assertEqual(numbering.unplaced, 0)

    def test_an_absent_disc_and_unplaced_tracks_stay_on_the_release(self) -> None:
        # «The Dark Side of the Moog, Vol. 3»: 6 + 6 + 4 of 18, disc 4 gone.
        tracks = [
            *disc_tracks("Moog/CD1", "Moog", "1/4", range(1, 7), 18),
            *disc_tracks("Moog/CD2", "Moog", "2/4", range(1, 7), 18),
            *disc_tracks("Moog/CD3", "Moog", "3/4", range(1, 5), 18),
        ]

        self.assertEqual(analyze_track_completeness(tracks), [])
        numbering = release_numbering(tracks)
        self.assertEqual(numbering.absent_discs, (4,))
        self.assertEqual(numbering.unplaced, 2)

    def test_continuous_numbering_is_one_sequence_over_the_discs(self) -> None:
        # The normalizer made Track # continuous: disc 2 goes on from disc 1.
        tracks = [
            *disc_tracks("Seq/CD1", "Seq", "1", (3, 4), 7),
            *disc_tracks("Seq/CD2", "Seq", "2", (7,), 7),
        ]

        issues = analyze_track_completeness(tracks)

        # Disc 2 is not «missing 1 … 6»; the gap between the discs is the
        # release's, not a disc's.
        self.assertEqual(
            [(issue.relative_folder, issue.missing_numbers) for issue in issues],
            [("Seq/CD1", (1, 2))],
        )
        numbering = release_numbering(tracks)
        self.assertEqual(numbering.mode, CONTINUOUS)
        self.assertEqual(numbering.missing, ((0, (1, 2, 5, 6)),))

    def test_per_disc_totals_are_checked_per_disc_as_before(self) -> None:
        tracks = [
            *disc_tracks("Set", "Set", "1/2", range(1, 11), 10),
            *disc_tracks("Set", "Set", "2/2", range(1, 8), 10),
        ]

        issues = analyze_track_completeness(tracks)

        self.assertEqual(
            [(issue.disc, issue.missing_numbers) for issue in issues],
            [(2, (8, 9, 10))],
        )
        self.assertTrue(issues[0].total_from_tags)
        self.assertEqual(release_numbering(tracks).mode, PER_DISC)

    def test_an_equal_total_not_above_the_numbers_is_a_disc_total(self) -> None:
        tracks = [
            *disc_tracks("Eq", "Eq", "1/2", range(1, 13), 12),
            *disc_tracks("Eq", "Eq", "2/2", range(1, 10), 12),
        ]

        issues = analyze_track_completeness(tracks)

        self.assertEqual([issue.missing_numbers for issue in issues], [(10, 11, 12)])

    def test_disc_folders_without_disc_tags_still_make_discs(self) -> None:
        tracks = [
            *disc_tracks("Live/CD1", "Live", "", range(1, 4), None),
            *disc_tracks("Live/CD2", "Live", "", range(1, 3), None),
        ]

        numbering = release_numbering(tracks)

        self.assertEqual(numbering.discs, (1, 2))
        self.assertEqual(numbering.missing_count, 0)

    def test_disc_folder_names(self) -> None:
        self.assertEqual(disc_number_of_folder("CD2"), 2)
        self.assertEqual(disc_number_of_folder("Диск 3"), 3)
        self.assertIsNone(disc_number_of_folder("Discography"))
        self.assertEqual(release_folder(make("A/Album/CD1", 1)), str(Path("A/Album")))
        self.assertEqual(release_folder(make("CD1", 1)), str(ROOT))
        self.assertEqual(release_folder(make(str(ROOT), 1)), str(ROOT))


if __name__ == "__main__":
    unittest.main()
