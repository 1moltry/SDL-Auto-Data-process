"""Batch processing dialog: pick .abf files / a folder and an output directory.

Runs :func:`nanopore.pipeline.run_batch` in a worker thread so the window stays
responsive, streaming a per-file progress log. Parameters come from the existing
parameter panel (single source of truth).
"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QPlainTextEdit, QProgressBar,
                             QPushButton, QVBoxLayout)

from ..pipeline import run_batch


def collect_abf_files(items: list[str]) -> list[Path]:
    """Expand a mixed list of .abf files and folders into a sorted file list.

    Folders are walked recursively (tPAL-style nested layouts included);
    duplicates are dropped and the result is sorted for a stable order.
    """
    files: dict[str, Path] = {}
    for item in items:
        p = Path(item)
        if p.is_dir():
            for f in sorted(p.rglob("*.abf")):
                files[str(f.resolve())] = f
        elif p.is_file() and p.suffix.lower() == ".abf":
            files[str(p.resolve())] = p
    return sorted(files.values())


class BatchWorker(QThread):
    progress = pyqtSignal(int, int, str, object)   # done, total, file name, report
    finished_ok = pyqtSignal(object)               # list of reports
    failed = pyqtSignal(str)

    def __init__(self, files: list[Path], out_dir: Path, cfg) -> None:
        super().__init__()
        self.files = files
        self.out_dir = out_dir
        self.cfg = cfg
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            reports = run_batch(self.files, self.out_dir, self.cfg,
                                progress=self._on_progress)
            self.finished_ok.emit(reports)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    def _on_progress(self, i, total, name, rep) -> None:
        self.progress.emit(i, total, name, rep)
        if self._cancel:
            raise RuntimeError("已取消")


class BatchDialog(QDialog):
    def __init__(self, cfg, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("批量处理")
        self.resize(720, 520)
        self._cfg = cfg
        self._worker: BatchWorker | None = None

        self.files = QListWidget()
        self._add_files = QPushButton("添加文件…")
        self._add_dir = QPushButton("添加文件夹…")
        self._remove = QPushButton("移除选中")
        self._clear = QPushButton("清空")
        self._add_files.clicked.connect(self._pick_files)
        self._add_dir.clicked.connect(self._pick_dir)
        self._remove.clicked.connect(self._remove_selected)
        self._clear.clicked.connect(self.files.clear)

        pick_row = QHBoxLayout()
        for b in (self._add_files, self._add_dir, self._remove, self._clear):
            pick_row.addWidget(b)
        pick_row.addStretch(1)

        self.out_edit = QLineEdit()
        self.out_btn = QPushButton("输出目录…")
        self.out_btn.clicked.connect(self._pick_out)
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("输出目录"))
        out_row.addWidget(self.out_edit, 1)
        out_row.addWidget(self.out_btn)

        self.bar = QProgressBar()
        self.bar.setFormat("%v / %m 个文件")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)

        self.run_btn = QPushButton("开始处理")
        self.close_btn = QPushButton("关闭")
        self.run_btn.clicked.connect(self._run)
        self.close_btn.clicked.connect(self._close)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.close_btn)

        lay = QVBoxLayout(self)
        lay.addLayout(pick_row)
        lay.addWidget(self.files, 1)
        lay.addLayout(out_row)
        lay.addWidget(self.bar)
        lay.addWidget(self.log, 1)
        lay.addLayout(btn_row)
        # keep the counter in sync however items change (buttons or otherwise)
        self.files.model().rowsInserted.connect(self._update_count)
        self.files.model().rowsRemoved.connect(self._update_count)
        self._update_count()

    # ---- file picking ----
    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "选择 .abf 文件", "", "ABF (*.abf)")
        for p in paths:
            if not self._has(p):
                self.files.addItem(p)

    def _pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择文件夹（递归搜集 .abf）")
        if d and not self._has(d):
            self.files.addItem(d)

    def _pick_out(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self.out_edit.setText(d)

    def _has(self, item: str) -> bool:
        return any(self.files.item(i).text() == item for i in range(self.files.count()))

    def _remove_selected(self) -> None:
        for it in self.files.selectedItems():
            self.files.takeItem(self.files.row(it))

    def _update_count(self, *_) -> None:
        n = len(self.selected_files())
        self.bar.setMaximum(max(n, 1))
        self.bar.setValue(0)
        self._log(f"当前选择 {n} 个 .abf 文件")

    def selected_files(self) -> list[Path]:
        items = [self.files.item(i).text() for i in range(self.files.count())]
        return collect_abf_files(items)

    # ---- run ----
    def _run(self) -> None:
        files = self.selected_files()
        if not files:
            self._log("没有可处理的 .abf 文件")
            return
        out = self.out_edit.text().strip()
        if not out:
            self._log("请先选择输出目录")
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self.bar.setMaximum(len(files))
        self.bar.setValue(0)
        self.run_btn.setEnabled(False)
        self._log(f"开始处理 {len(files)} 个文件 → {out}")
        self._worker = BatchWorker(files, Path(out), self._cfg)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, i: int, total: int, name: str, rep) -> None:
        self.bar.setValue(i)
        if getattr(rep, "error", ""):
            self._log(f"[{i}/{total}] {name}: 失败 — {rep.error}")
        else:
            self._log(f"[{i}/{total}] {name}: {rep.n_events} 事件 "
                      f"(原始 {rep.n_events_raw})，有效 {rep.valid_pct:.0f}%")

    def _on_done(self, reports) -> None:
        ok = sum(1 for r in reports if not getattr(r, "error", ""))
        self._log(f"完成：{ok}/{len(reports)} 个文件成功；汇总表 summary.xlsx 已写入输出目录")
        self.run_btn.setEnabled(True)

    def _on_failed(self, msg: str) -> None:
        self._log(f"批处理中断：{msg}")
        self.run_btn.setEnabled(True)

    def _log(self, text: str) -> None:
        self.log.appendPlainText(text)

    def _close(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)
        self.reject()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)
        super().closeEvent(event)
