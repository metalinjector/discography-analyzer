from __future__ import annotations

import io
import os
import queue
import threading
import time
import unittest

from PIL import Image

from discography_analyzer.online.covers import (
    FAILED_TEXT,
    LOADING_TEXT,
    CoverLoader,
    cover_to_show,
    progress_text,
    wanted_covers,
)
from discography_analyzer.online.lookup import AlbumLookup, Candidate
from discography_analyzer.online.release import AlbumQuery, Release


def picture(size: int = 8) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), (200, 40, 40)).save(buffer, "PNG")
    return buffer.getvalue()


PICTURE = picture()


def release(number: int, *, small: bool = True, full: bool = True) -> Release:
    return Release(
        provider="apple",
        release_id=str(number),
        title=f"Variant {number}",
        artist="Artist",
        thumbnail_url=f"https://img.test/{number}/100.jpg" if small else "",
        cover_url=f"https://img.test/{number}/1200.jpg" if full else "",
    )


def lookup(count: int, chosen: int | None = None) -> AlbumLookup:
    return AlbumLookup(
        album=None,  # the covers never look at the local album
        query=AlbumQuery("Artist", "Album"),
        candidates=[Candidate(release(number), 0) for number in range(count)],
        chosen=chosen,
    )


def noise(size: int) -> bytes:
    """A picture that does not compress: its size in bytes follows its size in pixels."""
    buffer = io.BytesIO()
    Image.frombytes("RGB", (size, size), os.urandom(size * size * 3)).save(buffer, "PNG")
    return buffer.getvalue()


class Events:
    """``notify`` of the loader: events land in a queue the test waits on."""

    def __init__(self) -> None:
        self.queue: queue.Queue[tuple] = queue.Queue()
        self.seen: list[tuple] = []

    def __call__(self, *event) -> None:
        self.queue.put(event)

    def wait(self, kinds: set[str], count: int, timeout: float = 5.0) -> list[tuple]:
        found: list[tuple] = []
        deadline = time.monotonic() + timeout
        while len(found) < count:
            event = self.queue.get(timeout=max(0.01, deadline - time.monotonic()))
            self.seen.append(event)
            if event[0] in kinds:
                found.append(event)
        return found


class CoverLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events = Events()
        self.loaders: list[CoverLoader] = []

    def tearDown(self) -> None:
        for loader in self.loaders:
            loader.close()

    def loader(self, fetch, **options) -> CoverLoader:
        loader = CoverLoader(fetch, self.events, **options)
        self.loaders.append(loader)
        return loader

    def test_downloads_run_side_by_side(self) -> None:
        def fetch(_url, _progress):
            time.sleep(0.3)
            return PICTURE

        loader = self.loader(fetch, workers=4)
        start = time.monotonic()
        loader.focus([f"https://img.test/{index}.jpg" for index in range(4)])
        self.events.wait({"cover_loaded"}, 4)

        # One after another this would take 1.2 s.
        self.assertLess(time.monotonic() - start, 0.9)

    def test_queued_covers_no_longer_wanted_are_dropped(self) -> None:
        gate = threading.Event()
        fetched: list[str] = []

        def fetch(url, _progress):
            fetched.append(url)
            if url.endswith("a"):
                gate.wait(5)
            return PICTURE

        loader = self.loader(fetch, workers=1)
        loader.focus(["https://img.test/a", "https://img.test/b", "https://img.test/c"])
        deadline = time.monotonic() + 5
        while not fetched and time.monotonic() < deadline:
            time.sleep(0.01)
        # The user moved on while «a» was downloading: only «c» is wanted now.
        loader.focus(["https://img.test/c"])
        gate.set()
        self.events.wait({"cover_loaded"}, 2)

        self.assertEqual(fetched, ["https://img.test/a", "https://img.test/c"])
        self.assertIsNotNone(loader.get("https://img.test/a"))  # finished into the cache

    def test_the_most_urgent_cover_starts_first(self) -> None:
        fetched: list[str] = []

        def fetch(url, _progress):
            fetched.append(url)
            return PICTURE

        loader = self.loader(fetch, workers=1)
        loader.focus(["https://img.test/1", "https://img.test/2", "https://img.test/3"])
        self.events.wait({"cover_loaded"}, 3)

        self.assertEqual(
            fetched, ["https://img.test/1", "https://img.test/2", "https://img.test/3"]
        )

    def test_a_cover_is_fetched_once(self) -> None:
        fetched: list[str] = []

        def fetch(url, _progress):
            fetched.append(url)
            return PICTURE

        loader = self.loader(fetch)
        loader.focus(["https://img.test/a"])
        self.events.wait({"cover_loaded"}, 1)
        loader.focus(["https://img.test/a"])
        time.sleep(0.1)

        self.assertEqual(fetched, ["https://img.test/a"])
        self.assertEqual(loader.get("https://img.test/a"), PICTURE)

    def test_a_failed_cover_is_not_asked_for_again_until_forgotten(self) -> None:
        calls: list[str] = []

        def fetch(url, _progress):
            calls.append(url)
            raise OSError("timed out")

        loader = self.loader(fetch)
        loader.focus(["https://img.test/a"])
        self.events.wait({"cover_failed"}, 1)
        loader.focus(["https://img.test/a"])
        time.sleep(0.1)

        self.assertTrue(loader.failed("https://img.test/a"))
        self.assertEqual(len(calls), 1)

        loader.forget_failures()  # another proxy: worth one more try
        loader.focus(["https://img.test/a"])
        self.events.wait({"cover_failed"}, 1)
        self.assertEqual(len(calls), 2)

    def test_an_answer_that_is_not_a_picture_counts_as_failed(self) -> None:
        loader = self.loader(lambda _url, _progress: b"<html>Not found</html>")
        loader.focus(["https://img.test/a"])
        self.events.wait({"cover_failed"}, 1)

        self.assertTrue(loader.failed("https://img.test/a"))
        self.assertIsNone(loader.get("https://img.test/a"))

    def test_progress_is_told_once_per_percent(self) -> None:
        def fetch(_url, progress):
            for done in range(0, 200_001, 500):  # 401 chunks of 500 bytes
                progress(done, 200_000)
            return PICTURE

        loader = self.loader(fetch)
        loader.focus(["https://img.test/a"])
        self.events.wait({"cover_loaded"}, 1)
        # Progress comes from the same thread, before the picture.
        steps = [event[2] for event in self.events.seen if event[0] == "cover_progress"]

        self.assertEqual(len(steps), 101)
        self.assertEqual(steps[-1], 200_000)

    def test_the_cache_keeps_its_size(self) -> None:
        pictures = {
            "https://img.test/a": noise(64),
            "https://img.test/b": noise(48),
            "https://img.test/c": noise(32),
        }

        def fetch(url, _progress):
            return pictures[url]

        limit = len(pictures["https://img.test/b"]) + len(pictures["https://img.test/c"]) + 1
        loader = self.loader(fetch, workers=1, max_cached_bytes=limit)
        loader.focus(list(pictures))
        self.events.wait({"cover_loaded"}, 3)

        self.assertIsNone(loader.get("https://img.test/a"))  # the oldest went first
        self.assertIsNotNone(loader.get("https://img.test/b"))
        self.assertIsNotNone(loader.get("https://img.test/c"))

    def test_a_closed_loader_starts_nothing(self) -> None:
        fetched: list[str] = []
        loader = self.loader(lambda url, _progress: fetched.append(url) or PICTURE)
        loader.close()
        loader.focus(["https://img.test/a"])
        time.sleep(0.1)

        self.assertEqual(fetched, [])


class CoverChoiceTests(unittest.TestCase):
    class FakeLoader:
        def __init__(self, cached=(), failed=()) -> None:
            self.cached = dict.fromkeys(cached, PICTURE)
            self.failed_urls = set(failed)

        def get(self, url):
            return self.cached.get(url)

        def failed(self, url):
            return url in self.failed_urls

    def test_the_chosen_variant_first_then_small_pictures_then_full_ones(self) -> None:
        urls = wanted_covers(lookup(4, chosen=2))

        self.assertEqual(
            urls,
            [
                "https://img.test/2/100.jpg",
                "https://img.test/2/1200.jpg",
                # the neighbours of the chosen variant before the far ones
                "https://img.test/1/100.jpg",
                "https://img.test/3/100.jpg",
                "https://img.test/0/100.jpg",
                "https://img.test/1/1200.jpg",
                "https://img.test/3/1200.jpg",
                "https://img.test/0/1200.jpg",
            ],
        )

    def test_without_a_choice_the_list_goes_in_order(self) -> None:
        urls = wanted_covers(lookup(2))

        self.assertEqual(
            urls,
            [
                "https://img.test/0/100.jpg",
                "https://img.test/1/100.jpg",
                "https://img.test/0/1200.jpg",
                "https://img.test/1/1200.jpg",
            ],
        )

    def test_a_cover_asked_for_by_name_goes_before_everything(self) -> None:
        urls = wanted_covers(lookup(2, chosen=0), first="https://img.test/1/1200.jpg")

        self.assertEqual(urls[0], "https://img.test/1/1200.jpg")
        self.assertEqual(urls.count("https://img.test/1/1200.jpg"), 1)

    def test_no_album_wants_no_covers(self) -> None:
        self.assertEqual(wanted_covers(None), [])

    def test_the_full_picture_wins_over_the_small_one(self) -> None:
        variant = release(1)
        small_only = self.FakeLoader(cached=[variant.thumbnail_url])
        both = self.FakeLoader(cached=[variant.thumbnail_url, variant.cover_url])
        both.cached[variant.cover_url] = b"full"

        self.assertEqual(cover_to_show(variant, small_only), (PICTURE, ""))
        self.assertEqual(cover_to_show(variant, both), (b"full", ""))

    def test_a_variant_whose_cover_failed_never_shows_another_variants_cover(self) -> None:
        # 1.16.0: a failed download stayed «loading» for good, and coming back
        # to that variant left the previous variant's cover in the slot.
        failed, shown_before = release(1), release(2)
        loader = self.FakeLoader(
            cached=[shown_before.thumbnail_url, shown_before.cover_url],
            failed=[failed.thumbnail_url, failed.cover_url],
        )

        self.assertEqual(cover_to_show(failed, loader), (None, FAILED_TEXT))

    def test_a_cover_on_its_way_says_so(self) -> None:
        self.assertEqual(cover_to_show(release(1), self.FakeLoader()), (None, LOADING_TEXT))

    def test_a_release_without_a_cover_leaves_the_slot_empty(self) -> None:
        bare = release(1, small=False, full=False)

        self.assertEqual(cover_to_show(bare, self.FakeLoader()), (None, ""))
        self.assertEqual(cover_to_show(None, self.FakeLoader()), (None, ""))

    def test_progress_in_percent_or_in_kilobytes(self) -> None:
        self.assertEqual(progress_text(42, 100), f"{LOADING_TEXT}\n42 %")
        self.assertEqual(progress_text(100, 100), f"{LOADING_TEXT}\n99 %")
        self.assertEqual(progress_text(51_200, 0), f"{LOADING_TEXT}\n50 КБ")


if __name__ == "__main__":
    unittest.main()
