"""The provider adapters on recorded-shape answers; no request leaves the test."""

from __future__ import annotations

import json
import unittest
from urllib.parse import parse_qs, urlsplit

from discography_analyzer.online.apple import AppleProvider, artwork_url
from discography_analyzer.online.deezer import DeezerProvider
from discography_analyzer.online.discogs import DiscogsProvider, artist_name
from discography_analyzer.online.http import HttpClient, HttpError, Response
from discography_analyzer.online.musicbrainz import MusicBrainzProvider
from discography_analyzer.online.release import AlbumQuery, LookupOptions, Release


class FakeWeb:
    """Answers by URL prefix; a list of answers is used in turn."""

    def __init__(self, routes: dict) -> None:
        self.routes = {prefix: list(answers) if isinstance(answers, list) else [answers]
                       for prefix, answers in routes.items()}
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, dict(headers)))
        for prefix, answers in self.routes.items():
            if url.startswith(prefix):
                answer = answers.pop(0) if len(answers) > 1 else answers[0]
                body = answer if isinstance(answer, bytes) else json.dumps(answer).encode()
                return Response(200, body)
        return Response(404, b"")

    def query(self, index: int) -> dict[str, list[str]]:
        return parse_qs(urlsplit(self.calls[index][0]).query)


def make(provider_type, routes, **options):
    web = FakeWeb(routes)
    client = HttpClient(transport=web, sleep=lambda _seconds: None)
    return provider_type(client, LookupOptions(**options)), web


ARTWORK = "https://is1-ssl.mzstatic.com/image/thumb/Music115/v4/0a/1b/2c/0a1b2c/source/100x100bb.jpg"
APPLE_ALBUM = {
    "wrapperType": "collection",
    "collectionType": "Album",
    "collectionId": 1443536580,
    "artistName": "Metallica",
    "collectionName": "Master of Puppets",
    "collectionViewUrl": "https://music.apple.com/us/album/master-of-puppets/1443536580?uo=4",
    "artworkUrl60": ARTWORK.replace("100x100", "60x60"),
    "artworkUrl100": ARTWORK,
    "collectionExplicitness": "notExplicit",
    "trackCount": 8,
    "country": "USA",
    "releaseDate": "1986-03-03T08:00:00Z",
    "primaryGenreName": "Metal",
}


def apple_song(number: int, title: str, disc: int = 1, **extra) -> dict:
    return {
        "wrapperType": "track",
        "kind": "song",
        "collectionId": 1443536580,
        "artistName": "Metallica",
        "trackName": title,
        "discNumber": disc,
        "discCount": 1,
        "trackNumber": number,
        "trackCount": 8,
        "trackTimeMillis": 312000 + number,
        **extra,
    }


class AppleTests(unittest.TestCase):
    def test_search_reads_albums_and_asks_the_chosen_storefront(self) -> None:
        provider, web = make(
            AppleProvider,
            {"https://itunes.apple.com/search": {"resultCount": 1, "results": [APPLE_ALBUM]}},
            country="de",
        )

        releases = provider.search(AlbumQuery("Metallica", "Master of Puppets"))

        query = web.query(0)
        self.assertEqual(query["term"], ["Metallica Master of Puppets"])
        self.assertEqual(query["entity"], ["album"])
        self.assertEqual(query["country"], ["DE"])
        release = releases[0]
        self.assertEqual(
            (release.release_id, release.title, release.artist, release.year, release.genre),
            ("1443536580", "Master of Puppets", "Metallica", 1986, "Metal"),
        )
        self.assertEqual(release.track_count, 8)
        self.assertTrue(release.cover_url.endswith("/source/1200x1200bb.jpg"))
        self.assertEqual(release.thumbnail_url, ARTWORK)

    def test_lookup_keeps_only_the_songs_of_this_album_in_order(self) -> None:
        provider, _web = make(
            AppleProvider,
            {
                "https://itunes.apple.com/lookup": {
                    "results": [
                        APPLE_ALBUM,
                        apple_song(2, "The Thing That Should Not Be"),
                        apple_song(1, "Battery"),
                        apple_song(3, "Video", kind="music-video"),
                        apple_song(4, "Other album", collectionId=1),
                    ]
                }
            },
        )
        search_result = provider._release(APPLE_ALBUM)

        release = provider.details(search_result)

        self.assertEqual([track.title for track in release.tracks], ["Battery", "The Thing That Should Not Be"])
        self.assertEqual(release.tracks[0].duration, 312.001)
        self.assertEqual(release.tracks[0].artist, "Metallica")

    def test_artwork_url_is_resized_by_its_name(self) -> None:
        self.assertTrue(artwork_url(ARTWORK, 600).endswith("/600x600bb.jpg"))
        self.assertEqual(artwork_url("", 600), "")
        self.assertEqual(
            artwork_url("https://example.com/a/100x100-cover.png", 600),
            "https://example.com/a/600x600-cover.png",
        )


class DeezerTests(unittest.TestCase):
    ALBUM = {
        "id": 7776830,
        "title": "Master Of Puppets (Remastered)",
        "link": "https://www.deezer.com/album/7776830",
        "cover_medium": "https://e-cdns-images.dzcdn.net/images/cover/x/250x250-000000-80-0-0.jpg",
        "cover_xl": "https://e-cdns-images.dzcdn.net/images/cover/x/1000x1000-000000-80-0-0.jpg",
        "nb_tracks": 2,
        "release_date": "1986-03-03",
        "genres": {"data": [{"id": 152, "name": "Rock"}, {"id": 464, "name": "Metal"}]},
        "artist": {"id": 119, "name": "Metallica"},
    }

    def test_quota_answer_is_waited_out(self) -> None:
        provider, web = make(
            DeezerProvider,
            {
                "https://api.deezer.com/search/album": [
                    {"error": {"type": "Exception", "message": "Quota limit exceeded", "code": 4}},
                    {"data": [self.ALBUM], "total": 1},
                ]
            },
        )

        releases = provider.search(AlbumQuery("Metallica", "Master of Puppets"))

        self.assertEqual(len(web.calls), 2)
        self.assertEqual(releases[0].artist, "Metallica")
        self.assertEqual(releases[0].cover_url, self.ALBUM["cover_xl"])

    def test_other_errors_are_reported(self) -> None:
        provider, _web = make(
            DeezerProvider,
            {"https://api.deezer.com/album/1": {"error": {"message": "no data", "code": 800}}},
        )

        with self.assertRaisesRegex(HttpError, "Deezer: no data"):
            provider.details(provider._release({"id": 1, "title": "x"}))

    def test_details_follow_the_track_pages_and_take_the_first_genre(self) -> None:
        provider, web = make(
            DeezerProvider,
            {
                "https://api.deezer.com/album/7776830/tracks": [
                    {
                        "data": [
                            {"title": "Battery (Remastered)", "duration": 313, "disk_number": 1,
                             "track_position": 1, "artist": {"name": "Metallica"}},
                        ],
                        "next": "https://api.deezer.com/album/7776830/tracks?limit=100&index=1",
                    },
                    {
                        "data": [
                            {"title": "Master Of Puppets (Remastered)", "duration": 515,
                             "disk_number": 1, "track_position": 2, "artist": {"name": "Metallica"}},
                        ]
                    },
                ],
                "https://api.deezer.com/album/7776830": self.ALBUM,
            },
        )

        release = provider.details(provider._release(self.ALBUM))

        self.assertEqual(len(web.calls), 3)
        self.assertEqual([track.number for track in release.tracks], [1, 2])
        self.assertEqual(release.tracks[1].duration, 515.0)
        self.assertEqual((release.year, release.genre), (1986, "Rock"))


MB_RELEASE_ID = "fed37cfc-2a6d-4569-9ac0-501a7c7598eb"


class MusicBrainzTests(unittest.TestCase):
    SEARCH_HIT = {
        "id": MB_RELEASE_ID,
        "score": 100,
        "title": "Master of Puppets",
        "date": "1986-03-03",
        "track-count": 8,
        "artist-credit": [{"name": "Metallica", "artist": {"id": "65f4f0c5", "name": "Metallica"}}],
        "media": [{"format": "CD", "track-count": 8}],
    }

    def test_a_loose_query_follows_an_empty_exact_one(self) -> None:
        provider, web = make(
            MusicBrainzProvider,
            {
                "https://musicbrainz.org/ws/2/release?": [
                    {"releases": []},
                    {"releases": [self.SEARCH_HIT]},
                ]
            },
        )

        releases = provider.search(AlbumQuery("Metallica", "Master of Puppets (Remastered)"))

        self.assertEqual(
            web.query(0)["query"], ['release:"Master of Puppets" AND artist:"Metallica"']
        )
        self.assertEqual(
            web.query(1)["query"], ["release:(Master of Puppets) AND artist:(Metallica)"]
        )
        self.assertEqual(releases[0].release_id, MB_RELEASE_ID)
        self.assertEqual(releases[0].cover_url, f"https://coverartarchive.org/release/{MB_RELEASE_ID}/front-1200")

    def test_details_skip_video_media_and_take_the_group_genre(self) -> None:
        release_answer = {
            "id": MB_RELEASE_ID,
            "title": "Master of Puppets",
            "date": "1986-03-03",
            "artist-credit": [
                {"name": "Metallica", "joinphrase": " & "},
                {"name": "Guest", "joinphrase": ""},
            ],
            "release-group": {"id": "rg-1", "first-release-date": "1986-03-03"},
            "genres": [],
            "cover-art-archive": {"artwork": True, "front": False, "count": 1},
            "media": [
                {
                    "position": 1,
                    "format": "CD",
                    "tracks": [
                        {"position": 1, "title": "Battery", "length": 312000,
                         "recording": {"title": "Battery", "length": 311000}},
                        {"position": 2, "title": "Orion", "length": None,
                         "recording": {"title": "Orion", "length": 507000}},
                    ],
                },
                {"position": 2, "format": "DVD-Video", "tracks": [{"position": 1, "title": "Live clip"}]},
            ],
        }
        provider, web = make(
            MusicBrainzProvider,
            {
                f"https://musicbrainz.org/ws/2/release/{MB_RELEASE_ID}": release_answer,
                "https://musicbrainz.org/ws/2/release-group/rg-1": {
                    "genres": [{"name": "heavy metal", "count": 3}, {"name": "thrash metal", "count": 9}]
                },
            },
        )

        release = provider.details(provider._release(self.SEARCH_HIT))

        self.assertEqual(web.query(0)["inc"], ["recordings+artist-credits+release-groups+genres"])
        self.assertEqual([track.title for track in release.tracks], ["Battery", "Orion"])
        self.assertEqual([track.duration for track in release.tracks], [312.0, 507.0])
        self.assertEqual(release.artist, "Metallica & Guest")
        self.assertEqual(release.genre, "Thrash Metal")
        # The archive says there is no front cover.
        self.assertEqual(release.cover_url, "")


class DiscogsTests(unittest.TestCase):
    def test_search_without_a_token_explains_where_to_get_one(self) -> None:
        provider, web = make(DiscogsProvider, {})

        with self.assertRaisesRegex(HttpError, "Generate new token"):
            provider.search(AlbumQuery("Metallica", "Master of Puppets"))
        self.assertEqual(web.calls, [])

    def test_search_sends_the_token_and_splits_the_title(self) -> None:
        provider, web = make(
            DiscogsProvider,
            {
                "https://api.discogs.com/database/search": {
                    "results": [
                        {"id": 1259482, "type": "release", "title": "Nirvana (2) - Local Anaesthetic",
                         "year": "1971", "style": ["Prog Rock"], "genre": ["Rock"],
                         "cover_image": "https://i.discogs.com/a.jpg", "thumb": "https://i.discogs.com/t.jpg",
                         "uri": "/release/1259482-Nirvana-Local-Anaesthetic"}
                    ]
                }
            },
            discogs_token="test-token",
        )

        release = provider.search(AlbumQuery("Nirvana", "Local Anaesthetic"))[0]

        self.assertEqual(web.calls[0][1]["Authorization"], "Discogs token=test-token")
        self.assertEqual(web.query(0)["release_title"], ["Local Anaesthetic"])
        self.assertEqual((release.artist, release.title, release.year), ("Nirvana", "Local Anaesthetic", 1971))
        self.assertEqual(release.genre, "Prog Rock")
        self.assertEqual(release.page_url, "https://www.discogs.com/release/1259482-Nirvana-Local-Anaesthetic")

    def test_details_number_vinyl_sides_and_cd_positions(self) -> None:
        answer = {
            "id": 5,
            "title": "Live",
            "artists": [{"name": "Artist (3)", "anv": "", "join": "&"}, {"name": "Friend", "join": ""}],
            "year": 0,
            "released": "1999-05-00",
            "styles": ["Doom Metal"],
            "tracklist": [
                {"position": "", "type_": "heading", "title": "Side A"},
                {"position": "1-1", "type_": "track", "title": "One", "duration": "4:05"},
                {"position": "1-2", "type_": "track", "title": "Two", "duration": "1:02:03"},
                {"position": "2-1", "type_": "track", "title": "Three", "duration": ""},
                {"position": "", "type_": "index", "title": "Suite",
                 "sub_tracks": [{"position": "2-2a", "type_": "track", "title": "Part"}]},
            ],
            "images": [
                {"type": "secondary", "uri": "https://i.discogs.com/back.jpg"},
                {"type": "primary", "uri": "https://i.discogs.com/front.jpg", "uri150": "https://i.discogs.com/f150.jpg"},
            ],
            "uri": "https://www.discogs.com/release/5-Live",
        }
        provider, _web = make(
            DiscogsProvider,
            {"https://api.discogs.com/releases/5": answer},
            discogs_token="test-token",
        )
        release = provider.details(Release("discogs", "5", "Live", "Artist"))

        self.assertEqual(
            [(track.disc, track.number, track.title) for track in release.tracks],
            [(1, 1, "One"), (1, 2, "Two"), (2, 1, "Three"), (2, 2, "Part")],
        )
        self.assertEqual([track.duration for track in release.tracks][:3], [245.0, 3723.0, None])
        self.assertEqual(release.artist, "Artist & Friend")
        self.assertEqual((release.year, release.genre), (1999, "Doom Metal"))
        self.assertEqual(release.cover_url, "https://i.discogs.com/front.jpg")

    def test_artist_names_join_like_the_site(self) -> None:
        self.assertEqual(
            artist_name(
                [
                    {"name": "A", "join": ","},
                    {"name": "B (2)", "anv": "Bee", "join": "Feat."},
                    {"name": "C", "join": ""},
                ]
            ),
            "A, Bee Feat. C",
        )


if __name__ == "__main__":
    unittest.main()
