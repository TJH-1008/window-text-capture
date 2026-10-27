import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from app import CaptureApp


class WorkspaceUiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.addCleanup(self.root.update_idletasks)
        self.app = CaptureApp(self.root, self.temp.name)

    def test_button_hover_animates_without_clicking_and_disabled_does_not_activate(self):
        app = self.app
        app.navigate_workspace('capture')
        self.root.deiconify()
        for callback in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.after_cancel(callback)
        self.root.update_idletasks()
        skin = app.button_skins[app.auto_button]
        invoked = []
        app.auto_button.configure(command=lambda: invoked.append(True))

        def wait_for_level(target):
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                self.root.update()
                if skin.level == target:
                    return
                time.sleep(.01)
            self.fail(f'Hover stopped at frame {skin.level}, expected {target}')

        app.auto_button.event_generate('<Enter>')
        wait_for_level(8)
        self.assertEqual(skin.level, 8)
        self.assertEqual(invoked, [])
        app.auto_button.event_generate('<Leave>')
        wait_for_level(0)
        self.assertEqual(skin.level, 0)
        app.set_busy(True)
        app.auto_button.event_generate('<Enter>')
        app.auto_button.invoke()
        self.assertEqual(invoked, [])

    def test_navigation_switches_real_workflows_and_preserves_roster_selection(self):
        app = self.app
        self.assertTrue(hasattr(app, 'navigate_workspace'), 'Missing workspace navigation')
        source = Path(self.temp.name) / 'roster.csv'
        source.write_text('商场名称,行政区域\nA,锦江区\nB,成华区\n', encoding='utf-8-sig')
        app.import_roster(source)
        task_id = app.roster['items'][1]['task_id']
        app.roster_tree.selection_set(task_id)
        app.navigate_workspace('excel')
        self.assertEqual(app.operations.select(), str(app.batch_panel))
        app.navigate_workspace('queue')
        self.assertEqual(app.tables.select(), str(app.roster_table))
        self.assertEqual(app.roster_tree.selection(), (task_id,))
        app.navigate_workspace('capture')
        self.assertEqual(app.tables.select(), str(app.records_panel))
        self.assertEqual(app.active_page.get(), 'capture')

    def test_workspace_uses_high_resolution_gradient_cover_and_updates_heading(self):
        app = self.app
        self.assertTrue(hasattr(app, 'workspace_cover'), 'Missing cover banner')
        self.assertIsNotNone(app.workspace_cover_image)
        self.assertGreaterEqual(app.workspace_cover_image.width(), 2000)
        self.assertGreaterEqual(app.workspace_cover_image.height(), 500)
        self.assertEqual(app.workspace_cover.itemcget(app.cover_title_item, 'text'), '商场清单')
        app.navigate_workspace('excel')
        self.assertEqual(app.workspace_cover.itemcget(app.cover_title_item, 'text'), '批量 Excel')
        self.assertTrue(app.workspace_cover.winfo_exists())

    def test_workspace_switches_cover_art_and_kicker_by_page(self):
        app = self.app
        self.assertEqual(set(app.workspace_cover_images), {'capture', 'queue', 'excel'})
        queue_image = app.workspace_cover.itemcget(app.cover_image_item, 'image')
        app.navigate_workspace('excel')
        self.assertNotEqual(app.workspace_cover.itemcget(app.cover_image_item, 'image'), queue_image)
        self.assertEqual(app.workspace_cover.itemcget(app.cover_kicker_item, 'text'), '品牌与业态整理')

    def test_table_row_hover_is_added_and_cleared_without_losing_other_tags(self):
        app = self.app
        self.root.deiconify()
        self.root.update()
        row = app.roster_tree.insert('', 'end', iid='hover-row', values=('1', '2', '测试商场', '锦江区', '待采集', ''))
        app.roster_tree.item(row, tags=('saved', 'even'))
        self.root.update_idletasks()
        box = app.roster_tree.bbox(row)
        event = type('PointerEvent', (), {'y': box[1] + 2})()
        app.update_table_hover(app.roster_tree, event)
        self.assertIn('hover', app.roster_tree.item(row, 'tags'))
        app.clear_table_hover(app.roster_tree)
        self.assertEqual(app.roster_tree.item(row, 'tags'), ('saved', 'even'))

    def test_general_mode_uses_capture_page_and_disables_queue_navigation(self):
        app = self.app
        self.assertTrue(hasattr(app, 'nav_buttons'), 'Missing navigation controls')
        app.capture_profile.set('通用窗口文本')
        app.change_capture_profile()
        self.assertEqual(app.active_page.get(), 'capture')
        self.assertTrue(app.nav_buttons['queue'].instate(['disabled']))
        self.assertTrue(app.nav_buttons['excel'].instate(['disabled']))
        app.navigate_workspace('queue')
        self.assertEqual(app.active_page.get(), 'capture')
        app.capture_profile.set('商场小程序')
        app.change_capture_profile()
        self.assertFalse(app.nav_buttons['queue'].instate(['disabled']))

    def test_search_filters_display_without_mutating_task_order_or_progress(self):
        app = self.app
        self.assertTrue(hasattr(app, 'roster_search'), 'Missing roster search')
        source = Path(self.temp.name) / 'roster.csv'
        source.write_text('商场名称,行政区域\n龙湖三千集,成华区\n群光广场,锦江区\n', encoding='utf-8-sig')
        app.import_roster(source)
        first, second = [item['task_id'] for item in app.roster['items']]
        app.roster_tree.selection_set(first)
        app.roster_search.set('锦江')
        self.assertEqual(app.roster_tree.get_children(), (second,))
        self.assertEqual(len(app.roster['items']), 2)
        self.assertEqual(app.roster['items'][0]['task_id'], first)
        app.roster_search.set('')
        self.assertEqual(app.roster_tree.get_children(), (first, second))
        self.assertEqual(app.roster_tree.selection(), (first,))

    def test_hover_tooltip_and_busy_state_are_keyboard_accessible(self):
        app = self.app
        self.assertTrue(hasattr(app, 'tooltips'), 'Missing contextual hints')
        app.navigate_workspace('capture')
        hint = app.tooltips[app.auto_button]
        self.root.deiconify()
        self.root.update_idletasks()
        hint.show()
        self.assertIsNotNone(hint.popup)
        hint.hide()
        self.assertIsNone(hint.popup)
        app.set_busy(True)
        self.assertTrue(app.auto_button.instate(['disabled']))
        self.assertTrue(app.maximum_steps_input.instate(['disabled']))
        self.assertTrue(app.wait_input.instate(['disabled']))
        self.assertEqual(app.activity_label.get(), '处理中')
        app.set_busy(False)
        self.assertEqual(app.activity_label.get(), '就绪')
        app.open_folder_button.focus_set()
        with patch.object(app, 'open_directory') as open_directory:
            app.open_folder_button.invoke()
            self.assertTrue(open_directory.called)

    def test_compact_layout_keeps_stop_visible_and_table_usable(self):
        app = self.app
        self.root.deiconify()
        self.root.geometry('1100x650')
        self.root.update_idletasks()
        app.adapt_layout()
        self.root.update_idletasks()
        self.assertFalse(app.summary_row.winfo_ismapped())
        self.assertTrue(app.stop_button.winfo_viewable())
        bottom = app.stop_button.winfo_rooty() + app.stop_button.winfo_height()
        self.assertLessEqual(bottom, self.root.winfo_rooty()+self.root.winfo_height())
        self.assertGreater(app.roster_tree.winfo_height(), 120)

    def test_settings_scroll_hint_reaches_hidden_controls_without_moving_stop(self):
        app = self.app
        self.root.deiconify()
        self.root.geometry('1100x650')
        self.root.update()
        panel = app.settings_panel
        self.assertTrue(hasattr(panel, 'scroll_hint'), 'Missing overflow affordance')
        self.assertTrue(panel.scroll_hint.winfo_ismapped())
        stop_y = app.stop_button.winfo_rooty()
        panel.scroll_hint.event_generate('<Button-1>')
        self.root.update_idletasks()
        self.assertGreater(panel.canvas.yview()[0], 0)
        self.assertEqual(app.stop_button.winfo_rooty(), stop_y)
        self.assertTrue(app.stop_button.winfo_viewable())

    def test_reimport_after_search_removes_detached_old_rows(self):
        app = self.app
        source = Path(self.temp.name) / 'roster.csv'
        source.write_text('任务编号,商场名称\nold-a,OldA\nold-b,OldB\n', encoding='utf-8-sig')
        app.import_roster(source)
        hidden_id = app.roster['items'][0]['task_id']
        app.roster_search.set('OldB')
        new_source = Path(self.temp.name) / 'new.csv'
        new_source.write_text('任务编号,商场名称\nnew-c,NewC\n', encoding='utf-8-sig')
        app.import_roster(new_source)
        self.assertFalse(app.roster_tree.exists(hidden_id))
        app.roster_search.set('')
        self.assertEqual(len(app.roster_tree.get_children()), 1)


if __name__ == '__main__':
    unittest.main()
