from __future__ import annotations

import io
import unittest

from PIL import Image

from discography_analyzer.metadata import _cover_details


class MetadataTests(unittest.TestCase):
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
