"""Offline merchant-list parsing and portable XLSX output (standard library)."""

import csv
import io
import json
import re
import sys
import time
import uuid
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

from biz_mapping import (FALLBACK_GROUP, NON_BRAND, coerce_mapping, default_mapping, discover_table,
                         read_table, save_mapping as save_mapping_table)
from capture_core import csv_literal, safe_slug, write_json

HEADERS = ["数据季度", "项目编号", "项目名称", "品牌名称", "楼层", "楼层来源", "四大业态--更细划分", "细分业态", "是否奢侈品", "经营状态", "官网链接"]
MAPPING_SHEET = "业态映射"
PENDING_SHEET = "业态待补清单"
MATCH_METHODS = ("精确", "表内别名", "内置别名", "关键词")
FLOOR_ZONE = r"(?:[A-Z]\d*区|[东西南北中]{1,2}[区馆]|[一二三四五六七八九十\d]+期)"
FLOOR_LEVEL = r"(?:[BLFP]\d+[FL]?|\d+[FL]?|LG层?|G层?)"
# Preserve the platform's notation and zone, rather than guessing L2 == 2F.
FLOOR = re.compile(
    rf"^商场(内|(?:{FLOOR_ZONE})*{FLOOR_LEVEL}(?:[,，、/](?:{FLOOR_ZONE})*{FLOOR_LEVEL})*)"
    r"(?:(?:商场|商)(?:[东西南北中区馆A-Z0-9期]*[.…]+)?|[.…]+)?$",
    re.IGNORECASE,
)
META = re.compile(r"^(?:[★☆]+|\d+(?:\.\d+)?条|\d\.\d|暂无星级|(?:消费[:：])?[￥¥]\d+(?:\.\d+)?(?:/人)?|\d+人预约)$")
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MAX_INPUT = 128 * 1024 * 1024


def clean_lines(text):
    return [(i + 1, line.strip().replace("\ufffc", "")) for i, line in enumerate(text.splitlines())
            if line.strip().replace("\ufffc", "")]


def parse_list(text, mapping=None):
    table = coerce_mapping(mapping)
    lines = clean_lines(text)
    records, issues = [], []
    for index, (line_number, value) in enumerate(lines):
        match = FLOOR.fullmatch(value)
        if not match:
            if value.startswith("商场") and value not in {"商场", "商场服务", "商场专享特惠"}:
                issues.append(f"第{line_number}行楼层标签未识别：{value}")
            continue
        if index < 3:
            issues.append(f"第{line_number}行商户边界不完整")
            continue
        category, locality = lines[index - 2][1], lines[index - 1][1]
        name_index = index - 3
        while name_index >= 0 and META.fullmatch(lines[name_index][1]):
            name_index -= 1
        if name_index < 0 or lines[name_index][1] in {"筛选", "全部分类", "全部楼层", "智能排序"}:
            issues.append(f"第{line_number}行未能确定商户名称")
            continue
        name = lines[name_index][1]
        row_issues = []
        found = table.resolve(category)
        unmapped = found.unmatched or found.method == "歧义"
        group = FALLBACK_GROUP if unmapped else found.group
        standard = category if unmapped else found.category
        floor = "未注明（商场内）" if match[1] == "内" else match[1].upper()
        if "…" in name or "..." in name:
            row_issues.append("名称含截断/重复展示文字")
        if match[1] == "内":
            row_issues.append("未注明具体楼层")
        if "…" in value:
            row_issues.append("楼层标签含截断/重复展示")
        if re.search(r"[,，、/]", match[1]):
            row_issues.append("平台显示多个楼层，未拆成多店")
        if unmapped:
            row_issues.append("一级业态待复核" + (f"：{found.note}" if found.note else ""))
        if category in {"经济型", "舒适型", "高档型", "民宿"}:
            row_issues.append("住宿类记录，项目边界待核")
        if category in NON_BRAND:
            row_issues.append("服务设施/非独立品牌记录")
        records.append(dict(name=name, category=category, category_std=standard, group=group,
                            match=found.method, match_note=found.note,
                            locality=locality, floor=floor, floor_raw=value, line=lines[name_index][0],
                            raw="\n".join(item[1] for item in lines[name_index:index + 1]), issues=row_issues))
    return records, issues


def select_document(snapshot):
    docs = snapshot.get("documents", [])
    index = snapshot.get("primary_document_index")
    if isinstance(index, int) and 0 <= index < len(docs):
        text = docs[index].get("text", "")
        if "输入商户名" in text[:250] and "商场" in text:
            return index, text
        raise ValueError("当前文档不是可识别的商户列表；不使用历史页面替代")
    candidates = [(i, d.get("text", "")) for i, d in enumerate(docs)
                  if re.match(r"^[\s\ufffc]*输入商户名", d.get("text", ""))]
    unique = {}
    for i, text in candidates:
        unique[text] = i
    if len(unique) == 1:
        text, index = next(iter(unique.items()))
        return index, text
    raise ValueError("未找到唯一商户列表文档；保留原文供复核，不解析首页或历史页面")


def quarter_of(value):
    match = re.match(r"(\d{4})[-/](\d{1,2})[-/]", str(value))
    if match and 1 <= int(match[2]) <= 12:
        return f"{match[1]}Q{(int(match[2]) - 1) // 3 + 1}"
    return ""


def convert_session(label, snapshots, mapping=None, source=""):
    if any(snap.get('capture_profile') == 'general' for snap in snapshots):
        raise ValueError('通用窗口文本不适用商场品牌业态整理；请使用原始TXT/JSON。')
    table = coerce_mapping(mapping)
    merged, raw_texts, session_issues = {}, [], []
    platform_count = None
    identity_verified = False
    bottom = False
    dates = []
    for number, snap in enumerate(snapshots):
        dates.append(snap.get("captured_at", ""))
        docs = snap.get("documents", [])
        for i, doc in enumerate(docs):
            raw_texts.append([number, i, doc.get("name", ""), doc.get("text", "")])
        try:
            doc_index, text = select_document(snap)
        except ValueError as exc:
            session_issues.append(f"快照{number}：{exc}")
            continue
        if not ("全部楼层" in text[:500] and "全部分类" in text[:500]):
            session_issues.append(f"快照{number}：未确认全部楼层、全部分类，可能为筛选结果")
        bottom = any(marker in text for marker in ("已经到底", "没有更多了", "暂无更多", "已显示全部"))
        if snap.get("collection_mode") == "final_only":
            bottom = bottom and bool(snap.get("bottom_stable")) and bool(snap.get("bottom_confirmed"))
        identities = [d.get("text", "").split("输入商户名")[0] for d in docs[:doc_index]
                      if label in d.get("text", "") and "商场服务" in d.get("text", "")]
        if identities:
            identity = min(identities, key=len)
            identity_verified = True
            count = re.search(r"全部\s*[（(]\s*(\d+)\s*[）)]", identity)
            if count:
                platform_count = int(count[1])
        records, problems = parse_list(text, table)
        session_issues.extend(f"快照{number}：{p}" for p in problems)
        occurrences = Counter()
        for row in records:
            identity = (row["name"], row["floor_raw"], row["category"], row["locality"])
            occurrences[identity] += 1
            key = (*identity, occurrences[identity])
            if occurrences[identity] > 1:
                row["issues"].append("同一快照存在相同记录，保留并待核对重复")
            provenance = f"快照{number}/文档{doc_index}/原文行{row['line']}"
            if key not in merged:
                row["sources"] = [provenance]
                merged[key] = row
            else:
                merged[key]["sources"].append(provenance)
    if not identity_verified:
        session_issues.append("项目名称采用采集标签；未找到与标签匹配的商场主页身份，归属待核对")
    if not bottom:
        session_issues.append("最终列表未确认底部提示，覆盖范围可能不完整")
    if not merged:
        session_issues.append("未识别到商户；请查看原始文本，不能视为零商户")
    if platform_count is not None and platform_count != len(merged):
        session_issues.append(f"数量差异：解析{len(merged)}条，平台显示{platform_count}家；全部保留，不凑数")
    variants = {}
    for row in merged.values():
        variants.setdefault(row["name"], set()).add((row["floor_raw"], row["category"]))
    for row in merged.values():
        if len(variants[row["name"]]) > 1:
            row["issues"].append("同名记录楼层或分类不同，可能多门店或快照变化，分别保留待核")
    captured_at = next((str(d) for d in reversed(dates) if d), "")
    if not quarter_of(captured_at):
        session_issues.append("采集日期缺失或无效，数据季度留空")
    methods, pending = Counter(), Counter()
    pending_reason = {}
    for row in merged.values():
        methods[row["match"]] += 1
        if row["group"] == FALLBACK_GROUP:
            pending[row["category"]] += 1
            pending_reason.setdefault(row["category"], row.get("match_note", "") or
                                      ("对照表里同一细分业态对应多个标准业态" if row["match"] == "歧义"
                                       else "对照表和内置归并都没有命中"))
    unmapped = sum(pending.values())
    if unmapped:
        session_issues.append(f"业态待补：{len(pending)}个细分业态未在对照表中归并，{unmapped}条记录暂标{FALLBACK_GROUP}")
    total = len(merged) or 1
    mapping_info = dict(description=table.describe(), source=str(table.source or "内置对照"),
                        fingerprint=table.fingerprint or "", mtime=str(table.mtime or ""),
                        groups=list(table.groups), warnings=list(table.warnings),
                        methods=dict(methods), unmapped=unmapped,
                        matched_ratio=round((total - unmapped) / total, 4) if merged else None)
    return dict(label=label, source=source, captured_at=captured_at, quarter=quarter_of(captured_at),
                records=list(merged.values()), issues=list(dict.fromkeys(session_issues)), mapping=mapping_info,
                pending=[[category, count] for category, count in pending.most_common()],
                pending_reason=pending_reason,
                raw_texts=raw_texts, platform_count=platform_count, bottom_confirmed=bottom,
                identity_verified=identity_verified, snapshot_count=len(snapshots))


def column_name(index):
    value = ""
    while index:
        index, digit = divmod(index - 1, 26)
        value = chr(65 + digit) + value
    return value


def xml_bytes(element):
    return ET.tostring(element, encoding="utf-8", xml_declaration=True)


def write_xlsx(path, sheets):
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"不覆盖已有文件：{path}")
    sheets = list(sheets)
    used_names = {name.lower() for name, _, _ in sheets}
    continuation_name = "超长文本续表"
    suffix = 2
    while continuation_name.lower() in used_names:
        continuation_name = f"超长文本续表_{suffix}"
        suffix += 1
    overflow_rows = [["来源工作表", "单元格", "分段", "完整内容"]]
    prepared_sheets = []
    for name, rows, widths in sheets:
        prepared_rows = []
        for rownum, values in enumerate(rows, 1):
            prepared = list(values)
            for colnum, value in enumerate(values, 1):
                if value is None or (isinstance(value, (float, int)) and not isinstance(value, bool)):
                    continue
                text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value))
                if len(text.encode("utf-16-le")) // 2 <= 32767:
                    continue
                cell_reference = f"{column_name(colnum)}{rownum}"
                # 14000 code points fit even when every character uses a surrogate pair.
                for part, offset in enumerate(range(0, len(text), 14000), 1):
                    overflow_rows.append([name, cell_reference, part, text[offset:offset + 14000]])
                prepared[colnum - 1] = (text[:1000] + f"\n【超长内容已分段保存，完整内容见“{continuation_name}”，"
                                       f"来源工作表“{name}”、单元格{cell_reference}，按分段顺序拼接。】")
            prepared_rows.append(prepared)
        prepared_sheets.append((name, prepared_rows, widths))
    if len(overflow_rows) > 1:
        prepared_sheets.append((continuation_name, overflow_rows, [30, 16, 12, 110]))
    sheets = prepared_sheets
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    types = ET.Element("Types", xmlns="http://schemas.openxmlformats.org/package/2006/content-types")
    for ext, content in [("rels", "application/vnd.openxmlformats-package.relationships+xml"), ("xml", "application/xml")]:
        ET.SubElement(types, "Default", Extension=ext, ContentType=content)
    book = ET.Element("workbook", xmlns=NS, attrib={"xmlns:r": REL})
    sheet_nodes = ET.SubElement(book, "sheets")
    relationships = ET.Element("Relationships", xmlns="http://schemas.openxmlformats.org/package/2006/relationships")
    styles = f'''<styleSheet xmlns="{NS}"><fonts count="2"><font><sz val="10"/><name val="Microsoft YaHei"/></font><font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Microsoft YaHei"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''
    try:
        with zipfile.ZipFile(temporary, "x", zipfile.ZIP_DEFLATED) as z:
            for n, (name, rows, widths) in enumerate(sheets, 1):
                ET.SubElement(sheet_nodes, "sheet", name=name, sheetId=str(n), attrib={"r:id": f"rId{n}"})
                ET.SubElement(relationships, "Relationship", Id=f"rId{n}", Type=REL + "/worksheet", Target=f"worksheets/sheet{n}.xml")
                ET.SubElement(types, "Override", PartName=f"/xl/worksheets/sheet{n}.xml", ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml")
                sheet = ET.Element("worksheet", xmlns=NS)
                ET.SubElement(sheet, "dimension", ref=f"A1:{column_name(max((len(r) for r in rows), default=1))}{max(1, len(rows))}")
                views = ET.SubElement(sheet, "sheetViews")
                view = ET.SubElement(views, "sheetView", workbookViewId="0")
                ET.SubElement(view, "pane", ySplit="1", topLeftCell="A2", activePane="bottomLeft", state="frozen")
                ET.SubElement(sheet, "sheetFormatPr", defaultRowHeight="32")
                cols = ET.SubElement(sheet, "cols")
                for col, width in enumerate(widths, 1):
                    ET.SubElement(cols, "col", min=str(col), max=str(col), width=str(width), customWidth="1")
                data = ET.SubElement(sheet, "sheetData")
                for rownum, values in enumerate(rows, 1):
                    row = ET.SubElement(data, "row", r=str(rownum), ht="32" if rownum == 1 else "58", customHeight="1")
                    for colnum, value in enumerate(values, 1):
                        if value is None:
                            continue
                        cell = ET.SubElement(row, "c", r=f"{column_name(colnum)}{rownum}", s="1" if rownum == 1 else "2")
                        if isinstance(value, (float, int)) and not isinstance(value, bool):
                            ET.SubElement(cell, "v").text = str(value)
                        else:
                            cell.set("t", "inlineStr")
                            text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value))
                            if len(text.encode("utf-16-le")) // 2 > 32767:
                                raise ValueError("Excel单元格超过32767字符；请拆分原文")
                            ET.SubElement(ET.SubElement(cell, "is"), "t", attrib={"xml:space": "preserve"}).text = text
                if rows:
                    ET.SubElement(sheet, "autoFilter", ref=f"A1:{column_name(len(rows[0]))}{len(rows)}")
                z.writestr(f"xl/worksheets/sheet{n}.xml", xml_bytes(sheet))
            ET.SubElement(relationships, "Relationship", Id="styles", Type=REL + "/styles", Target="styles.xml")
            for part, kind in [("workbook.xml", "sheet.main"), ("styles.xml", "styles")]:
                ET.SubElement(types, "Override", PartName="/xl/" + part, ContentType=f"application/vnd.openxmlformats-officedocument.spreadsheetml.{kind}+xml")
            z.writestr("[Content_Types].xml", xml_bytes(types))
            z.writestr("xl/workbook.xml", xml_bytes(book))
            z.writestr("xl/_rels/workbook.xml.rels", xml_bytes(relationships))
            z.writestr("xl/styles.xml", styles)
            z.writestr("_rels/.rels", f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        temporary.rename(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return path


def read_template(path):
    with zipfile.ZipFile(path) as z:
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        sheets = workbook.find(f"{{{NS}}}sheets")
        selected = next((s for s in sheets if s.get("name") in {"品牌明细", "品牌明细表"}), None)
        if selected is None:
            raise ValueError("模板中未找到“品牌明细”或“品牌明细表”工作表")
        relations = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = next(r.get("Target") for r in relations if r.get("Id") == selected.get(f"{{{REL}}}id"))
        part = target.lstrip("/") if target.startswith("/") else "xl/" + target
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            shared = ["".join(si.itertext()) for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
        doc = ET.fromstring(z.read(part))
        rows = doc.findall(f"{{{NS}}}sheetData/{{{NS}}}row")
        for row in rows[:20]:
            values = []
            for cell in row:
                col = re.match(r"[A-Z]+", cell.get("r", "A"))[0]
                number = 0
                for char in col:
                    number = number * 26 + ord(char) - 64
                while len(values) < number:
                    values.append("")
                value = cell.find(f"{{{NS}}}v")
                values[number - 1] = (shared[int(value.text)] if cell.get("t") == "s" else value.text or "") if value is not None else "".join(cell.itertext())
            if set(HEADERS).issubset(values):
                if any(not value for value in values) or len(values) != len(set(values)):
                    raise ValueError("模板表头有空列或重复字段")
                return values
    raise ValueError("模板未包含既有品牌明细的11个字段")


def mapping_rows(result):
    """每个细分业态的归并结果，用来核对"标准业态是查表来的还是内置归并来的"。"""
    rows = [["细分业态（对照表）", "标准业态（对照表）", "平台细分业态原文", "匹配方式", "记录数", "说明"]]
    stats = {}
    for row in result["records"]:
        key = (row["category_std"], row["group"], row["category"], row["match"], row.get("match_note", ""))
        stats[key] = stats.get(key, 0) + 1
    order = {method: index for index, method in enumerate(MATCH_METHODS)}
    for key in sorted(stats, key=lambda item: (order.get(item[3], 9), -stats[item], item[0])):
        standard, group, raw, method, note = key
        rows.append([standard, group, raw, method, stats[key], note])
    return rows


def allowed_groups_text(groups):
    """把对照表里的标准业态列成"可选值"，跟着表走，不写死。"""
    values = [str(group).strip() for group in (groups or []) if str(group).strip()]
    return "、".join(values) if values else "对照表里的标准业态"


def pending_rows(result):
    groups = (result.get("mapping") or {}).get("groups") or []
    reasons = result.get("pending_reason") or {}
    rows = [["平台细分业态原文", "记录数", "建议动作", "判定依据"]]
    for category, count in result.get("pending", []):
        rows.append([category, count, pending_action(category, reasons.get(category, ""), groups),
                     reasons.get(category) or "对照表和内置归并都没有命中"])
    return rows


def pending_action(category, reason, groups):
    if "同时对应" in reason or "对应多个" in reason:
        return (f"表里存在同名细分业态但标准业态不同，先改写细分业态名称（如“{category}（{allowed_groups_text(groups).split('、')[0]}）”）"
                f"或在表里区分写法，否则这类记录只能标{FALLBACK_GROUP}")
    if "服务设施" in reason:
        return "平台把设施当分类，不是独立品牌业态；确认后可保留原文，不必补表"
    return (f"在对照表补一行：细分业态={category}（或更细的名称），"
            f"标准业态取 {allowed_groups_text(groups)} 之一")


def write_result(path, result, headers=None):
    headers = headers or HEADERS
    details = [headers]
    reviews = [["品牌明细行号", "商户名称（原文）", "细分业态（原文）", "位置标签（原文）", "楼层标签（原文）", "待核事项", "原文定位"]]
    evidence = [["品牌明细行号", "商户原文片段", "原文定位"]]
    for n, row in enumerate(result["records"], 2):
        values = dict(zip(HEADERS, [result["quarter"], None, result["label"], row["name"], row["floor"], "大众点评小程序列表", row["group"], row["category_std"], None, "平台收录，经营状态待核", None]))
        details.append([values.get(h) for h in headers])
        if row["issues"]:
            reviews.append([n, row["name"], row["category"], row["locality"], row["floor_raw"], "；".join(row["issues"]), "；".join(row["sources"])])
        evidence.append([n, row["raw"], "；".join(row["sources"])])
    for issue in result["issues"]:
        reviews.append([None, "整次采集", None, None, None, issue, result["source"]])
    info = result.get("mapping") or {}
    notes = [["项目", "内容"], ["项目名称/采集标签", result["label"]], ["来源", result["source"]],
             ["采集时间", result["captured_at"]], ["数据季度", result["quarter"]],
             ["解析记录数", len(result["records"])], ["平台显示数", result["platform_count"]],
             ["快照数", result["snapshot_count"]], ["底部提示", "已检测" if result["bottom_confirmed"] else "未确认"],
             ["项目身份", "标签与主页文字匹配，仍需核对项目边界" if result["identity_verified"] else "仅采用标签，归属待核"],
             ["业态对照表", info.get("description", "内置对照")],
             ["对照表来源", info.get("source", "内置对照")],
             ["对照表指纹", info.get("fingerprint") or "—"],
             ["标准业态", "、".join(info.get("groups") or []) or "—"],
             ["业态命中率", f"{info.get('matched_ratio'):.1%}" if info.get("matched_ratio") is not None else "—"],
             ["业态匹配方式", "；".join(f"{k}{v}条" for k, v in (info.get("methods") or {}).items()) or "—"],
             ["合并口径", "相同店名、楼层标签、分类、位置标签按快照合并；同一快照重复记录保留；同名不同楼层不合并。"],
             ["名称口径", "保留平台展示原文，不自动补全截断店名；记录数不等于独立品牌数。"],
             ["业态口径", "细分业态按对照表标准化；未在表内且无法归并的保留平台原文，标准业态标其他/待复核，并列入“业态待补清单”。"],
             ["匹配顺序", "表内精确 → 表内别名列 → 内置别名 → 内置关键词 → 其他/待复核；逐条可查“业态映射”工作表。"],
             ["缺失字段", "项目编号、是否奢侈品、官网链接及自定义字段缺少证据时留空。"],
             ["数据边界", "平台收录不证明在营或开闭店；底部提示不证明完整；历史文档只保存在原始文本，不直接解析。"],
             ["软件耗时/费用", "见批次索引；本工具离线运行，不调用模型/API。开发和人工整理费用不在此计量。"],
             ["原文保存", "原始文本按文档和快照分块；Excel不允许的控制字符会过滤，原始采集文件保持不动。"]]
    if result.get("mapping", {}).get("warnings"):
        notes.append(["对照表提示", "；".join(result["mapping"]["warnings"])])
    raw = [["快照", "文档", "文档名", "分块", "原文"]]
    for snap, doc, name, text in result["raw_texts"]:
        for offset in range(0, max(1, len(text)), 14000):
            raw.append([snap, doc, name, offset // 14000 + 1, text[offset:offset + 14000]])
    widths = {"品牌名称": 57, "项目名称": 32, "楼层来源": 27, "经营状态": 32, "四大业态--更细划分": 25, "细分业态": 25, "楼层": 26}
    sheets = [("品牌明细", details, [widths.get(h, 18) for h in headers]),
              ("待复核记录", reviews, [18, 57, 25, 24, 30, 65, 65]),
              ("采集说明", notes, [28, 115]), ("记录来源", evidence, [18, 80, 80]),
              (MAPPING_SHEET, mapping_rows(result), [28, 22, 30, 14, 10, 55])]
    if result.get("pending"):
        sheets.append((PENDING_SHEET, pending_rows(result), [32, 10, 66, 46]))
    sheets.append(("原始文本", raw, [10, 10, 28, 10, 110]))
    return write_xlsx(path, sheets)


def decode_json(data):
    return json.loads(data.decode("utf-8-sig"))


def capture_folder_label(name):
    return re.sub(r'^\d{8}_\d{6}_\d{6}_(?=.)', '', name)


def discover_sources(inputs):
    found = []
    for item in inputs:
        path = Path(item).expanduser().resolve()
        if path.is_dir():
            captures = sorted(path.rglob("capture.json"))
            found.extend(captures if captures else sorted(path.rglob("当前文档文本.txt")))
        elif path.is_file():
            found.append(path)
        else:
            raise FileNotFoundError(f"输入不存在：{path}")
    return list(dict.fromkeys(found))


def read_session(path):
    if path.stat().st_size > MAX_INPUT:
        raise ValueError("单个输入文件超过128MB，请分批导入")
    if path.suffix.lower() == ".txt":
        data = path.read_bytes()
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("gb18030")
        label = capture_folder_label(path.parent.name)
        return label, [dict(documents=[dict(name=path.name, text=text)], primary_document_index=0)], str(path)
    record = decode_json(path.read_bytes())
    if isinstance(record, list):
        return capture_folder_label(path.parent.name), [dict(documents=record)], str(path)
    if not isinstance(record, dict):
        raise ValueError("JSON必须是采集记录或文档数组")
    label = capture_folder_label(path.parent.name)
    snapshots = []
    if path.name == "capture.json":
        for raw in sorted(path.parent.glob("raw-*.json")):
            if raw.stat().st_size > MAX_INPUT:
                raise ValueError("原始快照超过128MB")
            snapshots.append(decode_json(raw.read_bytes()))
        jsonl = path.parent / "滚动文本快照.jsonl"
        if not snapshots and jsonl.exists():
            if jsonl.stat().st_size > MAX_INPUT:
                raise ValueError("快照合集超过128MB，请分批导入")
            snapshots = [json.loads(line) for line in jsonl.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    return label, snapshots or [record], str(path)


def zip_sessions(path):
    with zipfile.ZipFile(path) as z:
        members = z.namelist()
        captures = sorted(n for n in members if PurePosixPath(n).name == "capture.json")
        if not captures:
            raise ValueError("ZIP中没有capture.json；请导入采集器导出的ZIP")
        if sum(info.file_size for info in z.infolist()) > 512 * 1024 * 1024:
            raise ValueError("ZIP解压后超过512MB，请分批导入")
        for member in captures:
            source = f"{path} :: {member}"
            parent = PurePosixPath(member).parent
            label = capture_folder_label(parent.name or path.stem)
            try:
                if z.getinfo(member).file_size > MAX_INPUT:
                    raise ValueError("采集记录超过128MB")
                record = decode_json(z.read(member))
                raws = sorted(n for n in members if PurePosixPath(n).parent == parent and re.fullmatch(r"raw-\d+\.json", PurePosixPath(n).name))
                if any(z.getinfo(n).file_size > MAX_INPUT for n in raws):
                    raise ValueError("原始快照超过128MB")
                snapshots = [decode_json(z.read(n)) for n in raws]
                jsonl = str(parent / "滚动文本快照.jsonl")
                if not snapshots and jsonl in members:
                    snapshots = [json.loads(line) for line in z.read(jsonl).decode("utf-8-sig").splitlines() if line.strip()]
                yield label, snapshots or [record], source, None
            except Exception as exc:
                yield label, [], source, str(exc)


def program_dirs():
    """EXE/脚本所在目录：业态对照表默认放在这里。

    打包后 __file__ 指向解包临时目录 _MEIxxxx，那里不会有用户维护的表，
    所以冻结时只认 EXE 所在目录。
    """
    if getattr(sys, "frozen", False):
        return [Path(sys.executable).resolve().parent]
    return [Path(__file__).resolve().parent]


def resolve_mapping(mapping_path=None, inputs=(), destination=None):
    """确定本次使用的业态对照表：显式指定 > 自动发现最新 > 内置四类。"""
    if mapping_path is not None and not isinstance(mapping_path, (str, Path)):
        table = coerce_mapping(mapping_path)
        return table, str(table.source or "调用方传入"), "调用方传入的对照表", []
    hints = program_dirs() + [destination] + [Path(item) for item in inputs]
    table, path, note, candidates = discover_table(hints, explicit=mapping_path)
    if table is None:
        return default_mapping(), "内置对照", note, candidates
    return table, str(path), note, candidates


def load_mapping(path=None):
    """读取指定对照表；path 为空时用内置四类业态。"""
    if not path:
        return default_mapping()
    if isinstance(path, (str, Path)) and not Path(path).exists():
        raise FileNotFoundError(f"业态对照表不存在：{path}")
    return read_table(path) if isinstance(path, (str, Path)) else coerce_mapping(path)


def save_mapping(path, mapping=None):
    return save_mapping_table(path, mapping)


def batch_export(inputs, destination, template=None, mapping_path=None, progress=None):
    started = time.monotonic()
    headers = read_template(template) if template else HEADERS
    mapping, mapping_source, mapping_note, mapping_candidates = resolve_mapping(mapping_path, inputs, destination)
    sources = discover_sources(inputs)
    if not sources:
        raise ValueError("未找到采集记录；请选择包含capture.json的目录、ZIP或当前文档TXT")
    folder = Path(destination) / (datetime.now().strftime("批量业态明细_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6])
    folder.mkdir(parents=True, exist_ok=False)
    index_rows, outputs, pending_total = [], [], Counter()
    pending_reasons = {}
    def process(label, snapshots, source, error=None):
        if progress:
            progress(f"正在整理：{label}")
        try:
            if error:
                raise ValueError(error)
            result = convert_session(label, snapshots, mapping, source)
            for category, count in result.get("pending", []):
                pending_total[category] += count
            for category, reason in (result.get("pending_reason") or {}).items():
                pending_reasons.setdefault(category, reason)
            filename = f"{len(index_rows) + 1:03d}_{safe_slug(label)}_品牌业态明细.xlsx"
            path = write_result(folder / filename, result, headers)
            outputs.append(str(path))
            write_json(path.with_suffix(".json"), {k: v for k, v in result.items() if k != "raw_texts"})
            ratio = result["mapping"].get("matched_ratio")
            ratio_text = "—" if ratio is None else f"{ratio:.1%}"
            status = "未识别商户，仅保留原文待核" if not result["records"] else ("已生成（有待核事项）" if result["issues"] or any(r["issues"] for r in result["records"]) else "已生成（仍需核对经营状态）")
            index_rows.append([label, len(result["records"]), result["platform_count"], result["snapshot_count"], status, filename, source, "；".join(result["issues"]), ratio_text])
        except Exception as exc:
            index_rows.append([label, None, None, None, "失败，原始文件保留", "", source, str(exc), "—"])
    for path in sources:
        try:
            if path.suffix.lower() == ".zip":
                for args in zip_sessions(path):
                    process(*args)
            else:
                process(*read_session(path))
        except Exception as exc:
            process(path.stem, [], str(path), str(exc))
    elapsed = round(time.monotonic() - started, 3)
    index = folder / "批次索引.xlsx"
    index_headers = ["采集标签/商场", "解析记录数", "平台显示数", "快照数", "处理状态", "结果文件", "来源", "待核事项/错误", "业态命中率"]
    notes = [["项目", "内容"], ["批量转换耗时（秒）", elapsed], ["本次模型API Token", 0], ["本次模型API费用", 0],
             ["计量边界", "只统计本机批量转换；不含前期采集、软件开发及后续人工整理。"],
             ["模板", str(template or "内置品牌明细11字段")],
             ["业态对照表", mapping.describe()],
             ["对照表位置", mapping_source],
             ["对照表识别方式", mapping_note],
             ["对照表指纹", mapping.fingerprint or "—"],
             ["标准业态", "、".join(mapping.groups) or "—"],
             ["对照表提示", "；".join(mapping.warnings) if mapping.warnings else "无"],
             ["换表说明", "改完对照表（CSV 或 XLSX）直接重新整理即可；程序取所在目录里修改时间最新的一份，不需要改代码或重新安装。"],
             ["未匹配处理", f"未在表中的细分业态保留平台原文，标准业态标{FALLBACK_GROUP}，汇总在“{PENDING_SHEET}”工作表，补进对照表后重新整理即可。"],
             ["异常处理", "失败记录和未识别内容保留；不代表零商户。"],
             ["快照口径", "不同采集记录分别输出，避免跨日期合并；商场标签相同也不覆盖。"]]
    index_sheets = [("批次索引", [index_headers, *index_rows], [35, 18, 18, 14, 38, 65, 80, 100, 14]),
                    ("处理说明", notes, [32, 110])]
    if pending_total:
        index_sheets.append((PENDING_SHEET,
                             [["平台细分业态原文", "记录数", "建议动作", "判定依据"]]
                             + [[category, count,
                                 pending_action(category, pending_reasons.get(category, ""), mapping.groups),
                                 pending_reasons.get(category) or "对照表和内置归并都没有命中"]
                                for category, count in pending_total.most_common()],
                             [30, 10, 66, 46]))
    write_xlsx(index, index_sheets)
    with (folder / "批次索引.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(index_headers)
        writer.writerows([[csv_literal(v if v is not None else "") for v in row] for row in index_rows])
    if pending_total:
        with (folder / f"{PENDING_SHEET}.csv").open("x", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["细分业态", "标准业态", "记录数", "说明"])
            for category, count in pending_total.most_common():
                writer.writerow([category, FALLBACK_GROUP, count,
                                 pending_action(category, pending_reasons.get(category, ""), mapping.groups)])
    report = dict(folder=str(folder), index=str(index), outputs=outputs, success_count=len(outputs),
                  error_count=sum(r[4].startswith("失败") for r in index_rows), elapsed_seconds=elapsed,
                  mapping=dict(description=mapping.describe(), source=mapping_source, note=mapping_note,
                               fingerprint=mapping.fingerprint or "", groups=list(mapping.groups),
                               warnings=list(mapping.warnings),
                               candidates=[str(item) for item in mapping_candidates],
                               pending=dict(pending_total.most_common())))
    write_json(folder / "批次报告.json", report)
    return report
