"""Scrollable native workspace and its pinned navigation material."""

import tkinter as tk
from tkinter import ttk
from frosted_header import GlassHeader


class WorkspaceViewport(tk.Frame):
    def __init__(self, parent, title_getter, status_getter):
        super().__init__(parent, background='#FAFAFA', takefocus=True)
        self.pixel_scale = 1
        self.minimum_height = 740
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, width=10, background='#FAFAFA', highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.scrollbar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.scrollbar.grid(row=0, column=1, sticky='ns')
        self.inner = tk.Frame(self.canvas, background='#FAFAFA')
        self.window = self.canvas.create_window(0, 64, window=self.inner, anchor='nw')
        self.glass = GlassHeader(self, title_getter, status_getter)
        self.canvas.configure(yscrollcommand=self.scrolled)
        self.canvas.bind('<Configure>', self.fit, add='+')
        self.bind('<Destroy>', self.destroy_jobs, add='+')

    def fit(self, _event=None):
        scale = self.pixel_scale
        top = round(64*scale)
        width = max(1, self.canvas.winfo_width())
        height = max(round(self.minimum_height*scale), self.canvas.winfo_height()-top)
        self.canvas.coords(self.window, 0, top)
        self.canvas.itemconfigure(self.window, width=width, height=height)
        self.canvas.configure(scrollregion=(0, 0, width, height+top))
        self.glass.schedule()

    def scrolled(self, first, last):
        self.scrollbar.set(first, last)
        self.glass.schedule()

    def scroll(self, event):
        self.canvas.yview_scroll(-int(event.delta/120), 'units')
        return 'break'

    def bind_wheel(self):
        def visit(widget):
            if isinstance(widget, (tk.Frame, tk.Canvas, tk.Label)):
                widget.bind('<MouseWheel>', self.scroll, add='+')
            for child in widget.winfo_children():
                visit(child)
        visit(self.inner)
        self.canvas.bind('<MouseWheel>', self.scroll, add='+')

    def destroy_jobs(self, event):
        if event.widget == self:
            self.glass.cancel()
