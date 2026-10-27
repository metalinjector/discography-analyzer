"""Covers of the found releases, fetched ahead and several at a time.

Moving through the variants of an album must not wait for the network. As
soon as an album is shown, the covers of all its variants are fetched: the
selected variant first, then every small picture, then the full ones, four
downloads side by side. Each download has its own HTTP client, so one slow
picture never holds up the rest, and a queued download nobody needs any more
(the user went to another album) is dropped before it starts.

Nothing here touches Tk: the panel hears about a picture through ``notify``
and reads it with :meth:`CoverLoader.get` on its own thread.
"""

from __future__ import annotations

import io
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable

from PIL import Image

from .lookup import AlbumLookup
from .release import Release

WORKERS = 4
# The pictures of one session: about a hundred full covers.
MAX_CACHED_BYTES = 64 * 1024 * 1024
# Without a Content-Length the progress is told every 20 KB.
PROGRESS_STEP_BYTES = 20 * 1024
LOADING_TEXT = "Загрузка обложки…"
FAILED_TEXT = "Обложка не загружена"

# fetch(url, progress) -> bytes; progress(done, total) while it reads.
Fetch = Callable[[str, Callable[[int, int], None]], bytes]


def release_urls(release: Release) -> tuple[str, ...]:
    """The small picture, then the full one: the small one is shown first."""
    return tuple(url for url in (release.thumbnail_url, release.cover_url) if url)


def wanted_covers(lookup: AlbumLookup | None, first: str = "") -> list[str]:
    """Every cover of the album's variants in the order they will be needed.

    The selected variant's pictures come first, then the small pictures of
    the others and then their full ones, the neighbours of the selected
    variant before the far ones: that is where the user moves next.
    """
    urls = [first]
    if lookup is not None and lookup.candidates:
        releases = [candidate.release for candidate in lookup.candidates]
        chosen = lookup.chosen
        if chosen is not None:
            urls.extend(release_urls(releases[chosen]))
        start = chosen if chosen is not None else 0
        order = sorted(range(len(releases)), key=lambda index: (abs(index - start), index))
        urls.extend(releases[index].thumbnail_url for index in order)
        urls.extend(releases[index].cover_url for index in order)
    return [url for url in dict.fromkeys(urls) if url]


def cover_to_show(release: Release | None, loader: CoverLoader) -> tuple[bytes | None, str]:
    """What the cover slot shows for ``release``: a picture or a line of text.

    Only this release's own pictures count: a variant whose cover failed shows
    «Обложка не загружена», never the cover of the variant shown before it.
    """
    if release is None:
        return None, ""
    urls = release_urls(release)
    if not urls:
        return None, ""  # the service has no cover for this release
    for url in reversed(urls):  # the full picture once it is there
        data = loader.get(url)
        if data is not None:
            return data, ""
    if all(loader.failed(url) for url in urls):
        return None, FAILED_TEXT
    return None, LOADING_TEXT


def progress_text(done: int, total: int) -> str:
    if total:
        return f"{LOADING_TEXT}\n{min(99, done * 100 // total)} %"
    return f"{LOADING_TEXT}\n{done // 1024} КБ"


def _checked(data: bytes) -> bytes:
    """``data`` when it is a picture; an error page is not."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except Exception as exc:
        raise ValueError("ответ сервиса — не картинка") from exc
    return data


class CoverLoader:
    """Downloads pictures in background threads and keeps them for the session.

    Events, through ``notify``: ``("cover_loaded", url)``,
    ``("cover_failed", url)`` and ``("cover_progress", url, done, total)``.
    A picture that failed is not asked for again until
    :meth:`forget_failures` (the proxy changed).
    """

    def __init__(
        self,
        fetch: Fetch,
        notify: Callable[..., None],
        *,
        workers: int = WORKERS,
        max_cached_bytes: int = MAX_CACHED_BYTES,
    ) -> None:
        self._fetch = fetch
        self._notify = notify
        self._workers = workers
        self._max_cached_bytes = max_cached_bytes
        self._condition = threading.Condition()
        self._queue: list[str] = []  # most urgent first
        self._loading: set[str] = set()
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._cached_bytes = 0
        self._failed: set[str] = set()
        self._threads: list[threading.Thread] = []
        self._closed = False

    def focus(self, urls: Iterable[str]) -> None:
        """Fetch ``urls``, most urgent first, instead of what was queued.

        Downloads already running go on and land in the cache; queued ones
        that are not in ``urls`` are dropped.
        """
        with self._condition:
            if self._closed:
                return
            self._queue = [
                url
                for url in dict.fromkeys(urls)
                if url
                and url not in self._cache
                and url not in self._failed
                and url not in self._loading
            ]
            while self._queue and len(self._threads) < self._workers:
                thread = threading.Thread(target=self._work, daemon=True)
                self._threads.append(thread)
                thread.start()
            self._condition.notify_all()

    def get(self, url: str) -> bytes | None:
        with self._condition:
            data = self._cache.get(url)
            if data is not None:
                self._cache.move_to_end(url)
            return data

    def failed(self, url: str) -> bool:
        with self._condition:
            return url in self._failed

    def forget_failures(self) -> None:
        """Let failed pictures be asked for again: they may load another way."""
        with self._condition:
            self._failed.clear()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._queue.clear()
            self._condition.notify_all()

    def _work(self) -> None:
        while True:
            with self._condition:
                while not self._queue and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                url = self._queue.pop(0)
                self._loading.add(url)
            try:
                data: bytes | None = _checked(self._fetch(url, self._progress(url)))
            except Exception:
                data = None
            with self._condition:
                self._loading.discard(url)
                if data is None:
                    self._failed.add(url)
                else:
                    self._store(url, data)
                closed = self._closed
            if not closed:
                self._notify("cover_loaded" if data is not None else "cover_failed", url)

    def _progress(self, url: str) -> Callable[[int, int], None]:
        last = -1

        def report(done: int, total: int) -> None:
            nonlocal last
            # One event per percent (or per 20 KB), not one per chunk.
            step = done * 100 // total if total else done // PROGRESS_STEP_BYTES
            if step != last:
                last = step
                self._notify("cover_progress", url, done, total)

        return report

    def _store(self, url: str, data: bytes) -> None:
        self._cache[url] = data
        self._cached_bytes += len(data)
        while self._cached_bytes > self._max_cached_bytes and len(self._cache) > 1:
            _old, evicted = self._cache.popitem(last=False)
            self._cached_bytes -= len(evicted)
