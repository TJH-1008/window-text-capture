"""Desktop workspace layout and dependency-free Tk interactions."""

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from PIL import Image, ImageTk
from display_scale import scale_styles, scale_tree
from ui_effects import ButtonSkin
from frosted_header import FrostedHeader
from modern_scrollbars import configure_scrollbars
from brand_icon import application_icon
from roster import SOURCE_VALUE

VERSION = '1.5.0'
BG = '#FAFAFA'
INK = '#262626'
MUTED = '#626262'
PURPLE = '#35A82F'
PINK_PALE = '#EAF6E5'
LINE = '#D9D9D9'
FONT = 'Microsoft YaHei UI'
SIDEBAR = '#FFFFFF'


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        self.popup = None
        self.pending = None
        widget.bind('<Enter>', self.schedule, add='+')
        widget.bind('<FocusIn>', self.schedule, add='+')
        for event in ('<Leave>', '<FocusOut>', '<ButtonPress>', '<Destroy>'):
            widget.bind(event, self.hide, add='+')

    def schedule(self, _event=None):
        self.hide()
        self.pending = self.widget.after(550, self.show)

    def show(self):
        self.pending = None
        if self.popup or not self.widget.winfo_viewable():
            return
        popup = self.popup = tk.Toplevel(self.widget)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.attributes('-topmost', True)
        scale = float(self.widget.tk.call('tk', 'scaling'))/(96/72)
        tk.Label(popup, text=self.text, background=INK, foreground='white',
                 font=(FONT, 9), justify='left', wraplength=round(300*scale),
                 padx=round(12*scale), pady=round(9*scale)).pack()
        popup.update_idletasks()
        x = min(self.widget.winfo_rootx(), popup.winfo_screenwidth() - popup.winfo_reqwidth() - 12)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        if y + popup.winfo_reqheight() > popup.winfo_screenheight() - 40:
            y = self.widget.winfo_rooty() - popup.winfo_reqheight() - 6
        popup.geometry(f'+{max(0, x)}+{max(0, y)}')
        popup.deiconify()

    def hide(self, _event=None):
        if self.pending:
            self.widget.after_cancel(self.pending)
            self.pending = None
        if self.popup:
            self.popup.destroy()
            self.popup = None


class Card(tk.Canvas):
    def __init__(self, parent, *, color='white', height=120, padding=18, background=BG):
        super().__init__(parent, background=background, highlightthickness=0, borderwidth=0,
                         width=10, height=height)
        self.color, self.padding, self.radius = color, padding, 9
        self.inner = tk.Frame(self, background=color)
        self.surface = self.create_polygon(0, 0, 0, 0, fill=color, outline=LINE, smooth=True)
        self.window = self.create_window(padding, padding, anchor='nw', window=self.inner)
        self.bind('<Configure>', self.resize)

    def resize(self, event):
        w, h, r = event.width, event.height, self.radius
        self.coords(self.surface, r, 0, w-r, 0, w, 0, w, r, w, h-r, w, h,
                    w-r, h, r, h, 0, h, 0, h-r, 0, r, 0, 0)
        self.itemconfigure(self.window, width=max(1, w-2*self.padding), height=max(1, h-2*self.padding))


class ScrollPanel(tk.Frame):
    """Wheel handling stays inside this panel rather than hijacking table scrolling."""
    def __init__(self, parent, width=304):
        super().__init__(parent, background='#FAFAFA', width=width)
        self.grid_propagate(False)
        self.pixel_scale = 1
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, background='#FAFAFA', highlightthickness=0, width=width-12)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.scroll = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.scroll.grid(row=0, column=1, sticky='ns')
        self.scroll_hint = tk.Label(self, text='向下滚动查看更多设置  ↓', background='#EAF6E5',
                                    foreground='#24531C', font=(FONT, 8), cursor='hand2', pady=5)
        self.scroll_hint.bind('<Button-1>', lambda _event: self.canvas.yview_scroll(3, 'units'))
        self.canvas.configure(yscrollcommand=self.update_scroll_hint)
        self.inner = tk.Frame(self.canvas, background='#FAFAFA')
        self.window = self.canvas.create_window(18, 72, window=self.inner, anchor='nw')
        self.inner.bind('<Configure>', self.measure)
        self.canvas.bind('<Configure>', self.fit)
        self.frosted_header = FrostedHeader(self, '采集设置')

    def measure(self, _event=None):
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), self.inner.winfo_reqheight()+round(100*self.pixel_scale)))
        self.update_scroll_hint(*self.canvas.yview())

    def update_scroll_hint(self, first, last):
        self.scroll.set(first, last)
        if hasattr(self, 'frosted_header'):
            self.frosted_header.schedule()
        overflow = self.inner.winfo_reqheight()+round(100*self.pixel_scale) > self.canvas.winfo_height()
        if overflow:
            self.scroll_hint.place(in_=self.canvas, relx=0, rely=1, relwidth=1, anchor='sw',
                                   height=round(26*self.pixel_scale))
            self.scroll_hint.lift()
        else:
            self.scroll_hint.place_forget()

    def fit(self, event):
        self.canvas.coords(self.window, round(18*self.pixel_scale), round(72*self.pixel_scale))
        self.canvas.itemconfigure(self.window, width=max(1, event.width-round(36*self.pixel_scale)))
        self.measure()

    def bind_wheel(self):
        def scroll(event):
            if self.inner.winfo_reqheight()+round(100*self.pixel_scale) > self.canvas.winfo_height():
                self.canvas.yview_scroll(-int(event.delta / 120), 'units')
            return 'break'
        def visit(widget):
            if not isinstance(widget, (ttk.Combobox, ttk.Spinbox)):
                widget.bind('<MouseWheel>', scroll, add='+')
            for child in widget.winfo_children():
                visit(child)
        visit(self.canvas)


def configure_styles(root):
    root.configure(background=BG)
    root.option_add('*Font', (FONT, 10))
    root.option_add('*TCombobox*Listbox.background', 'white')
    root.option_add('*TCombobox*Listbox.selectBackground', '#EAF6E5')
    root.option_add('*TCombobox*Listbox.selectForeground', INK)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=(FONT, 10), background='white', foreground=INK)
    style.configure('TFrame', background='white')
    style.configure('TLabel', background='white', foreground=INK)
    style.configure('TButton', padding=(12, 8), relief='flat', background='#FFFFFF',
                    foreground='#262626', borderwidth=0, focusthickness=2, focuscolor='#35A82F')
    style.map('TButton', background=[('disabled', '#F2F2F2'), ('pressed', '#E5E5E5'), ('active', '#F3F3F3')],
              foreground=[('disabled', '#767676')], focuscolor=[('focus', '#35A82F')],
              relief=[('pressed', 'sunken'), ('!pressed', 'flat')])
    style.configure('Primary.TButton', background=INK, foreground='white', font=(FONT, 10, 'bold'))
    style.map('Primary.TButton', background=[('disabled', '#EAEAEA'), ('pressed', '#111111'), ('active', '#414141')],
              foreground=[('disabled', '#767676'), ('!disabled', 'white')],
              relief=[('pressed', 'sunken'), ('!pressed', 'flat')])
    style.configure('Danger.TButton', background='#FFF5F3', foreground='#A13423')
    style.map('Danger.TButton', background=[('disabled', '#F1F1F1'), ('pressed', '#F6D2CA'), ('active', '#FCE9E5')],
              foreground=[('disabled', '#767676')])
    style.configure('Quiet.TButton', background='white', foreground=MUTED, padding=(9, 7))
    style.map('Quiet.TButton', background=[('disabled', '#F6F6F6'), ('active', '#F3F3F3')])
    style.configure('Nav.TButton', anchor='w', background=SIDEBAR, foreground='#434343', padding=(16, 13),
                    font=(FONT, 10), focuscolor='#35A82F')
    style.map('Nav.TButton', background=[('disabled', 'white'), ('selected', PINK_PALE), ('active', '#F3F3F3')],
              foreground=[('disabled', '#767676'), ('selected', '#24531C'), ('active', INK)],
              relief=[('pressed', 'sunken'), ('!pressed', 'flat')])
    style.configure('TEntry', padding=8, fieldbackground='#FFFFFF', bordercolor=LINE,
                    lightcolor=LINE, darkcolor=LINE, insertcolor=PURPLE)
    style.map('TEntry', bordercolor=[('focus', '#35A82F')], fieldbackground=[('disabled', '#F2F2F2')])
    style.configure('TCombobox', padding=7, fieldbackground='#FFFFFF', background='#FFFFFF',
                    bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, arrowcolor=MUTED)
    style.map('TCombobox', fieldbackground=[('disabled', '#F2F2F2'), ('readonly', '#FFFFFF')],
              foreground=[('disabled', '#767676')], bordercolor=[('focus', '#35A82F')],
              selectbackground=[('readonly', '#FFFFFF')], selectforeground=[('readonly', INK)])
    style.configure('TSpinbox', padding=7, fieldbackground='#FFFFFF', bordercolor=LINE,
                    lightcolor=LINE, darkcolor=LINE, arrowcolor=MUTED)
    style.map('TSpinbox', bordercolor=[('focus', '#35A82F')], foreground=[('disabled', '#767676')])
    style.configure('TCheckbutton', background='#FAFAFA', font=(FONT, 9), padding=(0, 6))
    style.map('TCheckbutton', background=[('active', '#FAFAFA')], foreground=[('disabled', '#767676')])
    style.configure('Workspace.TNotebook', background='white', borderwidth=0, tabmargins=0)
    style.configure('Workspace.TNotebook', bordercolor='white', lightcolor='white', darkcolor='white')
    style.layout('Workspace.TNotebook.Tab', [])
    style.configure('Treeview', rowheight=37, background='white', fieldbackground='white',
                    foreground=INK, borderwidth=0, font=(FONT, 9))
    style.layout('Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
    style.configure('Treeview.Heading', background='#F5F6F5', foreground='#5A5A5A', relief='flat',
                    font=(FONT, 9), padding=(10, 10), borderwidth=0)
    style.map('Treeview', background=[('selected', '#EAF6E5')], foreground=[('selected', '#24531C')])
    style.map('Treeview.Heading', background=[('active', '#F3F3F3')])
    style.configure('Capture.Horizontal.TProgressbar', background=PURPLE, troughcolor='#EAEAEA', borderwidth=0, thickness=3)
    return style


class WorkspaceUI:
    def ui_label(self, parent, text='', *, size=10, color=INK, bold=False, **kwargs):
        kwargs.setdefault('anchor', 'w')
        background = 'white' if isinstance(parent, ttk.Widget) else parent.cget('background')
        return tk.Label(parent, text=text, font=(FONT, size, 'bold' if bold else 'normal'),
                        background=background, foreground=color, **kwargs)

    def ui_button(self, parent, text, command, *, primary=False, hint=None, style=None, icon=None):
        parent_style = style or ('Primary.TButton' if primary else 'TButton')
        button = ttk.Button(parent, text=text, command=command,
                            style=parent_style, cursor='hand2')
        palette = {
            'Primary.TButton': ('#262626', '#414141', '#111111', '#EAEAEA', '#262626', 'white'),
            'Nav.TButton': (SIDEBAR, '#F2F6F0', '#DFEBD9', SIDEBAR, '#EAF6E5', SIDEBAR),
            'Danger.TButton': ('#FFF5F3', '#FCE9E5', '#F6D2CA', '#F1F1F1', '#FFF5F3', '#FAFAFA'),
            'Quiet.TButton': ('#FFFFFF', '#F4F4F4', '#E7E7E7', '#F6F6F6', '#EAF6E5', 'white'),
        }.get(parent_style, ('#FFFFFF', '#F3F3F3', '#E5E5E5', '#F3F3F3', '#EAF6E5', 'white'))
        skin = ButtonSkin(button, self.style, parent_style, self.ui_scale, palette, len(self.button_skins))
        self.button_skins[button] = skin
        if icon:
            image = self.ui_image(icon)
            if image:
                button.configure(image=image, compound='left')
        if hint:
            self.tooltips[button] = Tooltip(button, hint)
        return button

    def ui_image(self, name):
        if name not in self.ui_images:
            suffix = '' if name == 'app' else f'-{round(self.ui_scale*100)}'
            file = self.asset_path / (name + suffix + '.png')
            if not file.exists():
                file = self.asset_path / (name + '.png')
            self.ui_images[name] = tk.PhotoImage(master=self.root, file=str(file)) if file.exists() else None
        return self.ui_images[name]

    def build_workspace(self, asset_path):
        self.asset_path = Path(asset_path)
        raw_scale = float(self.root.tk.call('tk', 'scaling')) / (96/72)
        self.ui_scale = max(.75, round(raw_scale*4)/4)
        self.root.tk.call('tk', 'scaling', self.ui_scale*96/72)
        self.ui_images, self.tooltips, self.nav_buttons, self.button_skins = {}, {}, {}, {}
        self.style = configure_styles(self.root)
        self.active_page = tk.StringVar(value='queue')
        self.activity_label = tk.StringVar(value='就绪')
        self.page_title = tk.StringVar(value='商场清单')
        self.page_subtitle = tk.StringVar(value='导入名单，选择起点，按顺序采集每一家商场。')
        self.roster_search = tk.StringVar()
        self.roster_saved_selection = ()
        self.roster_tree_ids = set()
        self.status_preview = tk.StringVar()
        self.roster_count_text = tk.StringVar(value='0')
        self.roster_progress_text = tk.StringVar(value='导入商场清单，建立你的采集任务')
        self.session_count_text = tk.StringVar(value='0')
        self.session_note_text = tk.StringVar(value='原文保留  ·  随时导出')
        self.table_count_text = tk.StringVar(value='0 项任务')
        self.table_title = tk.StringVar(value='商场任务清单')
        self.queue_empty_text = tk.StringVar(value=f'从一份商场清单开始\n支持 Excel / CSV，原始数据库自动筛选来源={SOURCE_VALUE}')
        self.root.title(f'窗口文本采集器 {VERSION} · 采集工作台')
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        width, height = min(round(1400*self.ui_scale), screen_w-60), min(round(900*self.ui_scale), screen_h-100)
        self.root.geometry(f'{width}x{height}+{max(0,(screen_w-width)//2)}+{max(0,(screen_h-height)//2-20)}')
        self.root.minsize(min(round(1100*self.ui_scale), screen_w-40), min(round(650*self.ui_scale), screen_h-90))
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        try:
            self.root.iconbitmap(str(self.asset_path / 'app.ico'))
        except tk.TclError:
            icon = self.ui_image('app')
            if icon:
                self.root.iconphoto(True, icon)
        self._build_sidebar()
        center = tk.Frame(self.root, background=BG)
        center.grid(row=0, column=1, sticky='nsew', padx=24, pady=(22, 18))
        center.columnconfigure(0, weight=1)
        center.rowconfigure(3, weight=1)
        self._build_heading(center)
        self._build_summary(center)
        self._build_operations(center)
        self._build_tables(center)
        self._build_log(center)
        self._build_settings()
        self.status.trace_add('write', self.refresh_status_preview)
        self.output.trace_add('write', self.refresh_status_preview)
        self.refresh_status_preview()
        self.roster_search.trace_add('write', self.filter_roster)
        self.operations.bind('<<NotebookTabChanged>>', self.show_queue_table)
        self.operations.select(self.queue_panel)
        self.tables.select(self.roster_table)
        self.root.bind('<Control-f>', self.focus_roster_search)
        self.root.bind('<Control-r>', lambda event: self.refresh_windows())
        self.root.bind('<Escape>', lambda event: self.stop() if self.busy and not self.converting else None)
        for number, page in enumerate(('capture', 'queue', 'excel'), 1):
            self.root.bind(f'<Alt-Key-{number}>', lambda event, key=page: self.navigate_workspace(key))
        self.sync_workspace()
        scale_tree(self.root, self.ui_scale)
        scale_styles(self.style, self.ui_scale)
        configure_scrollbars(self.root, self.style, self.ui_scale)
        self.layout_pending = None
        self.root.bind('<Configure>', self.schedule_layout, add='+')
        self.root.bind('<Destroy>', self.cancel_layout_on_destroy, add='+')
        self.root.after_idle(self.adapt_layout)
        self.root.bind('<Destroy>', self._dispose_workspace, add='+')

    def _dispose_workspace(self, event):
        if event.widget != self.root:
            return
        # Tk deletes registered Python commands on teardown, but leaves timers
        # queued in its interpreter unless they are explicitly cancelled.
        for job in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.tk.call('after', 'cancel', job)

    def _build_sidebar(self):
        sidebar = tk.Frame(self.root, background=SIDEBAR, width=176)
        sidebar.grid(row=0, column=0, sticky='ns')
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, background=SIDEBAR)
        brand.pack(fill='x', padx=22, pady=(28, 30))
        self.brand_mark = ImageTk.PhotoImage(application_icon(round(38*self.ui_scale)), master=self.root)
        tk.Label(brand, image=self.brand_mark, background=SIDEBAR).pack(anchor='w')
        self.ui_label(brand, '窗口采集', size=17, color=INK, bold=True).pack(anchor='w', pady=(12, 2))
        self.ui_label(brand, 'CAPTURE STUDIO', size=8, color=MUTED).pack(anchor='w')
        self.ui_label(sidebar, '工作空间', size=9, color='#626262').pack(anchor='w', padx=24, pady=(2, 10))
        for key, text, icon in [('capture', '  单次采集', 'window'), ('queue', '  商场清单', 'list'), ('excel', '  批量 Excel', 'table')]:
            button = self.ui_button(sidebar, text, lambda page=key: self.navigate_workspace(page),
                                    style='Nav.TButton', icon=icon,
                                    hint={'capture': '读取当前窗口，或自动滚动并保留文本。Alt+1',
                                          'queue': '按商场名单查询，支持从选中项续采。Alt+2',
                                          'excel': '把已采集的商场文本批量整理为业态明细。Alt+3'}[key])
            button.pack(fill='x', padx=12, pady=4)
            self.nav_buttons[key] = button
        tk.Frame(sidebar, height=1, background='#D9D9D9').pack(fill='x', padx=24, pady=25)
        self.ui_label(sidebar, '数据与文件', size=9, color='#626262').pack(anchor='w', padx=24, pady=(0, 10))
        self.open_folder_button = self.ui_button(sidebar, '  数据目录', lambda: self.open_directory(),
                                               style='Nav.TButton', icon='folder', hint='打开当前保存目录，查看原始文本、快照和 Excel。')
        self.open_folder_button.pack(fill='x', padx=12, pady=4)
        self.export_button = self.ui_button(sidebar, '  导出 ZIP', self.export, style='Nav.TButton', icon='archive',
                                           hint='将当前保存目录中的采集记录和批次索引统一打包。')
        self.export_button.pack(fill='x', padx=12, pady=4)
        footer = tk.Frame(sidebar, background=SIDEBAR)
        footer.pack(side='bottom', fill='x', padx=24, pady=24)
        badge = tk.Frame(footer, background='#F2F2F2', padx=12, pady=12)
        badge.pack(fill='x', pady=(0, 16))
        self.ui_label(badge, '原文在本地', color='#262626', size=9, bold=True).pack(anchor='w')
        self.ui_label(badge, '采集 · 存档 · 整理', color='#626262', size=8).pack(anchor='w', pady=(4, 0))
        self.ui_label(footer, f'v{VERSION}', color='#626262', size=8,
                      wraplength=124, justify='left').pack(anchor='w')

    def _build_heading(self, parent):
        header = tk.Canvas(parent, background=BG, highlightthickness=0, borderwidth=0, height=120)
        self.workspace_header = header
        self.workspace_cover = header
        header.grid(row=0, column=0, sticky='ew', pady=(0, 20))
        self.workspace_cover_sources = {key: Image.new('RGBA', (2600, 720), BG)
                                        for key in ('queue', 'capture', 'excel')}
        self.workspace_cover_images = {
            page: ImageTk.PhotoImage(image.resize((2600, 720), Image.Resampling.LANCZOS), master=self.root)
            for page, image in self.workspace_cover_sources.items()
        }
        self.cover_render_key = None
        self.workspace_cover_image = self.workspace_cover_images['queue']
        self.cover_image_item = header.create_image(0, 0, image=self.workspace_cover_image, anchor='center')
        self.cover_kicker_item = header.create_text(0, 0, text='商场数据采集', anchor='w',
            fill='#626262', font=(FONT, 9, 'bold'), tags=('cover_kicker',))
        self.cover_title_item = header.create_text(0, 0, text=self.page_title.get(), anchor='w',
            fill=INK, font=(FONT, 30, 'bold'))
        self.cover_accent = header.create_rectangle(0, 0, 0, 0, fill='#80F000', outline='')
        header.tag_lower(self.cover_accent, self.cover_title_item)
        self.cover_rule = header.create_line(0, 0, 0, 0, fill=LINE)
        self.cover_subtitle_item = header.create_text(0, 0, text=self.page_subtitle.get(), anchor='w',
            fill='#626262', font=(FONT, 9))
        header.create_rectangle(0, 0, 0, 0, fill='#F1F8EE', outline='#D9D9D9', tags=('cover_status_bg',))
        self.activity_badge = header.create_text(0, 0, text=self.activity_label.get(),
            fill='#367D60', font=(FONT, 9, 'bold'), tags=('cover_status',))
        header.create_text(0, 0, text=f'v{VERSION}', anchor='e',
            fill='#626262', font=('Segoe UI', 8, 'bold'), tags=('cover_version',))
        header.bind('<Configure>', self._layout_cover)
        self.page_title.trace_add('write', lambda *_: header.itemconfigure(self.cover_title_item, text=self.page_title.get()))
        self.page_subtitle.trace_add('write', lambda *_: header.itemconfigure(self.cover_subtitle_item, text=self.page_subtitle.get()))
        self.activity_label.trace_add('write', lambda *_: header.itemconfigure(self.activity_badge, text=self.activity_label.get()))

    def _layout_cover(self, event):
        width, height = event.width, event.height
        left = round(8*self.ui_scale)
        page = self.active_page.get()
        render_key = (page, width, height)
        if self.cover_render_key != render_key and width > 1 and height > 1:
            self.cover_render_image = ImageTk.PhotoImage(
                self.workspace_cover_sources[page].resize((width, height), Image.Resampling.LANCZOS), master=self.root)
            self.workspace_cover.itemconfigure(self.cover_image_item, image=self.cover_render_image)
            self.cover_render_key = render_key
        self.workspace_cover.coords(self.cover_image_item, width // 2, height // 2)
        self.workspace_cover.coords(self.cover_kicker_item, left, round(height*.17))
        self.workspace_cover.coords(self.cover_title_item, left, round(height*.40))
        title_box = self.workspace_cover.bbox(self.cover_title_item)
        if title_box:
            self.workspace_cover.coords(self.cover_accent, title_box[0], title_box[3]-round(7*self.ui_scale),
                                         title_box[2], title_box[3]+round(2*self.ui_scale))
        self.workspace_cover.coords(self.cover_rule, 0, height-1, width, height-1)
        self.workspace_cover.coords(self.cover_subtitle_item, left, round(height*.79))
        self.workspace_cover.coords('cover_version', width-left, round(height*.15))
        self.workspace_cover.coords('cover_status', width-left-round(16*self.ui_scale), round(height*.82))
        bbox = self.workspace_cover.bbox('cover_status')
        if bbox:
            pad_x, pad_y = round(12*self.ui_scale), round(7*self.ui_scale)
            self.workspace_cover.coords('cover_status_bg', bbox[0]-pad_x, bbox[1]-pad_y,
                                        bbox[2]+pad_x, bbox[3]+pad_y)

    def _build_summary(self, parent):
        row = tk.Frame(parent, background=BG)
        self.summary_row = row
        row.grid(row=1, column=0, sticky='ew', pady=(0, 14))
        row.columnconfigure(0, weight=3, uniform='summary')
        row.columnconfigure(1, weight=2, uniform='summary')
        first = Card(row, color='#FFFFFF', height=122, padding=14)
        first.grid(row=0, column=0, sticky='nsew', padx=(0, 14))
        frame = first.inner
        frame.columnconfigure(0, weight=1)
        self.summary_heading = self.ui_label(frame, '清单任务', color='#626262', size=8)
        self.summary_heading.grid(row=0, column=0, sticky='w')
        number = tk.Frame(frame, background='#FFFFFF')
        number.grid(row=1, column=0, sticky='w', pady=(0, 0))
        self.ui_label(number, textvariable=self.roster_count_text, size=22, color=INK, bold=True).pack(side='left')
        self.summary_unit = self.ui_label(number, ' 家商场', color='#626262', size=10)
        self.summary_unit.pack(side='left', pady=(7, 0))
        self.summary_progress_label = self.ui_label(frame, textvariable=self.roster_progress_text,
                                                  color='#626262', size=8)
        self.summary_progress_label.grid(row=2, column=0, sticky='w')
        # 三个状态胶囊：比一整句更好扫。文字用"●"配状态色，省掉自绘圆点。
        self.summary_chips = tk.Frame(frame, background='#FFFFFF')
        self.summary_chips.grid(row=2, column=0, sticky='w')
        self.chip_text = {'saved': tk.StringVar(value=''), 'review': tk.StringVar(value=''),
                          'pending': tk.StringVar(value='')}
        for key, color in (('saved', '#398568'), ('review', '#8A6A1F'), ('pending', '#6E6E6E')):
            self.ui_label(self.summary_chips, textvariable=self.chip_text[key], color=color, size=8).pack(
                side='left', padx=(0, 10))
        self.summary_chips.grid_remove()
        self.completion_ring = tk.Canvas(frame, width=64, height=64, background='#FFFFFF', highlightthickness=0)
        self.completion_ring.grid(row=0, column=1, rowspan=3, padx=(8, 0))
        self.completion_ring.create_oval(6, 6, 58, 58, outline='#E4E4E4', width=5)
        self.ring_arc = self.completion_ring.create_arc(6, 6, 58, 58, start=90, extent=0,
                                                      style='arc', outline='#35A82F', width=5)
        self.ring_text = self.completion_ring.create_text(32, 32, text='0%', fill=INK, font=(FONT, 10, 'bold'))
        second = Card(row, color='white', height=104, padding=14)
        second.grid(row=0, column=1, sticky='nsew')
        self.ui_label(second.inner, '本次会话已保存', color=MUTED, size=8).pack(anchor='w')
        value = tk.Frame(second.inner, background='white')
        value.pack(anchor='w')
        self.ui_label(value, textvariable=self.session_count_text, size=22, bold=True, color=INK).pack(side='left')
        self.ui_label(value, ' 次采集', size=10, color='#626262').pack(side='left', pady=(12, 0))
        self.ui_label(second.inner, textvariable=self.session_note_text, color=MUTED, size=8).pack(anchor='w')

    def _build_operations(self, parent):
        card = Card(parent, height=174, padding=18)
        self.operations_card = card
        card.grid(row=2, column=0, sticky='ew', pady=(0, 16))
        card.inner.rowconfigure(0, weight=1)
        card.inner.columnconfigure(0, weight=1)
        self.operations = ttk.Notebook(card.inner, style='Workspace.TNotebook', takefocus=False)
        self.operations.grid(row=0, column=0, sticky='nsew')
        batch = self.batch_panel = ttk.Frame(self.operations)
        queue = self.queue_panel = ttk.Frame(self.operations)
        capture = self.capture_panel = ttk.Frame(self.operations)
        self.operations.add(batch, text='批量整理Excel')
        self.operations.add(queue, text='按商场清单采集')
        self.operations.add(capture, text='单次采集')
        self.queue_widgets, self.batch_widgets = [], []
        head = tk.Frame(queue, background='white')
        head.pack(fill='x')
        self.ui_label(head, '按清单顺序采集', size=12, bold=True).pack(side='left')
        self.import_roster_button = self.ui_button(head, '导入清单', self.choose_roster, icon='import',
                                                 hint=f'支持普通 Excel / CSV；原始数据库只取来源为{SOURCE_VALUE}的名单。')
        self.import_roster_button.pack(side='right')
        self.queue_widgets.append(self.import_roster_button)
        actions = ttk.Frame(queue)
        actions.pack(fill='x', pady=(10, 8))
        self.queue_from_selected_button = self.ui_button(actions, '从选中项往后采集', lambda: self.start_queue(from_selected=True), primary=True,
            hint='从选中商场起按原清单顺序采集。跳过已保存和待确认项；搜索仅筛选显示。采集期间可点击右侧停止。')
        self.queue_from_selected_button.pack(side='left', padx=(0, 8))
        self.queue_widgets.append(self.queue_from_selected_button)
        for text, command, hint in [('开始 / 继续', lambda: self.start_queue(False), '从清单首个待采集项目开始，继续上次进度。'),
                                    ('试采一家', lambda: self.start_queue(True), '仅试采下一个待采集商场。')]:
            button = self.ui_button(actions, text, command, hint=hint)
            button.pack(side='left', padx=(0, 8))
            self.queue_widgets.append(button)
        self.ui_label(queue, textvariable=self.queue_selection, size=9, color=MUTED).pack(anchor='w')
        self.ui_label(capture, '读取当前窗口的文字', size=12, bold=True).pack(anchor='w', pady=(2, 9))
        self.ui_label(capture, '在右侧选好目标窗口和保存位置，再选择采集方式。', color=MUTED, size=9).pack(anchor='w')
        actions = ttk.Frame(capture)
        actions.pack(fill='x', pady=(16, 0))
        self.auto_button = self.ui_button(actions, '自动滚动并采集', lambda: self.capture(True), primary=True, icon='play-white',
            hint='自动滚动目标窗口后保存文字。通用模式保留沿途快照；保持目标窗口前台，按 Esc 可停止。')
        self.auto_button.pack(side='left', padx=(0, 10))
        self.capture_button = self.ui_button(actions, '只读取当前内容', lambda: self.capture(False),
            hint='读取当前已加载且可访问的文字，不自动滚动。')
        self.capture_button.pack(side='left')
        head = tk.Frame(batch, background='white')
        head.pack(fill='x')
        self.ui_label(head, '把采集记录整理为 Excel', size=12, bold=True).pack(side='left')
        convert = self.ui_button(head, '整理并导出', self.convert_excel, primary=True,
                                 hint='批量识别输入目录中的商场记录，生成业态明细和批次索引。')
        convert.pack(side='right')
        self.batch_widgets.append(convert)
        self.ui_label(batch, textvariable=self.batch_input_text, color=MUTED, size=8, wraplength=640).pack(anchor='w', pady=(6, 9))
        actions = ttk.Frame(batch)
        actions.pack(fill='x')
        inputs = ttk.Frame(actions)
        inputs.pack(side='left')
        config = ttk.Frame(actions)
        for text, command, hint in [('选择目录', self.choose_batch_directory, '选择包含采集记录的目录；默认是上方保存目录。'),
                                    ('ZIP / JSON / TXT', self.choose_batch_files, '多选原始ZIP、capture.json 或当前文档 TXT。')]:
            button = self.ui_button(inputs, text, command, hint=hint)
            button.pack(side='left', padx=(0, 7))
            self.batch_widgets.append(button)
        # 输入类与配置类分开：左边是"这次整理哪些"，右边是"按什么规则整理"。
        tk.Frame(actions, background=LINE, width=1).pack(side='left', fill='y', padx=(4, 11), pady=3)
        config.pack(side='left')
        for text, command, hint in [('Excel 模板', self.choose_template, '选含品牌明细 11 字段的 xlsx；不选就用内置模板。'),
                                    ('选对照表', self.choose_mapping, '手工指定 CSV/XLSX；不选则按目录自动识别。'),
                                    ('打开对照表', self.edit_mapping, '打开当前生效的那份对照表，改完保存即生效。')]:
            button = self.ui_button(config, text, command, hint=hint)
            button.pack(side='left', padx=(0, 7))
            self.batch_widgets.append(button)
        def meta_row(pady):
            row = tk.Frame(batch, background='white')
            row.pack(anchor='w', fill='x', pady=pady)
            dot = tk.Canvas(row, width=9, height=9, background='white', highlightthickness=0)
            item = dot.create_oval(1, 1, 8, 8, fill='#C9C9C9', outline='')
            dot.pack(side='left', padx=(0, 7), pady=(4, 0))
            return row, dot, item
        row, self.template_dot, self.template_dot_item = meta_row((7, 0))
        self.template_label = self.ui_label(row, '模板：内置品牌明细 11 字段', color=MUTED, size=8)
        self.template_label.pack(side='left')
        row, self.mapping_dot, self.mapping_dot_item = meta_row((3, 0))
        self.mapping_label = self.ui_label(row, '业态对照表：正在识别…', color=MUTED, size=8,
                                            wraplength=600, justify='left')
        self.mapping_label.pack(side='left')

    def _build_tables(self, parent):
        card = Card(parent, height=260, padding=18)
        card.grid(row=3, column=0, sticky='nsew', pady=(0, 14))
        box = card.inner
        box.columnconfigure(0, weight=1)
        box.rowconfigure(2, weight=1)
        head = tk.Frame(box, background='white')
        head.grid(row=0, column=0, sticky='ew')
        self.ui_label(head, textvariable=self.table_title, size=12, bold=True).pack(side='left')
        self.ui_label(head, textvariable=self.table_count_text, size=9, color=MUTED).pack(side='right')
        tools = tk.Frame(box, background='white')
        tools.grid(row=1, column=0, sticky='ew', pady=(10, 10))
        self.search_entry = ttk.Entry(tools, textvariable=self.roster_search, width=21)
        self.search_entry.pack(side='left')
        self.tooltips[self.search_entry] = Tooltip(self.search_entry, '搜索商场名称、行政区域或状态。仅筛选显示，不改变采集顺序。Ctrl+F')
        self.search_clear = self.ui_button(tools, '清除', lambda: self.roster_search.set(''), style='Quiet.TButton')
        self.search_clear.pack(side='left', padx=4)
        self.search_hint = self.ui_label(tools, '搜索名称 / 区域 / 状态', color=MUTED, size=8)
        self.search_hint.pack(side='left')
        self.retry_button = self.ui_button(tools, '重试选中', self.retry_queue_item, style='Quiet.TButton',
                                          hint='把选中项恢复为待采集，再启动采集；已保存的原文保留。')
        self.retry_button.pack(side='right')
        self.progress_export_button = self.ui_button(tools, '导出进度', self.save_queue_progress, style='Quiet.TButton')
        self.progress_export_button.pack(side='right')
        self.queue_widgets.extend([self.retry_button, self.progress_export_button])
        self.table_tools = tools
        self.tables = ttk.Notebook(box, style='Workspace.TNotebook', takefocus=False)
        self.tables.grid(row=2, column=0, sticky='nsew')
        records_panel = self.records_panel = ttk.Frame(self.tables)
        roster_panel = self.roster_table = ttk.Frame(self.tables)
        self.tables.add(records_panel, text='本次采集记录')
        self.tables.add(roster_panel, text='商场任务清单')
        self.records = self._make_table(records_panel, [('time', '时间', 85), ('name', '采集名称', 200),
            ('chars', '文字数', 85), ('snapshots', '快照数', 70), ('bottom', '底部提示', 100)], height=5)
        self.roster_tree = self._make_table(roster_panel, [('position', '序号', 50), ('row', '原表行', 60),
            ('name', '商场名称', 180), ('district', '区域', 82), ('status', '状态', 116), ('error', '异常原因', 210)], height=5)
        self.roster_tree.configure(displaycolumns=('position', 'name', 'district', 'status', 'row', 'error'))
        self.roster_tree.bind('<<TreeviewSelect>>', self.select_queue_item)
        self.roster_tree.tag_configure('running', foreground='#24531C', background='#F1F6EE')
        self.roster_tree.tag_configure('saved', foreground='#398568')
        self.roster_tree.tag_configure('review', foreground='#806020')
        self.roster_tree.tag_configure('even', background='#FAFAFA')
        self.roster_empty = self.ui_label(roster_panel, textvariable=self.queue_empty_text, color=MUTED,
                                         size=10, justify='center', anchor='center')
        self.records_empty = self.ui_label(records_panel, '还没有采集记录\n完成采集后，保存结果会显示在这里',
                                          color=MUTED, size=10, justify='center', anchor='center')
        self.records_empty.place(relx=.5, rely=.5, anchor='center')
        self.roster_empty.place(relx=.5, rely=.5, anchor='center')

    def _make_table(self, parent, columns, height):
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        table = ttk.Treeview(parent, columns=tuple(key for key, _, _ in columns), show='headings',
                             selectmode='browse', height=height)
        table.grid(row=0, column=0, sticky='nsew')
        for key, title, width in columns:
            table.heading(key, text=title)
            table.column(key, width=width, minwidth=width, stretch=key in ('name', 'error'), anchor='w')
        vertical = ttk.Scrollbar(parent, orient='vertical', command=table.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(parent, orient='horizontal', command=table.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        table.tag_configure('hover', background='#F1F6EE')
        table.bind('<Motion>', lambda event, target=table: self.update_table_hover(target, event), add='+')
        table.bind('<Leave>', lambda _event, target=table: self.clear_table_hover(target), add='+')
        return table

    def update_table_hover(self, table, event):
        if not hasattr(self, 'hovered_table_rows'):
            self.hovered_table_rows = {}
        row = table.identify_row(event.y)
        if self.hovered_table_rows.get(table) == row:
            return
        self.clear_table_hover(table)
        if row:
            tags = tuple(tag for tag in table.item(row, 'tags') if tag != 'hover')
            table.item(row, tags=(*tags, 'hover'))
            self.hovered_table_rows[table] = row

    def clear_table_hover(self, table):
        row = getattr(self, 'hovered_table_rows', {}).pop(table, None)
        if row and table.exists(row):
            table.item(row, tags=tuple(tag for tag in table.item(row, 'tags') if tag != 'hover'))

    def _build_log(self, parent):
        card = Card(parent, height=112, padding=14)
        self.log_card = card
        card.grid(row=4, column=0, sticky='ew')
        box = card.inner
        box.columnconfigure(0, weight=1)
        box.rowconfigure(1, weight=1)
        self.ui_label(box, '运行日志', color=MUTED, size=9, bold=True).grid(row=0, column=0, sticky='w', pady=(0, 6))
        self.log = tk.Text(box, height=2, font=(FONT, 9), background='white', foreground='#626262',
                           relief='flat', highlightthickness=0, wrap='word', state='disabled', cursor='arrow')
        self.log.grid(row=1, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(box, orient='vertical', command=self.log.yview)
        scroll.grid(row=1, column=1, sticky='ns')
        self.log.configure(yscrollcommand=scroll.set)

    def _build_settings(self):
        self.settings_panel = ScrollPanel(self.root, width=306)
        self.settings_panel.grid(row=0, column=2, sticky='ns')
        panel = self.settings_panel.inner
        self._setting_label(panel, '01', '目标窗口')
        self.profile_combo = ttk.Combobox(panel, textvariable=self.capture_profile, values=['商场小程序', '通用窗口文本'], state='readonly')
        self.profile_combo.pack(fill='x', pady=(10, 10))
        self.profile_combo.bind('<<ComboboxSelected>>', self.change_capture_profile)
        self.ui_label(panel, '选择窗口', color=MUTED, size=9).pack(anchor='w', pady=(0, 6))
        self.window_combo = ttk.Combobox(panel, textvariable=self.selected_window, state='readonly', width=22)
        self.window_combo.pack(fill='x')
        self.tooltips[self.window_combo] = Tooltip(self.window_combo, '选择已打开的目标软件窗口。商场清单需选择大众点评小程序的 WeChatAppEx 窗口。')
        self.refresh_button = self.ui_button(panel, '刷新窗口列表', self.refresh_windows, icon='refresh',
                                             hint='重新读取可见窗口。打开目标软件后刷新即可。Ctrl+R')
        self.refresh_button.pack(fill='x', pady=(8, 14))
        self.ui_label(panel, '本次名称', color=MUTED, size=9).pack(anchor='w', pady=(0, 6))
        self.name_entry = ttk.Entry(panel, textvariable=self.label)
        self.name_entry.pack(fill='x')
        self.name_hint = tk.StringVar(value='商场模式填写名称；按清单采集时自动填入')
        self.ui_label(panel, textvariable=self.name_hint, color='#626262', size=8, wraplength=245).pack(anchor='w', pady=(6, 0))
        self._setting_divider(panel)
        self._setting_label(panel, '02', '滚动与保存')
        parameters = tk.Frame(panel, background=panel.cget('background'))
        parameters.pack(fill='x', pady=(12, 9))
        parameters.columnconfigure((0, 1), weight=1, uniform='parameters')
        self.ui_label(parameters, '滚动上限 / 步', color=MUTED, size=8).grid(row=0, column=0, sticky='w', pady=(0, 6))
        self.ui_label(parameters, '每步等待 / 毫秒', color=MUTED, size=8).grid(row=0, column=1, sticky='w', padx=(9, 0), pady=(0, 6))
        self.maximum_steps_input = ttk.Spinbox(parameters, from_=1, to=500, textvariable=self.maximum_steps, width=6)
        self.maximum_steps_input.grid(row=1, column=0, sticky='ew', padx=(0, 6))
        self.wait_input = ttk.Spinbox(parameters, from_=400, to=5000, increment=200, textvariable=self.wait_ms, width=6)
        self.wait_input.grid(row=1, column=1, sticky='ew', padx=(6, 0))
        self.ui_label(panel, '滚动方向（通用模式）', color=MUTED, size=9).pack(anchor='w', pady=(2, 6))
        self.direction_combo = ttk.Combobox(panel, textvariable=self.scroll_direction, values=['向下', '向上'], state='disabled', width=12)
        self.direction_combo.pack(fill='x')
        self.fast_capture_toggle = ttk.Checkbutton(panel, text='滚到底后只保存最终文本', variable=self.final_only)
        self.fast_capture_toggle.pack(anchor='w', pady=(7, 0))
        self.tooltips[self.fast_capture_toggle] = Tooltip(self.fast_capture_toggle, '仅商场模式可用，可减少快照和保存量。通用模式始终保留沿途文本。')
        self.ui_label(panel, '保存位置', color=MUTED, size=9).pack(anchor='w', pady=(8, 6))
        self.output_entry = ttk.Entry(panel, textvariable=self.output)
        self.output_entry.pack(fill='x')
        self.tooltips[self.output_entry] = Tooltip(self.output_entry, self.output.get())
        self.output_button = self.ui_button(panel, '更改保存目录', self.choose_directory, style='Quiet.TButton')
        self.output_button.pack(fill='x', pady=(6, 0))
        self.ui_label(panel, textvariable=self.mode_hint, color='#806020', size=8, wraplength=244, justify='left').pack(fill='x', pady=(14, 4))
        dock = tk.Frame(self.settings_panel, background='#FAFAFA', padx=18, pady=14)
        dock.grid(row=1, column=0, columnspan=2, sticky='ew')
        tk.Frame(dock, height=1, background=LINE).pack(fill='x', pady=(0, 12))
        self._setting_label(dock, '03', '当前状态')
        self.ui_label(dock, textvariable=self.status_preview, color=MUTED, size=9, wraplength=265,
                      justify='left', height=3).pack(fill='x', pady=(8, 8))
        self.progress = ttk.Progressbar(dock, mode='indeterminate', style='Capture.Horizontal.TProgressbar')
        self.progress.pack(fill='x')
        self.stop_button = self.ui_button(dock, '停止并保留已读内容', self.stop, style='Danger.TButton', hint='请求停止采集并保留已完成的快照。也可在目标窗口按 Esc。')
        self.stop_button.pack(fill='x', pady=(12, 0))
        self.stop_button.configure(state='disabled')
        self.settings_panel.bind_wheel()

    def _setting_label(self, parent, number, text):
        row = tk.Frame(parent, background=parent.cget('background'))
        row.pack(fill='x')
        self.ui_label(row, number, color='#626262', size=9, bold=True).pack(side='left', padx=(0, 8))
        self.ui_label(row, text, size=10, bold=True).pack(side='left')

    @staticmethod
    def _setting_divider(parent):
        tk.Frame(parent, background=LINE, height=1).pack(fill='x', pady=20)

    def navigate_workspace(self, page):
        if page in ('queue', 'excel') and self.capture_profile.get() == '通用窗口文本':
            return
        panel = {'capture': self.capture_panel, 'queue': self.queue_panel, 'excel': self.batch_panel}[page]
        self.operations.select(panel)
        self.tables.select(self.roster_table if page == 'queue' else self.records_panel)
        self.sync_workspace()

    def sync_workspace(self):
        selected = self.operations.select()
        page = 'queue' if selected == str(self.queue_panel) else ('excel' if selected == str(self.batch_panel) else 'capture')
        self.active_page.set(page)
        title, subtitle = {'queue': ('商场清单', '导入名单，选择起点，按顺序采集每一家商场。'),
                           'capture': ('单次采集', '读取一个窗口，让可访问的文字成为可保存的记录。'),
                           'excel': ('批量 Excel', '选择已有采集记录，批量整理为品牌与业态明细。')}[page]
        self.page_title.set(title)
        self.page_subtitle.set(subtitle)
        kicker = {'queue': '商场数据采集', 'capture': '当前窗口 · 原文留存', 'excel': '品牌与业态整理'}[page]
        self.workspace_cover.itemconfigure(self.cover_kicker_item, text=kicker)
        self.workspace_cover_image = self.workspace_cover_images[page]
        self.workspace_cover.itemconfigure(self.cover_image_item, image=self.workspace_cover_image)
        if hasattr(self, 'cover_render_key'):
            self.cover_render_key = None
            event = type('CoverSize', (), {'width': self.workspace_cover.winfo_width(),
                                         'height': self.workspace_cover.winfo_height()})()
            self._layout_cover(event)
        if hasattr(self, 'cover_title_item'):
            self.workspace_cover.itemconfigure(self.cover_title_item, text=title)
            self.workspace_cover.itemconfigure(self.cover_subtitle_item, text=subtitle)
        for key, button in self.nav_buttons.items():
            button.state(['selected'] if page == key else ['!selected'])
        self.table_title.set('商场任务清单' if page == 'queue' else '本次采集记录')
        if page == 'queue':
            self.table_tools.grid()
        else:
            self.table_tools.grid_remove()
        self.update_workspace_counts()

        if hasattr(self, 'layout_pending'):
            self.adapt_layout()

    def update_workspace_counts(self):
        items = self.roster['items'] if self.roster else []
        total = len(items)
        saved = sum(item['status'] == '已保存（待复核）' for item in items)
        review = sum(item['status'] == '待确认' for item in items)
        pending = sum(item['status'] == '待采集' for item in items)
        general = self.capture_profile.get() == '通用窗口文本'
        self.roster_count_text.set('通用' if general else str(total))
        self.summary_heading.configure(text='当前采集模式' if general else '清单任务')
        self.summary_unit.configure(text=' 窗口原文' if general else ' 家商场')
        self.roster_progress_text.set('已加载文字 · 沿途快照 · 本地存档' if general else
            (f'已保存 {saved}  ·  待采集 {pending}  ·  待确认 {review}' if total else '导入商场清单，建立你的采集任务'))
        if general or not total:
            self.summary_chips.grid_remove()
            self.summary_progress_label.grid()
        else:
            self.summary_progress_label.grid_remove()
            self.summary_chips.grid()
            self.chip_text['saved'].set(f'● {saved} 已保存')
            self.chip_text['review'].set(f'● {review} 待确认')
            self.chip_text['pending'].set(f'● {pending} 待采集')
        percentage = round(saved / total * 100) if total else 0
        self.completion_ring.itemconfigure(self.ring_arc, extent=-.01 if general else -max(.01, percentage*3.599))
        self.completion_ring.itemconfigure(self.ring_text, text='TXT' if general else f'{percentage}%')
        count = len(self.records.get_children())
        self.session_count_text.set(str(count))
        if count:
            self.records_empty.place_forget()
            latest = str(self.records.item(self.records.get_children()[-1], 'values')[0])
            self.session_note_text.set(f'最近一次 {latest}  ·  原文保留')
        else:
            self.session_note_text.set('原文保留  ·  随时导出')
        if self.active_page.get() == 'queue':
            shown = len(self.roster_tree.get_children())
            self.table_count_text.set(f'{shown} / {total} 项任务' if self.roster_search.get() else f'{total} 项任务')
        else:
            self.table_count_text.set(f'{count} 次保存')

    def filter_roster(self, *_args):
        if not self.roster:
            return
        query = self.roster_search.get().strip().casefold()
        selection = self.roster_tree.selection()
        if selection:
            self.roster_saved_selection = selection
        for item in self.roster['items']:
            task_id = item['task_id']
            matches = not query or query in ' '.join(str(item.get(key, '')) for key in ('name', 'district', 'status')).casefold()
            if matches:
                self.roster_tree.reattach(task_id, '', 'end')
            else:
                self.roster_tree.detach(task_id)
        visible = set(self.roster_tree.get_children())
        selected = tuple(key for key in self.roster_saved_selection if key in visible)
        self.roster_tree.selection_set(selected)
        self.queue_empty_text.set('没有匹配的任务\n试试其他名称、区域或状态' if query else f'从一份商场清单开始\n支持 Excel / CSV，原始数据库自动筛选来源={SOURCE_VALUE}')
        if visible:
            self.roster_empty.place_forget()
        else:
            self.roster_empty.place(relx=.5, rely=.5, anchor='center')
        self.update_workspace_counts()
        self.select_queue_item()

    def focus_roster_search(self, _event=None):
        if self.capture_profile.get() != '通用窗口文本':
            self.navigate_workspace('queue')
            self.search_entry.focus_set()
            self.search_entry.selection_range(0, 'end')
        return 'break'

    def refresh_status_preview(self, *_args):
        value = self.status.get().replace('\n', ' ')
        self.status_preview.set(value[:58] + '…' if len(value) > 58 else value)
        hint = self.tooltips.get(self.output_entry)
        if hint:
            hint.text = self.output.get()

    def schedule_layout(self, event):
        if event.widget == self.root:
            if self.layout_pending:
                self.root.after_cancel(self.layout_pending)
            self.layout_pending = self.root.after(80, self.adapt_layout)

    def cancel_layout_on_destroy(self, event):
        if event.widget == self.root and self.layout_pending:
            try:
                self.root.after_cancel(self.layout_pending)
            except tk.TclError:
                pass
            self.layout_pending = None

    def batch_page_required_height(self):
        """批量Excel页需要的高度：内容实际高度 + 卡片内边距，封顶免得挤掉表格。"""
        page = getattr(self, 'batch_panel', None)
        if page is None:
            return 180
        needed = page.winfo_reqheight() + self.operations_card.padding * 2
        cap = round(232 * self.ui_scale)
        return max(180, min(needed, cap))

    def adapt_layout(self):
        self.layout_pending = None
        factor = self.ui_scale
        compact = self.root.winfo_height() < round(830*factor)
        if compact:
            self.summary_row.grid_remove()
        else:
            self.summary_row.grid()
        self.operations_card.padding = round((12 if compact else 14)*factor)
        self.operations_card.coords(self.operations_card.window, self.operations_card.padding, self.operations_card.padding)
        operation_height = 180 if self.active_page.get() == 'excel' else (146 if compact else 154)
        if self.active_page.get() == 'excel':
            # 对照表提示的文字长度随表名变化，按实际需要的高度给卡片留位，避免提示被裁掉。
            operation_height = max(operation_height, self.batch_page_required_height())
        self.operations_card.configure(height=round(operation_height*factor))
        self.log_card.padding = round((10 if compact else 14)*factor)
        self.log_card.coords(self.log_card.window, self.log_card.padding, self.log_card.padding)
        self.log_card.configure(height=round((84 if compact else 96)*factor))
        self.workspace_header.grid_configure(pady=(0, round((12 if compact else 20)*factor)))
        self.workspace_header.configure(height=round((84 if compact else 120)*factor))
        self.workspace_header.itemconfigure(self.cover_kicker_item, state='hidden')
        self.workspace_header.itemconfigure(self.cover_title_item, font=(FONT, 23 if compact else 30, 'bold'))
        self.workspace_header.grid_configure(pady=(0, round((7 if compact else 16)*factor)))
        if self.root.winfo_width() < round(1260*factor):
            self.search_hint.pack_forget()
        elif not self.search_hint.winfo_manager():
            self.search_hint.pack(side='left')
