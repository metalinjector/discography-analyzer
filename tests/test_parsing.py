import unittest

from discography_analyzer.parsing import (
    artist_set,
    detect_variation,
    title_from_filename,
    validate_markers,
)


class ParsingTests(unittest.TestCase):
    def test_track_number_is_removed_from_filename(self) -> None:
        self.assertEqual(title_from_filename("01 Smile (Live).flac"), "Smile (Live)")
        self.assertEqual(title_from_filename("01 - Smile.mp3"), "Smile")

    def test_artists_are_split_without_damaging_artist_x_name(self) -> None:
        self.assertEqual(
            artist_set("Artist A feat. Guest"), {"artist a", "guest"}
        )
        self.assertEqual(
            artist_set("Artist A & Artist B"), {"artist a", "artist b"}
        )
        self.assertEqual(artist_set("Artist X"), {"artist x"})

    def test_variation_syntaxes(self) -> None:
        markers = ["Remix", "Live", "Acoustic", "Version", "Radio", "Edit"]
        self.assertEqual(detect_variation("Song (Remix)", markers), ("Song", "Remix"))
        self.assertEqual(detect_variation("Song [Live]", markers), ("Song", "Live"))
        self.assertEqual(
            detect_variation("Song - Acoustic Version", markers),
            ("Song", "Acoustic Version"),
        )
        self.assertEqual(
            detect_variation("Song Acoustic", markers), ("Song", "Acoustic")
        )
        self.assertEqual(
            detect_variation("Long Song Title Remix", markers),
            ("Long Song Title", "Remix"),
        )
        self.assertEqual(
            detect_variation("Song Radio Edit", markers),
            ("Song", "Radio Edit"),
        )

    def test_invalid_custom_marker_reports_line(self) -> None:
        with self.assertRaisesRegex(ValueError, "строке 2"):
            validate_markers(["Live", "bad[regex]"])


if __name__ == "__main__":
    unittest.main()
