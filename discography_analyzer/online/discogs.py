"""Discogs API: free with a personal token, 60 requests a minute.

Search needs the token (discogs.com → Settings → Developers → «Generate new
token»); ``/releases/<id>`` gives the track list, styles and images.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any
from urllib.parse import quote, urlencode

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

DISCOGS_API = "https://api.discogs.com"
TOKEN_HINT = (
    "Для Discogs нужен личный токен: discogs.com → Settings → Developers → "
    "«Generate new token». Вставьте его в поле «Токен Discogs»."
)
# «Nirvana (2)»: Discogs numbers artists that share a name.
ARTIST_NUMBER_RE = re.compile(r"\s+\(\d+\)$")
# «1-03», «CD2-01», «2.05», «2-2a» (a sub-track): disc and track. «A1» or «7»
# name no disc; tracks are numbered in order within their disc.
DISC_POSITION_RE = re.compile(r"^(?:cd|disc|dvd)?\s*(\d+)\s*[-.]\s*\d+[a-z]?$", re.IGNORECASE)


def _duration(text: Any) -> float | None:
    parts = str(text or "").strip().split(":")
    if not parts or not all(part.isdigit() for part in parts) or len(parts) > 3:
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return float(seconds) or None


def artist_name(artists: Any) -> str:
    if not isinstance(artists, list):
        return ""
    names = []
    for artist in artists:
        if not isinstance(artist, dict):
            continue
        name = ARTIST_NUMBER_RE.sub("", str(artist.get("anv") or artist.get("name") or ""))
        join = str(artist.get("join") or "").strip()
        names.append(f"{name} {join} " if join and join != "," else f"{name}{join} ")
    return re.sub(r"\s+", " ", "".join(names)).strip()


class DiscogsProvider(Provider):
    key = "discogs"
    name = "Discogs"
    pacing = {"api.discogs.com": 1.0}
    hosts = ("discogs.com",)
    status_url = f"{DISCOGS_API}/"

    def check(self) -> ServiceStatus:
        if not self.options.discogs_token.strip():
            self.client.get_bytes(self.status_url)
            return ServiceStatus(True, "отвечает; для поиска нужен токен")
        # /oauth/identity names the owner of the token: the token works.
        identity = self._get(f"{DISCOGS_API}/oauth/identity")
        return ServiceStatus(True, f"токен принят, пользователь «{identity.get('username', '?')}»")

    def _headers(self) -> dict[str, str]:
        token = self.options.discogs_token.strip()
        if not token:
            raise HttpError(DISCOGS_API, 401, TOKEN_HINT)
        return {"Authorization": f"Discogs token={token}"}

    def _get(self, url: str) -> dict:
        try:
            data = self.client.get_json(url, self._headers())
        except HttpError as exc:
            if exc.status == 401:
                raise HttpError(url, 401, f"Discogs не принял токен. {TOKEN_HINT}") from exc
            raise
        if not isinstance(data, dict):
            raise HttpError(url, 200, "Discogs вернул неожиданный ответ")
        return data

    def search(self, query: AlbumQuery, limit: int = 10) -> list[Release]:
        parameters: dict[str, Any] = {"type": "release", "per_page": limit}
        if query.artist.strip():
            parameters["artist"] = query.artist.strip()
        if query.title.strip():
            parameters["release_title"] = query.title.strip()
        data = self._get(f"{DISCOGS_API}/database/search?{urlencode(parameters)}")
        releases = []
        for item in data.get("results") or []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            # Search results name the release «Artist - Title».
            artist, _dash, title = str(item.get("title") or "").partition(" - ")
            if not title:
                artist, title = "", artist
            styles = item.get("style") or item.get("genre") or []
            releases.append(
                Release(
                    provider=self.key,
                    release_id=str(item["id"]),
                    title=title.strip(),
                    artist=ARTIST_NUMBER_RE.sub("", artist.strip()),
                    year=parse_year(item.get("year")),
                    genre=str(styles[0]).strip() if isinstance(styles, list) and styles else "",
                    cover_url=str(item.get("cover_image") or ""),
                    thumbnail_url=str(item.get("thumb") or ""),
                    page_url=f"https://www.discogs.com{item['uri']}"
                    if str(item.get("uri") or "").startswith("/")
                    else "",
                )
            )
        return releases

    def details(self, release: Release) -> Release:
        data = self._get(f"{DISCOGS_API}/releases/{quote(release.release_id)}")
        artist = artist_name(data.get("artists")) or release.artist
        entries: list[dict] = []
        for item in data.get("tracklist") or []:
            if not isinstance(item, dict):
                continue
            if item.get("type_") == "index":
                entries.extend(sub for sub in item.get("sub_tracks") or [] if isinstance(sub, dict))
            elif item.get("type_", "track") == "track":
                entries.append(item)
        tracks: list[ReleaseTrack] = []
        counters: dict[int, int] = {}
        disc = 1
        for item in entries:
            match = DISC_POSITION_RE.match(str(item.get("position") or "").strip())
            # A position without a disc stays on the disc of the track before.
            disc = int(match.group(1)) if match else disc
            counters[disc] = counters.get(disc, 0) + 1
            tracks.append(
                ReleaseTrack(
                    disc=disc,
                    number=counters[disc],
                    title=str(item.get("title") or "").strip(),
                    artist=artist_name(item.get("artists")) or artist,
                    duration=_duration(item.get("duration")),
                )
            )
        styles = data.get("styles") or data.get("genres") or []
        images = [image for image in data.get("images") or [] if isinstance(image, dict)]
        primary = next((image for image in images if image.get("type") == "primary"), None)
        image = primary or (images[0] if images else {})
        return replace(
            release,
            title=str(data.get("title") or release.title).strip(),
            artist=artist,
            year=to_int(data.get("year")) or parse_year(data.get("released")) or release.year,
            genre=str(styles[0]).strip() if isinstance(styles, list) and styles else release.genre,
            track_count=len(tracks),
            cover_url=str(image.get("uri") or release.cover_url),
            thumbnail_url=str(image.get("uri150") or release.thumbnail_url),
            page_url=str(data.get("uri") or release.page_url),
            tracks=tuple(tracks),
        )
