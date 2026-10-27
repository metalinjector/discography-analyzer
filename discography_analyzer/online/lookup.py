"""The search for one album: candidates, their track lists, the chosen release."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from .album import LocalAlbum
from .apple import AppleProvider
from .deezer import DeezerProvider
from .discogs import DiscogsProvider
from .http import HttpClient
from .matching import TrackMatch, match_tracks, release_fits, score_release
from .musicbrainz import MusicBrainzProvider
from .proxy import ProxySettings, ProxyTransport
from .release import AlbumQuery, Provider, Release

PROVIDERS: tuple[type[Provider], ...] = (
    AppleProvider,
    DeezerProvider,
    MusicBrainzProvider,
    DiscogsProvider,
)
SERVICE_NAMES = {provider.key: provider.name for provider in PROVIDERS}
SERVICE_HOSTS = {provider.key: provider.hosts for provider in PROVIDERS}
SEARCH_LIMIT = 10
# Track lists are loaded for the best candidates only: every list is one
# more request, and Apple allows about 20 a minute.
DETAILS_LIMIT = 2
CONFIDENT_COVERAGE = 0.8


def provider_class(key: str) -> type[Provider]:
    return next((provider for provider in PROVIDERS if provider.key == key), PROVIDERS[0])


def make_client(
    stop_event: threading.Event | None = None,
    proxy: ProxySettings | None = None,
    *,
    timeout: float = 20.0,
) -> HttpClient:
    """A client with the pauses of every service and the chosen proxy.

    ``ValueError`` if the proxy of one's own has an unusable address.
    """
    pacing: dict[str, float] = {}
    for provider in PROVIDERS:
        pacing.update(provider.pacing)
    return HttpClient(
        pacing=pacing,
        timeout=timeout,
        transport=ProxyTransport(proxy or ProxySettings(), SERVICE_HOSTS),
        stop_event=stop_event,
    )


@dataclass(slots=True)
class Candidate:
    release: Release
    score: int
    fits: bool = False  # see matching.release_fits
    matches: tuple[TrackMatch, ...] = ()

    @classmethod
    def of(cls, release: Release, album: LocalAlbum) -> Candidate:
        return cls(
            release,
            score_release(album.guess, release),
            release_fits(album.guess, release),
        )

    @property
    def matched(self) -> int:
        return sum(1 for match in self.matches if match.source is not None)

    @property
    def coverage(self) -> float:
        return self.matched / len(self.matches) if self.matches else 0.0

    @property
    def rank(self) -> float:
        return self.score + 100 * self.coverage

    @property
    def confident(self) -> bool:
        """Chosen without asking: the album agrees and so do most of its files."""
        return self.release.detailed and self.fits and self.coverage >= CONFIDENT_COVERAGE


@dataclass(slots=True)
class AlbumLookup:
    album: LocalAlbum
    query: AlbumQuery
    candidates: list[Candidate] = field(default_factory=list)
    chosen: int | None = None  # index in ``candidates``; None = do not write
    error: str = ""

    @property
    def choice(self) -> Candidate | None:
        return self.candidates[self.chosen] if self.chosen is not None else None


@dataclass(slots=True)
class LookupCache:
    """Answers of one session: a second search of the same album costs nothing."""

    searches: dict[tuple, list[Release]] = field(default_factory=dict)
    details: dict[tuple, Release] = field(default_factory=dict)


def _options_key(provider: Provider) -> tuple:
    return (provider.key, provider.options.country if provider.key == "apple" else "")


def load_details(
    provider: Provider,
    candidate: Candidate,
    album: LocalAlbum,
    cache: LookupCache,
) -> None:
    """Load the track list of ``candidate`` and match it with the local files."""
    key = (*_options_key(provider), candidate.release.release_id)
    release = cache.details.get(key)
    if release is None:
        release = provider.details(candidate.release)
        cache.details[key] = release
    candidate.release = release
    candidate.score = score_release(album.guess, release)
    candidate.fits = release_fits(album.guess, release)
    candidate.matches = match_tracks(album, release)


def look_up(
    provider: Provider,
    album: LocalAlbum,
    query: AlbumQuery | None = None,
    *,
    cache: LookupCache | None = None,
    auto_choose: bool = True,
) -> AlbumLookup:
    """Search ``provider`` for ``album`` and choose a release if one clearly fits.

    ``auto_choose=False`` is the manual mode: the candidates are found and the
    two best track lists are loaded, but nothing is chosen — the user picks a
    variant himself. Network errors propagate; the caller records them.
    """
    cache = cache if cache is not None else LookupCache()
    query = query or AlbumQuery(album.guess.artist, album.guess.title)
    lookup = AlbumLookup(album=album, query=query)
    if query.empty:
        lookup.error = "нет названия альбома и исполнителя для поиска"
        return lookup
    key = (*_options_key(provider), query.artist.strip().casefold(), query.title.strip().casefold())
    releases = cache.searches.get(key)
    if releases is None:
        releases = provider.search(query, SEARCH_LIMIT)
        cache.searches[key] = releases
    lookup.candidates = sorted(
        (Candidate.of(release, album) for release in releases),
        key=lambda candidate: -candidate.score,
    )
    for candidate in lookup.candidates[:DETAILS_LIMIT]:
        load_details(provider, candidate, album, cache)
        if candidate.confident and candidate.coverage == 1.0:
            break
    lookup.candidates.sort(key=lambda candidate: -candidate.rank)
    if auto_choose and lookup.candidates and lookup.candidates[0].confident:
        lookup.chosen = 0
    return lookup
