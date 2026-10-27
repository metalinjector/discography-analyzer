"""MusicBrainz and the Cover Art Archive: free, no key, one request a second.

Search: ``/ws/2/release?query=release:"…" AND artist:"…"``; the lookup
``/ws/2/release/<mbid>?inc=recordings+artist-credits+release-groups+genres``
gives media with tracks. Covers come from ``coverartarchive.org``, which
redirects to archive.org. Rate limit and User-Agent rules: see
global-music-scanner-2, ``services/musicbrainz/api.ts``.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any
from urllib.parse import quote, urlencode

from .release import AlbumQuery, Provider, Release, ReleaseTrack, parse_year, to_int

MUSICBRAINZ_API = "https://musicbrainz.org/ws/2"
COVER_ART_ARCHIVE = "https://coverartarchive.org"
VIDEO_MEDIUM_RE = re.compile(r"DVD|Blu-?ray|VCD|UMD|VHS|Laserdisc", re.IGNORECASE)
LUCENE_SPECIAL_RE = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')
EDITION_GROUP_RE = re.compile(r"\s*[(\[][^)\]]*[)\]]")


def _phrase(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _terms(text: str) -> str:
    return "(" + LUCENE_SPECIAL_RE.sub(r"\\\1", text) + ")"


def credit_name(credits: Any) -> str:
    """«Lou Reed & Metallica» from an ``artist-credit`` list."""
    if not isinstance(credits, list):
        return ""
    return "".join(
        f"{credit.get('name') or (credit.get('artist') or {}).get('name') or ''}"
        f"{credit.get('joinphrase') or ''}"
        for credit in credits
        if isinstance(credit, dict)
    ).strip()


def _top_genre(item: Any) -> str:
    genres = item.get("genres") if isinstance(item, dict) else None
    if not isinstance(genres, list):
        return ""
    ranked = sorted(
        (genre for genre in genres if isinstance(genre, dict) and genre.get("name")),
        key=lambda genre: -to_int(genre.get("count")),
    )
    # MusicBrainz genres are lower case: «thrash metal» → «Thrash Metal».
    return str(ranked[0]["name"]).strip().title() if ranked else ""


class MusicBrainzProvider(Provider):
    key = "musicbrainz"
    name = "MusicBrainz"
    pacing = {"musicbrainz.org": 1.1}
    # The Cover Art Archive redirects to archive.org.
    hosts = ("musicbrainz.org", "coverartarchive.org", "archive.org")
    status_url = f"{MUSICBRAINZ_API}/release?query=metallica&limit=1&fmt=json"

    def _query(self, query: AlbumQuery, strict: bool) -> str:
        title = EDITION_GROUP_RE.sub("", query.title).strip() or query.title.strip()
        artist = query.artist.strip()
        quote_text = _phrase if strict else _terms
        parts = []
        if title:
            parts.append(f"release:{quote_text(title)}")
        if artist:
            parts.append(f"artist:{quote_text(artist)}")
        return " AND ".join(parts)

    def search(self, query: AlbumQuery, limit: int = 10) -> list[Release]:
        releases: list[Release] = []
        # The exact phrase first; a looser query when the folder name differs.
        for strict in (True, False):
            parameters = {"query": self._query(query, strict), "fmt": "json", "limit": limit}
            data = self.client.get_json(f"{MUSICBRAINZ_API}/release?{urlencode(parameters)}")
            items = data.get("releases") if isinstance(data, dict) else None
            releases = [
                self._release(item)
                for item in (items if isinstance(items, list) else [])
                if isinstance(item, dict) and item.get("id")
            ]
            if releases:
                break
        return releases

    def details(self, release: Release) -> Release:
        # A literal «+» joins inc values, as in the MusicBrainz documentation.
        parameters = {"inc": "recordings+artist-credits+release-groups+genres", "fmt": "json"}
        data = self.client.get_json(
            f"{MUSICBRAINZ_API}/release/{quote(release.release_id)}?{urlencode(parameters)}"
        )
        if not isinstance(data, dict):
            return release
        artist = credit_name(data.get("artist-credit")) or release.artist
        tracks: list[ReleaseTrack] = []
        media = [
            medium
            for medium in data.get("media") or []
            if isinstance(medium, dict) and not VIDEO_MEDIUM_RE.search(str(medium.get("format") or ""))
        ]
        for medium_index, medium in enumerate(media, start=1):
            disc = to_int(medium.get("position"), medium_index) or medium_index
            for track_index, item in enumerate(medium.get("tracks") or [], start=1):
                if not isinstance(item, dict):
                    continue
                recording = item.get("recording") if isinstance(item.get("recording"), dict) else {}
                length = to_int(item.get("length")) or to_int(recording.get("length"))
                tracks.append(
                    ReleaseTrack(
                        disc=disc,
                        number=to_int(item.get("position"), track_index),
                        title=str(item.get("title") or recording.get("title") or "").strip(),
                        artist=credit_name(item.get("artist-credit")) or artist,
                        duration=length / 1000 if length else None,
                    )
                )
        group = data.get("release-group") if isinstance(data.get("release-group"), dict) else {}
        genre = _top_genre(data)
        if not genre and group.get("id"):
            # Genres are mostly voted on the release group, not on one edition.
            group_data = self.client.get_json(
                f"{MUSICBRAINZ_API}/release-group/{quote(str(group['id']))}?"
                + urlencode({"inc": "genres", "fmt": "json"})
            )
            genre = _top_genre(group_data)
        art = data.get("cover-art-archive") if isinstance(data.get("cover-art-archive"), dict) else {}
        has_front = art.get("front") is not False
        base = self._release(data)
        return replace(
            base,
            artist=artist,
            year=base.year or parse_year(group.get("first-release-date")),
            genre=genre,
            track_count=len(tracks) or base.track_count,
            cover_url=base.cover_url if has_front else "",
            thumbnail_url=base.thumbnail_url if has_front else "",
            tracks=tuple(
                sorted(
                    (track for track in tracks if track.number > 0),
                    key=lambda track: (track.disc, track.number),
                )
            ),
        )

    def _release(self, item: dict) -> Release:
        release_id = str(item.get("id"))
        media = item.get("media") if isinstance(item.get("media"), list) else []
        counted = sum(to_int(medium.get("track-count")) for medium in media if isinstance(medium, dict))
        return Release(
            provider=self.key,
            release_id=release_id,
            title=str(item.get("title") or "").strip(),
            artist=credit_name(item.get("artist-credit")),
            year=parse_year(item.get("date")),
            track_count=to_int(item.get("track-count")) or counted,
            cover_url=f"{COVER_ART_ARCHIVE}/release/{release_id}/front-1200",
            thumbnail_url=f"{COVER_ART_ARCHIVE}/release/{release_id}/front-250",
            page_url=f"https://musicbrainz.org/release/{release_id}",
        )
