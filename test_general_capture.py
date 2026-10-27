import base64
import json
import os
import subprocess
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from app import CaptureApp, capture_reader_arguments, finalize_capture, reader_command
from capture_core import write_json
from excel_import import convert_session
from navigation import SHELL


class GeneralCaptureTests(unittest.TestCase):
    def test_general_arguments_preserve_intermediate_content_and_direction(self):
        args = capture_reader_arguments(1, 'out', 'stop', 20, 400, True, True,
                                        profile='general', direction='up')
        self.assertIn('-AutoScroll', args)
        self.assertNotIn('-FinalOnly', args)
        self.assertEqual(args[args.index('-CaptureProfile') + 1], 'general')
        self.assertEqual(args[args.index('-ScrollDirection') + 1], 'up')

    def test_finalize_preserves_earlier_snapshots_and_repeated_lines_without_claiming_full_history(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for step, text in enumerate(['Alice\n10:00\n你好\n你好', 'Bob\n10:01\n没有更多了']):
                write_json(folder / f'raw-{step:04d}.json', dict(
                    capture_profile='general', scroll_direction='up', collection_mode='stepwise',
                    window_title='Fixture', window_handle=1, primary_document_index=0,
                    captured_at='2026-10-22T12:00:00+08:00',
                    documents=[dict(name='Visible text', text=text)],
                    coverage=dict(truncated=step == 0, visited_nodes=3)))
            result = finalize_capture(folder, '聊天样本', '连续5次文本不变')
            self.assertEqual(result['capture_profile'], 'general')
            self.assertFalse(result['bottom_confirmed'])
            self.assertEqual(result['scroll_direction'], 'up')
            combined = (folder / '滚动汇总文本.txt').read_text(encoding='utf-8-sig')
            self.assertIn('Alice\n10:00\n你好\n你好', combined)
            self.assertIn('Bob\n10:01\n没有更多了', combined)
            self.assertIn('完整性未确认', result['capture_status'])
            self.assertTrue(result['coverage_limited'])
            self.assertEqual(len((folder / '滚动文本快照.jsonl').read_text(encoding='utf-8').splitlines()), 2)

    def test_generic_content_is_rejected_by_mall_parser_even_if_it_looks_like_a_store_list(self):
        with self.assertRaisesRegex(ValueError, '通用窗口'):
            convert_session('聊天', [dict(capture_profile='general', documents=[dict(
                name='Text', text='全部楼层\n全部分类\n星巴克\n1F\n咖啡\n没有更多了')])])

    def test_unreadable_document_is_flagged_when_only_toolbar_text_was_saved(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            write_json(folder / 'raw-0000.json', dict(capture_profile='general',
                window_title='Browser', window_handle=1, captured_at='2026-10-22T12:00:00+08:00',
                documents=[dict(name='Text', text='Back\nRefresh\nAddress')],
                coverage=dict(unreadable_documents=1)))
            result = finalize_capture(folder, 'Browser')
            self.assertTrue(result['coverage_limited'])
            self.assertIn('正文', result['warning'])

    def test_general_ui_disables_mall_queue_and_fast_mode_and_restores_them(self):
        with tempfile.TemporaryDirectory() as temp:
            root = tk.Tk()
            root.withdraw()
            try:
                app = CaptureApp(root, temp)
                app.capture_profile.set('通用窗口文本')
                app.change_capture_profile()
                self.assertTrue(app.fast_capture_toggle.instate(['disabled']))
                self.assertTrue(app.queue_from_selected_button.instate(['disabled']))
                self.assertEqual(str(app.direction_combo.cget('state')), 'readonly')
                self.assertIn('可访问', app.mode_hint.get())
                app.set_busy(True)
                self.assertEqual(str(app.profile_combo.cget('state')), 'disabled')
                app.set_busy(False)
                self.assertTrue(app.fast_capture_toggle.instate(['disabled']))
                with patch('app.messagebox.showinfo') as info:
                    app.start_queue()
                self.assertTrue(info.called)
                app.capture_profile.set('商场小程序')
                app.change_capture_profile()
                self.assertFalse(app.queue_from_selected_button.instate(['disabled']))
                self.assertFalse(app.fast_capture_toggle.instate(['disabled']))
            finally:
                root.destroy()

    def test_command_line_direct_capture_creates_a_generic_archive(self):
        import app
        with tempfile.TemporaryDirectory() as temp:
            def reader(arguments, **kwargs):
                self.assertEqual(arguments[arguments.index('-CaptureProfile') + 1], 'general')
                folder = Path(arguments[arguments.index('-SaveDirectory') + 1])
                write_json(folder / 'raw-0000.json', dict(capture_profile='general',
                    window_title='Fixture', window_handle=5, captured_at='2026-10-22T12:00:00+08:00',
                    primary_document_index=0, documents=[dict(name='Text', text='Fixture content')]))
                return [dict(kind='done', data={'reason': 'Single capture'})]
            report = Path(temp) / 'report.json'
            with patch('sys.argv', ['app.py', '--capture-window', '5', '--profile', 'general',
                                   '--label', 'fixture', '--output', temp, '--smoke-report', str(report)]), \
                 patch('app.run_reader', side_effect=reader):
                app.main()
            saved = json.loads(report.read_text(encoding='utf-8'))
            self.assertEqual(saved['capture_profile'], 'general')
            self.assertTrue((Path(saved['folder']) / 'capture.json').exists())
            self.assertTrue((Path(saved['folder']) / '滚动汇总文本.txt').exists())


@unittest.skipUnless(os.name == 'nt', 'Windows UI Automation')
class NativeGeneralCaptureTests(unittest.TestCase):
    def test_reads_native_labels_textbox_and_list_with_scope_and_password_filtering(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            ready = folder / 'ready.json'
            code = r'''
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
$form=New-Object Windows.Forms.Form
$form.Text='Generic capture fixture';$form.Width=600;$form.Height=500
$label=New-Object Windows.Forms.Label
$label.Text='Fixture heading';$label.SetBounds(20,20,500,30);$form.Controls.Add($label)
$edit=New-Object Windows.Forms.TextBox
$edit.Multiline=$true;$edit.Text="Alice 10:00`r`nHello`r`nHello"
$edit.SetBounds(20,60,500,80);$form.Controls.Add($edit)
$password=New-Object Windows.Forms.TextBox
$password.UseSystemPasswordChar=$true;$password.Text='secret-fixture-must-never-appear'
$password.SetBounds(20,160,500,30);$form.Controls.Add($password)
$list=New-Object Windows.Forms.ListBox
$list.SetBounds(20,210,500,120)
[void]$list.Items.Add('Message list item');[void]$list.Items.Add('Repeated message')
$form.Controls.Add($list)
$panel=New-Object Windows.Forms.Panel
$panel.Text='Container annotation';$panel.SetBounds(20,350,500,30)
$form.Controls.Add($panel)
$outside=New-Object Windows.Forms.Form
$outside.Text='Unselected fixture';$outside.Width=300;$outside.Height=200
$other=New-Object Windows.Forms.Label
$other.Text='outside-selected-window';$other.Width=250;$outside.Controls.Add($other)
$form.Add_Shown({
    $outside.Show()
    [IO.File]::WriteAllText(READY, ('{"handle":'+[long]$form.Handle+'}'))
})
[Windows.Forms.Application]::Run($form)
'''.replace('READY', "'" + str(ready).replace("'", "''") + "'")
            encoded = base64.b64encode(code.encode('utf-16le')).decode('ascii')
            fixture = subprocess.Popen([str(SHELL), '-NoProfile', '-STA', '-EncodedCommand', encoded],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline = time.monotonic() + 15
                while not ready.exists() and fixture.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.1)
                self.assertTrue(ready.exists(), 'Native fixture did not start')
                handle = json.loads(ready.read_text())['handle']
                output = folder / 'capture'
                args = capture_reader_arguments(handle, output, folder / 'stop', 5, 400, False, False,
                                                profile='general', direction='down')
                process = subprocess.run(reader_command(*args), capture_output=True, timeout=40,
                                         creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(process.returncode, 0, process.stdout.decode('utf-8', errors='replace') +
                                 process.stderr.decode('utf-8', errors='replace'))
                result = finalize_capture(output, 'Native fixture')
                text = result['all_text']
                self.assertIn('Fixture heading', text)
                self.assertIn('Alice 10:00', text)
                self.assertEqual(text.count('Hello'), 2)
                self.assertIn('Message list item', text)
                self.assertIn('Container annotation', text)
                self.assertNotIn('secret-fixture', text)
                self.assertNotIn('outside-selected-window', text)
                self.assertFalse(result['bottom_confirmed'])
            finally:
                fixture.terminate()
                fixture.communicate(timeout=10)

    def test_generic_scroll_does_not_trust_mall_bottom_marker(self):
        script = Path(__file__).with_name('generic_reader.ps1')
        code = r'''
$ErrorActionPreference='Stop'
. SCRIPT
$state=@{reads=0;scrolls=0}
$probe={$state.reads++;if($state.reads -eq 1){'已经到底'}else{'More text '+$state.reads}}
$r=Invoke-GenericScroll $probe {$state.scrolls++} {} {$false} {$true} {} 3
if($state.scrolls -ne 3 -or $r.steps -ne 3){throw 'Stopped on a mall marker'}
$state=@{reads=0;scrolls=0}
$r=Invoke-GenericScroll {'Same'} {$state.scrolls++} {} {$false} {$true} {} 20
if($state.scrolls -ne 5){throw 'Unchanged text did not stop at the bound'}
$state=@{reads=0;scrolls=0;focused=$true}
$r=Invoke-GenericScroll {'Text'} {$state.scrolls++} {$state.focused=$false} {$false} {$state.focused} {} 20
if($state.scrolls -ne 1){throw 'Scroll continued after focus loss'}
'''.replace('SCRIPT', "'" + str(script).replace("'", "''") + "'")
        encoded = base64.b64encode(code.encode('utf-16le')).decode('ascii')
        process = subprocess.run([str(SHELL), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', encoded],
                                 capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(process.returncode, 0, process.stderr.decode('utf-8', errors='replace'))


if __name__ == '__main__':
    unittest.main()
