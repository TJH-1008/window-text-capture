"""Native ttk button geometry with rounded artwork and bounded hover animation."""

import tkinter as tk
from PIL import Image, ImageDraw, ImageTk


class ButtonSkin:
    def __init__(self, button, style, parent_style, scale, palette, index):
        self.button, self.style = button, style
        self.navigation = parent_style == 'Nav.TButton'
        self.pending, self.level = None, 0
        self.name = f'Polished{index}.{parent_style}'
        normal, hover, pressed, disabled, selected, background = palette
        self.frames = [self.artwork(normal, hover, step / 8, background, scale) for step in range(9)]
        self.pressed = self.artwork(pressed, pressed, 0, background, scale)
        self.disabled = self.artwork(disabled, disabled, 0, background, scale)
        self.selected = self.artwork(selected, selected, 0, background, scale, selected=True)
        self.selected_hover = self.artwork(selected, '#DDEFD3', 1, background, scale, selected=True)
        self.selected_focused = self.artwork(selected, selected, 0, background, scale,
                                             outline='#35A82F', selected=True)
        self.focused = self.artwork(hover, hover, 0, background, scale, outline='#35A82F')
        self.current = tk.PhotoImage(master=button, width=self.frames[0].width(), height=self.frames[0].height())
        self.current.tk.call(str(self.current), 'copy', str(self.frames[0]))
        element = self.name + '.surface'
        style.element_create(element, 'image', self.current,
            ('disabled', self.disabled), ('pressed', self.pressed),
            ('selected', 'focus', self.selected_focused),
            ('selected', 'active', self.selected_hover),
            ('selected', self.selected), ('focus', self.focused),
            border=round(8 * scale), padding=0, sticky='nsew')
        style.layout(self.name, [(element, {'sticky': 'nsew', 'children': [
            ('Button.focus', {'sticky': 'nsew', 'children': [
                ('Button.padding', {'sticky': 'nsew', 'children': [
                    ('Button.label', {'sticky': 'nsew'})]})]})]})])
        button.configure(style=self.name)
        button.bind('<Enter>', lambda _event: self.animate(8), add='+')
        button.bind('<Leave>', lambda _event: self.animate(0), add='+')
        button.bind('<Destroy>', self.cancel, add='+')

    def artwork(self, start, end, amount, background, scale, outline=None, selected=False):
        def rgb(color):
            return tuple(int(color[i:i+2], 16) for i in (1, 3, 5))
        a, b = rgb(start), rgb(end)
        fill = tuple(round(x + (y-x)*amount) for x, y in zip(a, b))
        if outline is None and min(fill) > 220 and not self.navigation:
            outline = '#D9D9D9'
        size = (round(80*scale), round(32*scale))
        image = Image.new('RGB', (size[0]*3, size[1]*3), background)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((1, 1, image.width-2, image.height-2), radius=round(7*scale*3),
                               fill=fill, outline=outline, width=max(1, round(1.4*scale*3)))
        if self.navigation:
            if amount > 0 and not selected:
                draw.line((round(8*scale*3), round(2*scale*3), image.width-round(8*scale*3),
                           round(2*scale*3)), fill='white', width=max(1, round(scale*3)))
            if selected:
                draw.rounded_rectangle((round(2*scale*3), round(8*scale*3),
                                        round(5*scale*3), image.height-round(8*scale*3)),
                                       radius=max(1, round(scale*3)), fill='#35A82F')
        image = image.resize(size, Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image, master=self.button)

    def cancel(self, _event=None):
        if self.pending:
            self.button.after_cancel(self.pending)
            self.pending = None

    def animate(self, target):
        self.cancel()
        if not self.button.winfo_exists() or self.button.instate(['disabled']):
            return
        self.level += (target > self.level) - (target < self.level)
        self.current.tk.call(str(self.current), 'copy', str(self.frames[self.level]))
        if self.level != target:
            self.pending = self.button.after(16, lambda: self.animate(target))
