"""Scale pixel geometry with Tk's DPI while leaving point-sized fonts native."""

import ctypes
import os
import tkinter as tk
from tkinter import ttk


def enable_dpi_awareness():
    if os.name != 'nt':
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Local.WindowTextCapture.OpenDesign.2')
    except (AttributeError, OSError):
        pass


def scale_tree(root, factor):
    """Rescale only pixel-based options; entry widths and text heights use characters."""
    def scaled(value):
        parts = root.tk.splitlist(value) if isinstance(value, str) else (value if isinstance(value, (list, tuple)) else (value,))
        return tuple(round(float(str(part))*factor) for part in parts)

    def visit(widget):
        manager = widget.winfo_manager()
        if manager in ('pack', 'grid'):
            getter = widget.pack_info if manager == 'pack' else widget.grid_info
            setter = widget.pack_configure if manager == 'pack' else widget.grid_configure
            info = getter()
            setter(**{key: scaled(info[key]) for key in ('padx', 'pady', 'ipadx', 'ipady') if key in info})
        options = widget.keys()
        for key in ('padx', 'pady', 'wraplength', 'highlightthickness', 'borderwidth'):
            if key in options:
                value = widget.cget(key)
                if value and str(value).replace('.', '', 1).isdigit():
                    widget.configure(**{key: round(float(str(value))*factor)})
        if isinstance(widget, (tk.Frame, tk.Canvas)):
            for key in ('width', 'height'):
                value = widget.cget(key)
                if value:
                    widget.configure(**{key: round(float(str(value))*factor)})
        if isinstance(widget, tk.Canvas) and not hasattr(widget, 'surface'):
            widget.scale('all', 0, 0, factor, factor)
            for item in widget.find_all():
                if widget.type(item) in ('oval', 'arc', 'line'):
                    widget.itemconfigure(item, width=float(widget.itemcget(item, 'width'))*factor)
        if hasattr(widget, 'surface'):
            widget.padding = round(widget.padding*factor)
            widget.radius = round(widget.radius*factor)
            widget.coords(widget.window, widget.padding, widget.padding)
        if hasattr(widget, 'canvas') and hasattr(widget, 'scroll'):
            widget.pixel_scale = factor
        if isinstance(widget, ttk.Treeview):
            for column in widget['columns']:
                for option in ('width', 'minwidth'):
                    widget.column(column, **{option: round(int(widget.column(column, option))*factor)})
        for child in widget.winfo_children():
            visit(child)

    for child in root.winfo_children():
        visit(child)


def scale_styles(style, factor):
    for name in ('TButton', 'Quiet.TButton', 'Nav.TButton', 'TEntry', 'TCombobox', 'TSpinbox',
                 'TCheckbutton', 'Treeview.Heading'):
        padding = style.lookup(name, 'padding')
        if padding:
            values = padding if isinstance(padding, (tuple, list)) else str(padding).split()
            style.configure(name, padding=tuple(round(float(str(v))*factor) for v in values))
    style.configure('Treeview', rowheight=round(37*factor))
    style.configure('Vertical.TScrollbar', arrowsize=0)
    style.configure('Horizontal.TScrollbar', arrowsize=0)
    style.configure('Capture.Horizontal.TProgressbar', thickness=max(3, round(3*factor)))
