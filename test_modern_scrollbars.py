import tkinter as tk
import unittest
from tkinter import ttk

from modern_scrollbars import configure_scrollbars


class ModernScrollbarTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.style = ttk.Style(self.root)
        self.style.theme_use('clam')
        configure_scrollbars(self.root, self.style, 1)

    def test_scrollbars_have_thumb_but_no_arrow_buttons(self):
        for orientation in ('Vertical', 'Horizontal'):
            layout = str(self.style.layout(f'{orientation}.TScrollbar'))
            self.assertIn('thumb', layout)
            self.assertNotIn('arrow', layout)
            self.assertEqual(int(self.style.lookup(f'{orientation}.TScrollbar', 'arrowsize')), 0)

    def test_dragging_thumb_moves_the_actual_scrollable_content(self):
        text = tk.Text(self.root, width=30, height=12)
        bar = ttk.Scrollbar(self.root, command=text.yview)
        text.configure(yscrollcommand=bar.set)
        text.pack(side='left')
        bar.pack(side='left', fill='y')
        text.insert('end', '\n'.join(f'Row {n}' for n in range(160)))
        self.root.update()
        x = bar.winfo_width() // 2
        ys = [y for y in range(bar.winfo_height()) if 'thumb' in bar.identify(x, y)]
        self.assertTrue(ys, 'The native widget cannot identify the custom thumb')
        y = ys[len(ys) // 2]
        bar.event_generate('<ButtonPress-1>', x=x, y=y)
        bar.event_generate('<B1-Motion>', x=x, y=y + 70)
        bar.event_generate('<ButtonRelease-1>', x=x, y=y + 70)
        self.root.update()
        self.assertGreater(text.yview()[0], 0)


if __name__ == '__main__':
    unittest.main()
