"""Local frosted scroll header, rendered from this application's widgets only."""

import tkinter as tk
from tkinter import font as tkfont
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageTk


def frost_image(source, scale=1):
    blurred = source.convert('RGB').filter(ImageFilter.GaussianBlur(7 * scale))
    return Image.blend(blurred, Image.new('RGB', blurred.size, '#F3F8F2'), .34)


class FrostedHeader:
    """Approximate backdrop blur without capturing desktop or other windows.

    Tk cannot sample a composited backdrop. Rasterize the actual visible labels
    below the header, blur that local image, then draw the header copy sharply.
    Updates are coalesced and happen only after scrolling or resizing.
    """

    def __init__(self, panel, title):
        self.panel, self.title = panel, title
        self.pending = None
        self.image = None
        self.source = None
        self.revision = 0
        self.closed = False
        self.fonts = {}
        self.surface = tk.Canvas(panel.canvas, highlightthickness=0,
                                 borderwidth=0, background='#FAFAFA')
        self.surface.bind('<MouseWheel>', self.scroll)
        self.surface.bind('<Destroy>', self.cancel, add='+')

    def scroll(self, event):
        self.panel.canvas.yview_scroll(-int(event.delta / 120), 'units')
        return 'break'

    def cancel(self, _event=None):
        self.closed = True
        if self.pending:
            self.surface.after_cancel(self.pending)
            self.pending = None

    def schedule(self):
        if not self.closed and not self.pending:
            self.pending = self.surface.after(24, self.render)

    def render(self):
        if self.pending:
            self.surface.after_cancel(self.pending)
        self.pending = None
        panel = self.panel
        if self.closed or not panel.canvas.winfo_ismapped():
            return
        scale = panel.pixel_scale
        width = panel.canvas.winfo_width()
        height = round(60 * scale)
        origin_x, origin_y = panel.canvas.winfo_rootx(), panel.canvas.winfo_rooty()
        source = Image.new('RGB', (max(1, width), height), '#FAFAFA')
        draw = ImageDraw.Draw(source)

        def color(widget, option):
            return tuple(value // 257 for value in widget.winfo_rgb(widget.cget(option)))

        def visit(widget):
            if isinstance(widget, tk.Label) and widget.winfo_ismapped():
                x = widget.winfo_rootx() - origin_x
                y = widget.winfo_rooty() - origin_y
                w, h = widget.winfo_width(), widget.winfo_height()
                if y < height and y + h > 0:
                    font = tkfont.Font(widget, font=widget.cget('font')).actual()
                    pixels = max(8, round(abs(font['size']) * scale * 96 / 72))
                    key = (pixels, font['weight'])
                    if key not in self.fonts:
                        name = 'msyhbd.ttc' if font['weight'] == 'bold' else 'msyh.ttc'
                        self.fonts[key] = ImageFont.truetype('C:/Windows/Fonts/' + name, pixels)
                    text = widget.cget('text')
                    variable = widget.cget('textvariable')
                    if variable:
                        text = widget.getvar(variable)
                    draw.rectangle((x, y, x+w, y+h), fill=color(widget, 'background'))
                    draw.text((x+2, y+2), str(text), font=self.fonts[key],
                              fill=color(widget, 'foreground'))
            for child in widget.winfo_children():
                visit(child)

        visit(panel.inner)
        self.source = source
        self.image = ImageTk.PhotoImage(frost_image(source, scale), master=self.surface)
        self.surface.delete('all')
        self.surface.create_image(0, 0, image=self.image, anchor='nw')
        self.surface.create_text(round(18*scale), round(21*scale), text=self.title, anchor='w',
                                 font=('Microsoft YaHei UI', 12, 'bold'), fill='#262626')
        self.surface.create_text(round(18*scale), round(43*scale), text='对当前工作页生效', anchor='w',
                                 font=('Microsoft YaHei UI', 8), fill='#626262')
        self.surface.create_rectangle(round(0*scale), round(8*scale), round(3*scale),
                                      height-round(8*scale), fill='#35A82F', outline='')
        self.surface.create_line(0, height-1, width, height-1, fill='#D9D9D9')
        self.surface.create_line(0, 0, width, 0, fill='#BFD8C3')
        self.surface.place(x=0, y=0, width=width, height=height)
        self.surface.tk.call('raise', str(self.surface))
        self.revision += 1
