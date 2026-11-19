#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hardware Analyzer —— Tkinter 图形界面

设计要点
--------
1. 三区布局：顶栏 48px(#1f2d3d) → 步骤条 → 左栏(输入树)/中区(卡片)/右栏(参数摘要) → 状态栏
2. 步骤条是真实流程映射：① 选择输入 → ② 配置参数 → ③ 分析中 → ④ 查看报告
3. 控件严格对应 src/main.py 的 argparse 参数（-s/-n/-d/-m/-o + 6 个掉压参数）
4. 执行方式：subprocess.Popen 逐行读取 stdout/stderr 到日志框（真实日志流，无假进度条）
   源码运行：[python, main.py, ...]
   打包运行：[自身.exe, --kernel-args-file, 一次性JSON]（由 app_entry.py 分发，不二次解压）
5. 所有异常统一由 _report_unhandled() 兜底，弹 messagebox 而不是静默退出

用法：
  python src/gui.py                 # 源码方式启动
  HardwareAnalyzer_GUI.exe          # 打包后双击启动
"""
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "Hardware Analyzer —— 硬件分析工具"
APP_SUBTITLE = "纯标准库 ｜ 只读模式"

# 配色（与设计稿一致）
C_TOPBAR = "#1f2d3d"
C_TOPBAR_TEXT = "#e8eef5"
C_TOPBAR_SUB = "#8fa3b8"
C_BG = "#f4f6f8"
C_PANEL = "#ffffff"
C_BORDER = "#d8dee6"
C_TEXT = "#1f2d3d"
C_MUTED = "#6b7a8c"
C_ACCENT = "#2d7ff9"
C_ACCENT_DK = "#1c6ae0"
C_OK = "#1f9d55"
C_WARN = "#d97706"
C_ERR = "#dc2626"
C_STEP_IDLE = "#c9d2dc"
C_STEP_DONE = "#1f9d55"
C_STEP_ACTIVE = "#2d7ff9"

# 与 build/create_entry.py 的 KERNEL_ARGS_FLAG 一致
KERNEL_ARGS_FLAG = "--kernel-args-file"

ANALYSIS_MODES = [
    ("full", "完整分析"),
    ("power", "电源"),
    ("signal", "信号"),
    ("clock", "时钟"),
    ("interface", "接口"),
    ("diagnostic", "诊断"),
]


def is_frozen():
    """是否为打包后的 EXE。

    两种打包器的标志不同，必须都认：
      · PyInstaller → sys.frozen = True
      · Nuitka      → 不多写 sys.frozen，而是在被编译的模块里注入
                      __compiled__ 全局变量，同时 sys.frozen 保持缺失。

    只判断 sys.frozen 的话（历史实现），Nuitka 产物会被误判成「源码模式」：
    gui.py 于是去 __file__ 同级目录找 main.py —— 而 onefile 的 __file__
    指向临时解包目录，里面只有编译后的模块、没有 .py 源文件，最终弹
    「源码模式需要 src/ 与 gui.py 在同一目录」并且连分析都跑不起来。
    """
    if getattr(sys, "frozen", False):
        return True
    return "__compiled__" in globals()


def exe_path():
    """返回「用户实际拿到的那份 EXE」的绝对路径。

    Nuitka --onefile 的坑（实测确认）
    ---------------------------------
    打包后运行，sys.executable 指向的是**解包临时目录里的 python.exe**：

        sys.executable = <解包临时目录>\python.exe
        sys.argv[0]    = <发布目录>\HardwareAnalyzer_GUI.exe      ← 真实 EXE

    如果照 PyInstaller 的习惯用 sys.executable 启动子进程，会得到：

        [CMD] python.exe --kernel-args-file ...
        [DIR] 工作目录: <解包临时目录>
        [ERROR] 启动失败: [WinError 2] 系统找不到指定的文件。

    因为那个 python.exe 只是解包目录里的陪衬，拿它去 Popen 必然找不到；
    拿它的 parent 当 cwd 也会把工作目录指到临时解包目录。

    只有 sys.argv[0] 才是用户点击的那个 EXE 的真实路径，所以打包态用它。
    """
    if is_frozen():
        return Path(sys.argv[0]).resolve()
    return Path(sys.executable).resolve()


def app_base_dir():
    """程序所在目录（打包态取 EXE 目录，源码态取 src 的父目录）。"""
    if is_frozen():
        # 不能用 Path(sys.executable).parent —— onefile 下那是临时解包目录
        return exe_path().parent
    return Path(__file__).resolve().parent.parent


def default_report_dir():
    """默认报告输出目录。"""
    return app_base_dir() / "reports"


def write_kernel_args_file(args):
    """把分析参数写成一次性 JSON 文件，返回路径。

    为什么不用环境变量传参？
      环境变量是「继承 + 持久 + 全局」的。若系统里恰好残留同名变量，
      或本程序从设置过该变量的父进程启动，那么「双击无参数启动」也会被
      误判成 GUI 派生的内核进程 —— 窗口打不开、还莫名其妙跑了一次分析。
      改成一次性文件后，参数是显式、独占、用完即删的，不存在被继承的问题。
    """
    fd, path = tempfile.mkstemp(prefix="hwa_args_", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(list(args), fh, ensure_ascii=False)
    return path


def build_cli_command(main_py, args):
    """构造分析内核命令行（源码 / 打包两种模式）。

    - 源码运行：[python, main.py, ...]                   参数直接上命令行
    - 打包运行：[真实EXE, KERNEL_ARGS_FLAG, 参数文件]     参数走一次性文件

    打包模式为什么不把参数直接拼到命令行？
      onefile 的 EXE 在带参数启动时，父进程会先把自身"再解压一次"给子进程，
      而 GUI 自身就运行在这个解压目录里，等于同一份程序被解压两遍（耗时+占空间）。
      改成"同一个 EXE、只多一个参数文件路径"后，解压目录被复用，
      同时避免路径含空格/引号/中文时的转义问题。
      入口文件 app_entry.py 的 run_cli_env() 负责读取并删除该文件。

    打包模式为什么用 exe_path() 而不是 sys.executable？
      见 exe_path() 文档：onefile 下 sys.executable 是解包临时目录里的
      python.exe，拿它 Popen 会 WinError 2。
    """
    if is_frozen():
        return [str(exe_path()), KERNEL_ARGS_FLAG, write_kernel_args_file(args)]
    return [sys.executable, str(main_py)] + list(args)


class HardwareAnalyzerGUI:
    """主窗口：顶栏 + 步骤条 + 三栏工作区 + 状态栏。"""

    def __init__(self, root):
        self.root = root
        self.proc = None            # subprocess.Popen
        self.log_queue = queue.Queue()
        self.report_dir = None      # 本次分析输出目录（StringVar 同步）
        self._step = 1              # 当前步骤 1..4
        self._left_labels = []      # 左栏输入树的行（结构化状态）

        self._init_window()
        self._init_vars()
        self._build_topbar()
        self._build_stepbar()
        self._build_body()
        self._build_statusbar()

        self._refresh_inputs()
        self._refresh_cards()
        self.set_step(1)
        self.root.after(120, self._pump_log_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- 窗口 ----------------
    def _init_window(self):
        self.root.title(APP_TITLE)
        self.root.configure(bg=C_BG)
        self.root.minsize(1080, 680)

        w, h = 1240, 800
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 3)
            self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))
        except tk.TclError:
            self.root.geometry("%dx%d" % (w, h))

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=C_BG)
        style.configure("Panel.TFrame", background=C_PANEL)
        style.configure("Card.TFrame", background=C_PANEL,
                        relief="solid", borderwidth=1)
        style.configure("TLabel", background=C_BG, foreground=C_TEXT,
                        font=("Microsoft YaHei UI", 9))
        style.configure("Panel.TLabel", background=C_PANEL, foreground=C_TEXT,
                        font=("Microsoft YaHei UI", 9))
        style.configure("Muted.TLabel", background=C_PANEL, foreground=C_MUTED,
                        font=("Microsoft YaHei UI", 8))
        style.configure("Head.TLabel", background=C_PANEL, foreground=C_TEXT,
                        font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TButton", font=("Microsoft YaHei UI", 9), padding=(10, 5))
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"),
                        padding=(14, 7))
        style.configure("TCheckbutton", background=C_PANEL, foreground=C_TEXT,
                        font=("Microsoft YaHei UI", 9))
        style.configure("TRadiobutton", background=C_PANEL, foreground=C_TEXT,
                        font=("Microsoft YaHei UI", 9))
        style.configure("TNotebook", background=C_BG, borderwidth=0)
        style.configure("TNotebook.Tab", font=("Microsoft YaHei UI", 9),
                        padding=(14, 6))

    def _init_vars(self):
        """所有 Tk 变量集中在这里，便于 _refresh_* 统一读写。"""
        self.var_schematic = tk.StringVar()
        self.var_netlist = tk.StringVar()
        self.var_deliverables = tk.StringVar()
        self.var_ipc2581 = tk.StringVar()
        self.var_gerber = tk.StringVar()
        self.var_mode = tk.StringVar(value="full")
        self.var_output = tk.StringVar(value=str(default_report_dir()))
        # 掉压参数（均对应 main.py 的 argparse）
        self.var_istep = tk.StringVar(value="1.0")
        self.var_dt_us = tk.StringVar(value="10.0")
        self.var_trise_us = tk.StringVar(value="1.0")
        self.var_esr_mohm = tk.StringVar(value="")
        self.var_esl_nh = tk.StringVar(value="")
        self.var_ripple_mv = tk.StringVar(value="50.0")
        self.var_status = tk.StringVar(value="就绪")
        self.var_step_hint = tk.StringVar(value="请选择输入文件或目录，然后开始分析")
        # 实时刷新左栏与右栏摘要
        for v in (self.var_schematic, self.var_netlist, self.var_deliverables,
                  self.var_ipc2581, self.var_gerber, self.var_mode, self.var_output,
                  self.var_istep, self.var_dt_us, self.var_trise_us,
                  self.var_esr_mohm, self.var_esl_nh, self.var_ripple_mv):
            v.trace_add("write", lambda *_: self._on_var_changed())

    # ---------------- 顶栏 ----------------
    def _build_topbar(self):
        bar = tk.Frame(self.root, bg=C_TOPBAR, height=48)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)

        left = tk.Frame(bar, bg=C_TOPBAR)
        left.pack(side="left", fill="y", padx=16)
        tk.Label(left, text="Hardware Analyzer", bg=C_TOPBAR, fg=C_TOPBAR_TEXT,
                 font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")
        tk.Label(left, text="   " + APP_SUBTITLE, bg=C_TOPBAR, fg=C_TOPBAR_SUB,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")

        right = tk.Frame(bar, bg=C_TOPBAR)
        right.pack(side="right", fill="y", padx=16)
        self.btn_open_report = tk.Button(
            right, text="打开报告目录", command=self.open_report_dir,
            bg=C_TOPBAR, fg=C_TOPBAR_TEXT, activebackground=C_ACCENT,
            activeforeground="#ffffff", relief="flat", bd=0,
            font=("Microsoft YaHei UI", 9), padx=12, cursor="hand2")
        self.btn_open_report.pack(side="right", pady=11)

    # ---------------- 步骤条 ----------------
    def _build_stepbar(self):
        wrap = tk.Frame(self.root, bg=C_BG)
        wrap.pack(side="top", fill="x", padx=16, pady=(12, 4))

        self._step_widgets = []
        specs = [("1", "选择输入"), ("2", "配置参数"), ("3", "开始分析"), ("4", "查看报告")]
        for idx, (num, label) in enumerate(specs, start=1):
            cell = tk.Frame(wrap, bg=C_BG)
            cell.pack(side="left", padx=(0, 26))

            dot = tk.Canvas(cell, width=26, height=26, bg=C_BG,
                            highlightthickness=0, bd=0)
            dot.pack(side="left")
            oval = dot.create_oval(2, 2, 24, 24, fill=C_STEP_IDLE, outline=C_STEP_IDLE)
            text = dot.create_text(13, 13, text=num, fill="#ffffff",
                                   font=("Microsoft YaHei UI", 9, "bold"))

            cap = tk.Label(cell, text=label, bg=C_BG, fg=C_MUTED,
                           font=("Microsoft YaHei UI", 9))
            cap.pack(side="left", padx=(6, 0))
            self._step_widgets.append((dot, oval, text, cap))

        hint = tk.Label(wrap, textvariable=self.var_step_hint, bg=C_BG, fg=C_MUTED,
                        font=("Microsoft YaHei UI", 8))
        hint.pack(side="right")

    def set_step(self, step):
        """更新步骤条高亮。"""
        self._step = max(1, min(4, int(step)))
        for i, (dot, oval, text, cap) in enumerate(self._step_widgets, start=1):
            if i < self._step:
                color, fg = C_STEP_DONE, "#ffffff"
            elif i == self._step:
                color, fg = C_STEP_ACTIVE, "#ffffff"
            else:
                color, fg = C_STEP_IDLE, "#ffffff"
            try:
                dot.itemconfigure(oval, fill=color, outline=color)
                dot.itemconfigure(text, text=("✓" if i < self._step else str(i)), fill=fg)
                cap.configure(fg=(C_TEXT if i <= self._step else C_MUTED),
                              font=("Microsoft YaHei UI", 9,
                                    "bold" if i == self._step else "normal"))
            except tk.TclError:
                pass

    # ---------------- 主体 ----------------
    def _build_body(self):
        body = tk.Frame(self.root, bg=C_BG)
        body.pack(side="top", fill="both", expand=True, padx=16, pady=(4, 8))

        # 左栏：输入来源
        left = tk.Frame(body, bg=C_PANEL, highlightbackground=C_BORDER,
                        highlightthickness=1, width=290)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self._left_frame = left

        tk.Label(left, text="输入来源", bg=C_PANEL, fg=C_TEXT,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(
            anchor="w", padx=14, pady=(12, 6))

        self._input_box = tk.Frame(left, bg=C_PANEL)
        self._input_box.pack(fill="x", padx=10)

        tk.Label(left, text="提示：原理图 / Netlist / PCB交付件 至少提供一项；\n"
                            "交付件目录会自动递归查找 xy.xlsx / *.ipc / *.dxf。",
                 bg=C_PANEL, fg=C_MUTED, justify="left",
                 font=("Microsoft YaHei UI", 8)).pack(
            anchor="w", padx=14, pady=(10, 12))

        # 中区：参数 + 日志
        center = tk.Frame(body, bg=C_BG)
        center.pack(side="left", fill="both", expand=True, padx=10)

        self._notebook = ttk.Notebook(center)
        self._notebook.pack(fill="both", expand=True)

        self._tab_params = tk.Frame(self._notebook, bg=C_PANEL)
        self._tab_log = tk.Frame(self._notebook, bg=C_PANEL)
        self._notebook.add(self._tab_params, text="分析参数")
        self._notebook.add(self._tab_log, text="运行日志")

        self._build_params_tab(self._tab_params)
        self._build_log_tab(self._tab_log)

        # 右栏：参数摘要 + 操作
        right = tk.Frame(body, bg=C_PANEL, highlightbackground=C_BORDER,
                         highlightthickness=1, width=280)
        right.pack(side="left", fill="y")
        right.pack_propagate(False)
        self._right_frame = right

        tk.Label(right, text="参数摘要", bg=C_PANEL, fg=C_TEXT,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(
            anchor="w", padx=14, pady=(12, 6))

        self._summary_box = tk.Frame(right, bg=C_PANEL)
        self._summary_box.pack(fill="both", expand=True, padx=14)

        btnbar = tk.Frame(right, bg=C_PANEL)
        btnbar.pack(side="bottom", fill="x", padx=14, pady=14)

        self.btn_start = tk.Button(
            btnbar, text="开始分析", command=self.start_analysis,
            bg=C_ACCENT, fg="#ffffff", activebackground=C_ACCENT_DK,
            activeforeground="#ffffff", relief="flat", bd=0,
            font=("Microsoft YaHei UI", 11, "bold"), pady=9, cursor="hand2")
        self.btn_start.pack(fill="x")

        self.btn_report = tk.Button(
            btnbar, text="查看报告", command=self.open_report_dir,
            bg="#e8eef5", fg=C_TEXT, activebackground="#d8dee6",
            relief="flat", bd=0, font=("Microsoft YaHei UI", 9),
            pady=7, cursor="hand2", state="disabled")
        self.btn_report.pack(fill="x", pady=(8, 0))

    def _build_input_row(self, parent, label, var, kind):
        """左栏一行输入：标题 + 当前值 + 选择按钮。"""
        row = tk.Frame(parent, bg=C_PANEL)
        row.pack(fill="x", pady=(0, 8))

        head = tk.Frame(row, bg=C_PANEL)
        head.pack(fill="x")
        tk.Label(head, text=label, bg=C_PANEL, fg=C_TEXT,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Button(head, text="选择" if kind != "dir" else "选择目录",
                  command=lambda v=var, k=kind: self._pick(v, k),
                  bg="#e8eef5", fg=C_TEXT, relief="flat", bd=0,
                  font=("Microsoft YaHei UI", 8), padx=8, pady=2,
                  cursor="hand2").pack(side="right")

        val = tk.Label(row, textvariable=var, bg="#f7f9fb", fg=C_MUTED,
                       anchor="w", justify="left", wraplength=250,
                       font=("Microsoft YaHei UI", 8), padx=6, pady=4)
        val.pack(fill="x", pady=(3, 0))

        clear = tk.Button(row, text="清除", command=lambda v=var: v.set(""),
                          bg=C_PANEL, fg=C_MUTED, relief="flat", bd=0,
                          font=("Microsoft YaHei UI", 8), cursor="hand2")
        clear.pack(anchor="e")
        return row

    def _pick(self, var, kind):
        """打开文件/目录选择框。"""
        try:
            if kind == "dir":
                path = filedialog.askdirectory(title="选择目录", parent=self.root)
            elif kind == "sch":
                path = filedialog.askopenfilename(
                    title="选择原理图", parent=self.root,
                    filetypes=[("原理图", "*.sch *.Sch *.SCH *.kicad_sch *.dsn"),
                               ("所有文件", "*.*")])
            elif kind == "net":
                path = filedialog.askopenfilename(
                    title="选择 Netlist", parent=self.root,
                    filetypes=[("Netlist", "*.net *.NET *.txt"), ("所有文件", "*.*")])
            elif kind == "xml":
                path = filedialog.askopenfilename(
                    title="选择 IPC-2581 XML", parent=self.root,
                    filetypes=[("IPC-2581", "*.xml *.XML"), ("所有文件", "*.*")])
            else:
                path = filedialog.askopenfilename(
                    title="选择文件", parent=self.root, filetypes=[("所有文件", "*.*")])
        except tk.TclError:
            return
        if path:
            var.set(path)

    # ---------------- 参数页 ----------------
    def _build_params_tab(self, parent):
        wrap = tk.Frame(parent, bg=C_PANEL)
        wrap.pack(fill="both", expand=True, padx=16, pady=14)

        # —— 分析模式 ——
        sec1 = tk.LabelFrame(wrap, text=" 分析模式 ", bg=C_PANEL, fg=C_TEXT,
                             font=("Microsoft YaHei UI", 9, "bold"),
                             bd=1, relief="solid", labelanchor="nw")
        sec1.pack(fill="x", pady=(0, 12))
        grid1 = tk.Frame(sec1, bg=C_PANEL)
        grid1.pack(fill="x", padx=12, pady=10)
        for i, (value, text) in enumerate(ANALYSIS_MODES):
            ttk.Radiobutton(grid1, text=text, value=value,
                            variable=self.var_mode).grid(
                row=i // 3, column=i % 3, sticky="w", padx=(0, 26), pady=4)

        # —— 输出目录 ——
        sec2 = tk.LabelFrame(wrap, text=" 输出目录 ", bg=C_PANEL, fg=C_TEXT,
                             font=("Microsoft YaHei UI", 9, "bold"),
                             bd=1, relief="solid", labelanchor="nw")
        sec2.pack(fill="x", pady=(0, 12))
        row2 = tk.Frame(sec2, bg=C_PANEL)
        row2.pack(fill="x", padx=12, pady=10)
        tk.Entry(row2, textvariable=self.var_output, relief="solid", bd=1,
                 font=("Microsoft YaHei UI", 9)).pack(
            side="left", fill="x", expand=True, ipady=4)
        tk.Button(row2, text="浏览", command=self._pick_output,
                  bg="#e8eef5", fg=C_TEXT, relief="flat", bd=0,
                  font=("Microsoft YaHei UI", 9), padx=12, pady=4,
                  cursor="hand2").pack(side="left", padx=(8, 0))

        # —— 母线瞬态掉压参数 ——
        sec3 = tk.LabelFrame(wrap, text=" 母线瞬态掉压参数（留空则按封装自动查表） ",
                             bg=C_PANEL, fg=C_TEXT,
                             font=("Microsoft YaHei UI", 9, "bold"),
                             bd=1, relief="solid", labelanchor="nw")
        sec3.pack(fill="x")
        grid3 = tk.Frame(sec3, bg=C_PANEL)
        grid3.pack(fill="x", padx=12, pady=10)

        fields = [
            ("瞬态电流阶跃 I_step (A)", self.var_istep, "--istep"),
            ("负载持续时间 Δt (us)", self.var_dt_us, "--dt-us"),
            ("电流上升时间 t_rise (us)", self.var_trise_us, "--trise-us"),
            ("允许纹波/跌落 V_ripple (mV)", self.var_ripple_mv, "--ripple-mv"),
            ("电容 ESR (mΩ，可选)", self.var_esr_mohm, "--esr-mohm"),
            ("电容 ESL (nH，可选)", self.var_esl_nh, "--esl-nh"),
        ]
        for i, (label, var, flag) in enumerate(fields):
            r, c = i // 2, (i % 2) * 2
            tk.Label(grid3, text=label, bg=C_PANEL, fg=C_TEXT,
                     font=("Microsoft YaHei UI", 9)).grid(
                row=r, column=c, sticky="w", padx=(0, 8), pady=6)
            tk.Entry(grid3, textvariable=var, width=12, relief="solid", bd=1,
                     font=("Microsoft YaHei UI", 9),
                     justify="right").grid(row=r, column=c + 1,
                                           sticky="w", padx=(0, 26), ipady=3)

    def _pick_output(self):
        path = filedialog.askdirectory(title="选择输出目录", parent=self.root)
        if path:
            self.var_output.set(path)

    # ---------------- 日志页 ----------------
    def _build_log_tab(self, parent):
        wrap = tk.Frame(parent, bg=C_PANEL)
        wrap.pack(fill="both", expand=True)

        bar = tk.Frame(wrap, bg=C_PANEL)
        bar.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(bar, text="内核实时输出", bg=C_PANEL, fg=C_TEXT,
                 font=("Microsoft YaHei UI", 9, "bold")).pack(side="left")
        tk.Button(bar, text="清空", command=self.clear_log,
                  bg="#e8eef5", fg=C_TEXT, relief="flat", bd=0,
                  font=("Microsoft YaHei UI", 8), padx=10, pady=2,
                  cursor="hand2").pack(side="right")

        holder = tk.Frame(wrap, bg=C_PANEL)
        holder.pack(fill="both", expand=True, padx=12, pady=(6, 12))

        self.txt_log = tk.Text(holder, bg="#101820", fg="#d6e2ee", bd=0,
                               relief="flat", wrap="none",
                               font=("Consolas", 9), insertbackground="#d6e2ee",
                               padx=10, pady=8)
        vsb = ttk.Scrollbar(holder, orient="vertical", command=self.txt_log.yview)
        hsb = ttk.Scrollbar(holder, orient="horizontal", command=self.txt_log.xview)
        self.txt_log.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.txt_log.pack(side="left", fill="both", expand=True)

        self.txt_log.tag_configure("head", foreground="#7fd1ff")
        self.txt_log.tag_configure("ok", foreground="#6ee7a8")
        self.txt_log.tag_configure("err", foreground="#ff8f8f")
        self.txt_log.tag_configure("warn", foreground="#ffd479")
        self.txt_log.configure(state="disabled")

    # ---------------- 状态栏 ----------------
    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg="#e8eef5", height=28)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)

        self.lbl_status = tk.Label(bar, textvariable=self.var_status, bg="#e8eef5",
                                   fg=C_MUTED, anchor="w",
                                   font=("Microsoft YaHei UI", 8))
        self.lbl_status.pack(side="left", padx=16)
        tk.Label(bar, text="只读模式 ｜ 不修改任何输入文件", bg="#e8eef5",
                 fg=C_MUTED, font=("Microsoft YaHei UI", 8)).pack(side="right", padx=16)

    # ---------------- 状态刷新 ----------------
    def _on_var_changed(self):
        """任一变量变化时刷新左栏与右栏摘要。"""
        self._refresh_inputs()
        self._refresh_summary()
        if self._step < 3:
            has_input = bool(self._active_inputs())
            self.set_step(2 if has_input else 1)

    def _active_inputs(self):
        """返回当前已填写的输入项列表 [(标签, 路径), ...]。"""
        items = []
        for label, var in (("原理图", self.var_schematic),
                           ("Netlist", self.var_netlist),
                           ("PCB交付件", self.var_deliverables),
                           ("IPC-2581", self.var_ipc2581),
                           ("Gerber", self.var_gerber)):
            path = (var.get() or "").strip()
            if path:
                items.append((label, path))
        return items

    def _refresh_inputs(self):
        """重建左栏输入树。"""
        for child in self._input_box.winfo_children():
            child.destroy()

        specs = [
            ("原理图", self.var_schematic, "sch"),
            ("Netlist", self.var_netlist, "net"),
            ("PCB交付件目录", self.var_deliverables, "dir"),
            ("IPC-2581 XML", self.var_ipc2581, "xml"),
            ("Gerber 目录", self.var_gerber, "dir"),
        ]
        self._left_labels = []
        for label, var, kind in specs:
            self._build_input_row(self._input_box, label, var, kind)
            self._left_labels.append((label, var))

    def _refresh_summary(self):
        """重建右栏参数摘要。"""
        for child in self._summary_box.winfo_children():
            child.destroy()

        def add(k, v, color=C_TEXT):
            row = tk.Frame(self._summary_box, bg=C_PANEL)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=k, bg=C_PANEL, fg=C_MUTED, width=11, anchor="w",
                     font=("Microsoft YaHei UI", 8)).pack(side="left")
            tk.Label(row, text=v, bg=C_PANEL, fg=color, anchor="w",
                     wraplength=160, justify="left",
                     font=("Microsoft YaHei UI", 8)).pack(side="left")

        inputs = self._active_inputs()
        add("输入项", "%d 项" % len(inputs),
            C_OK if inputs else C_WARN)
        for label, path in inputs:
            name = Path(path).name or path
            add("  " + label, name, C_TEXT)

        mode = self.var_mode.get()
        mode_text = dict(ANALYSIS_MODES).get(mode, mode)
        add("分析模式", mode_text)
        add("输出目录", Path(self.var_output.get() or "reports").name or "reports")

        droop = [
            ("I_step", self.var_istep.get(), "A"),
            ("Δt", self.var_dt_us.get(), "us"),
            ("t_rise", self.var_trise_us.get(), "us"),
            ("V_ripple", self.var_ripple_mv.get(), "mV"),
        ]
        for k, v, unit in droop:
            if (v or "").strip():
                add(k, "%s %s" % (v.strip(), unit))
        for k, v, unit in (("ESR", self.var_esr_mohm.get(), "mΩ"),
                           ("ESL", self.var_esl_nh.get(), "nH")):
            if (v or "").strip():
                add(k, "%s %s" % (v.strip(), unit))
        if not (self.var_esr_mohm.get() or "").strip() and \
           not (self.var_esl_nh.get() or "").strip():
            add("ESR/ESL", "按封装自动查表", C_MUTED)

    def _refresh_cards(self):
        """首次构建时的占位：刷新摘要。"""
        self._refresh_summary()

    def _validate_params(self):
        """校验数值参数；返回 (是否通过, 错误信息)。"""
        numeric = [
            ("瞬态电流 I_step", self.var_istep, True, 0.0),
            ("负载持续时间 Δt", self.var_dt_us, True, 0.0),
            ("电流上升时间 t_rise", self.var_trise_us, True, 0.0),
            ("允许纹波 V_ripple", self.var_ripple_mv, True, 0.0),
            ("ESR", self.var_esr_mohm, False, 0.0),
            ("ESL", self.var_esl_nh, False, 0.0),
        ]
        for label, var, required, minimum in numeric:
            raw = (var.get() or "").strip()
            if not raw:
                if required:
                    return False, "「%s」不能为空。" % label
                continue
            try:
                val = float(raw)
            except ValueError:
                return False, "「%s」必须是数字，当前为：%s" % (label, raw)
            if val <= minimum:
                return False, "「%s」必须大于 %g，当前为：%s" % (label, minimum, raw)
        return True, ""


    # ---------------- 开始分析 ----------------
    def build_args(self):
        """按主界面状态构造 main.py 的命令行参数列表。"""
        args = []

        schematic = (self.var_schematic.get() or "").strip()
        netlist = (self.var_netlist.get() or "").strip()
        deliverables = (self.var_deliverables.get() or "").strip()
        ipc = (self.var_ipc2581.get() or "").strip()
        gerber = (self.var_gerber.get() or "").strip()

        if schematic:
            args += ["-s", schematic]
        if netlist:
            args += ["-n", netlist]
        if deliverables:
            args += ["-d", deliverables]

        args += ["-m", self.var_mode.get() or "full"]

        output = (self.var_output.get() or "").strip()
        if output:
            args += ["-o", output]

        # 掉压参数：留空表示交给内核按封装自动查表
        for flag, var in (("--istep", self.var_istep),
                          ("--dt-us", self.var_dt_us),
                          ("--trise-us", self.var_trise_us),
                          ("--ripple-mv", self.var_ripple_mv),
                          ("--esr-mohm", self.var_esr_mohm),
                          ("--esl-nh", self.var_esl_nh)):
            raw = (var.get() or "").strip()
            if raw:
                args += [flag, raw]

        if ipc:
            args += ["--ipc2581", ipc]
        if gerber:
            args += ["--gerber", gerber]
        return args

    def start_analysis(self):
        """校验 → 构造参数 → 启动内核子进程。"""
        if self.proc is not None and self.proc.poll() is None:
            messagebox.showinfo("正在运行", "当前已有分析进程在运行，请先等待完成。",
                                parent=self.root)
            return

        if not self._active_inputs():
            messagebox.showwarning(
                "缺少输入",
                "请至少提供一项输入：\n"
                "  · 原理图（-s）\n"
                "  · Netlist（-n）\n"
                "  · PCB 交付件目录（-d）",
                parent=self.root)
            return

        ok, err = self._validate_params()
        if not ok:
            messagebox.showerror("参数有误", err, parent=self.root)
            return

        out_dir = Path((self.var_output.get() or "").strip() or default_report_dir())
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror("输出目录不可用",
                                 "无法创建输出目录：\n%s\n\n%s" % (out_dir, e),
                                 parent=self.root)
            return
        self.report_dir = out_dir

        main_py = Path(__file__).resolve().parent / "main.py"
        if not is_frozen() and not main_py.is_file():
            messagebox.showerror(
                "缺少分析内核",
                "找不到 main.py：\n%s\n\n源码模式需要 src/ 与 gui.py 在同一目录。"
                % main_py, parent=self.root)
            return

        args = self.build_args()
        cmd = build_cli_command(main_py, args)
        cwd = str(app_base_dir())

        self.clear_log()
        self._append_log("[CMD] " + self._format_cmd(cmd, args) + "\n", "head")
        self._append_log("[DIR] 工作目录: %s\n" % cwd, "head")
        self._append_log("[RUN] 正在执行分析...\n\n", "head")
        self.set_step(3)
        self._set_running(True)
        self.set_status("分析中...")
        self._notebook.select(self._tab_log)

        env = dict(os.environ)
        # 强制 UTF-8 输出，避免 Windows GBK 控制台把特殊字符打成 UnicodeEncodeError
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        # 清掉历史版本用过的环境变量，避免旧版残留值污染本次的子进程
        env.pop("HWA_CLI_ARGS", None)

        try:
            self.proc = subprocess.Popen(
                cmd, cwd=cwd, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            self._set_running(False)
            self.set_step(2)
            messagebox.showerror("启动失败",
                                 "无法启动分析进程：\n%s" % e, parent=self.root)
            self._append_log("[ERROR] 启动失败: %s\n" % e, "err")
            return

        threading.Thread(target=self._reader_thread, args=(self.proc,),
                         daemon=True).start()


    def _format_cmd(self, cmd, args):
        """把命令格式化成可读形式（打包态参数在临时文件里，需展开显示）。"""
        if is_frozen():
            return "%s %s <%d 项参数>" % (Path(cmd[0]).name, KERNEL_ARGS_FLAG, len(args))
        exe = Path(cmd[0]).name
        parts = [exe] + ['"%s"' % a if " " in str(a) else str(a) for a in cmd[1:]]
        return " ".join(parts)

    def _reader_thread(self, proc):
        """后台线程：把子进程输出逐行塞进队列（Tk 只能在主线程操作控件）。"""
        try:
            for raw in iter(proc.stdout.readline, ""):
                self.log_queue.put(("line", raw.rstrip("\r\n")))
        except Exception as e:  # noqa: BLE001 - 读取中断不应影响主流程
            self.log_queue.put(("line", "[ERROR] 读取输出失败: %s" % e))
        finally:
            try:
                proc.stdout.close()
            except Exception:
                pass
            # 必须 wait() 才能拿到真实退出码。
            #
            # readline() 返回空串只代表「stdout 被关闭」，并不等于「进程已退出」：
            # 子进程关掉 stdout 之后还要做收尾（flush / 清理 / 退出），
            # 这段间隙里 Popen.returncode 仍是 None。直接读它，就会把
            # 「还没拿到」误判成「失败」，日志出现：
            #     [ERROR] 分析失败，退出码 None
            # 而实际上报告已经生成、退出码是 0。
            #
            # 实测（Nuitka onefile + 1360655 字节 / 595 元件原理图）：
            #   finally 里读 returncode = None
            #   3 秒后 poll()          = 0     ← 真实结果
            # wait() 阻塞到进程真正结束，返回的一定是真实退出码（非 None）。
            try:
                rc = proc.wait()
            except Exception:  # noqa: BLE001 - 极端情况下兜底，不让线程崩
                rc = proc.poll()
            self.log_queue.put(("done", rc))

    def _pump_log_queue(self):
        """主线程定时器：把队列里的日志刷进 Text 控件。"""
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "line":
                    self._append_log(payload + "\n", self._guess_tag(payload))
                elif kind == "done":
                    self._on_process_done(payload)
        except queue.Empty:
            pass
        except Exception:
            pass
        try:
            self.root.after(120, self._pump_log_queue)
        except tk.TclError:
            pass

    @staticmethod
    def _guess_tag(text):
        low = text.lower()
        if "[error]" in low or "traceback" in low or "失败" in text or "错误" in text:
            return "err"
        if "[warn" in low or "警告" in text or "[!]" in text:
            return "warn"
        if "[v]" in low or "[ok]" in low or "完成" in text or "[✓]" in text:
            return "ok"
        return None

    def _append_log(self, text, tag=None):
        """向日志框追加一行（自动滚动到底）。"""
        try:
            self.txt_log.configure(state="normal")
            if tag:
                self.txt_log.insert("end", text, tag)
            else:
                self.txt_log.insert("end", text)
            self.txt_log.see("end")
            self.txt_log.configure(state="disabled")
        except tk.TclError:
            pass

    def clear_log(self):
        try:
            self.txt_log.configure(state="normal")
            self.txt_log.delete("1.0", "end")
            self.txt_log.configure(state="disabled")
        except tk.TclError:
            pass

    def _on_process_done(self, returncode):
        """子进程结束后的界面收尾。"""
        self._set_running(False)
        if returncode == 0:
            self._append_log("\n[OK] 分析完成。\n", "ok")
            self.set_step(4)
            self.set_status("分析完成")
            self.btn_report.configure(state="normal")
            self.var_step_hint.set("分析完成，点击右侧「查看报告」打开输出目录")
        else:
            self._append_log("\n[ERROR] 分析失败，退出码 %s\n" % returncode, "err")
            self.set_step(2)
            self.set_status("分析失败（退出码 %s）" % returncode)
            self.var_step_hint.set("分析失败，请查看运行日志定位原因")
        self.proc = None

    def _set_running(self, running):
        """运行期间禁用开始按钮，防止重复启动。"""
        try:
            self.btn_start.configure(
                state="disabled" if running else "normal",
                text="分析中..." if running else "开始分析",
                bg=C_MUTED if running else C_ACCENT)
        except tk.TclError:
            pass

    def set_status(self, text):
        self.var_status.set(text)

    # ---------------- 报告 ----------------
    def open_report_dir(self):
        """在资源管理器中打开报告目录。"""
        target = self.report_dir or Path((self.var_output.get() or "").strip()
                                         or default_report_dir())
        try:
            if not target.exists():
                target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror("目录不可用", "%s\n\n%s" % (target, e), parent=self.root)
            return
        try:
            os.startfile(str(target))  # noqa: S606 - Windows 打开目录
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("无法打开目录", "%s\n\n%s" % (target, e), parent=self.root)

    # ---------------- 关闭 ----------------
    def _on_close(self):
        """关闭窗口：若内核仍在运行，确认后终止。"""
        if self.proc is not None and self.proc.poll() is None:
            if not messagebox.askyesno("确认退出",
                                       "分析仍在进行中，确定要退出吗？",
                                       parent=self.root):
                return
            try:
                self.proc.terminate()
            except Exception:
                pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass



def _report_unhandled(exc_type, exc_value, exc_tb):
    """全局异常兜底：弹窗告知用户，而不是静默退出。"""
    detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        sys.stderr.write(detail)
    except Exception:
        pass
    try:
        messagebox.showerror("程序出错",
                             "发生未处理的异常：\n\n" + detail[-1800:])
    except Exception:
        pass


def main():
    """程序入口。"""
    sys.excepthook = _report_unhandled

    if sys.platform == "win32":
        try:
            # 高 DPI 下避免界面模糊
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    root = None
    try:
        root = tk.Tk()
        HardwareAnalyzerGUI(root)
        root.mainloop()
    except Exception:
        _report_unhandled(*sys.exc_info())
        raise
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    main()

