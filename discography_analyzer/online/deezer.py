"""Deezer API: free, no key, 50 requests per 5 seconds.

``/search/album`` finds albums, ``/album/<id>`` adds the date and genres,
``/album/<id>/tracks`` gives positions (``disk_number``, ``track_position``),
which the album's own track list does not carry. An exceeded quota comes as
HTTP 200 with ``{"error": {"code": 4}}`` and is waited out, as in
global-music-scanner-2 (``services/deezer/api.ts``). Deezer is closed in some
countries; ``/infos`` names the country it sees and whether it is open there.
"""

from __future__ import annotations

from dataclasses import replace
from urllib.parse import urlencode

from .http import HttpError
from .release import (
    AlbumQuery,
    Provider,
    Release,
    ReleaseTrack,
    ServiceStatus,
    parse_year,
    to_int,
)

DEEZER_API = "https://api.deezer.com"
QUOTA_ERRORS = {4, 700}
QUOTA_PAUSES = (5.0, 10.0)
MAX_TRACK_PAGES = 10


class DeezerProvider(Provider):
    key = "deezer"
    name = "Deezer"
    pacing = {"api.deezer.com": 0.15}
    hosts = ("deezer.com", "dzcdn.net")
    status_url = f"{DEEZER_API}/infos"

    def check(self) -> ServiceStatus:
        data = self._get(self.status_url)
        country = str(data.get("country") or data.get("country_iso") or "?")
        if data.get("open") is False:
            return ServiceStatus(
                False,
                f"Deezer закрыт в стране «{country}» — включите для Deezer свой прокси",
            )
        return ServiceStatus(True, f"доступен, страна запроса — {country}")

    def _get(self, url: str) -> dict:
        for pause in (*QUOTA_PAUSES, None):
            data = self.client.get_json(url)
            if not isinstance(data, dict):
                raise HttpError(url, 200, "Deezer вернул неожиданный ответ")
            error = data.get("error")
            if not error:
                return data
            code = to_int(error.get("code")) if isinstance(error, dict) else 0
            if code not in QUOTA_ERRORS or pause is None:
                message = error.get("message") if isinstance(error, dict) else error
                raise HttpError(url, 200, f"Deezer: {message or 'ошибка'}")
            self.client.pause(pause)
        raise AssertionError("unreachable")

    def search(self, query: AlbumQuery, limit: int = 10) -> list[Release]:
        term = " ".join(part for part in (query.artist.strip(), query.title.strip()) if part)
        data = self._get(f"{DEEZER_API}/search/album?{urlencode({'q': term, 'limit': limit})}")
        items = data.get("data")
        return [
            self._release(item)
            for item in (items if isinstance(items, list) else [])
            if isinstance(item, dict) and item.get("id")
        ]

    def details(self, release: Release) -> Release:
        album = self._get(f"{DEEZER_API}/album/{release.release_id}")
        tracks: list[ReleaseTrack] = []
        url: str | None = f"{DEEZER_API}/album/{release.release_id}/tracks?limit=100"
        for _page in range(MAX_TRACK_PAGES):
            if not url:
                break
            page = self._get(url)
            for item in page.get("data") or []:
                if not isinstance(item, dict):
                    continue
                artist = item.get("artist") if isinstance(item.get("artist"), dict) else {}
                tracks.append(
                    ReleaseTrack(
                        disc=max(1, to_int(item.get("disk_number"), 1)),
                        number=to_int(item.get("track_position")),
                        title=str(item.get("title") or "").strip(),
                        artist=str(artist.get("name") or "").strip(),
                        duration=float(to_int(item.get("duration"))) or None,
                    )
                )
            next_url = page.get("next")
            url = next_url if isinstance(next_url, str) and next_url.startswith(DEEZER_API) else None
        genres = album.get("genres") if isinstance(album.get("genres"), dict) else {}
        genre = next(
            (
                str(item.get("name")).strip()
                for item in genres.get("data") or []
                if isinstance(item, dict) and item.get("name")
            ),
            "",
        )
        base = self._release(album) if album.get("id") else release
        return replace(
            base,
            year=parse_year(album.get("release_date")) or base.year,
            genre=genre or base.genre,
            tracks=tuple(
                sorted(
                    (track for track in tracks if track.number > 0),
                    key=lambda track: (track.disc, track.number),
                )
            ),
        )

    def _release(self, item: dict) -> Release:
        artist = item.get("artist") if isinstance(item.get("artist"), dict) else {}
        return Release(
            provider=self.key,
            release_id=str(item.get("id")),
            title=str(item.get("title") or "").strip(),
            artist=str(artist.get("name") or "").strip(),
            year=parse_year(item.get("release_date")),
            track_count=to_int(item.get("nb_tracks")),
            cover_url=str(item.get("cover_xl") or item.get("cover_big") or ""),
            thumbnail_url=str(item.get("cover_medium") or item.get("cover_small") or ""),
            page_url=str(item.get("link") or ""),
        )
