import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from app import CaptureApp
from display_scale import enable_dpi_awareness


class DisplayScaleTests(unittest.TestCase):
    def test_fonts_geometry_icons_and_stop_control_follow_display_scale(self):
        enable_dpi_awareness()
        for factor in (1, 1.25, 1.5, 2):
            with self.subTest(scale=factor), tempfile.TemporaryDirectory() as temp:
                root = tk.Tk()
                root.withdraw()
                original = root.tk.call('tk', 'scaling')
                try:
                    root.tk.call('tk', 'scaling', factor*96/72)
                    app = CaptureApp(root, temp)
                    self.assertTrue(hasattr(app, 'ui_scale'), 'Missing DPI-aware layout')
                    self.assertAlmostEqual(app.ui_scale, factor, delta=.02)
                    image = app.ui_image('logo')
                    self.assertEqual(image.width(), round(44*factor))
                    self.assertGreaterEqual(int(app.style.lookup('Treeview', 'rowheight')), round(36*factor))
                    width, height = round(1100*factor), round(700*factor)
                    if width > root.winfo_screenwidth() or height > root.winfo_screenheight():
                        self.skipTest(f'屏幕放不下 {width}x{height}，跳过 {factor:g} 倍布局断言')
                    root.geometry(f'{width}x{height}+0+0')
                    root.deiconify()
                    root.update_idletasks()
                    app.adapt_layout()
                    root.update_idletasks()
                    self.assertTrue(app.stop_button.winfo_viewable())
                    bottom = app.stop_button.winfo_rooty() + app.stop_button.winfo_height()
                    self.assertLessEqual(bottom, root.winfo_rooty()+root.winfo_height())
                    self.assertGreater(app.roster_tree.winfo_height(), round(100*factor))
                    self.assertTrue((Path(__file__).with_name('assets')/'app.ico').exists())
                finally:
                    root.tk.call('tk', 'scaling', original)
                    root.update_idletasks()
                    root.destroy()
