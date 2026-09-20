"""Main window: waveform plus dockable event/anomaly/parameter panels."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QAction, QDockWidget, QFileDialog, QMainWindow,
                             QToolBar)

from . import controller as ctrl_mod
from .anomalyview import AnomalyView
from .bus import bus
from .eventtable import EventTable
from .parampanel import ParamPanel
from .scatterview import ScatterView
from .waveview import WaveView


class MainWindow(QMainWindow):
    def __init__(self, data: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("SDL 纳米孔分析 — 交互式分析界面")

        self.wave = WaveView()
        self.setCentralWidget(self.wave)

        self.event = EventTable()
        self.scatter = ScatterView()
        self.params = ParamPanel()
        self.anom = AnomalyView()

        self.addDockWidget(Qt.LeftDockWidgetArea, self._dock("事件", self.event))
        self.addDockWidget(Qt.RightDockWidgetArea, self._dock("统计 (直方图/散点)", self.scatter))
        self.addDockWidget(Qt.RightDockWidgetArea, self._dock("参数", self.params))
        self.addDockWidget(Qt.BottomDockWidgetArea, self._dock("异常/剔除", self.anom))

        self._build_toolbar()

        bus.status.connect(self.statusBar().showMessage)
        bus.detection_finished.connect(self._on_results)
        bus.event_selected.connect(self._on_select)
        bus.region_selected.connect(self._on_region)
        bus.roi_rerun.connect(ctrl_mod.controller.rerun_roi)

        if data:
            ctrl_mod.controller.load(data)

    def _dock(self, title: str, widget) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setWidget(widget)
        return dock

    def _build_toolbar(self) -> None:
        bar = QToolBar("main")
        bar.setMovable(False)
        self.addToolBar(bar)

        act_open = QAction("打开", self)
        act_open.triggered.connect(self._open)
        bar.addAction(act_open)

        act_run = QAction("重跑", self)
        act_run.triggered.connect(self.params._run)
        bar.addAction(act_run)

        act_fit = QAction("全览", self)
        act_fit.triggered.connect(self.wave.autoscale)
        bar.addAction(act_fit)

        act_batch = QAction("批量处理…", self)
        act_batch.triggered.connect(self._batch)
        bar.addAction(act_batch)

    def _open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "打开 .abf", "", "ABF (*.abf)")
        if path:
            ctrl_mod.controller.load(path)

    def _batch(self) -> None:
        from .batchdialog import BatchDialog

        dlg = BatchDialog(self.params.build_config(), self)
        dlg.exec_()

    def _on_results(self) -> None:
        c = ctrl_mod.controller
        self.wave.set_data(c.rec, c.lv, c.df, c.anom)
        self.scatter.set_data(c.df)
        self.event.set_data(c.df)
        self.anom.set_data(c.anom, c.df_excluded)

    def _on_select(self, idx: int) -> None:
        self.wave.focus(idx)
        self.event.select_row(idx)
        self.scatter.highlight(idx)

    def _on_region(self, start_s: float, end_s: float) -> None:
        self.wave.focus_region(start_s, end_s)
