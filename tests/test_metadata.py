from __future__ import annotations

import io
import unittest

from PIL import Image

from discography_analyzer.metadata import _cover_details, _first, _values


class _LazyTags:
    """Mimics mutagen's EasyID3: ``len()`` is a full key enumeration."""

    def __init__(self, data: dict[str, list[str]]) -> None:
        self._data = data
        self.length_calls = 0

    def __len__(self) -> int:
        self.length_calls += 1
        return len(self._data)

    def get(self, key: str, default=None):
        return self._data.get(key, default)


class MetadataTests(unittest.TestCase):
    def test_tag_helpers_do_not_enumerate_easy_tags(self) -> None:
        # ``bool(EasyID3)`` walks every registered easy key, which made tag
        # lookups the slowest part of the whole analysis.
        tags = _LazyTags({"title": ["Song"], "artist": ["A", "B"]})

        self.assertEqual(_first(tags, "title"), "Song")
        self.assertEqual(_values(tags, "artist"), ["A", "B"])
        self.assertEqual(_values(tags, "album"), [])
        self.assertEqual(_first(None, "title"), "")
        self.assertEqual(_values(None, "title"), [])
        self.assertEqual(tags.length_calls, 0)

    def test_cover_details_validate_image_and_dimensions(self) -> None:
        buffer = io.BytesIO()
        Image.new("RGB", (32, 48), "#e97824").save(buffer, format="PNG")

        mime, size, digest, width, height, error = _cover_details(
            buffer.getvalue(),
            "image/png",
        )

        self.assertEqual(mime, "image/png")
        self.assertGreater(size, 0)
        self.assertEqual(len(digest), 64)
        self.assertEqual((width, height), (32, 48))
        self.assertEqual(error, "")

    def test_broken_cover_is_reported(self) -> None:
        _mime, _size, _digest, _width, _height, error = _cover_details(
            b"not an image",
            "image/jpeg",
        )
        self.assertTrue(error)


if __name__ == "__main__":
    unittest.main()
