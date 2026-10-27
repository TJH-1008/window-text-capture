"""Render the native UI with isolated output and verify visible controls."""

import json
import ctypes
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from roster import ROSTER_FILE

from display_scale import enable_dpi_awareness

enable_dpi_awareness()

import tkinter as tk
from PIL import Image
from app import CaptureApp


def capture_client(root):
    from ctypes import wintypes as wt
    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    user.GetAncestor.argtypes = [wt.HWND, wt.UINT]
    user.GetAncestor.restype = wt.HWND
    user.GetDC.argtypes = [wt.HWND]
    user.GetDC.restype = wt.HDC
    user.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
    user.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
    gdi.CreateCompatibleDC.argtypes = [wt.HDC]
    gdi.CreateCompatibleDC.restype = wt.HDC
    gdi.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = wt.HBITMAP
    gdi.SelectObject.argtypes = [wt.HDC, wt.HANDLE]
    gdi.SelectObject.restype = wt.HANDLE
    gdi.DeleteObject.argtypes = [wt.HANDLE]
    gdi.DeleteDC.argtypes = [wt.HDC]
    gdi.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT,
                             ctypes.c_void_p, ctypes.c_void_p, wt.UINT]
    hwnd = user.GetAncestor(root.winfo_id(), 2)
    width, height = root.winfo_width(), root.winfo_height()
    dc = user.GetDC(hwnd)
    memory = gdi.CreateCompatibleDC(dc)
    bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
    previous = gdi.SelectObject(memory, bitmap)
    try:
        if not user.PrintWindow(hwnd, memory, 3):
            raise RuntimeError('PrintWindow failed; no desktop-capture fallback')
        gdi.SelectObject(memory, previous)
        info = ctypes.create_string_buffer(40)
        import struct
        info.raw = struct.pack('<IiiHHIIiiII', 40, width, -height, 1, 32, 0,
                               width*height*4, 0, 0, 0, 0)
        pixels = ctypes.create_string_buffer(width*height*4)
        if not gdi.GetDIBits(memory, bitmap, 0, height, pixels, info, 0):
            raise RuntimeError('GetDIBits failed')
        return Image.frombytes('RGB', (width, height), pixels.raw, 'raw', 'BGRX')
    finally:
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(memory)
        user.ReleaseDC(hwnd, dc)


def main():
    output = Path(__file__).with_name('verification-opendesign')
    output.mkdir(exist_ok=True)
    results = []
    def settle(root, seconds=.14):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            root.update()
            time.sleep(.01)

    def wait_for(root, condition, message, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            root.update()
            if condition():
                return
            time.sleep(.01)
        raise AssertionError(message)

    with tempfile.TemporaryDirectory() as temp:
        root = tk.Tk()
        root.tk.call('tk', 'scaling', 96/72)
        with patch.object(CaptureApp, 'refresh_windows'), patch.object(CaptureApp, 'load_bundled_roster'):
            app = CaptureApp(root, temp)
            # Public UI previews display a portable path, never the temp username.
            app.output.set('./采集数据')
            root.geometry('1400x900+30+30')
            root.update()
            roster = Path(os.environ.get('WTC_ROSTER', Path(__file__).with_name(ROSTER_FILE)))
            if roster.exists():
                app.import_roster(roster)
            for page in ('queue', 'capture', 'excel'):
                app.navigate_workspace(page)
                root.update()
                app.adapt_layout()
                settle(root)
                assert app.settings_panel.frosted_header.surface.winfo_ismapped(), 'Header missing at scroll origin'
                if page == 'excel':
                    assert app.template_label.winfo_ismapped(), 'Template label is not mapped'
                    label_bottom = app.template_label.winfo_rooty() + app.template_label.winfo_height()
                    assert label_bottom <= app.operations_card.winfo_rooty() + app.operations_card.winfo_height(), 'Template label clipped'
                    assert app.mapping_label.winfo_ismapped(), 'Mapping label is not mapped'
                    mapping_bottom = app.mapping_label.winfo_rooty() + app.mapping_label.winfo_height()
                    assert mapping_bottom <= app.operations_card.winfo_rooty() + app.operations_card.winfo_height(), 'Mapping label clipped'
                assert app.log.winfo_height() >= 32, 'Log cannot display a full wrapped line'
                capture_client(root).save(output / f'{page}-1400.png')
                results.append({'page': page, 'title': app.page_title.get(),
                                'stop_visible': bool(app.stop_button.winfo_viewable())})
            app.navigate_workspace('queue')
            settle(root)
            hover = app.nav_buttons['capture']
            hover.event_generate('<Enter>')
            wait_for(root, lambda: app.button_skins[hover].level == 8,
                     'Hover animation did not reach its target')
            capture_client(root).save(output / 'navigation-hover.png')
            hover.event_generate('<Leave>')
            wait_for(root, lambda: app.button_skins[hover].level == 0,
                     'Hover animation did not return to its resting state')
            selected = app.nav_buttons['queue']
            selected.event_generate('<Enter>')
            selected.focus_force()
            wait_for(root, lambda: selected.instate(['selected', 'focus']),
                     'Selected navigation lost keyboard focus')
            capture_client(root).save(output / 'navigation-selected-focus.png')
            results.append({'page': 'navigation', 'hover_completed': True,
                            'leave_completed': True, 'selected_focus': True})
            selected.event_generate('<Leave>')
            app.search_entry.focus_set()
            app.capture_profile.set('通用窗口文本')
            app.change_capture_profile()
            root.geometry('1100x650+30+30')
            root.update()
            app.adapt_layout()
            root.update()
            panel = app.settings_panel
            header = panel.frosted_header
            for fraction in (.16, .22, .28, .34, .4, .46, .52):
                panel.canvas.yview_moveto(fraction)
                settle(root)
                if header.source and header.source.getextrema()[0][0] < 60:
                    break
            assert header.surface.winfo_ismapped(), 'Frosted header missing after scrolling'
            assert header.revision > 0, 'Frosted header was not rendered'
            assert header.source.getextrema()[0][0] < 60, 'No dark text behind frosted header'
            assert app.nav_buttons['queue'].instate(['disabled'])
            assert app.stop_button.winfo_rooty()+app.stop_button.winfo_height() <= root.winfo_rooty()+root.winfo_height()
            bounds = (root.winfo_rootx(), root.winfo_rooty(),
                      root.winfo_rootx()+root.winfo_width(), root.winfo_rooty()+root.winfo_height())
            capture_client(root).save(output / 'general-1100-frosted.png')
            header.source.save(output / 'frost-source.png')
            x = panel.canvas.winfo_rootx() - root.winfo_rootx()
            y = panel.canvas.winfo_rooty() - root.winfo_rooty()
            capture_client(root).crop((x, y, x+panel.canvas.winfo_width(), y+120)).save(output / 'frosted-detail.png')
            results.append({'page': 'general-compact', 'frosted_visible': True,
                            'frosted_revision': header.revision,
                            'queue_disabled': True, 'stop_inside_window': True})
            root.destroy()
    (output / 'native-checks.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    main()
