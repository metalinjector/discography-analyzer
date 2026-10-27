"""What every provider returns: a release, its tracks, and the provider base."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from .http import HttpClient


@dataclass(frozen=True, slots=True)
class ReleaseTrack:
    disc: int
    number: int
    title: str
    artist: str = ""
    duration: float | None = None  # seconds


@dataclass(frozen=True, slots=True)
class Release:
    provider: str
    release_id: str
    title: str
    artist: str
    year: int | None = None
    genre: str = ""
    track_count: int = 0
    cover_url: str = ""
    thumbnail_url: str = ""
    page_url: str = ""
    tracks: tuple[ReleaseTrack, ...] = ()

    @property
    def detailed(self) -> bool:
        """The track list is loaded (search results carry only the album)."""
        return bool(self.tracks)

    @property
    def disc_total(self) -> int:
        return max((track.disc for track in self.tracks), default=1)

    def disc_size(self, disc: int) -> int:
        return sum(1 for track in self.tracks if track.disc == disc)

    def label(self) -> str:
        name = f"{self.artist} — {self.title}" if self.artist else self.title
        details: list[str] = []
        if self.year:
            details.append(str(self.year))
        count = len(self.tracks) or self.track_count
        if count:
            details.append(f"треков: {count}")
        if self.disc_total > 1:
            details.append(f"дисков: {self.disc_total}")
        return f"{name} ({', '.join(details)})" if details else name


@dataclass(frozen=True, slots=True)
class AlbumQuery:
    artist: str
    title: str

    @property
    def empty(self) -> bool:
        return not self.artist.strip() and not self.title.strip()


@dataclass(frozen=True, slots=True)
class LookupOptions:
    country: str = "US"  # Apple storefront
    discogs_token: str = ""


class Provider:
    """One online catalogue: album search and the track list of a release."""

    key = ""
    name = ""
    # Minimal pause between two requests to a host, seconds.
    pacing: Mapping[str, float] = {}

    def __init__(self, client: HttpClient, options: LookupOptions) -> None:
        self.client = client
        self.options = options

    def search(self, query: AlbumQuery, limit: int = 10) -> list[Release]:
        raise NotImplementedError

    def details(self, release: Release) -> Release:
        """The same release with ``tracks`` (and the fields only the lookup has)."""
        raise NotImplementedError


def parse_year(value: object) -> int | None:
    """Year of «1986-03-03T08:00:00Z», «1986» or 1986; None for nonsense."""
    match = re.search(r"[0-9]{4}", str(value or ""))
    if match is None:
        return None
    year = int(match.group())
    return year if 1900 <= year <= date.today().year + 2 else None


def to_int(value: object, default: int = 0) -> int:
    """``int(value)`` for the numbers services send as text, ``default`` otherwise."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default
