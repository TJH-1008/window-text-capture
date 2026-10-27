"""Windows accessible-window text capture GUI. Standard library only."""

import argparse
import csv
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from capture_core import build_capture, create_capture_folder, csv_literal, export_archive, safe_slug, write_json
from biz_mapping import discover_table, save_mapping as save_mapping_table
from excel_import import batch_export, program_dirs, resolve_mapping, save_mapping
from roster import ROSTER_FILE, SOURCE_VALUE, load_task_list
from batch_runner import BatchStopped, MallNavigator, export_progress, run_queue
from navigation import action as navigate_action
from workspace_ui import VERSION, Tooltip, WorkspaceUI

HOME = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
RESOURCES = Path(getattr(sys, "_MEIPASS", HOME))
POWERSHELL = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe")
READER = RESOURCES / "window_reader.ps1"


def reader_command(*arguments):
    return [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(READER), *map(str, arguments)]


def capture_reader_arguments(handle, folder, stop_file, steps, wait, auto_scroll, final_only,
                             *, profile='mall', direction='down'):
    args = ["-Mode", "capture", "-WindowHandle", str(handle), "-SaveDirectory", str(folder),
            "-StopFile", str(stop_file), "-MaximumSteps", str(steps), "-WaitMilliseconds", str(wait)]
    if profile == 'general':
        args.extend(['-CaptureProfile', 'general', '-ScrollDirection', direction])
    if auto_scroll:
        args.append("-AutoScroll")
        if final_only and profile != 'general':
            args.append("-FinalOnly")
    return args


def run_reader(arguments, on_event=None, timeout=60):
    process = subprocess.Popen(reader_command(*arguments), stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise RuntimeError("窗口接口未响应，已结束本次读取。") from None
    events = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(event)
        if on_event:
            on_event(event)
    if process.returncode:
        errors = [str(e["data"]) for e in events if e.get("kind") == "error"]
        raise RuntimeError("\n".join(errors) or stderr.strip() or "窗口读取失败")
    return events


def finalize_capture(folder, label, stop_reason="", elapsed=0):
    folder = Path(folder)
    raw_files = sorted(folder.glob("raw-*.json"))
    if not raw_files:
        raise ValueError("没有取得可读文本；未生成成功记录")
    latest = json.loads(raw_files[-1].read_text(encoding="utf-8-sig"))
    result = build_capture(label, latest["window_title"], latest["window_handle"], latest["documents"], latest["captured_at"], latest.get("primary_document_index"))
    collection_mode = latest.get("collection_mode", "stepwise")
    bottom_stable = bool(latest.get("bottom_stable", result["bottom_confirmed"]))
    result["bottom_marker_present"] = result["bottom_confirmed"]
    result["bottom_confirmed"] = bool(latest.get("bottom_confirmed", result["bottom_confirmed"]))
    if collection_mode == "final_only":
        result["bottom_confirmed"] = result["bottom_confirmed"] and bottom_stable
    if collection_mode == "final_only":
        result["capture_status"] = ("已读取最终窗口文本；检测到底部提示且文本稳定"
                                    if result["bottom_confirmed"] else "已读取最终窗口文本；底部或内容稳定状态未确认")
    result.update(raw_snapshot_count=len(raw_files), collection_mode=collection_mode, bottom_stable=bottom_stable,
                  stop_reason=stop_reason, elapsed_seconds=round(elapsed, 3), finished_at=datetime.now().astimezone().isoformat())
    if latest.get('capture_profile') == 'general':
        snapshots = [json.loads(file.read_text(encoding='utf-8-sig')) for file in raw_files]
        limited = any(snap.get('coverage', {}).get('truncated') or snap.get('coverage', {}).get('read_errors') or
                      snap.get('coverage', {}).get('unreadable_documents') for snap in snapshots)
        result.update(capture_profile='general', scroll_direction=latest.get('scroll_direction', 'down'),
                      coverage=latest.get('coverage', {}), coverage_limited=bool(limited),
                      bottom_confirmed=False, bottom_stable=False, bottom_marker_present=False,
                      capture_status='已保存通用窗口可访问文本；完整性未确认',
                      warning='仅包含目标窗口已加载且可访问的文字；可能包含菜单、按钮和重复内容。未加载历史、图片和画布不保证可读。' +
                              (' 部分快照达到读取限制、正文不可读或控件读取失败，请查看原始JSON；浏览器可尝试开启辅助功能后重读。' if limited else ''),
                      combined_text_file='滚动汇总文本.txt')
        with (folder / '滚动汇总文本.txt').open('w', encoding='utf-8-sig') as stream:
            for number, snap in enumerate(snapshots, 1):
                stream.write(f"--- 快照 {number} | {snap.get('captured_at', '')} | {snap.get('scroll_direction', 'down')} ---\n")
                stream.write('\n'.join(doc.get('text', '') for doc in snap.get('documents', []) if doc.get('text')) + '\n\n')
    if not result["all_text"]:
        raise ValueError("窗口返回空文本")
    write_json(folder / "capture.json", result)
    (folder / "原始页面文本.txt").write_text(result["all_text"], encoding="utf-8-sig")
    primary_index = result.get("primary_document_index")
    primary_text = latest["documents"][primary_index]["text"] if primary_index is not None and primary_index >= 0 else result["all_text"]
    (folder / "当前文档文本.txt").write_text(primary_text, encoding="utf-8-sig")
    if collection_mode != "final_only":
        with (folder / "滚动文本快照.jsonl").open("w", encoding="utf-8") as stream:
            for file in raw_files:
                raw = json.loads(file.read_text(encoding="utf-8-sig"))
                stream.write(json.dumps(raw, ensure_ascii=False) + "\n")
    return result


class CaptureApp(WorkspaceUI):
    def __init__(self, root, output=None):
        self.root = root
        self.events = queue.Queue()
        self.windows = []
        self.busy = False
        self.process = None
        self.stop_file = None
        self.stop_requested_at = None
        self.closing = False
        self.converting = False
        self.running_queue = False
        self.queue_stop = threading.Event()
        self.roster = None
        self.queue_checkpoint = None
        self.roster_label = tk.StringVar(value=f"尚未导入清单。原始数据库自动筛选来源={SOURCE_VALUE}；也支持普通 xlsx/CSV 清单。")
        self.queue_selection = tk.StringVar(value="在下方清单单击一行，再点“从选中项往后采集”。")
        self.last_excel_result = None
        self.batch_inputs = []
        self.batch_input_text = tk.StringVar(value="默认使用上方保存目录；也可选择其他目录或ZIP/JSON/TXT文件。")
        self.template = tk.StringVar()
        self.mapping_path = HOME / "业态对照表.csv"
        self.mapping_pick = None
        self.output = tk.StringVar(value=str(output or HOME / "采集数据"))
        self.label = tk.StringVar()
        self.selected_window = tk.StringVar()
        self.status = tk.StringVar(value="先刷新并选择小程序窗口，再采集。")
        self.maximum_steps = tk.IntVar(value=120)
        self.wait_ms = tk.IntVar(value=1200)
        self.final_only = tk.BooleanVar(value=True)
        self.capture_profile = tk.StringVar(value='商场小程序')
        self.scroll_direction = tk.StringVar(value='向下')
        self.mode_hint = tk.StringVar()
        self._build_ui()
        self.change_capture_profile()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self.poll)
        self.root.after(150, self.refresh_windows)
        self.root.after(250, self.load_bundled_roster)
        self.root.after(400, self.refresh_mapping_label)

    def load_bundled_roster(self):
        """同目录放着清单就自动载入：先认导出时的固定文件名，再认通用名。"""
        candidates = [HOME / ROSTER_FILE, HOME / "商场采集清单.xlsx"]
        bundled = next((path for path in candidates if path.exists()), None)
        if bundled and not self.roster:
            try:
                self.import_roster(bundled)
            except Exception as exc:
                self.log_message("同目录清单未加载：" + str(exc))

    def _build_ui(self):
        self.build_workspace(RESOURCES / 'assets')

    def choose_directory(self):
        folder = filedialog.askdirectory(title="选择采集数据保存位置", initialdir=self.output.get())
        if folder:
            self.output.set(folder)

    def change_capture_profile(self, _event=None):
        if self.busy:
            return
        general = self.capture_profile.get() == '通用窗口文本'
        self.mode_hint.set('通用模式：读取已加载的可访问文字；名称留空用窗口标题。聊天历史可选向上滚动。按 Esc 或失焦停止；完整性未确认。'
                           if general else '商场模式：按清单查询商场或直接采集商户列表。自动滚动时保持目标窗口在前台；按 Esc 或失焦停止。')
        self.apply_profile_controls()
        if general:
            self.navigate_workspace('capture')
        self.name_hint.set('留空时使用窗口标题；聊天历史可选择向上滚动' if general
                           else '商场模式填写名称；按清单采集时自动填入')

    def apply_profile_controls(self):
        general = self.capture_profile.get() == '通用窗口文本'
        self.profile_combo.configure(state='disabled' if self.busy else 'readonly')
        self.direction_combo.configure(state='readonly' if general and not self.busy else 'disabled')
        self.fast_capture_toggle.configure(state='disabled' if self.busy or general else 'normal')
        for widget in (*self.queue_widgets, *self.batch_widgets):
            widget.configure(state='disabled' if self.busy or general else 'normal')
        for key in ('queue', 'excel'):
            self.nav_buttons[key].configure(state='disabled' if general else 'normal')

    def choose_roster(self):
        file = filedialog.askopenfilename(title="选择原数据库或商场清单（xlsx/CSV）", filetypes=[("商场清单", "*.xlsx *.csv")])
        if file:
            try:
                self.import_roster(file)
            except Exception as exc:
                messagebox.showerror("清单导入失败", str(exc))

    def import_roster(self, file):
        roster = load_task_list(file)
        task_dir = Path(self.output.get()).expanduser().resolve() / "清单任务"
        task_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = task_dir / (roster["source_sha256"][:20] + ".json")
        if checkpoint.exists():
            previous = json.loads(checkpoint.read_text(encoding="utf-8"))
            states = {i["task_id"]: i for i in previous.get("items", [])}
            for item in roster["items"]:
                old = states.get(item["task_id"], {})
                if old.get("name") == item["name"]:
                    for key in ("status", "result", "last_error", "completed_at"):
                        if key in old:
                            item[key] = old[key]
                    if item["status"] == "采集中":
                        item["status"] = "待采集"
        self.roster, self.queue_checkpoint = roster, checkpoint
        write_json(checkpoint, roster)
        self.refresh_roster_table()
        if self.capture_profile.get() != '通用窗口文本':
            self.operations.select(self.queue_panel)
            self.show_queue_table()
        self.log_message(f"清单已导入：{roster['count']}家；原始{roster['total_rows']}行。进度保存：{checkpoint}")
        return roster

    def show_queue_table(self, _event=None):
        if self.capture_profile.get() != '通用窗口文本' and self.operations.select() == str(self.queue_panel):
            self.tables.select(self.roster_table)
        else:
            self.tables.select(self.records_panel)
        self.sync_workspace()

    def refresh_roster_table(self, active_task_id=None):
        if self.roster:
            ids = {item["task_id"] for item in self.roster["items"]}
            for row in self.roster_tree_ids:
                if row not in ids:
                    self.roster_tree.delete(row)
            self.roster_tree_ids = ids
            for position, item in enumerate(self.roster["items"], 1):
                task_id = item["task_id"]
                values = (position, item["source_row"], item["name"], item.get("district", ""), item["status"], item.get("last_error", ""))
                tag = {'采集中': 'running', '已保存（待复核）': 'saved', '待确认': 'review'}.get(item['status'])
                tags = tuple(value for value in (tag, 'even' if position % 2 == 0 else None) if value)
                if self.roster_tree.exists(task_id):
                    self.roster_tree.item(task_id, values=values, tags=tags)
                    self.roster_tree.move(task_id, "", position - 1)
                else:
                    self.roster_tree.insert("", "end", iid=task_id, values=values, tags=tags)
            items = self.roster["items"]
            saved = sum(i["status"] == "已保存（待复核）" for i in items)
            pending = sum(i["status"] == "待采集" for i in items)
            review = sum(i["status"] == "待确认" for i in items)
            self.roster_label.set(f"当前清单 {len(items)} 家：已保存 {saved}，待采集 {pending}，待确认 {review}。")
            if active_task_id and self.roster_tree.exists(active_task_id):
                self.roster_tree.see(active_task_id)
            self.filter_roster()
        self.select_queue_item()

    def select_queue_item(self, _event=None):
        selected = self.roster_tree.selection()
        if self.roster and selected:
            index, item = next((n, i) for n, i in enumerate(self.roster["items"], 1) if i["task_id"] == selected[0])
            self.queue_selection.set(f"已选第{index}/{len(self.roster['items'])}项：{item['name']}（{item['status']}）")
            if not self.busy:
                self.label.set(item["name"])
        else:
            self.queue_selection.set("在下方清单单击一行，再点“从选中项往后采集”。")

    def retry_queue_item(self):
        if not self.roster or self.busy:
            return
        for task_id in self.roster_tree.selection():
            item = next(i for i in self.roster["items"] if i["task_id"] == task_id)
            item.update(status="待采集", last_error="")
        write_json(self.queue_checkpoint, self.roster)
        self.refresh_roster_table()
        self.log_message("选中项目已恢复待采集；之前保存的数据不会删除。")

    def save_queue_progress(self):
        if self.roster:
            try:
                path = export_progress(self.roster, self.queue_checkpoint.parent)
                self.log_message("任务进度已导出：" + str(path))
                os.startfile(path.parent)
            except Exception as exc:
                messagebox.showerror("导出进度失败", str(exc))

    def start_queue(self, single=False, from_selected=False):
        if self.busy:
            return
        if self.capture_profile.get() == '通用窗口文本':
            messagebox.showinfo('切换采集模式', '商场清单任务请切换到“商场小程序”模式。')
            return
        if not self.roster:
            messagebox.showinfo("导入清单", "请先导入商场清单。")
            return
        start_task_id = None
        start_index = 0
        if from_selected:
            selected = self.roster_tree.selection()
            if not selected:
                self.operations.select(self.queue_panel)
                self.show_queue_table()
                messagebox.showinfo("选择采集起点", "请先在下方商场任务清单中单击要开始的商场。")
                return
            start_task_id = selected[0]
            start_index = next(i for i, item in enumerate(self.roster["items"]) if item["task_id"] == start_task_id)
        index = self.window_combo.current()
        if index < 0 or index >= len(self.windows) or self.windows[index]["process"].lower() != "wechatappex":
            messagebox.showinfo("选择小程序", "请打开大众点评小程序，刷新并选择对应WeChatAppEx窗口。")
            return
        window = self.windows[index]
        steps, wait = self.maximum_steps.get(), self.wait_ms.get()
        if not (1 <= steps <= 500 and 400 <= wait <= 5000):
            messagebox.showerror("参数错误", "请检查滚动上限和等待时间。")
            return
        final_only = self.final_only.get()
        output = Path(self.output.get()).expanduser().resolve()
        if not any(i["status"] in {"待采集", "采集中"} for i in self.roster["items"][start_index:]):
            self.log_message("所选范围内没有待采集项目；待确认或已保存项目需选中后点“重试选中项目”。")
            return
        self.queue_stop.clear()
        self.running_queue = True
        self.stop_file = self.queue_checkpoint.parent / datetime.now().strftime("stop_%Y%m%d_%H%M%S_%f.request")
        self.stop_requested_at = None
        self.set_busy(True)
        self.stop_button.configure(state="normal")
        self.log_message("3秒后开始；请保持目标小程序在前台。任何导航失败都会暂停队列，避免误搜下一家。")
        if from_selected:
            self.log_message(f"本次起点：第{start_index + 1}项 {self.roster['items'][start_index]['name']}；之前的项目不变。")
        def worker():
            def progress(text):
                self.events.put(("progress", text))
            def changed(item):
                # Keep every row in the checkpoint when starting partway through.
                write_json(self.queue_checkpoint, self.roster)
                self.events.put(("queue_changed", item["task_id"]))
                if item.get("last_error"):
                    progress(f"{item['name']}：{item['last_error']}")
            def capture_one(item):
                folder = create_capture_folder(output / "captures", item["name"])
                item['navigation_evidence'] = str(folder / '导航证据')
                navigator = MallNavigator(window["handle"], folder / "导航证据", self.queue_stop.is_set, progress)
                identity = navigator.open_mall(item)
                started = time.monotonic()
                args = capture_reader_arguments(window["handle"], folder, self.stop_file, steps, wait, True, final_only)
                reason, error = "", ""
                self.process = subprocess.Popen(reader_command(*args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    for line in self.process.stdout:
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if event.get("kind") == "done":
                            reason = event["data"]["reason"]
                        elif event.get("kind") == "error":
                            error = str(event["data"])
                        elif event.get("kind") == "snapshot":
                            progress(f"{item['name']}：已保存滚动快照{event['data']['step']}")
                        elif event.get("kind") == "progress":
                            progress(f"{item['name']}：{event['data']}")
                    self.process.wait(timeout=10)
                    code = self.process.returncode
                finally:
                    self.process = None
                result = finalize_capture(folder, item["name"], reason or error, time.monotonic() - started)
                result.update(roster_task=item, identity_check=identity,
                              mall_navigation={"verified_list": True, "expected_store_count": identity.get("expected_store_count"),
                                               "geography_status": identity.get("geography_status")})
                # Avoid recursively embedding this task's prior result on retry.
                result["roster_task"] = {k: v for k, v in item.items() if k != "result"}
                write_json(folder / "capture.json", result)
                item["result"] = dict(folder=str(folder), bottom_confirmed=result["bottom_confirmed"], stop_reason=reason or error)
                self.events.put(("queue_saved", (result, str(folder))))
                if self.queue_stop.is_set() or any(word in reason for word in ("失去焦点", "用户停止")):
                    raise BatchStopped(reason or "用户停止，快照已保留")
                if code or error:
                    raise ValueError(error or "采集未正常完成，已保存快照")
                return item["result"]
            try:
                time.sleep(3)
                if self.queue_stop.is_set():
                    raise BatchStopped("用户停止")
                navigate_action(window["handle"], "focus")
                result = run_queue(self.roster, self.queue_checkpoint.parent / "本次运行.json", capture_one, self.queue_stop.is_set, progress, changed,
                                   start_task_id=start_task_id, single=single)
                write_json(self.queue_checkpoint, self.roster)
                path = export_progress(self.roster, self.queue_checkpoint.parent)
                result["progress_file"] = str(path)
                self.events.put(("queue_done", result))
            except Exception as exc:
                self.events.put(("error", "清单采集已暂停：" + str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def log_message(self, message):
        self.log.configure(state='normal')
        self.log.insert("end", datetime.now().strftime("%H:%M:%S ") + str(message) + "\n")
        self.log.see("end")
        self.log.configure(state='disabled')
        self.status.set(str(message))
        self.update_workspace_counts()

    def choose_batch_directory(self):
        folder = filedialog.askdirectory(title="选择包含采集记录的目录", initialdir=self.output.get())
        if folder:
            self.batch_inputs = [folder]
            self.batch_input_text.set("输入目录：" + folder)
            self.refresh_mapping_label()

    def choose_batch_files(self):
        files = filedialog.askopenfilenames(title="批量选择采集ZIP、capture.json或当前文档TXT", filetypes=[("采集文件", "*.zip *.json *.txt"), ("所有文件", "*.*")])
        if files:
            self.batch_inputs = list(files)
            self.batch_input_text.set(f"已选择 {len(files)} 个输入文件：" + Path(files[0]).name)
            self.refresh_mapping_label()

    def set_status_dot(self, dot, item, active):
        """元信息前的状态点：绿＝用的是自己的文件，灰＝走内置默认。"""
        try:
            dot.itemconfigure(item, fill='#35A82F' if active else '#C9C9C9')
        except (AttributeError, tk.TclError):
            pass

    def choose_template(self):
        file = filedialog.askopenfilename(title="选择含品牌明细/品牌明细表的Excel模板（取消则恢复内置）", filetypes=[("Excel工作簿", "*.xlsx")])
        self.template.set(file or "")
        self.template_label.configure(text="模板：" + (Path(file).name if file else "内置品牌明细 11 字段"))
        self.set_status_dot(self.template_dot, self.template_dot_item, bool(file))

    def current_mapping(self):
        """返回 (对照表对象, 路径, 识别说明)；找不到就用内置四类业态。"""
        try:
            mapping, source, note, _ = resolve_mapping(
                self.mapping_pick or None, self.batch_inputs or [self.output.get()], self.output.get())
            return mapping, source, note
        except Exception as exc:
            return None, None, f"读取失败：{exc}"

    def refresh_mapping_label(self):
        mapping, source, note = self.current_mapping()
        self.mapping_note = note or ""
        if mapping is None:
            text = f"业态对照表：{note}"
        else:
            text = f"业态对照表：{mapping.describe()}"
            if source and source != "内置对照":
                # 说清这份表是手工选的还是程序自己找的，改表后能对上"到底用的哪一份"。
                text += " · 手工指定" if self.mapping_pick else " · 自动识别"
        self.mapping_label.configure(text=text)
        self.set_status_dot(self.mapping_dot, self.mapping_dot_item,
                            bool(source and source != "内置对照"))
        detail = self.mapping_note or text
        tip = getattr(self, "mapping_tip", None)
        if tip is None:
            self.mapping_tip = Tooltip(self.mapping_label, detail)
        else:
            tip.text = detail
        if hasattr(self, "layout_pending"):
            self.adapt_layout()  # 表名长短不同，重算卡片高度，避免提示被裁

    def choose_mapping(self):
        file = filedialog.askopenfilename(
            title="选择业态对照表（CSV 或 Excel）",
            initialdir=str(HOME),
            filetypes=[("业态对照表", "*.csv *.xlsx *.xlsm"), ("所有文件", "*.*")])
        if file:
            self.mapping_pick = Path(file)
            self.log_message(f"已选用对照表：{Path(file).name}；也可把表放回程序目录并改名为“业态对照表.csv”，下次自动识别。")
            self.refresh_mapping_label()
        else:
            self.mapping_pick = None
            self.refresh_mapping_label()

    def edit_mapping(self):
        try:
            mapping, source, note = self.current_mapping()
            path = Path(source) if source and source != "内置对照" else None
            if path is None or not path.exists():
                path = save_mapping_table(HOME / "业态对照表.csv")
                self.log_message("程序目录还没有对照表，已按内置四类业态生成 业态对照表.csv。")
            os.startfile(path)
            self.log_message(f"已打开对照表：{path.name}。改完保存并重新整理即可生效，不需要重新安装。")
        except Exception as exc:
            messagebox.showerror("对照表提示", str(exc))

    def convert_excel(self):
        if self.busy:
            return
        if self.capture_profile.get() == '通用窗口文本':
            messagebox.showinfo('通用窗口文本', '通用模式保存原始TXT/JSON；商场业态Excel请切换到商场模式处理。')
            return
        inputs = self.batch_inputs or [self.output.get()]
        destination = Path(self.output.get()).expanduser().resolve() / "Excel结果"
        template = self.template.get() or None
        # 只在用户手工选过表时才传路径；否则交给自动识别，改 CSV 或改 Excel 参考表都能立刻生效。
        mapping = self.mapping_pick or None
        self.converting = True
        self.set_busy(True)
        self.log_message("正在批量整理；原始采集文件和模板保持不动。")
        def worker():
            try:
                result = batch_export(inputs, destination, template, mapping, lambda text: self.events.put(("progress", text)))
                self.events.put(("excel_saved", result))
            except Exception as exc:
                self.events.put(("error", "批量转换失败：" + str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def set_busy(self, busy):
        self.busy = busy
        for widget in (self.capture_button, self.auto_button, self.fast_capture_toggle, self.refresh_button, self.export_button, self.output_button, self.output_entry, self.name_entry, self.maximum_steps_input, self.wait_input, *self.batch_widgets, *self.queue_widgets):
            widget.configure(state="disabled" if busy else "normal")
        self.window_combo.configure(state="disabled" if busy else "readonly")
        self.apply_profile_controls()
        self.stop_button.configure(state="normal" if busy and self.process else "disabled")
        self.activity_label.set('处理中' if busy else '就绪')
        if hasattr(self, 'workspace_cover'):
            color = '#88652F' if busy else '#367D60'
            self.workspace_cover.itemconfigure(self.activity_badge, fill=color)
        else:
            color, background = ('#88652F', '#FCF0D9') if busy else ('#378365', '#E7F5EE')
            self.activity_badge.configure(foreground=color, background=background)
            self.activity_badge.master.configure(background=background)
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def refresh_windows(self):
        if self.busy:
            return
        self.set_busy(True)
        self.log_message("正在读取可见窗口列表…")
        def worker():
            try:
                events = run_reader(["-Mode", "list"], timeout=35)
                values = next((e["data"] for e in events if e.get("kind") == "windows"), [])
                self.events.put(("windows", values))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def capture(self, auto):
        if self.busy:
            return
        index = self.window_combo.current()
        if index < 0 or index >= len(self.windows):
            messagebox.showinfo("选择窗口", "请先选择要采集的目标窗口。")
            return
        window = self.windows[index]
        general = self.capture_profile.get() == '通用窗口文本'
        profile = 'general' if general else 'mall'
        direction = 'up' if general and self.scroll_direction.get() == '向上' else 'down'
        label = self.label.get().strip()
        if general and not label:
            label = window['title']
        if not label:
            messagebox.showinfo("填写商场名", "请先填写本次商场名称，用于文件夹命名；批量采集会自动使用清单商场名。")
            return
        final_only = self.final_only.get() and not general
        try:
            steps = self.maximum_steps.get()
            wait = self.wait_ms.get()
            if not (1 <= steps <= 500 and 400 <= wait <= 5000):
                raise ValueError()
            folder = create_capture_folder(Path(self.output.get()).expanduser().resolve() / "captures", label)
        except Exception as exc:
            messagebox.showerror("无法开始", "请检查保存目录和滚动参数。\n" + str(exc))
            return
        self.stop_file = folder / "stop.request"
        self.stop_requested_at = None
        self.set_busy(True)
        self.stop_button.configure(state="normal")
        self.log_message(f"正在采集：{label}；" + ('通用窗口可访问原文，保留沿途快照。' if general else ("滚到底并集中保存最终文本。" if auto and final_only else "逐步保存滚动快照。")))
        started = time.monotonic()
        def worker():
            reason = ""
            error = ""
            try:
                args = capture_reader_arguments(window["handle"], folder, self.stop_file, steps, wait, auto, final_only,
                                                profile=profile, direction=direction)
                self.process = subprocess.Popen(reader_command(*args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
                stderr_parts = []
                def drain_errors():
                    stderr_parts.append(self.process.stderr.read())
                threading.Thread(target=drain_errors, daemon=True).start()
                for line in self.process.stdout:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    kind, data = event.get("kind"), event.get("data")
                    if kind == "progress":
                        self.events.put(("progress", data))
                    elif kind == "snapshot":
                        self.events.put(("progress", f"已保存第 {data['step']} 步，文档总字数 {data['characters']}。"))
                    elif kind == "done":
                        reason = data["reason"]
                    elif kind == "error":
                        error = str(data)
                self.process.wait(timeout=10)
                if self.process.returncode and not error:
                    error = "窗口读取进程返回错误；已有原始快照会保留。" + "".join(stderr_parts)[-1000:]
                result = finalize_capture(folder, label, reason or error, time.monotonic() - started)
                if error:
                    result["warning"] = (result.get('warning', '') + '\n' + error).strip()
                    write_json(folder / "capture.json", result)
                self.events.put(("saved", (result, str(folder))))
            except Exception as exc:
                self.events.put(("error", str(exc) + f"\n本次目录：{folder}"))
            finally:
                self.process = None
        threading.Thread(target=worker, daemon=True).start()

    def stop(self):
        if self.running_queue:
            self.queue_stop.set()
        if self.stop_file:
            self.stop_file.touch(exist_ok=True)
            if self.stop_requested_at is None:
                self.stop_requested_at = time.monotonic()
            self.log_message("已请求停止；正在保存已完成的快照。")

    def export(self):
        if self.busy:
            return
        root = Path(self.output.get()).expanduser().resolve()
        destination = filedialog.asksaveasfilename(title="导出全部原始采集数据", initialdir=str(root), initialfile="原始窗口文本_批次_" + datetime.now().strftime("%Y%m%d_%H%M%S.zip"), defaultextension=".zip", filetypes=[("ZIP压缩包", "*.zip")])
        if not destination:
            return
        try:
            summaries = []
            for file in sorted((root / "captures").glob("*/capture.json")):
                record = json.loads(file.read_text(encoding="utf-8"))
                summaries.append([record["captured_at"], record["merchant_name"], record["window_title"], len(record["all_text"]), record["raw_snapshot_count"], record["bottom_confirmed"], file.parent.name])
            if not summaries:
                raise ValueError("当前目录尚无成功采集记录")
            with (root / "captures" / "批次索引.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["采集时间", "本次名称", "窗口标题", "全部文档字数", "快照数", "检测到底部提示", "相对目录"])
                writer.writerows([[csv_literal(value) for value in row] for row in summaries])
            export_archive(root / "captures", destination)
            self.log_message(f"已导出 {len(summaries)} 次采集：{destination}")
            messagebox.showinfo("导出完成", f"已打包 {len(summaries)} 次采集。\n{destination}")
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))

    def open_directory(self):
        folder = Path(self.output.get()).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def poll(self):
        if self.stop_requested_at and self.process and time.monotonic() - self.stop_requested_at > 12:
            self.process.kill()
            self.stop_requested_at = None
            self.log_message("读取接口未及时返回，已结束读取进程；已保存快照会保留。")
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "windows":
                    self.windows = sorted(value, key=lambda w: (not any(s in w["process"].lower() for s in ("wechatappex", "weixin", "wechat")), w["title"]))
                    self.window_combo["values"] = [f"{w['title']}  [{w['process']} · {w['handle']}]" for w in self.windows]
                    if self.windows:
                        selected = next((i for i, w in enumerate(self.windows) if w["process"].lower() == "wechatappex"), 0)
                        self.window_combo.current(selected)
                    self.set_busy(False)
                    self.log_message(f"找到 {len(self.windows)} 个可见窗口。选择目标后采集；商场模式需填写本次名称。")
                elif kind == "progress":
                    self.log_message(value)
                elif kind == "saved":
                    record, folder = value
                    primary = record.get("primary_document_index")
                    count = len(record["documents"][primary]["text"]) if primary is not None and primary >= 0 else len(record["all_text"])
                    self.records.insert("", "end", values=(record["captured_at"][11:19], record["merchant_name"], count, record["raw_snapshot_count"], "检测到提示" if record["bottom_confirmed"] else "未确认"))
                    self.set_busy(False)
                    next_step = '通用原文已存档，可查看滚动汇总文本。' if record.get('capture_profile') == 'general' else '可以切换下一家。'
                    self.log_message(f"已保存：{record['merchant_name']}，{count}字，{record['raw_snapshot_count']}个快照。{record['stop_reason']}。{next_step}")
                    if record.get("warning"):
                        self.log_message("注意：" + record["warning"])
                elif kind == "queue_changed":
                    self.refresh_roster_table(value)
                elif kind == "queue_saved":
                    record, folder = value
                    self.records.insert("", "end", values=(record["captured_at"][11:19], record["merchant_name"], len(record["all_text"]), record["raw_snapshot_count"], "检测到提示" if record["bottom_confirmed"] else "未确认"))
                elif kind == "queue_done":
                    self.running_queue = False
                    self.set_busy(False)
                    self.refresh_roster_table()
                    self.log_message(f"清单任务{'已暂停' if value['stopped'] else '本次已结束'}：已保存{value['saved']}家，待确认{value['review']}家，待采集{value['pending']}家。原始记录可在批量Excel页整理。")
                elif kind == "excel_saved":
                    self.converting = False
                    self.last_excel_result = value
                    self.set_busy(False)
                    info = value.get("mapping") or {}
                    self.log_message(f"Excel已生成：{value['success_count']}份，失败{value['error_count']}项，用时{value['elapsed_seconds']}秒。"
                                     f"对照表：{info.get('description', '内置对照')}。目录：{value['folder']}")
                    self.refresh_mapping_label()
                    if not self.closing:
                        pending = info.get("pending") or {}
                        extra = ""
                        if pending:
                            top = "、".join(f"{name}({count})" for name, count in list(pending.items())[:5])
                            extra = f"\n另有 {len(pending)} 个细分业态没在对照表里，已列入“业态待补清单”：{top}。补进对照表后重新整理即可。"
                        messagebox.showinfo("批量Excel完成", f"已生成 {value['success_count']} 份业态明细；失败 {value['error_count']} 项。\n"
                                           f"对照表：{info.get('description', '内置对照')}（{info.get('note', '')}）{extra}\n"
                                           f"请查看批次索引和各表的待复核记录。\n{value['folder']}")
                        os.startfile(value["folder"])
                elif kind == "error":
                    self.converting = False
                    self.running_queue = False
                    self.set_busy(False)
                    self.log_message(value)
                    messagebox.showerror("采集提示", value)
        except queue.Empty:
            pass
        if self.closing and not self.busy:
            self.root.destroy()
            return
        self.root.after(120, self.poll)

    def close(self):
        if self.busy:
            self.closing = True
            if self.converting:
                self.log_message("正在完成Excel保存，完成后自动关闭。")
            else:
                self.stop()
                self.log_message("正在停止并保存；完成后自动关闭。")
        else:
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--output")
    parser.add_argument("--smoke-report")
    parser.add_argument("--batch-import", nargs="+")
    parser.add_argument("--excel-output")
    parser.add_argument("--template")
    parser.add_argument("--mapping", help="业态对照表 CSV/XLSX；不填则自动识别程序目录里最新修改的一份")
    parser.add_argument("--roster")
    parser.add_argument('--profile', choices=['mall', 'general'], default='mall')
    parser.add_argument('--scroll-direction', choices=['down', 'up'], default='down')
    parser.add_argument('--capture-window', type=int, help='Read one selected window once and save its accessible text')
    parser.add_argument('--label')
    args = parser.parse_args()
    if args.capture_window:
        if args.batch_import:
            parser.error('--capture-window and --batch-import cannot be combined')
        output = Path(args.output or HOME / '采集数据').expanduser().resolve()
        label = args.label or f'窗口_{args.capture_window}'
        folder = create_capture_folder(output / 'captures', label)
        started = time.monotonic()
        events = run_reader(capture_reader_arguments(args.capture_window, folder, folder / 'stop.request',
                            120, 1200, False, False, profile=args.profile, direction=args.scroll_direction))
        reason = next((event['data']['reason'] for event in events if event.get('kind') == 'done'), '单次读取')
        result = finalize_capture(folder, label, reason, time.monotonic() - started)
        report = dict(folder=str(folder), capture_profile=result.get('capture_profile', 'mall'),
                      raw_snapshot_count=result['raw_snapshot_count'], characters=len(result['all_text']),
                      capture_status=result['capture_status'])
        if args.smoke_report:
            write_json(args.smoke_report, report)
        if sys.stdout:
            print(json.dumps(report, ensure_ascii=False))
        return
    if args.batch_import:
        result = batch_export(args.batch_import, args.excel_output or HOME / "采集数据" / "Excel结果",
                              args.template, args.mapping)
        if args.smoke_report:
            write_json(args.smoke_report, result)
        if sys.stdout:
            print(json.dumps(result, ensure_ascii=False))
        return
    from display_scale import enable_dpi_awareness
    enable_dpi_awareness()
    root = tk.Tk()
    if args.smoke_test:
        root.withdraw()
        app = CaptureApp(root, args.output)
        app.capture_profile.set('通用窗口文本' if args.profile == 'general' else '商场小程序')
        app.scroll_direction.set('向上' if args.scroll_direction == 'up' else '向下')
        app.change_capture_profile()
        if args.roster:
            app.import_roster(args.roster)
        def finish_smoke():
            selected_id = None
            if app.roster:
                selected_id = app.roster['items'][len(app.roster['items']) // 2]['task_id']
                app.roster_tree.selection_set(selected_id)
                app.select_queue_item()
                app.refresh_roster_table()
            if args.smoke_report:
                write_json(args.smoke_report, {"gui_created": True, "windows_loaded": len(app.windows), "reader_exists": READER.exists(), "navigation_reader_exists": (RESOURCES / "window_navigation.ps1").exists(), "frozen": bool(getattr(sys, "frozen", False)), "roster_count": len(app.roster["items"]) if app.roster else 0, "queue_controls": len(app.queue_widgets),
                                              "roster_tab_visible": app.tables.select() == str(app.roster_table),
                                              "selected_start_available": app.queue_from_selected_button.winfo_exists() == 1,
                                              "selection_preserved": app.roster_tree.selection() == (selected_id,) if selected_id else None,
                                              "selected_position": app.queue_selection.get(),
                                              'generic_reader_exists': (RESOURCES / 'generic_reader.ps1').exists() and (RESOURCES / 'generic_native.cs').exists(),
                                              'profile': args.profile,
                                              'version': VERSION,
                                              'display_scale': app.ui_scale,
                                              'logo_pixels': app.ui_image('logo').width(),
                                              'icon_exists': (RESOURCES / 'assets' / 'app.ico').exists(),
                                              'workspace_pages': list(app.nav_buttons),
                                              'general_controls_ready': app.profile_combo.winfo_exists() == 1 and app.direction_combo.winfo_exists() == 1})
            root.destroy()
        root.after(6500, finish_smoke)
        root.mainloop()
        if sys.stdout:
            print("GUI_SMOKE_OK")
    else:
        app = CaptureApp(root, args.output)
        app.capture_profile.set('通用窗口文本' if args.profile == 'general' else '商场小程序')
        app.scroll_direction.set('向上' if args.scroll_direction == 'up' else '向下')
        app.change_capture_profile()
        if args.roster:
            app.import_roster(args.roster)
        root.mainloop()


if __name__ == "__main__":
    main()
