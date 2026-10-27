import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

MODULE = Path(__file__).with_name("capture_core.py")
SPEC = importlib.util.spec_from_file_location("capture_core", MODULE)
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


class CaptureCoreTests(unittest.TestCase):
    def test_capture_keeps_all_document_text_and_flags_bottom_evidence(self):
        documents = [
            {"name": "Page-Frame", "text": "商场名称\n第一店\n已经到底了"},
            {"name": "Context", "text": "辅助文本"},
        ]
        result = core.build_capture("龙湖三千集", "窗口", 123, documents, "2026-10-21T10:00:00+08:00")
        self.assertEqual(result["merchant_name"], "龙湖三千集")
        self.assertEqual(result["document_count"], 2)
        self.assertEqual(result["all_text"], "商场名称\n第一店\n已经到底了\n\n--- 文档分隔：Context ---\n辅助文本")
        self.assertTrue(result["bottom_confirmed"])

    def test_bottom_is_not_claimed_without_explicit_evidence(self):
        result = core.build_capture("测试", "窗口", 7, [{"name": "Page-Frame", "text": "仅当前视口"}], "now")
        self.assertFalse(result["bottom_confirmed"])
        self.assertEqual(result["capture_status"], "已读取窗口文本；底部状态未确认")

    def test_history_bottom_does_not_mark_current_page_complete(self):
        docs = [{"name": "Old", "text": "旧页面 已经到底了"}, {"name": "New", "text": "新页面仍在加载"}]
        result = core.build_capture("新商场", "窗口", 7, docs, "now", primary_index=1)
        self.assertFalse(result["bottom_confirmed"])
        self.assertIn("旧页面", result["all_text"])
        self.assertIn("新页面", result["all_text"])

    def test_export_refuses_existing_file_instead_of_overwriting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            captures = root / "captures"
            captures.mkdir()
            (captures / "x.txt").write_text("new", encoding="utf-8")
            output = root / "existing.zip"
            output.write_bytes(b"keep original")
            with self.assertRaises(FileExistsError):
                core.export_archive(captures, output)
            self.assertEqual(output.read_bytes(), b"keep original")

    def test_index_fields_are_not_spreadsheet_formulas(self):
        self.assertEqual(core.csv_literal("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(core.csv_literal("普通中文"), "普通中文")

    def test_export_packages_each_capture_without_rewriting_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture = root / "captures" / "one"
            capture.mkdir(parents=True)
            (capture / "capture.json").write_text(json.dumps({"merchant_name": "A"}), encoding="utf-8")
            (capture / "原始页面文本.txt").write_text("原文保留", encoding="utf-8")
            output = core.export_archive(root / "captures", root / "批次.zip")
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), {"one/capture.json", "one/原始页面文本.txt"})
                self.assertEqual(archive.read("one/原始页面文本.txt").decode("utf-8"), "原文保留")
            self.assertTrue((capture / "capture.json").exists())

    def test_capture_name_slug_is_safe_and_nonempty(self):
        self.assertEqual(core.safe_slug("龙湖/三千集"), "龙湖_三千集")
        self.assertTrue(core.safe_slug("***"))

    def test_create_capture_folder_uses_search_name_and_suffixes_duplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "captures"
            first = core.create_capture_folder(root, "龙湖/三千集")
            (first / "keep.txt").write_text("keep", encoding="utf-8")
            second = core.create_capture_folder(root, "龙湖/三千集")
            self.assertEqual(first.name, "龙湖_三千集")
            self.assertEqual(second.name, "龙湖_三千集_2")
            self.assertTrue(second.is_dir())
            self.assertEqual((first / "keep.txt").read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
