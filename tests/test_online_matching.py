from __future__ import annotations

import unittest
from pathlib import Path

from discography_analyzer.models import Track
from discography_analyzer.online.album import (
    AlbumGuess,
    LocalAlbum,
    disc_number_of_folder,
    folder_artist,
    guess_album,
    parse_folder_name,
)
from discography_analyzer.online.matching import (
    edition_of,
    editions_compatible,
    filename_position,
    fold,
    match_tracks,
    normalize_title,
    normalize_track_title,
    release_fits,
    score_release,
)
from discography_analyzer.online.release import Release, ReleaseTrack, parse_year


def track(filename: str, *, title: str = "", number: str = "", disc: str = "", seconds: float = 200.0, **tags) -> Track:
    path = Path("/music/Album") / filename
    item = Track(
        id=filename,
        path=path,
        root=Path("/music"),
        filename=filename,
        relative_path=f"Album/{filename}",
        relative_folder="Album",
        format=path.suffix[1:].upper(),
        size_bytes=1,
        title=title,
        track_number=number,
        disc_number=disc,
        duration_exact=seconds,
        **tags,
    )
    from discography_analyzer.parsing import title_from_filename

    item.filename_title = title_from_filename(filename)
    return item


def album(tracks: list[Track], *, artist="Metallica", title="Master of Puppets", year=1986, disc=None) -> LocalAlbum:
    return LocalAlbum(
        folder=Path("/music/Album"),
        relative_folder="Album",
        tracks=tracks,
        guess=AlbumGuess(artist, title, year, len(tracks), disc),
        folder_cover=None,
    )


def release(*tracks: ReleaseTrack, title="Master of Puppets", artist="Metallica", year=1986, count=None) -> Release:
    return Release(
        provider="apple",
        release_id="1",
        title=title,
        artist=artist,
        year=year,
        track_count=count if count is not None else len(tracks),
        tracks=tracks,
    )


class NormalizationTests(unittest.TestCase):
    def test_latin_letters_fold_and_other_scripts_stay(self) -> None:
        self.assertEqual(fold("Erik Wøllo"), fold("Erik Wollo"))
        self.assertEqual(fold("Beyoncé"), "beyonce")
        self.assertEqual(fold("Ария — Герой асфальта"), "ариягеройасфальта")
        self.assertNotEqual(fold("Мой"), fold("Мои"))
        self.assertEqual(fold("だ"), "だ")

    def test_album_title_key_drops_edition_words_and_punctuation(self) -> None:
        self.assertEqual(normalize_title("Master Of Puppets (Remastered)"), normalize_title("Master of Puppets"))
        self.assertEqual(normalize_title("Ride the Lightning [2016 Remaster]"), "ridethelightning")
        self.assertEqual(normalize_title("Live Acoustic EP"), normalize_title("Live Acoustic - EP"))
        self.assertEqual(normalize_title("My Head and My Heart"), normalize_title("My Head & My Heart"))
        self.assertNotEqual(normalize_title("S&M"), normalize_title("S&M2"))

    def test_track_title_key_ignores_guests(self) -> None:
        self.assertEqual(
            normalize_track_title("Spicy (feat. Charli XCX) [Majestic Remix]"),
            normalize_track_title("Spicy (with Diplo & Charli XCX) (Majestic Remix)"),
        )

    def test_editions_part_live_and_remaster_years_not_explicit(self) -> None:
        self.assertTrue(editions_compatible(edition_of("Album"), edition_of("Album (Explicit)")))
        self.assertFalse(editions_compatible(edition_of("Album"), edition_of("Album (Live)")))
        self.assertFalse(
            editions_compatible(edition_of("Album (Remastered 2009)"), edition_of("Album (2011 Remaster)"))
        )
        # «- Single»/«- EP» is a release type, not another edition: Apple names
        # the album «Christmas & Chill - EP» while the folder says
        # «Christmas & Chill». A single is rejected by its track list instead.
        self.assertTrue(editions_compatible(edition_of("Song - Single"), edition_of("Song")))

    def test_year_comes_from_any_date_shape(self) -> None:
        self.assertEqual(parse_year("1986-03-03T08:00:00Z"), 1986)
        self.assertEqual(parse_year(1999), 1999)
        self.assertIsNone(parse_year("0000"))
        self.assertIsNone(parse_year(None))


class FolderNameTests(unittest.TestCase):
    def test_common_folder_names(self) -> None:
        cases = {
            "Metallica - 1986 - Master of Puppets": ("Metallica", "Master of Puppets", 1986),
            "1986 - Master of Puppets": ("", "Master of Puppets", 1986),
            "Master of Puppets (1986)": ("", "Master of Puppets", 1986),
            "(1986) Master of Puppets": ("", "Master of Puppets", 1986),
            "Metallica - Master of Puppets [FLAC 24-96]": ("Metallica", "Master of Puppets", None),
            "Metallica - Master of Puppets (Remastered)": ("Metallica", "Master of Puppets (Remastered)", None),
            "Van Halen - 1984": ("Van Halen", "1984", None),
            "1984": ("", "1984", None),
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(parse_folder_name(name), expected)

    def test_disc_folders(self) -> None:
        self.assertEqual(disc_number_of_folder("CD2"), 2)
        self.assertEqual(disc_number_of_folder("Disc 1 - Bonus"), 1)
        self.assertEqual(disc_number_of_folder("Диск 3"), 3)
        self.assertIsNone(disc_number_of_folder("CDs"))
        self.assertIsNone(disc_number_of_folder("Discography"))

    def test_artist_folder_skips_grouping_folders_inside_the_collection(self) -> None:
        root = Path("/music")
        self.assertEqual(folder_artist(root / "Metallica" / "Albums" / "1986 - X", root), "Metallica")
        self.assertEqual(folder_artist(root / "Metallica" / "1986 - X", root), "Metallica")
        # «Music» is the collection itself; nothing above it is looked at.
        self.assertEqual(folder_artist(Path("/home/user/Music/Unknown"), Path("/home/user/Music")), "")
        # The album folder chosen as the collection: its parent is the artist.
        self.assertEqual(folder_artist(Path("/music/Metallica/X"), Path("/music/Metallica/X")), "Metallica")

    def test_tags_win_over_folder_names_and_disc_folders_use_the_album_folder(self) -> None:
        root = Path("/music")
        tagged = [track("01.flac", album="Master of Puppets", artist="Metallica", year="1986-03-03")]
        guess = guess_album(root / "Wrong Artist - Wrong Title", tagged, root)
        self.assertEqual((guess.artist, guess.title, guess.year), ("Metallica", "Master of Puppets", 1986))

        guess = guess_album(root / "Metallica" / "1991 - Metallica" / "CD2", [track("01.flac")], root)
        self.assertEqual((guess.artist, guess.title, guess.year, guess.disc), ("Metallica", "Metallica", 1991, 2))


class ScoreTests(unittest.TestCase):
    def test_the_same_album_scores_high_and_others_low(self) -> None:
        guess = AlbumGuess("Metallica", "Master of Puppets", 1986, 8, None)
        same = Release("apple", "1", "Master of Puppets", "Metallica", 1986, track_count=8)
        other_artist = Release("apple", "2", "Master of Puppets", "Tribute Band", 2003, track_count=8)
        live = Release("apple", "3", "Master of Puppets (Live)", "Metallica", 1986, track_count=8)

        self.assertEqual(score_release(guess, same), 100 + 35 + 40 + 50 + 20)
        self.assertLess(score_release(guess, other_artist), score_release(guess, same) - 100)
        self.assertLess(score_release(guess, live), score_release(guess, same) - 100)
        self.assertTrue(release_fits(guess, same))
        # A tribute with the same title still scores 95: only the rule stops it.
        self.assertFalse(release_fits(guess, other_artist))
        self.assertFalse(release_fits(guess, live))

    def test_an_unknown_album_never_fits_by_itself(self) -> None:
        unknown = AlbumGuess("", "", None, 3, None)
        anything = Release("apple", "1", "Master of Puppets", "Metallica", 1986, track_count=3)

        self.assertFalse(release_fits(unknown, anything))
        # A partly known album fits on what is known.
        self.assertTrue(release_fits(AlbumGuess("", "Master of Puppets", None, 3, None), anything))
        self.assertTrue(release_fits(AlbumGuess("The Metallica", "", None, 3, None), anything))

    def test_a_disc_folder_is_compared_with_its_disc(self) -> None:
        guess = AlbumGuess("Metallica", "Garage Inc.", None, 2, 2)
        two_discs = release(
            ReleaseTrack(1, 1, "a"), ReleaseTrack(1, 2, "b"), ReleaseTrack(1, 3, "c"),
            ReleaseTrack(2, 1, "d"), ReleaseTrack(2, 2, "e"),
            title="Garage Inc.",
            year=None,
        )
        self.assertEqual(score_release(guess, two_discs), 100 + 35 + 40 + 50)


class TrackMatchingTests(unittest.TestCase):
    TRACKS = (
        ReleaseTrack(1, 1, "Battery", duration=312.0),
        ReleaseTrack(1, 2, "Master of Puppets", duration=515.0),
        ReleaseTrack(1, 3, "The Thing That Should Not Be", duration=396.0),
    )

    def test_file_name_numbers_and_titles_pair_up(self) -> None:
        local = album(
            [
                track("01 - Battery.flac", seconds=312.4),
                track("02 - Master of Puppets.flac", seconds=515.0),
                track("03. The Thing That Should Not Be.flac", seconds=396.2),
            ]
        )

        matches = match_tracks(local, release(*self.TRACKS))

        self.assertEqual([match.source.number for match in matches], [1, 2, 3])
        self.assertTrue(all(match.score >= 120 for match in matches))

    def test_another_edition_with_other_titles_and_lengths_does_not_pair(self) -> None:
        local = album([track("01 - Intro.flac", seconds=60.0), track("02 - Outro.flac", seconds=90.0)])

        matches = match_tracks(local, release(*self.TRACKS))

        self.assertEqual([match.source for match in matches], [None, None])

    def test_titles_and_lengths_pair_files_without_numbers(self) -> None:
        local = album(
            [
                track("x.flac", title="Master of Puppets", seconds=516.0),
                track("y.flac", title="Battery", seconds=311.0),
            ]
        )

        matches = match_tracks(local, release(*self.TRACKS))

        self.assertEqual([match.source.title for match in matches], ["Master of Puppets", "Battery"])

    def test_placeholder_titles_rely_on_number_and_length(self) -> None:
        local = album([track("Track01.flac", seconds=312.0), track("Track02.flac", seconds=40.0)])

        matches = match_tracks(local, release(*self.TRACKS))

        self.assertEqual(matches[0].source.title, "Battery")
        # Position alone (50) with a length 475 s off (-30) is not enough.
        self.assertIsNone(matches[1].source)

    def test_a_disc_folder_pairs_with_the_tracks_of_its_disc(self) -> None:
        two_discs = release(
            ReleaseTrack(1, 1, "Free Speech for the Dumb", duration=155.0),
            ReleaseTrack(2, 1, "Helpless", duration=398.0),
        )
        local = album([track("01.flac", seconds=398.0)], disc=2)

        matches = match_tracks(local, two_discs)

        self.assertEqual(matches[0].source.title, "Helpless")

    def test_file_name_positions(self) -> None:
        cases = {
            "02. Battery.flac": (None, 2),
            "1-02 Battery.flac": (1, 2),
            "CD2 - 03 - Battery.flac": (2, 3),
            "04.flac": (None, 4),
            "Track 07.wav": (None, 7),
            "Battery.flac": (None, None),
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(filename_position(name), expected)


if __name__ == "__main__":
    unittest.main()


class LiveShapeTests(unittest.TestCase):
    """Shapes met in real answers: «- EP» suffixes and «Artist - Title» names."""

    def test_an_apple_ep_suffix_is_not_another_edition(self) -> None:
        guess = AlbumGuess("Ariana Grande", "Christmas & Chill", 2015, 7, None)
        ep = release(
            *[ReleaseTrack(1, index, f"Song {index}") for index in range(1, 8)],
            title="Christmas & Chill - EP",
            artist="Ariana Grande",
            year=2015,
        )

        self.assertTrue(release_fits(guess, ep))
        self.assertEqual(edition_of(ep.title).flags, frozenset())

    def test_a_file_named_artist_dash_title_matches_its_track(self) -> None:
        # «02 - ROSÉ - 3am.m4a»: rippers often leave the artist in the name.
        local = album(
            [
                track("02 - ROSÉ - 3am.m4a", seconds=200.0),
                track("03 - ROSÉ - two years.m4a", seconds=190.0),
            ],
            artist="ROSÉ",
            title="rosie",
            year=2024,
        )
        source = release(
            ReleaseTrack(1, 1, "3am", duration=200.0),
            ReleaseTrack(1, 2, "two years", duration=190.0),
            title="rosie",
            artist="ROSÉ",
            year=2024,
        )

        matches = match_tracks(local, source)

        self.assertEqual([match.source.title if match.source else None for match in matches],
                         ["3am", "two years"])

    def test_a_dash_in_a_title_is_not_read_as_an_artist(self) -> None:
        # Same position, but the duration is a minute off: only the title could
        # rescue the pair, and «Love - Hate» must not become «Hate» here.
        local = album(
            [track("03 - Love - Hate.flac", seconds=200.0)],
            artist="Someone",
            title="Album",
            year=2000,
        )
        source = release(
            ReleaseTrack(1, 3, "Hate", duration=260.0),
            title="Album",
            artist="Someone",
            year=2000,
        )

        matches = match_tracks(local, source)

        self.assertIsNone(matches[0].source)


class DiscFolderTests(unittest.TestCase):
    """A «CD2» folder against a one-disc release that holds all discs."""

    def test_a_disc_folder_is_not_matched_by_number_to_disc_one(self) -> None:
        local = album(
            [
                track("01 - Lonely Star.flac", seconds=334.0),
                track("02 - Life Of The Party.flac", seconds=280.0),
            ],
            artist="The Weeknd",
            title="Trilogy",
            year=2012,
            disc=2,
        )
        # No durations on the release tracks: with them the wrong pair
        # (50 − 10 − 30) stays under the threshold even before the fix, and
        # the test would pass without it. Without them the position (50 − 10)
        # ties with the title (40), and the tie went to track 1.
        source = release(
            ReleaseTrack(1, 1, "High For This"),
            ReleaseTrack(1, 2, "What You Need"),
            ReleaseTrack(1, 3, "Lonely Star"),
            ReleaseTrack(1, 4, "Life Of The Party"),
            title="Trilogy",
            artist="The Weeknd",
            year=2012,
        )

        matches = match_tracks(local, source)

        self.assertEqual(
            [match.source.title if match.source else None for match in matches],
            ["Lonely Star", "Life Of The Party"],
        )

    def test_a_disc_folder_prefers_a_real_multi_disc_release_in_the_score(self) -> None:
        guess = AlbumGuess("The Weeknd", "Trilogy", 2012, 5, 2)
        digital = Release(
            provider="discogs",
            release_id="1",
            title="Trilogy",
            artist="The Weeknd",
            year=2012,
            track_count=30,
            tracks=tuple(ReleaseTrack(1, number, f"Track {number}") for number in range(1, 31)),
        )
        physical = Release(
            provider="discogs",
            release_id="2",
            title="Trilogy",
            artist="The Weeknd",
            year=2012,
            track_count=30,
            tracks=tuple(
                ReleaseTrack(disc, number, f"Track {disc}-{number}")
                for disc in (1, 2, 3)
                for number in range(1, 11)
            ),
        )

        self.assertLess(score_release(guess, digital), score_release(guess, physical))
