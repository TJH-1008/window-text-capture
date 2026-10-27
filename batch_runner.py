"""Resumable roster runner; UI navigation is bounded and conservatively matched."""
import json
import re
import time
from datetime import datetime
from pathlib import Path

from capture_core import safe_slug, write_json
from excel_import import META, clean_lines, write_xlsx
from navigation import action, primary_text
from roster import search_queries


class BatchStopped(RuntimeError):
    pass


class NavigationError(ValueError):
    """A target-specific navigation failure that must pause the queue."""


def normalized(value):
    return re.sub(r'[\W_]+', '', str(value)).lower()


def names_for(item):
    return [value for value in [item['name'], item.get('alias', '')] if value]


def candidate_names(text, item):
    lines = [line for _, line in clean_lines(text)]
    found = []
    for index, line in enumerate(lines):
        if line not in {'商场', '购物中心', '百货商场'} or index == 0:
            continue
        name_index = index - 1
        while name_index >= 0 and META.fullmatch(lines[name_index]):
            name_index -= 1
        if name_index < 0:
            continue
        name = lines[name_index]
        if any(normalized(expected) in normalized(name) for expected in names_for(item)):
            found.append(name)
    return list(dict.fromkeys(found))


def verify_identity(text, item, matched_candidate=''):
    prefix = text.split('输入商户名')[0]
    prefix = re.split(r'全部\s*[（(]\s*\d+|查看全部网友评价|发笔记|写评价', prefix)[0]
    lines = [line for _, line in clean_lines(prefix)]
    # A tenant name, nearby-mall recommendation, or review is not project identity.
    heading = '\n'.join(lines[:10])
    name_match = any(normalized(name) in normalized(heading) for name in names_for(item))
    service = prefix.split('商场服务', 1)[-1] if '商场服务' in prefix else ''
    address_section = service.split('商场专享特惠')[0].split('推荐')[0]
    district = item.get('district', '').strip()
    address = item.get('address', '').strip()
    district_match = bool(district and district in address_section)
    address_match = bool(address and normalized(address) in normalized(address_section))
    districts = ('锦江区', '青羊区', '金牛区', '武侯区', '成华区', '龙泉驿区', '青白江区',
                 '新都区', '温江区', '双流区', '郫都区', '新津区', '金堂县', '大邑县',
                 '蒲江县', '都江堰市', '彭州市', '邛崃市', '崇州市', '简阳市')
    other_districts = [value for value in districts if value in address_section and value != district]
    explicit_conflict = bool((address and address_section and not address_match)
                             or (district and other_districts and not district_match))
    geography_status = 'verified' if (district_match or address_match) else 'unresolved'
    # A unique, exact mall result is sufficient to continue when the platform
    # omits the district/address. Explicit address conflicts remain blocking.
    exact_candidate = bool(matched_candidate and any(normalized(line) == normalized(matched_candidate)
                                                    for line in lines[:10]))
    street_address = bool(re.search(r'(?:路|街|道|巷).{0,25}\d+\s*号', address_section))
    verified = name_match and '商场服务' in text and not explicit_conflict and bool(
        district_match or address_match or (exact_candidate and street_address and not address))
    return dict(verified=bool(verified), name_match=name_match, district_match=district_match,
                address_match=address_match, identity_text=prefix[:4000],
                geography_status=geography_status,
                explicit_conflict=explicit_conflict,
                reason='' if verified else '商场名称或地址/行政区域未可靠匹配，待确认')


def run_queue(roster, checkpoint, capture, stopped, progress=None, changed=None,
              *, start_task_id=None, single=False):
    start_index = 0
    if start_task_id is not None:
        start_index = next((i for i, item in enumerate(roster['items'])
                            if item.get('task_id') == start_task_id), None)
        if start_index is None:
            raise ValueError('选中的起点不在当前清单中，请重新选择。')
    progress = progress or (lambda text: None)
    changed = changed or (lambda item: None)
    halted = False
    for index, item in enumerate(roster['items'], 1):
        if index <= start_index:
            continue
        if item.get('status') not in {'待采集', '采集中'}:
            continue
        if stopped():
            halted = True
            break
        item.update(status='采集中', last_error='')
        write_json(checkpoint, roster)
        changed(item)
        progress(f"{index}/{len(roster['items'])} 正在查询：{item['name']}（{item.get('district', '')}）")
        try:
            result = capture(item)
            if result.get('stopped'):
                raise BatchStopped(result.get('stop_reason', '用户停止'))
            item.update(status='已保存（待复核）', result=result, completed_at=datetime.now().astimezone().isoformat())
        except BatchStopped as exc:
            item.update(status='待采集', last_error=str(exc))
            halted = True
        except NavigationError as exc:
            item.update(status='待确认', last_error=str(exc))
            halted = True
        except Exception as exc:
            item.update(status='待确认', last_error=str(exc))
        write_json(checkpoint, roster)
        changed(item)
        if halted or single:
            break
    return dict(stopped=halted, saved=sum(i.get('status') == '已保存（待复核）' for i in roster['items']),
                review=sum(i.get('status') == '待确认' for i in roster['items']),
                pending=sum(i.get('status') == '待采集' for i in roster['items']))


def export_progress(roster, folder):
    folder = Path(folder)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    path = folder / f'任务进度_{stamp}.xlsx'
    rows = [['原表行号', '商场名称', '行政区域', '来源', '任务状态', '异常原因', '数据目录']]
    for item in roster['items']:
        rows.append([item.get('source_row'), item['name'], item.get('district', ''), item.get('source', ''),
                     item['status'], item.get('last_error', ''), item.get('result', {}).get('folder', '')])
    write_xlsx(path, [('任务进度', rows, [16, 52, 20, 16, 28, 90, 100])])
    return path


class MallNavigator:
    def __init__(self, handle, evidence, stopped=lambda: False, progress=None, transport=None):
        self.handle = handle
        self.evidence = Path(evidence)
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.stopped = stopped
        self.progress = progress or (lambda text: None)
        self.transport = transport or action
        self.step = 0
        self.action_step = 0

    def command(self, mode, **kwargs):
        if self.stopped():
            raise BatchStopped('用户停止')
        record = dict(action=mode, parameters=kwargs, started_at=datetime.now().astimezone().isoformat())
        record_path = self.evidence / f'action-{self.action_step:03d}.json'
        self.action_step += 1
        try:
            result = self.transport(self.handle, mode, **kwargs)
            record['ok'] = True
            return result
        except Exception as exc:
            record.update(ok=False, error=str(exc))
            if any(word in str(exc) for word in ('失去焦点', '已关闭', 'Esc停止')):
                raise BatchStopped(str(exc)) from exc
            raise
        finally:
            write_json(record_path, record)

    def inspect(self):
        snap = self.command('inspect')
        write_json(self.evidence / f'page-{self.step:03d}.json', snap)
        self.step += 1
        text = primary_text(snap)
        if any(word in text[:2000] for word in ('安全验证', '请完成验证', '访问过于频繁', '拖动滑块')):
            raise BatchStopped('页面要求验证或限制访问；已保存当前页面，请人工处理后继续')
        return text

    def wait(self, predicate, attempts=4, stage='目标页面'):
        text = ''
        for _ in range(attempts):
            if self.stopped():
                raise BatchStopped('用户停止')
            time.sleep(.7)
            text = self.inspect()
            if predicate(text):
                return text
        raise ValueError(f'等待{stage}超时；已保存页面证据：{self.evidence}')

    @staticmethod
    def search_editor(text):
        head = text[:700]
        return '筛选' not in head and any(word in head for word in ('取消', '最近搜索', '搜索历史'))

    def search(self, query):
        for _ in range(6):
            text = self.inspect()
            if '商场服务' in text or '全部楼层' in text:
                self.command('back')
                time.sleep(.5)
                continue
            header = next((line for _, line in clean_lines(text)), '')
            self.progress('定位搜索输入框')
            if self.search_editor(text):
                if header and header not in {'取消', '最近搜索', '搜索历史'}:
                    self.command('click', text=header)
            else:
                if '筛选' in text and '全部分类' in text:
                    if not header or header in {'商户', '全城', '全部分类', '筛选'}:
                        raise ValueError('未识别到当前搜索栏文字，已保存页面')
                    self.command('click', text=header)
                else:
                    self.command('click', text='搜索')
                self.wait(self.search_editor, stage='搜索输入页')
            self.progress('输入并核对搜索词：' + query)
            self.command('type', text=query)
            self.wait(lambda t: self.search_editor(t) and normalized(query) in normalized(t[:300]), stage='搜索词回读')
            self.command('key', key=13)
            self.progress('等待本次搜索结果')
            return self.wait(lambda t: normalized(query) in normalized(t[:500]) and '筛选' in t and '全部分类' in t and '商场服务' not in t, stage='本次搜索结果')
        raise ValueError('无法返回可识别的搜索入口，已保存页面；需要首次页面适配')

    def click_mall_result(self, candidate):
        failures = []
        for attempt in range(1, 4):
            if attempt > 1:
                text = self.inspect()
                if not ('筛选' in text and '全部分类' in text and normalized(candidate) in normalized(text)):
                    raise ValueError('商场结果点击后页面已变化，停止重试以避免误点其他内容')
                self.progress(f'重新定位商场结果并重试点击（{attempt}/3）')
                time.sleep(.35)
            try:
                self.command('click', text=candidate, after='筛选')
            except BatchStopped:
                raise
            except (RuntimeError, ValueError) as exc:
                failures.append(str(exc))
                continue
            try:
                return self.wait(lambda text: '商场服务' in text, attempts=3, stage='商场主页')
            except ValueError as exc:
                failures.append(str(exc))
                current = self.inspect()
                if '商场服务' in current:
                    return current
                if not ('筛选' in current and '全部分类' in current and normalized(candidate) in normalized(current)):
                    raise ValueError('点击后页面不再是商场搜索结果，停止重试；' + str(exc)) from exc
        raise ValueError('商场名称连续3次未能点击；已重新读取页面并保留证据。最后错误：' + (failures[-1] if failures else '未知'))

    def open_mall(self, item):
        try:
            return self._open_mall(item)
        except (NavigationError, BatchStopped):
            raise
        except (ValueError, RuntimeError) as exc:
            raise NavigationError(str(exc)) from exc

    def _open_mall(self, item):
        for query in search_queries(item):
            self.progress('搜索：' + query)
            text = self.search(query)
            candidates = candidate_names(text, item)
            if len(candidates) != 1:
                if len(candidates) > 1:
                    raise ValueError('搜索结果不唯一：' + '；'.join(candidates) + '。请补充地址或搜索别名')
                continue
            self.command('top')
            identity_text = self.click_mall_result(candidates[0])
            identity = verify_identity(identity_text, item, matched_candidate=candidates[0])
            write_json(self.evidence / 'identity-check.json', identity)
            if not identity['verified']:
                raise ValueError(identity['reason'])
            if identity['geography_status'] == 'unresolved':
                self.progress('商场名称精确匹配，主页街道地址已记录；行政区未展示，地理归属待复核')
            self.progress('已匹配商场，打开全部商户：' + item['name'])
            entry = re.search(r'查看全部\s*\d+\s*家门店', identity_text)
            if not entry:
                raise ValueError('未找到全部门店列表入口，已保留商场主页')
            count = re.search(r'查看全部\s*(\d+)\s*家门店', entry.group())
            identity['expected_store_count'] = int(count.group(1)) if count else None
            write_json(self.evidence / 'identity-check.json', identity)
            self.command('click', text=entry.group())
            self.wait(lambda t: re.search(r'输入商户名.{0,30}找优惠', t, re.S) is not None
                      and '全部楼层' in t and '全部分类' in t, stage='全部商户列表')
            return identity
        raise ValueError('未找到唯一匹配的商场结果；请补充地址或搜索别名')
