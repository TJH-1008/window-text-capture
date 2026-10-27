import tempfile
import unittest
from pathlib import Path
from PIL import Image

from brand_icon import application_icon, export_icons


class BrandIconTests(unittest.TestCase):
    def test_mark_keeps_dark_tile_white_window_and_lime_dot(self):
        """方案 D：深色圆角底 + 白色窗口 + 绿色捕捉点。"""
        icon = application_icon(1024)
        self.assertEqual(icon.size, (1024, 1024))
        self.assertEqual(icon.mode, 'RGBA')
        # 深色底允许竖向渐变，只保证足够深；圆角外必须透明
        for xy in ((120, 512), (512, 930)):
            r, g, b, a = icon.getpixel(xy)
            self.assertLess(max(r, g, b), 70, f'{xy} 应为深色底')
            self.assertEqual(a, 255)
        self.assertEqual(icon.getpixel((40, 40))[3], 0, '圆角外应透明')
        # 窗口上边框与标题栏是纯白
        for xy in ((512, 275), (600, 434)):
            self.assertGreater(min(icon.getpixel(xy)[:3]), 235, f'{xy} 应为白色线')
        # 绿色捕捉点：绿分量明显高于红蓝
        r, g, b, a = icon.getpixel((650, 656))
        self.assertGreater(g, r + 40)
        self.assertGreater(g, b + 40)
        self.assertEqual(a, 255)

    def test_small_sizes_stay_legible_and_drop_fine_detail(self):
        for size in (16, 24, 32, 48):
            icon = application_icon(size)
            colours = {p[:3] for p in icon.getdata() if p[3] > 200}
            whites = [c for c in colours if min(c) > 200]
            greens = [c for c in colours if c[1] > c[0] + 40 and c[1] > c[2] + 40]
            self.assertTrue(whites, f'{size}px 仍应有白色窗口线')
            self.assertTrue(greens, f'{size}px 仍应有绿色捕捉点')

    def test_ico_contains_real_small_and_high_dpi_sizes(self):
        with tempfile.TemporaryDirectory() as temp:
            export_icons(Path(temp))
            with Image.open(Path(temp) / 'app.ico') as icon:
                sizes = icon.ico.sizes()
                self.assertTrue({(n, n) for n in (16, 20, 24, 32, 48, 64, 128, 256)} <= sizes)
                for size in sizes:
                    self.assertEqual(icon.ico.getimage(size).size, size)
            with Image.open(Path(temp) / 'app.png') as icon:
                self.assertEqual(icon.size, (1024, 1024))
            with Image.open(Path(temp) / 'logo.png') as logo:
                self.assertEqual(logo.size, (44, 44))


if __name__ == '__main__':
    unittest.main()
