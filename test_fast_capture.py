import base64
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from app import capture_reader_arguments, finalize_capture
from navigation import SHELL


class FastCaptureTests(unittest.TestCase):
    def test_reader_arguments_select_fast_mode_only_for_auto_scroll(self):
        fast = capture_reader_arguments(123, "C:/captures/商场", "C:/stop.request", 120, 1200, True, True)
        self.assertIn("-AutoScroll", fast)
        self.assertIn("-FinalOnly", fast)
        regular = capture_reader_arguments(123, "C:/captures/商场", "C:/stop.request", 120, 1200, True, False)
        self.assertIn("-AutoScroll", regular)
        self.assertNotIn("-FinalOnly", regular)
        direct = capture_reader_arguments(123, "C:/captures/商场", "C:/stop.request", 120, 1200, False, True)
        self.assertNotIn("-AutoScroll", direct)
        self.assertNotIn("-FinalOnly", direct)

    def test_final_only_metadata_and_single_snapshot_survive_finalizing(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            raw = dict(window_title="通用窗口标题", window_handle=7,
                       captured_at="2026-10-22T10:00:00+08:00", step=6,
                       primary_document_index=0, bottom_confirmed=False,
                       collection_mode="final_only", bottom_stable=False,
                       documents=[dict(name="Page", text="商户A\n已经到底了", length=10)])
            (folder / "raw-0006.json").write_text(json.dumps(raw), encoding="utf-8")
            result = finalize_capture(folder, "群光广场", "用户停止")
            self.assertEqual(result["merchant_name"], "群光广场")
            self.assertEqual(result["raw_snapshot_count"], 1)
            self.assertEqual(result["collection_mode"], "final_only")
            self.assertFalse(result["bottom_confirmed"])
            self.assertFalse(result["bottom_stable"])
            self.assertIn("未确认", result["capture_status"])
            self.assertFalse((folder / "滚动文本快照.jsonl").exists())

    def test_final_only_unconfirmed_result_has_consistent_status(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            raw = dict(window_title="Page", window_handle=7,
                       captured_at="2026-10-22T10:00:00+08:00",
                       primary_document_index=0, bottom_confirmed=False,
                       collection_mode="final_only", bottom_stable=True,
                       documents=[dict(name="Page", text="已经到底了")])
            (folder / "raw-0000.json").write_text(json.dumps(raw), encoding="utf-8")
            result = finalize_capture(folder, "群光广场")
            self.assertTrue(result["bottom_marker_present"])
            self.assertFalse(result["bottom_confirmed"])
            self.assertIn("未确认", result["capture_status"])


@unittest.skipUnless(os.name == "nt", "Windows PowerShell")
class FinalScrollTests(unittest.TestCase):
    def run_scroll(self, body):
        script = Path(__file__).with_name("window_reader.ps1")
        prefix = r'''
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile(SCRIPT_PATH,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors.Message -join '; ')}
$fn=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-FinalScroll'},$true)
if(-not $fn){throw 'Missing Invoke-FinalScroll'}
Invoke-Expression $fn.Extent.Text
$state=@{i=0;scrolls=0;stopped=$false;focused=$true;waits=0}
$scroll={$state.scrolls++}
$wait={$state.waits++}
$stop={$state.stopped}
$focus={$state.focused}
$progress={param($message)}
'''.replace("SCRIPT_PATH", "'" + str(script).replace("'", "''") + "'")
        encoded = base64.b64encode((prefix + body).encode("utf-16le")).decode("ascii")
        process = subprocess.run([str(SHELL), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                                 capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", errors="replace"))

    def test_bottom_must_remain_stable_while_lazy_loading_finishes(self):
        self.run_scroll(r'''
$probe={$state.i++; switch($state.i){1 {'A'};2 {'A 已经到底'};3 {'AB 已经到底'};default {'AB 已经到底'}}}
$r=Invoke-FinalScroll $probe $scroll $wait $stop $focus $progress 10
if(-not $r.bottom_stable -or $r.steps -ne 1 -or $state.i -ne 5){throw 'Bottom was not verified after content stabilized'}
''')

    def test_unchanged_without_bottom_is_not_success(self):
        self.run_scroll(r'''
$probe={'A'}
$r=Invoke-FinalScroll $probe $scroll $wait $stop $focus $progress 10
if($r.bottom_stable -or $r.steps -ne 5 -or $state.scrolls -ne 5){throw 'Unchanged content was marked complete'}
''')

    def test_scroll_limit_stops_even_when_loading_never_finishes(self):
        self.run_scroll(r'''
$probe={$state.i++; 'A'+$state.i}
$r=Invoke-FinalScroll $probe $scroll $wait $stop $focus $progress 3
if($r.bottom_stable -or $r.steps -ne 3 -or $state.scrolls -ne 3){throw 'Scroll limit was not respected'}
''')

    def test_focus_loss_and_stop_prevent_more_input(self):
        for field in ("focused", "stopped"):
            with self.subTest(field=field):
                self.run_scroll(r'''
$probe={'A'}
$wait={$state.waits++; $state.FIELD=VALUE}
$r=Invoke-FinalScroll $probe $scroll $wait $stop $focus $progress 10
if($r.bottom_stable -or $state.scrolls -ne 1){throw 'Input continued after stop/focus loss'}
'''.replace("FIELD", field).replace("VALUE", "$false" if field == "focused" else "$true"))


if __name__ == "__main__":
    unittest.main()
