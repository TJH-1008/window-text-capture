import tkinter as tk
import unittest
from tkinter import ttk

from ui_effects import ButtonSkin
from workspace_ui import configure_styles


class NavigationStateTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.style = configure_styles(self.root)
        self.button = ttk.Button(self.root, text='清单')
        self.skin = ButtonSkin(
            self.button, self.style, 'Nav.TButton', 1,
            ('#FFFFFF', '#F2F2F2', '#E3E3E3', '#FFFFFF', '#EAF6E5', '#FFFFFF'), 0)
        self.root.update_idletasks()
        self.addCleanup(self.root.destroy)

    def test_selected_navigation_keeps_distinct_hover_and_keyboard_focus_artwork(self):
        skin = self.skin
        self.assertNotEqual(str(skin.selected), str(skin.selected_hover))
        self.assertNotEqual(str(skin.selected), str(skin.selected_focused))
        self.assertIn('focus', str(self.style.layout(skin.name)))

    def test_navigation_retains_native_disabled_pressed_and_selected_states(self):
        skin = self.skin
        layout = str(self.style.layout(skin.name))
        self.assertIn('Button.label', layout)
        self.assertTrue(str(skin.disabled))
        self.assertTrue(str(skin.pressed))
        self.assertTrue(str(skin.focused))


if __name__ == '__main__':
    unittest.main()
