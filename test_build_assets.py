import unittest
from PIL import Image
from build_assets import gradient_source, collection_art


class BuildAssetsTests(unittest.TestCase):
    def test_generated_backgrounds_are_distinct_high_resolution_and_opaque(self):
        capture = gradient_source('capture')
        excel = gradient_source('excel')
        self.assertEqual(capture.size, (2600, 720))
        self.assertEqual(capture.mode, 'RGBA')
        self.assertEqual(capture.getextrema()[3], (255, 255))
        self.assertNotEqual(capture.tobytes(), excel.tobytes())

    def test_collection_art_is_transparent_and_not_an_opaque_square(self):
        art = collection_art('queue')
        self.assertIsInstance(art, Image.Image)
        self.assertEqual(art.getpixel((0, 0))[3], 0)
        self.assertGreater(art.getbbox()[2], 300)

    def test_each_workspace_has_its_own_thematic_cover_art(self):
        images = [collection_art(name).tobytes() for name in ('queue', 'capture', 'excel')]
        self.assertEqual(len(set(images)), 3)


if __name__ == '__main__':
    unittest.main()
