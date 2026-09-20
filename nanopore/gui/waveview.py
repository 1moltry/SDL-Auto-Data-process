"""Interactive waveform view (pyqtgraph).

Renders the FULL current-vs-time trace (baseline included) on a white
background so the signal and its jitter are clearly visible. Raw samples are
drawn whenever they fit in the view; at coarser zoom a single thin block-mean
line is used (no envelope band). Only the idealised event square-pulses are
highlighted — all other overlays (level markers, envelope fill, baseline_step
shading) are intentionally omitted to keep the trace uncluttered.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QComboBox, QHBoxLayout, QPushButton, QVBoxLayout, QWidget)

from .bus import bus
from .units import AUTO, SEC_PER_UNIT, UNITS, TimeAxis, auto_unit

# int RGBA — pyqtgraph's mkBrush read float tuples as a colour width, not
# channels, and silently produced fully transparent brushes (invisible bands).
ANOM_COLORS = {
    "breakdown": (255, 0, 0, 31),
    "blockage": (255, 128, 0, 31),
    "jitter": (128, 0, 128, 26),
    # fine-grained kinds — same hues, slightly stronger so they read as the
    # "real" artifact vs the coarser macro overlay
    "reverse_voltage": (0, 153, 230, 51),
    "membrane_rupture": (255, 0, 0, 56),
    "membrane_jitter_mild": (128, 0, 128, 26),
    "membrane_jitter_severe": (128, 0, 128, 56),
    "blockage_spontaneous": (255, 128, 0, 46),
    "blockage_manual_recovery": (0, 153, 230, 56),
    "baseline_drift": (140, 89, 0, 41),
    # baseline_step deliberately omitted: too noisy visually, still in table/xlsx
}

TRACE_COLOR = "#333333"
EVENT_COLOR = "#1f77b4"


class WaveView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self._tax = TimeAxis(orientation="bottom")
        self.plot = pg.PlotWidget(axisItems={"bottom": self._tax})
        self.plot.setBackground("w")
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.plot.setLabel("bottom", "时间", units="s")
        self.plot.setLabel("left", "电流", units="pA")
        for ax in ("bottom", "left"):
            axis = self.plot.getAxis(ax)
            axis.setPen(pg.mkPen("k"))
            axis.setTextPen(pg.mkPen("k"))

        # cursor (ROI) toolbar: enable a draggable region, re-run analysis on it
        self.btn_roi = QPushButton("Cursor 选区")
        self.btn_run_roi = QPushButton("对区间重跑")
        self.btn_clear_roi = QPushButton("清除选区")
        self.btn_run_roi.setEnabled(False)
        self.btn_clear_roi.setEnabled(False)
        self._unit_box = QComboBox()
        self._unit_box.addItem(AUTO)
        self._unit_box.addItems(UNITS)
        self._unit_box.currentIndexChanged.connect(self._apply_time_unit)
        controls = QHBoxLayout()
        controls.setContentsMargins(4, 2, 4, 0)
        controls.addWidget(self.btn_roi)
        controls.addWidget(self.btn_run_roi)
        controls.addWidget(self.btn_clear_roi)
        controls.addWidget(self._unit_box)
        controls.addStretch(1)

        lay.addLayout(controls)
        lay.addWidget(self.plot)

        # full-trace line; block mean when zoomed out (no min/max band)
        self.trace = pg.PlotDataItem(pen=pg.mkPen(TRACE_COLOR, width=0.6))
        self.trace.setClipToView(True)
        self.plot.addItem(self.trace)

        # event indicator: idealized square-pulse trace over the full signal,
        # emphasised with a bright line (idealised-overlay style)
        self.events_item = pg.PlotDataItem(pen=pg.mkPen(EVENT_COLOR, width=1.6))
        self.events_item.setClipToView(True)
        self.events_item.setZValue(5)
        self.plot.addItem(self.events_item)

        self._anom_regions: list[pg.LinearRegionItem] = []
        self._focus_region: pg.LinearRegionItem | None = None
        # ROI cursor: draggable search region + its result square-pulse overlay
        self._roi_item: pg.LinearRegionItem | None = None
        self._roi_events: pg.PlotDataItem | None = None

        self._raw: np.ndarray | None = None
        self._sr: float = 0.0
        self._df = None
        self._lv = None

        vb = self.plot.getViewBox()
        vb.sigXRangeChanged.connect(self._on_range)
        vb.sigYRangeChanged.connect(self._on_range)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._render)

        self.btn_roi.clicked.connect(self.toggle_roi)
        self.btn_run_roi.clicked.connect(self._run_roi)
        self.btn_clear_roi.clicked.connect(self.clear_roi)
        bus.roi_finished.connect(self._on_roi_finished)

    # ---- cursor (ROI) -----------------------------------------------------
    def toggle_roi(self) -> None:
        if self._roi_item is not None:
            self.clear_roi()
            return
        if self._raw is None:
            bus.status.emit("请先打开一个 .abf 文件")
            return
        x0, x1 = self.plot.getViewBox().viewRange()[0]
        if x1 - x0 <= 0:
            x0, x1 = 0.0, len(self._raw) / self._sr
        span = max(1.0, 0.3 * (x1 - x0))
        mid = 0.5 * (x0 + x1)
        self._roi_item = pg.LinearRegionItem([mid - span / 2, mid + span / 2], movable=True)
        self._roi_item.setZValue(20)
        self._roi_item.setBrush(pg.mkBrush(31, 79, 181, 31))
        self.plot.addItem(self._roi_item)
        self.btn_run_roi.setEnabled(True)
        self.btn_clear_roi.setEnabled(True)
        self.btn_roi.setText("关闭选区")

    def clear_roi(self) -> None:
        if self._roi_item is not None:
            self.plot.removeItem(self._roi_item)
            self._roi_item = None
        if self._roi_events is not None:
            self.plot.removeItem(self._roi_events)
            self._roi_events = None
        self.btn_run_roi.setEnabled(False)
        self.btn_clear_roi.setEnabled(False)
        self.btn_roi.setText("Cursor 选区")

    def _run_roi(self) -> None:
        if self._roi_item is None:
            return
        start_s, end_s = self._roi_item.getRegion()
        bus.roi_rerun.emit(start_s, end_s)

    def _on_roi_finished(self, df, span) -> None:
        start_s, end_s = span
        if self._roi_events is not None:
            self.plot.removeItem(self._roi_events)
        self._roi_events = pg.PlotDataItem(pen=pg.mkPen(31, 140, 51, width=1.8))
        self._roi_events.setZValue(6)
        self.plot.addItem(self._roi_events)
        if df is not None and len(df):
            d = df.sort_values("t1")
            t1 = d["t1"].to_numpy()
            t2 = d["t2"].to_numpy()
            io = d["Io"].to_numpy()
            amp = io + d["mean"].to_numpy()
            x = np.empty(5 * len(d))
            y = np.empty(5 * len(d))
            for i in range(len(d)):
                j = 5 * i
                x[j:j + 5] = (t1[i], t1[i], t2[i], t2[i], np.nan)
                y[j:j + 5] = (io[i], amp[i], amp[i], io[i], np.nan)
            self._roi_events.setData(x, y, connect="finite")

    # ---- time unit --------------------------------------------------------
    def _duration_s(self) -> float:
        if self._raw is None or not self._sr:
            return 0.0
        return len(self._raw) / self._sr

    def _apply_time_unit(self) -> None:
        """Re-label the time axis in the selected (or file-fitted) unit."""
        unit = self._unit_box.currentText()
        if unit == AUTO:
            unit = auto_unit(self._duration_s())
        self._tax.set_time_unit(SEC_PER_UNIT[unit])
        self.plot.setLabel("bottom", "时间", units=unit)

    # ---- data loading -----------------------------------------------------
    def set_data(self, rec, lv, df, anom) -> None:
        self._raw = rec.current if rec is not None else None
        self._sr = rec.sample_rate_hz if rec is not None else 0.0
        self._df = df
        self._lv = lv
        self._clear_overlays()
        if self._raw is None:
            return
        self._apply_time_unit()
        if anom is not None:
            self._add_anomalies(anom)
        self._plot_events(df)
        self.autoscale()

    def _clear_overlays(self) -> None:
        for item in self._anom_regions:
            self.plot.removeItem(item)
        self._anom_regions = []
        if self._focus_region is not None:
            self.plot.removeItem(self._focus_region)
            self._focus_region = None
        self.events_item.setData([], [])

    def _add_anomalies(self, anom) -> None:
        for r in getattr(anom, "regions", []):
            color = ANOM_COLORS.get(r.kind)
            if color is None:
                continue  # baseline_step etc. are table-only, not drawn
            region = pg.LinearRegionItem([r.start_s, r.end_s], movable=False)
            region.setBrush(pg.mkBrush(*color))
            region.setZValue(-10)
            self.plot.addItem(region)
            self._anom_regions.append(region)

    def _plot_events(self, df) -> None:
        if df is None or len(df) == 0:
            self.events_item.setData([], [])
            return
        d = df.sort_values("t1")
        t1 = d["t1"].to_numpy()
        t2 = d["t2"].to_numpy()
        # per-event open-pore reference (Io) so square pulses follow baseline
        # steps (Ala/Asp slow state switching) instead of floating at a single
        # global level0. amplitude = Io + depth (mean is signed).
        io = d["Io"].to_numpy()
        amp = io + d["mean"].to_numpy()
        n = len(d)
        # square-pulse idealised trace: per-event baseline -> step -> back.
        # Segments are NaN-separated so pyqtgraph breaks the line between
        # events whose baselines differ (avoids a long diagonal between pulses).
        x = np.empty(5 * n)
        y = np.empty(5 * n)
        for i in range(n):
            j = 5 * i
            x[j:j + 5] = (t1[i], t1[i], t2[i], t2[i], np.nan)
            y[j:j + 5] = (io[i], amp[i], amp[i], io[i], np.nan)
        self.events_item.setData(x, y, connect="finite")

    # ---- rendering --------------------------------------------------------
    def _on_range(self) -> None:
        self._timer.start()

    def _render(self) -> None:
        if self._raw is None:
            return
        (x0, x1), _ = self.plot.getViewBox().viewRange()
        sr, n = self._sr, len(self._raw)
        i0 = max(0, int(x0 * sr))
        i1 = min(n, int(x1 * sr) + 1)
        if i1 <= i0:
            return
        cnt = i1 - i0
        w = max(self.plot.width(), 400)          # widget width in pixels

        # raw samples when few enough; otherwise block-mean downsample only
        if cnt <= 2 * w:
            t = np.arange(i0, i1) / sr
            self.trace.setData(t, self._raw[i0:i1])
            return
        bins = max(300, w)
        step = int(np.ceil(cnt / bins))
        m = (i1 - i0) // step
        if m < 2:
            t = np.arange(i0, i1) / sr
            self.trace.setData(t, self._raw[i0:i1])
            return
        seg = self._raw[i0:i0 + m * step].reshape(m, step)
        t = (np.arange(i0, i0 + m * step, step) + step / 2) / sr
        self.trace.setData(t, seg.mean(axis=1))

    def _full_extent(self) -> tuple[float, float, float, float]:
        n = len(self._raw)
        step = max(1, n // 100_000)
        seg = self._raw[::step]
        return 0.0, n / self._sr, float(np.nanmin(seg)), float(np.nanmax(seg))

    def autoscale(self) -> None:
        x0, x1, y0, y1 = self._full_extent()
        self.plot.setRange(xRange=(x0, x1), yRange=(y0, y1), padding=0.02)

    # ---- selection --------------------------------------------------------
    def focus_region(self, start_s: float, end_s: float) -> None:
        """Zoom to an anomaly region span (from the anomaly panel)."""
        if self._raw is None:
            return
        pad = 0.03 * (end_s - start_s) or 0.2
        if self._focus_region is not None:
            self.plot.removeItem(self._focus_region)
        self._focus_region = pg.LinearRegionItem([start_s, end_s], movable=False)
        self._focus_region.setBrush(pg.mkBrush(230, 51, 51, 31))
        self.plot.addItem(self._focus_region)
        sr = self._sr
        i0 = max(0, int((start_s - pad) * sr))
        i1 = min(len(self._raw), int((end_s + pad) * sr) + 1)
        seg = self._raw[i0:i1] if i1 > i0 else self._raw[:1]
        self.plot.setXRange(start_s - pad, end_s + pad, padding=0.03)
        self.plot.setYRange(float(np.nanmin(seg)), float(np.nanmax(seg)), padding=0.08)

    def focus(self, idx: int) -> None:
        if self._df is None or idx < 0 or idx >= len(self._df):
            return
        row = self._df.iloc[idx]
        t1, t2 = float(row["t1"]), float(row["t2"])
        span = max(t2 - t1, 1.0)
        pad = max(0.03, 0.5 * span)

        if self._focus_region is not None:
            self.plot.removeItem(self._focus_region)
        self._focus_region = pg.LinearRegionItem([t1, t2], movable=False)
        self._focus_region.setBrush(pg.mkBrush(31, 79, 181, 38))
        self.plot.addItem(self._focus_region)

        sr, n = self._sr, len(self._raw)
        i0 = max(0, int((t1 - pad) * sr))
        i1 = min(n, int((t2 + pad) * sr) + 1)
        seg = self._raw[i0:i1] if i1 > i0 else self._raw[:1]
        y0, y1v = float(np.nanmin(seg)), float(np.nanmax(seg))

        self.plot.setXRange(t1 - pad, t2 + pad, padding=0.03)
        self.plot.setYRange(y0, y1v, padding=0.08)
