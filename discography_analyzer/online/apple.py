"""Apple Music / iTunes Search API: free, no key, about 20 requests a minute.

The endpoints and fields are the ones global-music-scanner-2 uses
(``services/apple/api.ts``): ``/search?entity=album`` finds albums,
``/lookup?id=<collectionId>&entity=song`` returns the album and its songs.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any
from urllib.parse import urlencode

from .release import AlbumQuery, Provider, Release, ReleaseTrack, parse_year, to_int

ITUNES_API = "https://itunes.apple.com"
COVER_SIZE = 1200
STOREFRONTS = (
    "US", "GB", "DE", "FR", "IT", "ES", "NL", "SE", "PL", "FI",
    "RU", "UA", "KZ", "JP", "BR", "CA", "AU",
)
# …/source/100x100bb.jpg is resized by the server to any size in the name.
ARTWORK_SIZE_RE = re.compile(r"/\d+x\d+bb\.(?:jpg|png|webp)$")


def artwork_url(url: str, size: int) -> str:
    if not url:
        return ""
    if ARTWORK_SIZE_RE.search(url):
        return ARTWORK_SIZE_RE.sub(f"/{size}x{size}bb.jpg", url)
    return url.replace("100x100", f"{size}x{size}")


def _results(data: Any) -> list[dict]:
    results = data.get("results") if isinstance(data, dict) else None
    return [item for item in results if isinstance(item, dict)] if isinstance(results, list) else []


class AppleProvider(Provider):
    key = "apple"
    name = "Apple Music"
    pacing = {"itunes.apple.com": 3.0}
    hosts = ("apple.com", "mzstatic.com")
    status_url = f"{ITUNES_API}/search?term=metallica&entity=album&limit=1"

    @property
    def country(self) -> str:
        country = self.options.country.strip().upper()
        return country if re.fullmatch(r"[A-Z]{2}", country) else "US"

    def search(self, query: AlbumQuery, limit: int = 10) -> list[Release]:
        term = " ".join(part for part in (query.artist.strip(), query.title.strip()) if part)
        parameters = {"term": term, "entity": "album", "country": self.country, "limit": limit}
        data = self.client.get_json(f"{ITUNES_API}/search?{urlencode(parameters)}")
        return [
            self._release(item)
            for item in _results(data)
            if item.get("wrapperType") == "collection" and item.get("collectionId")
        ]

    def details(self, release: Release) -> Release:
        parameters = {
            "id": release.release_id,
            "country": self.country,
            "entity": "song",
            "limit": 300,
        }
        results = _results(
            self.client.get_json(f"{ITUNES_API}/lookup?{urlencode(parameters)}")
        )
        collection = next(
            (
                item
                for item in results
                if item.get("wrapperType") == "collection"
                and str(item.get("collectionId")) == release.release_id
            ),
            None,
        )
        tracks = sorted(
            (
                ReleaseTrack(
                    disc=max(1, to_int(item.get("discNumber"), 1)),
                    number=to_int(item.get("trackNumber")),
                    title=str(item.get("trackName") or "").strip(),
                    artist=str(item.get("artistName") or "").strip(),
                    duration=to_int(item.get("trackTimeMillis")) / 1000 or None,
                )
                for item in results
                if item.get("wrapperType") == "track"
                and item.get("kind") == "song"
                and str(item.get("collectionId")) == release.release_id
            ),
            key=lambda track: (track.disc, track.number),
        )
        base = self._release(collection) if collection is not None else release
        return replace(base, tracks=tuple(track for track in tracks if track.number > 0))

    def _release(self, item: dict) -> Release:
        artwork = str(item.get("artworkUrl100") or item.get("artworkUrl60") or "")
        return Release(
            provider=self.key,
            release_id=str(item.get("collectionId")),
            title=str(item.get("collectionName") or "").strip(),
            artist=str(item.get("artistName") or "").strip(),
            year=parse_year(item.get("releaseDate")),
            genre=str(item.get("primaryGenreName") or "").strip(),
            track_count=to_int(item.get("trackCount")),
            cover_url=artwork_url(artwork, COVER_SIZE),
            thumbnail_url=artwork,
            page_url=str(item.get("collectionViewUrl") or ""),
        )
