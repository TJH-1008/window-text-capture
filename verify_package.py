"""打包验证：用一批参考采集记录比对「打包后的 EXE」与「源码直接转换」的结果是否一致。

    python verify_package.py --exe dist/WindowCapture_1.5.0.exe \
        --reference-root D://参考采集//captures --validation-dir D://tmp//check \
        --report D://tmp//check.json --tests-count 113

只读参考记录，不修改原目录；输出一份 JSON 报告（逐商场的记录数、快照数、差异）。
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

import openpyxl

from capture_core import write_json
from excel_import import capture_folder_label, convert_session, read_session
from workspace_ui import VERSION


def run_executable(executable, arguments, report):
    process = subprocess.run([str(executable), *map(str, arguments), "--smoke-report", str(report)],
                             capture_output=True, timeout=90)
    if process.returncode:
        raise RuntimeError(f"Packaged command failed: {process.returncode}")
    if not report.is_file():
        raise RuntimeError(f"Packaged report missing: {report}")
    return json.loads(report.read_text(encoding="utf-8"))


def check_workbooks(report, expected):
    assert report["success_count"] == len(expected), report
    assert report["error_count"] == 0, report
    labels = []
    for output in report["outputs"]:
        book = openpyxl.load_workbook(output, read_only=True)
        try:
            rows = book["品牌明细"].iter_rows(values_only=True)
            headers = next(rows)
            records = list(rows)
            assert len(headers) == 11 and records
            label = records[0][2]
            assert all(row[2] == label for row in records)
            assert Path(output).name.endswith(label + "_品牌业态明细.xlsx")
            assert "待复核记录" in book.sheetnames
            labels.append(label)
        finally:
            book.close()
    assert sorted(labels) == sorted(expected), labels
    return dict(labels=labels, excel_readback=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--validation-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--tests-count", type=int, required=True)
    parser.add_argument("--version", default=VERSION)
    parser.add_argument("--roster", type=Path)
    args = parser.parse_args()
    work = args.validation_dir
    work.mkdir(parents=True, exist_ok=False)
    sources = sorted(args.reference_root.glob("*/capture.json"))
    comparisons = []
    selected = []
    for source in sources:
        label, snapshots, origin = read_session(source)
        all_result = convert_session(label, snapshots, source=origin)
        final_result = convert_session(label, snapshots[-1:], source=origin)
        def identities(result):
            return {(row["name"], row["floor_raw"], row["category"], row["locality"])
                    for row in result["records"]}
        comparisons.append(dict(label=label, snapshots=len(snapshots),
                                all_records=len(all_result["records"]),
                                final_records=len(final_result["records"]),
                                missing_unique=len(identities(all_result) - identities(final_result))))
        if label in {"群光广场", "茂业天地", "王府井", "华熙·LIVE528"}:
            selected.append(source)
    assert len(selected) == 4, selected
    fixtures = work / "fixtures"
    source_digests = {}
    expected = []
    long_index_texts = {}
    for source in selected:
        folder = fixtures / source.parent.name
        folder.mkdir(parents=True)
        for original in [source, *sorted(source.parent.glob("raw-*.json"))]:
            source_digests[original] = hashlib.sha256(original.read_bytes()).hexdigest()
            shutil.copy2(original, folder / original.name)
        label = capture_folder_label(folder.name)
        expected.append(label)
        _, snapshots, origin = read_session(folder / "capture.json")
        issues = "；".join(convert_session(label, snapshots, source=origin)["issues"])
        if len(issues.encode("utf-16-le")) // 2 > 32767:
            long_index_texts[label] = issues
    archive = work / "reference.zip"
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as z:
        for file in fixtures.rglob("*.json"):
            z.write(file, file.relative_to(fixtures).as_posix())
    checks = []
    for kind, input_path in (("directory", fixtures), ("zip", archive)):
        result = run_executable(args.exe, ["--batch-import", input_path,
                                "--excel-output", work / kind], work / (kind + ".json"))
        check = dict(input_type=kind, **check_workbooks(result, expected))
        book = openpyxl.load_workbook(result["index"], read_only=True)
        try:
            continuation = list(book["超长文本续表"].values)[1:]
            restored_labels = []
            for rownum, row in enumerate(list(book["批次索引"].values)[1:], 2):
                if row[0] in long_index_texts:
                    cell = "H" + str(rownum)
                    restored = "".join(part[3] for part in continuation
                                       if part[0] == "批次索引" and part[1] == cell)
                    assert restored == long_index_texts[row[0]], (kind, row[0])
                    restored_labels.append(row[0])
            assert len(restored_labels) == 2, restored_labels
            check["overflow_text_readback"] = restored_labels
        finally:
            book.close()
        checks.append(check)
    smoke_arguments = ["--smoke-test", "--output", work / "smoke-output"]
    if args.roster:
        smoke_arguments.extend(["--roster", args.roster])
    smoke = run_executable(args.exe, smoke_arguments,
                           work / "gui-smoke.json")
    assert smoke["gui_created"] and smoke["frozen"] and smoke["reader_exists"]
    assert smoke["navigation_reader_exists"]
    if args.roster:
        assert smoke['roster_count'] > 0 and smoke['roster_tab_visible']
        assert smoke['selected_start_available'] and smoke['selection_preserved']
    for source, digest in source_digests.items():
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    write_json(args.report, dict(version=args.version, verified_at=datetime.now().astimezone().isoformat(),
                                tests_passed=args.tests_count, packaged_export_checks=checks,
                                gui_smoke=smoke, final_snapshot_comparisons=comparisons,
                                sha256=hashlib.sha256(args.exe.read_bytes()).hexdigest(),
                                source_capture_copies_verified_unchanged=True,
                                live_miniprogram_capture_tested=False))
    print(json.dumps(dict(report=str(args.report), export_checks=checks,
                          reference_comparisons=len(comparisons)), ensure_ascii=False))


if __name__ == "__main__":
    main()
