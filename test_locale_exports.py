"""Exercise exports when the OS date formatter only accepts ASCII formats."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app
import excel_import
from test_excel_import import shop, snapshot


class AsciiDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 27, 12, 34, 56)

    def strftime(self, format):
        format.encode('ascii')
        return super().strftime(format)


class LocaleExportTests(unittest.TestCase):
    def test_batch_export_keeps_chinese_name_with_ascii_date_formatter(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / '演示商场' / 'capture.json'
            source.parent.mkdir()
            source.write_text(json.dumps(snapshot(shop())), encoding='utf-8')
            with patch.object(excel_import, 'datetime', AsciiDateTime):
                report = excel_import.batch_export([source.parent], root / 'out')
            self.assertEqual(report['success_count'], 1)
            self.assertEqual(report['error_count'], 0)
            self.assertRegex(Path(report['index']).parent.name,
                             r'^批量业态明细_20261027_123456_[0-9a-f]{6}$')

    def test_zip_export_dialog_keeps_chinese_name_with_ascii_date_formatter(self):
        # Cancel the dialog: no window or real capture data is needed.
        capture = SimpleNamespace(busy=False, output=SimpleNamespace(get=lambda: '.'))
        with patch.object(app, 'datetime', AsciiDateTime), \
                patch.object(app.filedialog, 'asksaveasfilename', return_value='') as dialog:
            app.CaptureApp.export(capture)
        self.assertEqual(dialog.call_args.kwargs['initialfile'],
                         '原始窗口文本_批次_20261027_123456.zip')


if __name__ == '__main__':
    unittest.main()
