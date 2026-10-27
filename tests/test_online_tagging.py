from __future__ import annotations

import io
import json
import os
import struct
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from discography_analyzer.online import tagging
from discography_analyzer.online.album import read_album, read_track
from discography_analyzer.online.apple import AppleProvider
from discography_analyzer.online.http import HttpClient, Response
from discography_analyzer.online.lookup import LookupCache, look_up
from discography_analyzer.online.matching import match_tracks
from discography_analyzer.online.preferences import (
    OnlinePreferences,
    load_preferences,
    save_preferences,
)
from discography_analyzer.online.release import LookupOptions, Release, ReleaseTrack
from discography_analyzer.online.tagging import (
    FillOptions,
    apply_plans,
    missing_fields,
    plan_album,
    write_disc,
)

EXTENSIONS = {".flac", ".mp3", ".ape"}
# MPEG-1 Layer III, 128 kbps, 44.1 kHz: 417-byte frames.
MP3_FRAMES = (b"\xff\xfb\x90\x00" + b"\x00" * 413) * 40
COVER_URL = "https://covers.example/1200x1200bb.jpg"


def flac_header() -> bytes:
    """Minimal FLAC: "fLaC" + STREAMINFO (44.1 kHz, stereo, 16 bit, 1 s)."""
    streaminfo = struct.pack(">HH", 4096, 4096) + b"\x00" * 6
    bits = (44100 << 44) | (1 << 41) | (15 << 36) | 44100
    streaminfo += bits.to_bytes(8, "big") + b"\x00" * 16
    return b"fLaC" + bytes([0x80]) + len(streaminfo).to_bytes(3, "big") + streaminfo


def ape_header() -> bytes:
    header = bytearray(76)
    header[0:4] = b"MAC "
    struct.pack_into("<H", header, 4, 3990)
    struct.pack_into("<IIIHHI", header, 56, 73728 * 4, 73728, 1, 16, 2, 44100)
    return bytes(header) + b"\x00" * 256


def make_flac(path: Path, **tags: str) -> Path:
    from mutagen.flac import FLAC

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(flac_header())
    if tags:
        audio = FLAC(path)
        for key, value in tags.items():
            audio[key] = [value]
        audio.save()
    return path


def make_mp3(path: Path, title: str) -> Path:
    from mutagen.id3 import ID3, TIT2

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(MP3_FRAMES)
    tags = ID3()
    tags.add(TIT2(encoding=3, text=title))
    tags.save(path, v2_version=3)
    return path


def jpeg(size: int = 64) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), "#884422").save(buffer, format="JPEG")
    return buffer.getvalue()


def release(*titles: str, discs: int = 1, duration: float = 1.0, cover_url: str = COVER_URL) -> Release:
    # The test files are 1 s long, so by default every length agrees.
    tracks = tuple(
        ReleaseTrack(disc, number, title, "Metallica", duration)
        for disc in range(1, discs + 1)
        for number, title in enumerate(titles, start=1)
    )
    return Release(
        provider="apple",
        release_id="1",
        title="Master of Puppets",
        artist="Metallica",
        year=1986,
        genre="Metal",
        track_count=len(tracks),
        cover_url=cover_url,
        tracks=tracks,
    )


def client(cover: bytes | None = None) -> HttpClient:
    def transport(url, headers, timeout):
        if url == COVER_URL and cover is not None:
            return Response(200, cover)
        return Response(404, b"")

    return HttpClient(transport=transport, sleep=lambda _seconds: None)


class PlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.folder = self.root / "Metallica" / "1986 - Master of Puppets"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def plan(self, remote: Release, options: FillOptions | None = None):
        album = read_album(self.folder, self.root, EXTENSIONS)
        return plan_album(album, remote, match_tracks(album, remote), options or FillOptions())

    def test_only_empty_fields_are_planned(self) -> None:
        make_flac(self.folder / "01 - Battery.flac", title="Battery (my title)", genre="Thrash")
        make_flac(self.folder / "02 - Master of Puppets.flac", tracknumber="2")

        plan = self.plan(release("Battery", "Master of Puppets"))

        first, second = plan.changes
        self.assertEqual(
            dict(first.text),
            {"artist": "Metallica", "album": "Master of Puppets", "album_artist": "Metallica", "year": "1986"},
        )
        self.assertEqual(first.track_position, (1, 2))
        self.assertEqual(dict(second.text)["title"], "Master of Puppets")
        self.assertEqual(dict(second.text)["genre"], "Metal")
        # The number was there, only the total is added.
        self.assertEqual(second.track_position, (2, 2))
        self.assertIsNone(first.disc_position)
        self.assertTrue(plan.save_cover_file)

    def test_unchecked_fields_and_a_present_cover_are_left_alone(self) -> None:
        make_flac(self.folder / "01.flac")
        (self.folder / "cover.jpg").write_bytes(jpeg())

        plan = self.plan(
            release("Battery"),
            FillOptions(fields=frozenset({"title"}), embed_cover=True, save_cover_file=True),
        )

        self.assertEqual(dict(plan.changes[0].text), {"title": "Battery"})
        self.assertFalse(plan.changes[0].embed_cover)
        self.assertFalse(plan.save_cover_file)
        self.assertEqual(plan.fields, ["название"])

    def test_disc_numbers_are_planned_for_sets_only(self) -> None:
        make_flac(self.folder / "1-01 Battery.flac")

        plan = self.plan(release("Battery", discs=2))

        self.assertEqual(plan.changes[0].disc_position, (1, 2))

    def test_a_release_without_matched_tracks_plans_nothing(self) -> None:
        make_flac(self.folder / "01 - Intro.flac", title="Intro")

        plan = self.plan(release("Something Else Entirely", duration=300.0))

        self.assertTrue(plan.empty)
        self.assertEqual([track.filename for track in plan.unmatched], ["01 - Intro.flac"])

    def test_missing_fields_ignore_totals_and_disc_numbers(self) -> None:
        make_flac(
            self.folder / "01.flac",
            title="Battery",
            artist="Metallica",
            album="Master of Puppets",
            date="1986",
            genre="Metal",
            tracknumber="1",
        )
        (self.folder / "cover.jpg").write_bytes(jpeg())
        album = read_album(self.folder, self.root, EXTENSIONS)

        self.assertEqual(missing_fields(album, FillOptions()), ["исполнитель альбома"])
        options = FillOptions(fields=frozenset({"title", "track", "disc"}))
        self.assertEqual(missing_fields(album, options), [])


class WriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name) / "Music"
        self.folder = self.root / "Metallica" / "1986 - Master of Puppets"
        self.backup = Path(self.directory.name) / "Backup"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def plans(self, remote: Release, options: FillOptions | None = None):
        album = read_album(self.folder, self.root, EXTENSIONS)
        return [plan_album(album, remote, match_tracks(album, remote), options or FillOptions())]

    def test_tags_numbers_and_cover_are_written_verified_and_backed_up(self) -> None:
        flac = make_flac(self.folder / "1-01 - Battery.flac")
        mp3 = make_mp3(self.folder / "1-02 Master of Puppets.mp3", "Master of Puppets")
        os.utime(flac, ns=(1_600_000_000_000_000_000,) * 2)
        cover = jpeg(1200)

        result = apply_plans(
            self.plans(release("Battery", "Master of Puppets", discs=2)),
            client=client(cover),
            root=self.root,
            backup_root=self.backup,
        )

        self.assertEqual((result.updated_files, result.backup_files, result.covers_saved), (2, 2, 1))
        self.assertEqual(result.failures, ())
        written = read_track(flac, self.root)
        self.assertEqual(
            (written.title, written.artist, written.album, written.year, written.genre),
            ("Battery", "Metallica", "Master of Puppets", "1986", "Metal"),
        )
        self.assertEqual((written.track_number, written.disc_number), ("1/2", "1/2"))
        self.assertGreater(written.cover_size, 0)
        self.assertEqual(flac.stat().st_mtime_ns, 1_600_000_000_000_000_000)
        self.assertEqual((self.folder / "cover.jpg").read_bytes(), cover)

        from mutagen.id3 import ID3

        tags = ID3(mp3)
        self.assertEqual(tags.version[:2], (2, 3))
        self.assertEqual(str(tags["TIT2"]), "Master of Puppets")
        self.assertEqual(str(tags["TRCK"]), "2/2")
        self.assertEqual(str(tags["TPOS"]), "1/2")
        backups = sorted(path.name for path in self.backup.rglob("*") if path.is_file())
        self.assertEqual(backups, ["1-01 - Battery.flac", "1-02 Master of Puppets.mp3"])
        self.assertEqual(list(self.folder.glob(".*")), [])

    def test_a_failed_cover_download_still_writes_the_tags(self) -> None:
        flac = make_flac(self.folder / "01 - Battery.flac")

        result = apply_plans(self.plans(release("Battery")), client=client(None), root=self.root)

        self.assertEqual(result.updated_files, 1)
        self.assertEqual(result.covers_saved, 0)
        self.assertIn("обложка не загружена", result.failures[0].reason)
        written = read_track(flac, self.root)
        self.assertEqual(written.title, "Battery")
        self.assertEqual(written.cover_size, 0)
        self.assertFalse((self.folder / "cover.jpg").exists())

    def test_a_cover_only_change_is_skipped_when_the_download_fails(self) -> None:
        make_flac(self.folder / "01 - Battery.flac", title="Battery")

        result = apply_plans(
            self.plans(release("Battery"), FillOptions(fields=frozenset(), embed_cover=True)),
            client=client(None),
            root=self.root,
        )

        self.assertEqual(result.updated_files, 0)
        self.assertEqual(len(result.failures), 1)

    def test_a_failed_verification_leaves_the_original_and_no_backup(self) -> None:
        flac = make_flac(self.folder / "01 - Battery.flac")
        original = flac.read_bytes()

        def wrong_total(path: Path, number: int, total: int) -> None:
            tagging_write_total(path, number, total + 1)

        tagging_write_total = tagging.write_total
        with patch.object(tagging, "write_total", wrong_total):
            result = apply_plans(
                self.plans(release("Battery"), FillOptions(save_cover_file=False, embed_cover=False)),
                client=client(None),
                root=self.root,
                backup_root=self.backup,
            )

        self.assertEqual(result.updated_files, 0)
        self.assertIn("номера трека", result.failures[0].reason)
        self.assertEqual(flac.read_bytes(), original)
        self.assertFalse(self.backup.exists())
        self.assertEqual(list(self.folder.glob(".*")), [])

    def test_stop_before_the_first_album_writes_nothing(self) -> None:
        flac = make_flac(self.folder / "01 - Battery.flac")
        original = flac.read_bytes()
        stop = threading.Event()
        stop.set()

        result = apply_plans(
            self.plans(release("Battery")), client=client(jpeg()), root=self.root, stop_event=stop
        )

        self.assertTrue(result.stopped)
        self.assertEqual(flac.read_bytes(), original)

    def test_ape_disc_number_uses_the_native_key(self) -> None:
        import mutagen

        path = self.folder / "01.ape"
        path.parent.mkdir(parents=True)
        path.write_bytes(ape_header())

        write_disc(path, 2, 3)

        tags = mutagen.File(path).tags
        self.assertEqual(str(tags["Disc"]), "2/3")


class LookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        folder = self.root / "Metallica" / "1986 - Master of Puppets"
        make_flac(folder / "01 - Battery.flac")
        make_flac(folder / "02 - Master of Puppets.flac")
        self.album = read_album(folder, self.root, EXTENSIONS)
        self.calls: list[str] = []

    def tearDown(self) -> None:
        self.directory.cleanup()

    def provider(self, albums: list[dict], songs: dict[str, list[dict]]) -> AppleProvider:
        def transport(url, headers, timeout):
            self.calls.append(url)
            if url.startswith("https://itunes.apple.com/search"):
                return Response(200, json.dumps({"results": albums}).encode())
            collection = url.split("id=")[1].split("&")[0]
            return Response(200, json.dumps({"results": songs[collection]}).encode())

        client = HttpClient(transport=transport, sleep=lambda _seconds: None)
        return AppleProvider(client, LookupOptions())

    @staticmethod
    def collection(collection_id: int, title: str, artist: str = "Metallica") -> dict:
        return {
            "wrapperType": "collection",
            "collectionId": collection_id,
            "collectionName": title,
            "artistName": artist,
            "trackCount": 2,
            "releaseDate": "1986-03-03T08:00:00Z",
        }

    @staticmethod
    def song(collection_id: int, number: int, title: str) -> dict:
        return {
            "wrapperType": "track",
            "kind": "song",
            "collectionId": collection_id,
            "trackNumber": number,
            "discNumber": 1,
            "trackName": title,
            "trackTimeMillis": 1000,
        }

    def test_the_fitting_release_is_chosen_with_two_requests_and_cached(self) -> None:
        albums = [self.collection(2, "Ride the Lightning"), self.collection(1, "Master of Puppets")]
        songs = {"1": [self.song(1, 1, "Battery"), self.song(1, 2, "Master of Puppets")]}
        provider = self.provider(albums, songs)
        cache = LookupCache()

        lookup = look_up(provider, self.album, cache=cache)
        again = look_up(provider, self.album, cache=cache)

        self.assertEqual(lookup.choice.release.title, "Master of Puppets")
        self.assertEqual(lookup.choice.matched, 2)
        self.assertEqual(len(self.calls), 2)  # one search, one track list
        self.assertEqual(again.choice.release.release_id, "1")

    def test_a_tribute_with_the_same_songs_is_offered_not_chosen(self) -> None:
        albums = [self.collection(3, "Master of Puppets", artist="Tribute Band")]
        songs = {"3": [self.song(3, 1, "Battery"), self.song(3, 2, "Master of Puppets")]}

        lookup = look_up(self.provider(albums, songs), self.album)

        self.assertIsNone(lookup.chosen)
        self.assertEqual(lookup.candidates[0].matched, 2)

    def test_an_album_without_any_name_is_not_searched(self) -> None:
        from discography_analyzer.online.release import AlbumQuery

        lookup = look_up(self.provider([], {}), self.album, AlbumQuery("", " "))

        self.assertIn("нет названия", lookup.error)
        self.assertEqual(self.calls, [])


class PreferencesTests(unittest.TestCase):
    def test_round_trip_and_defaults_for_broken_values(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "online_tags.json"
            self.assertEqual(load_preferences(path), OnlinePreferences())

            save_preferences(
                OnlinePreferences(
                    provider="deezer", fields=["title"], selection_mode="manual"
                ),
                path,
            )
            self.assertEqual(load_preferences(path).provider, "deezer")
            self.assertEqual(load_preferences(path).fields, ["title"])
            self.assertEqual(load_preferences(path).selection_mode, "manual")
            self.assertFalse(load_preferences(path).auto_select)

            path.write_text(json.dumps({"provider": 5, "fields": "title", "embed_cover": False}))
            loaded = load_preferences(path)
            self.assertEqual(loaded.provider, "apple")
            self.assertEqual(loaded.fields, OnlinePreferences().fields)
            self.assertFalse(loaded.embed_cover)
            self.assertNotIn("album_artist", loaded.fields)


if __name__ == "__main__":
    unittest.main()


class LiveShapeTaggingTests(unittest.TestCase):
    """Answers seen only in the live services: «- EP» titles, ID3v2.3 files."""

    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.folder = self.root / "Ariana Grande" / "2015 - Christmas & Chill"
        self.addCleanup(self.directory.cleanup)

    def test_the_album_tag_keeps_the_folder_name_without_an_ep_suffix(self) -> None:
        from discography_analyzer.online.album import read_album

        make_flac(self.folder / "01 - Intro.flac")
        album = read_album(self.folder, self.root, EXTENSIONS)
        remote = Release(
            provider="apple",
            release_id="1719737002",
            title="Christmas & Chill - EP",
            artist="Ariana Grande",
            year=2015,
            genre="Holiday",
            track_count=1,
            tracks=(ReleaseTrack(1, 1, "Intro", "Ariana Grande", 1.0),),
        )

        plan = plan_album(album, remote, match_tracks(album, remote), FillOptions())

        values = dict(plan.changes[0].text)
        self.assertEqual(values["album"], "Christmas & Chill")

    def test_an_id3v23_file_stays_v23_after_the_write(self) -> None:
        from mutagen.id3 import ID3

        path = make_mp3(self.folder / "01 - Battery.mp3", "Battery")
        album = read_album(self.folder, self.root, EXTENSIONS)
        remote = Release(
            provider="apple",
            release_id="1",
            title="Master of Puppets",
            artist="Metallica",
            year=1986,
            genre="Metal",
            track_count=1,
            tracks=(ReleaseTrack(1, 1, "Battery", "Metallica", 1.0),),
        )
        plan = plan_album(album, remote, match_tracks(album, remote), FillOptions())

        apply_plans([plan], client=client(), root=self.root)

        self.assertEqual(ID3(path).version, (2, 3, 0))


class AutoChooseTests(unittest.TestCase):
    """Auto mode picks a release; manual mode leaves the choice to the user."""

    def provider(self):
        from discography_analyzer.online.release import (
            AlbumQuery,
            Provider,
            Release,
            ReleaseTrack,
        )

        class FakeProvider(Provider):
            key = "fake"
            name = "Fake"

            def search(self, query: AlbumQuery, limit: int = 10):
                return [
                    Release(
                        provider="fake",
                        release_id="1",
                        title="Master of Puppets",
                        artist="Metallica",
                        year=1986,
                        track_count=2,
                        tracks=(),
                    )
                ]

            def details(self, release: Release) -> Release:
                return Release(
                    provider="fake",
                    release_id=release.release_id,
                    title=release.title,
                    artist=release.artist,
                    year=release.year,
                    track_count=2,
                    tracks=(
                        ReleaseTrack(1, 1, "Battery", "Metallica", 1.0),
                        ReleaseTrack(1, 2, "Master of Puppets", "Metallica", 1.0),
                    ),
                )

        return FakeProvider(client=client(), options=LookupOptions())

    def album(self) -> Path:
        from discography_analyzer.online.album import read_album

        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        folder = Path(directory.name) / "Metallica" / "1986 - Master of Puppets"
        make_flac(folder / "01 - Battery.flac")
        make_flac(folder / "02 - Master of Puppets.flac")
        return read_album(folder, Path(directory.name), EXTENSIONS)

    def test_auto_mode_chooses_a_confident_release(self) -> None:
        lookup = look_up(self.provider(), self.album())

        self.assertEqual(lookup.chosen, 0)
        self.assertTrue(lookup.choice is not None)

    def test_manual_mode_finds_the_same_release_but_chooses_nothing(self) -> None:
        lookup = look_up(self.provider(), self.album(), auto_choose=False)

        self.assertIsNone(lookup.chosen)
        self.assertIsNone(lookup.choice)
        self.assertEqual(len(lookup.candidates), 1)
        self.assertTrue(lookup.candidates[0].confident)


class CompleteAlbumTests(unittest.TestCase):
    def test_a_filled_album_is_searched_only_when_asked_for(self) -> None:
        from discography_analyzer.online.album import read_album
        from discography_analyzer.online.panel import needs_search

        with TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Ariana Grande" / "2015 - Christmas & Chill"
            make_flac(
                folder / "01 - Intro.flac",
                title="Intro",
                artist="Ariana Grande",
                album="Christmas & Chill",
                date="2015",
                genre="Christmas Music",
                tracknumber="1",
                tracktotal="7",
            )
            album = read_album(folder, root, EXTENSIONS)
            # Text fields only: the fixture has no album artist and no cover.
            options = FillOptions(
                fields=frozenset({"title", "artist", "album", "year", "genre", "track"}),
                embed_cover=False,
                save_cover_file=False,
            )
            self.assertEqual(missing_fields(album, options), [])
            self.assertFalse(needs_search(album, options, include_complete=False))
            self.assertTrue(needs_search(album, options, include_complete=True))
