import unittest
import tkinter as tk
from PIL import Image, ImageDraw, ImageChops


class FrostedHeaderTests(unittest.TestCase):
    def test_header_is_visible_at_top_and_after_scrolling(self):
        from workspace_ui import ScrollPanel
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry('340x350')
        panel = ScrollPanel(root)
        panel.pack(fill='both', expand=True)
        for n in range(30):
            tk.Label(panel.inner, text=f'Setting {n}', background='#FAFAFA').pack(pady=8)
        root.update()
        header = panel.frosted_header
        header.render()
        # place() queues geometry work; flush it before checking mapped state.
        root.update_idletasks()
        self.assertTrue(header.surface.winfo_ismapped())
        self.assertEqual(panel.canvas.yview()[0], 0)
        panel.canvas.yview_moveto(.3)
        root.update()
        header.render()
        root.update_idletasks()
        self.assertTrue(header.surface.winfo_ismapped())
        self.assertGreater(header.revision, 1)
        self.assertLess(header.source.getextrema()[0][0], 100)

    def test_frosted_surface_has_a_visible_tinted_boundary(self):
        from workspace_ui import ScrollPanel
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry('340x350')
        panel = ScrollPanel(root)
        panel.pack(fill='both', expand=True)
        for n in range(30):
            tk.Label(panel.inner, text=f'Setting {n}', background='#FAFAFA').pack(pady=8)
        root.update()
        panel.frosted_header.render()
        root.update_idletasks()
        self.assertEqual(panel.frosted_header.image.width(), panel.canvas.winfo_width())
        self.assertLess(panel.frosted_header.source.getpixel((1, 1))[1], 255)

    def test_blurs_content_instead_of_using_a_flat_white_fill(self):
        from frosted_header import frost_image
        source = Image.new('RGB', (160, 60), 'white')
        ImageDraw.Draw(source).rectangle((50, 5, 75, 55), fill='black')
        result = frost_image(source, 1)
        self.assertEqual(result.size, source.size)
        self.assertLess(result.getpixel((62, 30))[0], 200)
        self.assertGreater(result.getpixel((48, 30))[0], 120)
        self.assertLess(result.getpixel((48, 30))[0], 255)
        self.assertIsNotNone(ImageChops.difference(source, result).getbbox())


if __name__ == '__main__':
    unittest.main()
