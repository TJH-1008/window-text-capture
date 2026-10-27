"""Read-only roster import with an exact source filter.

默认按原始数据库模板取数：工作表''成都市综合体原始清单''、来源列的取值等于 SOURCE_VALUE。
换项目时只改这两个常量即可，其他代码不用动。
"""
import csv
import hashlib
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

from capture_core import csv_literal, write_json
from excel_import import NS, REL, write_xlsx

RAW_SHEET = '成都市综合体原始清单'
SOURCE_VALUE = '商务局'
ROSTER_FILE = f'{SOURCE_VALUE}商场采集清单.xlsx'
ROSTER_QUEUE = f'{SOURCE_VALUE}商场采集队列.json'


def search_queries(item):
    name, district = item['name'].strip(), item.get('district', '').strip()
    alias = item.get('alias', '').strip()
    values = [f'{name} {district}'.strip()]
    if alias and alias != name:
        values.append(f'{alias} {district}'.strip())
    return list(dict.fromkeys(values))


def worksheet_values(path, sheet_name):
    with zipfile.ZipFile(path) as archive:
        book = ET.fromstring(archive.read('xl/workbook.xml'))
        selected = next((s for s in book.find(f'{{{NS}}}sheets') if s.get('name') == sheet_name), None)
        if selected is None:
            raise ValueError(f'未找到工作表：{sheet_name}')
        relations = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        target = next(r.get('Target') for r in relations if r.get('Id') == selected.get(f'{{{REL}}}id'))
        part = target.lstrip('/') if target.startswith('/') else 'xl/' + target
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared = [''.join(node.itertext()) for node in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
        root = ET.fromstring(archive.read(part))
        result = []
        for row in root.findall(f'{{{NS}}}sheetData/{{{NS}}}row'):
            values = []
            for cell in row:
                number = 0
                for char in re.match(r'[A-Z]+', cell.get('r', 'A'))[0]:
                    number = number * 26 + ord(char) - 64
                while len(values) < number:
                    values.append('')
                value = cell.find(f'{{{NS}}}v')
                if cell.get('t') == 's' and value is not None:
                    content = shared[int(value.text)]
                elif value is not None:
                    content = value.text or ''
                else:
                    content = ''.join(cell.itertext())
                values[number - 1] = content
            result.append((int(row.get('r')), values))
        return result


def load_roster(path):
    path = Path(path).resolve()
    sheet = RAW_SHEET
    rows = worksheet_values(path, sheet)
    if not rows:
        raise ValueError('原始清单为空')
    headers = rows[0][1]
    if not {'来源', '行政区域', '项目名称'}.issubset(headers):
        raise ValueError('原始清单缺少来源、行政区域或项目名称字段')
    def field(row, header):
        if header not in headers:
            return ''
        index = headers.index(header)
        return str(row[index]).strip() if index < len(row) else ''
    sources, items = Counter(), []
    for rownum, row in rows[1:]:
        if not any(row):
            continue
        source = field(row, '来源')
        sources[source] += 1
        if source != SOURCE_VALUE:
            continue
        name = field(row, '项目名称')
        if not name:
            raise ValueError(f'{SOURCE_VALUE}第{rownum}行缺少项目名称')
        items.append(dict(task_id=f'commerce-row-{rownum}', name=name, district=field(row, '行政区域'),
                          address=next((field(row, h) for h in ('项目地址', '地址', '详细地址') if field(row, h)), ''),
                          source=source, source_row=rownum, source_sheet=sheet, source_file=str(path),
                          assessment=field(row, '审核判定'), note=field(row, '判定说明'), alias='', status='待采集'))
    if not items:
        raise ValueError(f'未找到来源等于{SOURCE_VALUE}的记录')
    return dict(source_file=str(path), source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                sheet=sheet, filter=f'来源去除首尾空格后精确等于{SOURCE_VALUE}；不按审核判定额外筛选',
                total_rows=sum(sources.values()), sources=dict(sources), count=len(items), items=items,
                duplicates=[n for n,c in Counter(i['name'] for i in items).items() if c > 1])


def load_task_list(path):
    path = Path(path).resolve()
    if path.suffix.lower() == '.xlsx':
        with zipfile.ZipFile(path) as archive:
            book = ET.fromstring(archive.read('xl/workbook.xml'))
            sheets = [s.get('name') for s in book.find(f'{{{NS}}}sheets')]
        if RAW_SHEET in sheets:
            return load_roster(path)
        sheet = '采集清单' if '采集清单' in sheets else sheets[0]
        rows = worksheet_values(path, sheet)
    elif path.suffix.lower() == '.csv':
        sheet = 'CSV'
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(enumerate(csv.reader(stream), 1))
    else:
        raise ValueError('清单支持xlsx和UTF-8 CSV')
    if not rows:
        raise ValueError('清单为空')
    headers = [str(h).strip() for h in rows[0][1]]
    def get(row, *options):
        for name in options:
            if name in headers:
                index = headers.index(name)
                if index < len(row):
                    return str(row[index]).strip()
        return ''
    if not {'商场名称', '项目名称'} & set(headers):
        raise ValueError('清单需要商场名称或项目名称列')
    items, sources = [], Counter()
    for rownum, values in rows[1:]:
        if not any(values):
            continue
        source = get(values, '来源') if '来源' in headers else '用户提供'
        sources[source] += 1
        if '来源' in headers and source != SOURCE_VALUE:
            continue
        name = get(values, '商场名称', '项目名称')
        if not name:
            raise ValueError(f'第{rownum}行缺少商场名称')
        original_row = get(values, '原表行号')
        if original_row and not original_row.isdigit():
            raise ValueError(f'第{rownum}行的原表行号不是正整数')
        items.append(dict(task_id=get(values, '任务编号') or f'list-row-{rownum}', name=name, district=get(values, '行政区域', '所在区', '区县'),
                          address=get(values, '地址', '项目地址', '详细地址'), alias=get(values, '搜索别名'),
                          source=source, source_row=int(original_row) if original_row else rownum, source_sheet=sheet, source_file=str(path),
                          assessment=get(values, '审核判定', '原审核判定'), note=get(values, '判定说明', '原判定说明'), status='待采集'))
    if not items:
        raise ValueError('没有符合条件的商场')
    if len({i['task_id'] for i in items}) != len(items):
        raise ValueError('清单任务编号重复，请使用唯一编号')
    return dict(source_file=str(path), source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                sheet=sheet, filter=f'有来源列时精确筛选{SOURCE_VALUE}；无来源列时采用用户提供的全清单',
                total_rows=sum(sources.values()), sources=dict(sources), count=len(items), items=items,
                duplicates=[n for n,c in Counter(i['name'] for i in items).items() if c > 1])


def export_roster(roster, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    headers = ['任务编号', '来源', '原表行号', '商场名称', '行政区域', '地址', '搜索别名', '原审核判定', '原判定说明', '采集状态']
    rows = [[i['task_id'], i['source'], i['source_row'], i['name'], i['district'], i['address'], i['alias'], i['assessment'], i['note'], i['status']] for i in roster['items']]
    file = folder / ROSTER_FILE
    write_xlsx(file, [('采集清单', [headers, *rows], [24, 16, 16, 52, 20, 40, 40, 28, 65, 24]),
                      ('筛选说明', [['项目', '内容'], ['来源文件', roster['source_file']], ['原表', roster['sheet']], ['筛选条件', roster['filter']], ['原始记录数', roster['total_rows']], [f'{SOURCE_VALUE}记录数', roster['count']], ['来源统计', str(roster['sources'])], ['名称重复', '；'.join(roster['duplicates']) or '无'], ['地址说明', '原始清单无地址字段时留空，搜索时结合行政区域核对；泛称和同名项目待确认。'], ['源文件SHA256', roster['source_sha256']]], [28, 115])])
    with (folder / ROSTER_FILE.replace('.xlsx', '.csv')).open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows([[csv_literal(x) for x in row] for row in rows])
    write_json(folder / ROSTER_QUEUE, roster)
    return file
