from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from discography_analyzer import playlist
from discography_analyzer.models import AnalysisResult, Track
from discography_analyzer.playlist import build_m3u8, write_playlist
from discography_analyzer.ui import DiscographyAnalyzerApp


def make_track(
    identifier: str,
    folder: str,
    *,
    title: str = "Song",
    artist: str = "Artist",
    duration: float | None = 180.0,
    disc: str = "1",
    number: str = "1",
    root: Path = Path("E:/Music"),
) -> Track:
    name = f"{number} {title}.flac"
    return Track(
        id=identifier,
        path=root / folder / name,
        root=root,
        filename=name,
        relative_path=f"{folder}/{name}",
        relative_folder=folder,
        format="FLAC",
        size_bytes=1000,
        filename_title=title,
        title=title,
        artist=artist,
        album="Album",
        album_artist=artist,
        track_number=f"{number}/10",
        disc_number=f"{disc}/1",
        duration_exact=duration,
        duration_seconds=round(duration) if duration else None,
    )


class PlaylistTextTests(unittest.TestCase):
    def test_header_and_extinf_lines(self) -> None:
        folder = Path("E:/Music/Artist/Album")
        tracks = [
            make_track("1", "Artist/Album", title="Первый", duration=185.4),
            make_track("2", "Artist/Album", title="Second", duration=None),
        ]

        text = build_m3u8(tracks, folder)
        lines = text.splitlines()

        self.assertEqual(lines[0], "#EXTM3U")
        self.assertEqual(lines[1], "#EXTINF:185,Artist - Первый")
        self.assertEqual(
            lines[2], os.path.relpath(tracks[0].path, folder)
        )
        self.assertEqual(lines[3], "#EXTINF:-1,Artist - Second")

    def test_missing_title_falls_back_to_the_filename(self) -> None:
        track = make_track("1", "Artist/Album", title="", artist="")
        track.filename_title = "Fallback"

        text = build_m3u8([track], Path("E:/Music/Artist/Album"))

        self.assertIn("#EXTINF:180,Fallback", text)

    def test_unknown_duration_is_minus_one(self) -> None:
        track = make_track("1", "Artist/Album", duration=None)

        self.assertIn("#EXTINF:-1,", build_m3u8([track], Path("E:/Music")))

    def test_a_file_on_another_drive_gets_an_absolute_path(self) -> None:
        track = make_track("1", "Artist/Album")

        with patch.object(playlist.os.path, "relpath", side_effect=ValueError):
            text = build_m3u8([track], Path("D:/Playlists"))

        self.assertIn(str(track.path), text)


class PlaylistWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.folder = Path(self._temp.name)
        self.addCleanup(self._temp.cleanup)

    def test_write_keeps_cyrillic_and_newlines(self) -> None:
        tracks = [
            make_track("1", "Artist/Album", title="Ёлка", artist="Исполнитель"),
            make_track("2", "Artist/Album", title="Второй", number="2"),
        ]
        destination = self.folder / "список.m3u8"

        write_playlist(tracks, destination)

        raw = destination.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        text = raw.decode("utf-8")
        self.assertIn("#EXTM3U\n", text)
        self.assertIn("Исполнитель - Ёлка", text)
        self.assertEqual(
            text, build_m3u8(tracks, self.folder)
        )

    def test_a_failed_replace_keeps_the_old_playlist(self) -> None:
        destination = self.folder / "list.m3u8"
        destination.write_text("старый список", encoding="utf-8")
        tracks = [make_track("1", "Artist/Album")]

        with (
            patch.object(playlist.os, "replace", side_effect=OSError("нет места")),
            self.assertRaises(OSError),
        ):
            write_playlist(tracks, destination)

        self.assertEqual(destination.read_text(encoding="utf-8"), "старый список")
        self.assertEqual(list(self.folder.glob(".playlist-*.part")), [])

    @unittest.skipIf(os.name == "nt", "POSIX permission bits")
    def test_the_playlist_gets_ordinary_permissions(self) -> None:
        # mkstemp creates 0600 files; a playlist is an ordinary user file.
        destination = self.folder / "list.m3u8"
        previous = os.umask(0o022)
        try:
            write_playlist([make_track("1", "Artist/Album")], destination)
        finally:
            os.umask(previous)

        self.assertEqual(destination.stat().st_mode & 0o777, 0o644)


class PlaylistSelectionTests(unittest.TestCase):
    def app_with(self, tracks: list[Track], focus: str, visible: list[Track]):
        app = DiscographyAnalyzerApp.__new__(DiscographyAnalyzerApp)
        app.result = AnalysisResult(
            tracks=tracks,
            folders_scanned=1,
            root=Path("E:/Music"),
        )
        app.visible_tracks = visible
        app.tree = type("FakeTree", (), {"focus": lambda _self: focus})()
        return app

    def test_a_folder_row_selects_its_whole_subtree_in_track_order(self) -> None:
        tracks = [
            make_track("3", "Artist/Album", title="Third", number="3"),
            make_track("1", "Artist/Album", title="First", number="1"),
            make_track("2", "Artist/Album/Disc2", title="Second", number="2", disc="2"),
            make_track("9", "Other/Album", title="Outside", number="1"),
        ]
        app = self.app_with(tracks, "folder-path::Artist/Album", visible=[tracks[3]])

        selected = app._playlist_tracks()

        self.assertEqual([track.id for track in selected], ["1", "3", "2"])

    def test_a_folder_with_several_albums_keeps_each_album_together(self) -> None:
        # The subtree was sorted by disc and number only, so an artist folder
        # with two albums played A1, B1, A2, B2: the albums interleaved.
        tracks = [
            make_track("A1", "Artist/(1986) A", number="1"),
            make_track("B1", "Artist/(1991) B", number="1"),
            make_track("A2", "Artist/(1986) A", number="2"),
            make_track("B2", "Artist/(1991) B", number="2"),
        ]
        app = self.app_with(tracks, "folder-path::Artist", visible=[])

        self.assertEqual(
            [track.id for track in app._playlist_tracks()],
            ["A1", "A2", "B1", "B2"],
        )

    def test_a_track_row_uses_the_visible_rows_in_screen_order(self) -> None:
        tracks = [
            make_track("1", "A", number="2"),
            make_track("2", "B", number="1"),
        ]
        app = self.app_with(tracks, "track-2", visible=[tracks[1], tracks[0]])

        self.assertEqual(
            [track.id for track in app._playlist_tracks()], ["2", "1"]
        )

    def test_the_root_row_selects_every_track(self) -> None:
        tracks = [
            make_track("1", "A", number="1"),
            make_track("2", "B/C", number="1"),
        ]
        app = self.app_with(tracks, "folder-root::node", visible=[])

        self.assertEqual(len(app._playlist_tracks()), 2)


if __name__ == "__main__":
    unittest.main()
