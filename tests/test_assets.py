"""Guards for the bundled controller artwork."""

from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ARTWORK = ROOT / "assets" / "ds4_front.png"
SOURCE = ROOT / "assets" / "ds4_reference.svg"
NOTICE = ROOT / "assets" / "NOTICE.txt"


class ArtworkTests(unittest.TestCase):
    def test_artwork_is_bundled(self) -> None:
        self.assertTrue(ARTWORK.is_file())
        self.assertTrue(SOURCE.is_file())
        self.assertTrue(NOTICE.is_file())

    def test_artwork_is_a_high_resolution_rgba_image(self) -> None:
        with Image.open(ARTWORK) as image:
            self.assertEqual(image.mode, "RGBA")
            self.assertGreaterEqual(image.width, 1200)
            self.assertGreaterEqual(image.height, 800)

    def test_attribution_names_the_source_author(self) -> None:
        text = NOTICE.read_text(encoding="utf-8")
        self.assertIn("Tokyoship", text)
        self.assertIn("CC BY 3.0", text)


if __name__ == "__main__":
    unittest.main()
