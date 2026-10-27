"""Lossless capture storage and batch export; no merchant parsing."""

import json
import re
import zipfile
from pathlib import Path


def safe_slug(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value)).strip(" .")
    if value.upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        value = "_" + value
    return value[:80] or "未命名页面"


def create_capture_folder(captures_root, name):
    root = Path(captures_root)
    root.mkdir(parents=True, exist_ok=True)
    label = safe_slug(name)
    candidate = root / label
    suffix = 2
    while True:
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            candidate = root / f"{label}_{suffix}"
            suffix += 1


def csv_literal(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def build_capture(merchant_name, title, handle, documents, captured_at, primary_index=None):
    nonempty = [(i, d) for i, d in enumerate(documents) if d.get("text")]
    primary = documents[primary_index] if primary_index is not None and 0 <= primary_index < len(documents) else (nonempty[0][1] if nonempty else {})
    text_parts = []
    for _, doc in nonempty:
        if text_parts:
            text_parts.append(f"\n\n--- 文档分隔：{doc.get('name') or '未命名'} ---\n")
        text_parts.append(doc["text"])
    bottom = any(marker in primary.get("text", "") for marker in ("已经到底", "没有更多了", "暂无更多", "已显示全部"))
    return {
        "schema_version": 1,
        "merchant_name": merchant_name,
        "window_title": title,
        "window_handle": handle,
        "captured_at": captured_at,
        "document_count": len(documents),
        "documents": documents,
        "primary_document_index": primary_index,
        "bottom_confirmed": bottom,
        "capture_status": "已读取窗口文本；检测到底部文字提示" if bottom else "已读取窗口文本；底部状态未确认",
        "all_text": "".join(text_parts),
        "limitations": "仅保存窗口通过可访问性接口提供的文本；图片、画布文字和未加载内容不保证可读。框架可能包含已打开的其他页面，原始文档分别保留。底部文字提示不证明商户总数一致。",
    }


def export_archive(captures_root, destination):
    captures_root = Path(captures_root).resolve()
    destination = Path(destination).resolve()
    if not captures_root.is_dir():
        raise ValueError("尚无采集记录")
    if destination.exists():
        raise FileExistsError("目标压缩包已存在，请更换文件名")
    files = [p for p in captures_root.rglob("*") if p.is_file() and p.resolve() != destination]
    if not files:
        raise ValueError("尚无采集记录")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(files):
                archive.write(file, file.relative_to(captures_root).as_posix())
    except Exception:
        if destination.exists():
            destination.unlink()
        raise
    return destination


def write_json(file, value):
    """Replace only our own checkpoint, atomically; retain immutable raw steps."""
    file = Path(file)
    temporary = file.with_suffix(file.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(file)
