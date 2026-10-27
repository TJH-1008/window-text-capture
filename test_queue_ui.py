import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import CaptureApp
from capture_core import write_json


class QueueUiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = CaptureApp(self.root, self.temp.name)
        self.source = Path(self.temp.name) / 'list.csv'
        self.source.write_text('商场名称,行政区域\nA,锦江区\nB,成华区\nC,金牛区\n', encoding='utf-8-sig')
        self.app.import_roster(self.source)

    def test_import_shows_roster_and_selected_position_survives_refresh(self):
        app = self.app
        self.assertEqual(app.tables.tab(app.tables.select(), 'text'), '商场任务清单')
        second = app.roster['items'][1]['task_id']
        app.roster_tree.selection_set(second)
        app.select_queue_item()
        self.assertEqual(app.label.get(), 'B')
        self.assertIn('第2/3项', app.queue_selection.get())
        app.refresh_roster_table()
        self.assertEqual(app.roster_tree.selection(), (second,))
        self.assertIn('第2/3项', app.queue_selection.get())
        app.operations.select(0)
        app.operations.select(app.queue_panel)
        app.show_queue_table()
        self.assertEqual(app.tables.tab(app.tables.select(), 'text'), '商场任务清单')

    def test_retry_and_reimport_keep_selection_and_saved_capture(self):
        app = self.app
        saved, retry = app.roster['items'][:2]
        saved.update(status='已保存（待复核）', result={'folder': 'old/A'})
        retry.update(status='待确认', last_error='核对地址')
        write_json(app.queue_checkpoint, app.roster)
        app.import_roster(self.source)
        app.roster_tree.selection_set(retry['task_id'])
        app.retry_queue_item()
        self.assertEqual(app.roster_tree.selection(), (retry['task_id'],))
        self.assertEqual(app.roster['items'][1]['status'], '待采集')
        self.assertEqual(app.roster['items'][0]['result'], {'folder': 'old/A'})
        persisted = json.loads(app.queue_checkpoint.read_text(encoding='utf-8'))
        self.assertEqual(len(persisted['items']), 3)
        self.assertEqual(persisted['items'][0]['result'], {'folder': 'old/A'})

    def test_selected_start_requires_row_and_does_not_reset_review_status(self):
        app = self.app
        with patch('app.messagebox.showinfo') as info:
            app.start_queue(from_selected=True)
        self.assertTrue(info.called)
        self.assertFalse(app.running_queue)
        second = app.roster['items'][1]
        second.update(status='待确认', last_error='核对地址')
        app.roster_tree.selection_set(second['task_id'])
        app.roster['items'][2]['status'] = '已保存（待复核）'
        app.windows = [{'handle': 1, 'process': 'WeChatAppEx'}]
        app.window_combo['values'] = ['test']
        app.window_combo.current(0)
        app.start_queue(from_selected=True)
        self.assertFalse(app.running_queue)
        self.assertEqual(second['status'], '待确认')
        self.assertEqual(second['last_error'], '核对地址')
        self.assertIn('没有待采集', app.status.get())

    def test_busy_disables_start_action_without_changing_selection(self):
        app = self.app
        second = app.roster['items'][1]['task_id']
        app.roster_tree.selection_set(second)
        app.set_busy(True)
        self.assertTrue(app.queue_from_selected_button.instate(['disabled']))
        app.start_queue(from_selected=True)
        app.refresh_roster_table()
        self.assertEqual(app.roster_tree.selection(), (second,))
        app.set_busy(False)
        self.assertFalse(app.queue_from_selected_button.instate(['disabled']))

    def test_start_button_runs_selected_suffix_and_keeps_all_checkpoint_rows(self):
        app = self.app
        second = app.roster['items'][1]['task_id']
        app.roster_tree.selection_set(second)
        app.windows = [{'handle': 1, 'process': 'WeChatAppEx'}]
        app.window_combo['values'] = ['test']
        app.window_combo.current(0)
        captured = []
        def reader(command, **kwargs):
            folder = Path(command[command.index('-SaveDirectory') + 1])
            captured.append(folder.name)
            write_json(folder / 'raw-0000.json', {
                'window_title': 'Fixture', 'window_handle': 1,
                'captured_at': '2026-10-22T12:00:00+08:00',
                'primary_document_index': 0,
                'documents': [{'name': 'Fixture', 'text': '全部楼层\n全部分类\n已经到底'}]})
            return SimpleNamespace(stdout=[json.dumps({'kind': 'done', 'data': {'reason': '完成'}})],
                                   wait=lambda **kw: 0, returncode=0)
        with patch('app.threading.Thread', side_effect=lambda target, **kw: SimpleNamespace(start=target)), \
             patch('app.time.sleep'), patch('app.navigate_action'), \
             patch('app.MallNavigator') as navigator, patch('app.subprocess.Popen', side_effect=reader), \
             patch('app.os.startfile', create=True):
            navigator.return_value.open_mall.return_value = {'verified': True}
            app.queue_from_selected_button.invoke()
        self.assertEqual(captured, ['B', 'C'])
        persisted = json.loads(app.queue_checkpoint.read_text(encoding='utf-8'))
        self.assertEqual([i['name'] for i in persisted['items']], ['A', 'B', 'C'])
        self.assertEqual([i['status'] for i in persisted['items']],
                         ['待采集', '已保存（待复核）', '已保存（待复核）'])
        for item in persisted['items'][1:]:
            self.assertTrue((Path(item['result']['folder']) / 'capture.json').is_file())
        app.import_roster(self.source)
        self.assertEqual([i['status'] for i in app.roster['items']],
                         ['待采集', '已保存（待复核）', '已保存（待复核）'])


if __name__ == '__main__':
    unittest.main()
