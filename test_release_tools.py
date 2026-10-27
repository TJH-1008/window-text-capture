import importlib.util
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

_path = Path(__file__).with_name('tools') / 'check_release.py'
_spec = importlib.util.spec_from_file_location('release_checker', _path)
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)


class ReleaseToolsTests(unittest.TestCase):
    def test_business_input_and_staged_binary_are_rejected(self):
        for name in ('原始数据库/private.xlsx', '商务局商场采集清单.csv',
                     '采集数据/session.json', 'private.db', 'program.exe', '.env.local'):
            with self.subTest(name=name):
                self.assertTrue(checker.source_problems([name]))

    def test_three_known_templates_are_allowed(self):
        self.assertEqual(checker.source_problems(sorted(checker.TEMPLATES)), [])

    def test_single_backslash_and_forward_slash_user_paths_are_rejected(self):
        for sep in ('/', chr(92)):
            text = 'C:' + sep + sep.join(('Users', 'private-name', 'Desktop', 'input.csv'))
            self.assertTrue(checker.text_problems('docs/example.md', text))

    def test_arbitrary_data_in_zip_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'WindowCapture_1.5.0_便携版.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                for name in checker.package_files('1.5.0'):
                    z.writestr('WindowCapture_1.5.0/' + name, b'')
                z.writestr('WindowCapture_1.5.0/private.csv', b'secret data')
            self.assertIn('Unexpected package file: private.csv', checker.zip_problems(archive, '1.5.0'))

    def test_upgrade_never_requires_or_accepts_mapping(self):
        files = checker.package_files('1.5.0', upgrade=True)
        self.assertFalse(any(n.endswith(('.csv', '.xlsx')) for n in files))
        self.assertIn('启动采集器.cmd', files)

    def test_zip_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'unsafe.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('WindowCapture_1.5.0/../private.csv', b'')
            self.assertEqual(checker.zip_problems(archive, '1.5.0'), ['Unsafe ZIP path'])

    def test_source_scan_works_without_git_and_keeps_unicode_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '普通说明.md').write_text('demo', encoding='utf-8')
            (root / '__pycache__').mkdir()
            (root / '__pycache__/cache.pyc').write_bytes(b'')
            self.assertEqual(checker.public_files(root), ['普通说明.md'])

    def test_workbook_internal_save_path_is_rejected(self):
        data = io.BytesIO()
        private_path = 'C:' + chr(92) + chr(92).join(('Users', 'private-name', 'Desktop'))
        with zipfile.ZipFile(data, 'w') as z:
            z.writestr('xl/workbook.xml', '<workbook path="' + private_path + '"/>')
        self.assertTrue(checker.workbook_problems(data.getvalue(), 'template.xlsx'))
