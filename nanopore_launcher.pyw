from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from merged_runner import run_analysis
from nanopore_prior.config import AnalysisConfig


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("纳米孔 ABF 自动分析（合并版）")
        self.geometry("940x760")
        self.minsize(900, 720)
        self.mode = tk.StringVar(value="单文件")
        self.input = tk.StringVar()
        self.output = tk.StringVar()
        self.ref = tk.StringVar()
        self.kind = tk.StringVar(value="自动")
        self.direction = tk.StringVar(value="自动识别")
        self.start = tk.StringVar()
        self.end = tk.StringVar()
        self.screen = tk.StringVar(value="不筛选")
        self.target_mean = tk.StringVar()
        self.target_sd = tk.StringVar()
        self.mean_tol = tk.StringVar()
        self.sd_tol = tk.StringVar()
        self.status = tk.StringVar(value="默认使用先验增强引擎；可另开交互复核界面对照检查。")
        self.wave = tk.BooleanVar(value=True)
        self.summary = tk.BooleanVar(value=True)
        self.group = tk.BooleanVar(value=True)
        self._build()

    def _build(self):
        paths = ttk.LabelFrame(self, text="文件与输出位置")
        paths.pack(fill="x", padx=12, pady=(12, 6))
        ttk.Label(paths, text="处理模式：").grid(row=0, column=0, sticky="e", padx=8, pady=6)
        ttk.Combobox(paths, textvariable=self.mode, values=["单文件", "批量文件夹（递归）"],
                     state="readonly", width=18).grid(row=0, column=1, sticky="w", padx=8, pady=6)
        self._row_in(paths, 1, "输入 ABF 文件 / 文件夹：", self.input, self.pick_input)
        self._row_in(paths, 2, "输出文件夹：", self.output, self.pick_output)
        self._row_in(paths, 3, "人工标定表（可选）：", self.ref, self.pick_ref)

        options = ttk.LabelFrame(self, text="主分析参数（先验增强引擎）")
        options.pack(fill="x", padx=12, pady=6)
        ttk.Label(options, text="事件种类数：").grid(row=0, column=0, sticky="e", padx=8, pady=7)
        ttk.Combobox(options, textvariable=self.kind, values=["自动", "1", "2", "3", "4", "5", "6"],
                     state="readonly", width=12).grid(row=0, column=1, sticky="w", padx=8, pady=7)
        ttk.Label(options, text="正常脉冲方向：").grid(row=0, column=2, sticky="e", padx=8, pady=7)
        ttk.Combobox(options, textvariable=self.direction, values=["自动识别", "向上", "向下"],
                     state="readonly", width=12).grid(row=0, column=3, sticky="w", padx=8, pady=7)
        ttk.Label(options, text="局部分析起点（s）：").grid(row=1, column=0, sticky="e", padx=8, pady=7)
        ttk.Entry(options, textvariable=self.start, width=15).grid(row=1, column=1, sticky="w", padx=8, pady=7)
        ttk.Label(options, text="终点（s；负数=距末尾）：").grid(row=1, column=2, sticky="e", padx=8, pady=7)
        ttk.Entry(options, textvariable=self.end, width=15).grid(row=1, column=3, sticky="w", padx=8, pady=7)
        ttk.Label(options, text="数据分级筛选：").grid(row=2, column=0, sticky="e", padx=8, pady=7)
        ttk.Combobox(options, textvariable=self.screen,
                     values=["不筛选", "异常事件筛选", "严格事件筛选"], state="readonly", width=16
                     ).grid(row=2, column=1, sticky="w", padx=8, pady=7)
        ttk.Label(options, text="目标电流变化（pA）：").grid(row=2, column=2, sticky="e", padx=8, pady=7)
        ttk.Entry(options, textvariable=self.target_mean, width=18).grid(row=2, column=3, sticky="w", padx=8, pady=7)
        ttk.Label(options, text="目标 SD（pA）：").grid(row=3, column=0, sticky="e", padx=8, pady=7)
        ttk.Entry(options, textvariable=self.target_sd, width=15).grid(row=3, column=1, sticky="w", padx=8, pady=7)
        ttk.Label(options, text="目标容差 mean / SD（pA）：").grid(row=3, column=2, sticky="e", padx=8, pady=7)
        pair = ttk.Frame(options)
        pair.grid(row=3, column=3, sticky="w", padx=8, pady=7)
        ttk.Entry(pair, textvariable=self.mean_tol, width=7).pack(side="left")
        ttk.Label(pair, text=" / ").pack(side="left")
        ttk.Entry(pair, textvariable=self.sd_tol, width=7).pack(side="left")

        plots = ttk.LabelFrame(self, text="输出与复核")
        plots.pack(fill="x", padx=12, pady=6)
        ttk.Checkbutton(plots, text="每个事件波形图", variable=self.wave).pack(side="left", padx=18, pady=8)
        ttk.Checkbutton(plots, text="基本统计图", variable=self.summary).pack(side="left", padx=18, pady=8)
        ttk.Checkbutton(plots, text="混合事件分群图", variable=self.group).pack(side="left", padx=18, pady=8)

        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=12, pady=12)
        self.button = ttk.Button(actions, text="开始主分析", command=self.begin)
        self.button.pack(side="left", padx=5)
        ttk.Button(actions, text="打开交互复核界面", command=self.open_reviewer).pack(side="left", padx=5)
        ttk.Button(actions, text="保存参数协议", command=self.save_protocol).pack(side="left", padx=5)
        ttk.Button(actions, text="载入参数协议", command=self.load_protocol).pack(side="left", padx=5)
        ttk.Button(actions, text="打开输出文件夹", command=self.open_output).pack(side="left", padx=5)
        ttk.Label(self, textvariable=self.status, wraplength=880, justify="left").pack(
            fill="x", padx=18, pady=(0, 10)
        )

    def _row_in(self, parent, row, label, var, command):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=8, pady=6)
        ttk.Entry(parent, textvariable=var, width=82).grid(row=row, column=1, sticky="ew", padx=8, pady=6)
        ttk.Button(parent, text="浏览", command=command).grid(row=row, column=2, padx=8, pady=6)
        parent.columnconfigure(1, weight=1)

    def pick_input(self):
        if self.mode.get().startswith("批量"):
            path = filedialog.askdirectory()
        else:
            path = filedialog.askopenfilename(filetypes=[("ABF 文件", "*.abf")])
        if path:
            self.input.set(path)

    def pick_output(self):
        path = filedialog.askdirectory()
        if path:
            self.output.set(path)

    def pick_ref(self):
        path = filedialog.askopenfilename(filetypes=[("Excel 标定表", "*.xls *.xlsx")])
        if path:
            self.ref.set(path)

    def _settings(self):
        start = None if not self.start.get().strip() else float(self.start.get())
        end = None if not self.end.get().strip() else float(self.end.get())
        means = tuple(float(x.strip()) for x in self.target_mean.get().split(",") if x.strip())
        sds = tuple(float(x.strip()) for x in self.target_sd.get().split(",") if x.strip())
        mean_tol = 3.0 if not self.mean_tol.get().strip() else float(self.mean_tol.get())
        sd_tol = 0.6 if not self.sd_tol.get().strip() else float(self.sd_tol.get())
        if self.screen.get() == "严格事件筛选" and not means and not sds:
            raise ValueError("严格事件筛选至少需填写目标电流变化或目标 SD。")
        if means and sds and len(means) != len(sds):
            raise ValueError("目标电流变化和目标 SD 的组数必须一致。")
        cfg = AnalysisConfig()
        cfg.event_polarity = {"自动识别": "auto", "向上": "up", "向下": "down"}[self.direction.get()]
        cfg.pulse_reference_path = self.ref.get().strip() or None
        cfg.expected_event_type_count = None if self.kind.get() == "自动" else int(self.kind.get())
        cfg.mixed_event_mode = cfg.expected_event_type_count is None or cfg.expected_event_type_count > 1
        cfg.save_event_waveforms = self.wave.get()
        cfg.plot_feature_scatter = cfg.plot_dwell_histogram = cfg.plot_frequency_histogram = self.summary.get()
        cfg.plot_mixed_group_scatter = self.group.get()
        cfg.screening_mode = {"不筛选": "none", "异常事件筛选": "anomaly",
                              "严格事件筛选": "strict"}[self.screen.get()]
        cfg.strict_target_means_pA = means
        cfg.strict_target_sds_pA = sds
        cfg.strict_mean_tolerance_pA = mean_tol
        cfg.strict_sd_tolerance_pA = sd_tol
        return cfg, start, end

    def begin(self):
        if not self.input.get().strip() or not self.output.get().strip():
            messagebox.showerror("缺少路径", "请选择输入文件/文件夹及输出文件夹。")
            return
        try:
            cfg, start, end = self._settings()
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        self.button.config(state="disabled")
        self.status.set("正在分析，请勿关闭窗口……")
        threading.Thread(target=self._run, args=(cfg, start, end), daemon=True).start()

    def _progress(self, index, total, item):
        state = "完成" if item.status == "ok" else "失败"
        self.after(0, self.status.set, f"[{index}/{total}] {item.source_file}：{state}，事件 {item.event_count}")

    def _run(self, cfg, start, end):
        try:
            results = run_analysis(self.input.get().strip(), self.output.get().strip(), cfg,
                                   start, end, self._progress)
            ok = sum(item.status == "ok" for item in results)
            failed = len(results) - ok
            message = (f"处理完成：成功 {ok}/{len(results)}，失败 {failed}。\n"
                       f"已生成逐文件 Excel、summary.xlsx、dataset_all.csv 和运行清单。\n"
                       f"结果目录：{self.output.get().strip()}")
            self.after(0, self._done, message, failed == 0)
        except Exception as exc:
            detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            Path(__file__).with_name("启动错误.log").write_text(detail, encoding="utf-8")
            self.after(0, self._done, f"分析失败：{exc}\n详情见 启动错误.log", False)

    def _done(self, message, ok):
        self.status.set(message)
        self.button.config(state="normal")
        (messagebox.showinfo if ok else messagebox.showwarning)("分析完成" if ok else "分析结果", message)

    def open_reviewer(self):
        if importlib.util.find_spec("PyQt5") is None or importlib.util.find_spec("pyqtgraph") is None:
            messagebox.showwarning(
                "缺少交互组件",
                "交互复核组件尚未安装。请关闭程序后重新双击顶层唯一的“启动纳米孔分析.bat”，启动器会自动补齐依赖。",
            )
            return
        path = self.input.get().strip()
        args = [sys.executable, "-m", "nanopore", "gui"]
        if path and Path(path).is_file():
            args.append(path)
        subprocess.Popen(args, cwd=Path(__file__).parent)

    def _protocol(self):
        variables = {"mode": self.mode, "reference": self.ref, "kind": self.kind,
                     "direction": self.direction, "start": self.start, "end": self.end,
                     "screen": self.screen, "target_mean": self.target_mean, "target_sd": self.target_sd,
                     "mean_tol": self.mean_tol, "sd_tol": self.sd_tol,
                     "wave": self.wave, "summary": self.summary, "group": self.group}
        return {name: variable.get() for name, variable in variables.items()}

    def save_protocol(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if path:
            Path(path).write_text(json.dumps(self._protocol(), ensure_ascii=False, indent=2), encoding="utf-8")

    def load_protocol(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        variables = {"mode": self.mode, "reference": self.ref, "kind": self.kind,
                     "direction": self.direction, "start": self.start, "end": self.end,
                     "screen": self.screen, "target_mean": self.target_mean, "target_sd": self.target_sd,
                     "mean_tol": self.mean_tol, "sd_tol": self.sd_tol,
                     "wave": self.wave, "summary": self.summary, "group": self.group}
        for name, variable in variables.items():
            if name in data:
                variable.set(data[name])
        self.status.set(f"已载入参数协议：{path}")

    def open_output(self):
        path = Path(self.output.get().strip())
        if path.is_dir():
            subprocess.Popen(["explorer", str(path)])
        else:
            messagebox.showinfo("输出目录", "请先选择一个已存在的输出文件夹。")


if __name__ == "__main__":
    Launcher().mainloop()
