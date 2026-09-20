"""Right-side statistics panel: toff histogram + SD vs |dI| scatter.

- Histogram: event count vs dwell time (toff). Two x scales toggleable:
  linear and log10. The x unit adapts to the file from μs/ms/s/min (a 25 s
  dwell axis reads seconds, not "kms"); a combo overrides the choice.
- Scatter: SD (pA) vs |dI| (pA), a plain reference cloud in one colour — no
  clustering. Click-to-locate is kept: each point carries the event's
  DataFrame row index and clicking emits ``bus.event_selected`` so the
  waveform jumps to it (goal.md 进阶(4)).
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import (
    QComboBox, QRadioButton, QVBoxLayout, QWidget)

from .units import AUTO, UNITS, auto_unit, per_second
from .bus import bus

# int RGBA — pyqtgraph's mkBrush/mkPen read float tuples as a colour width,
# not channels, and silently produce a fully transparent brush.
HIST_COLOR = (31, 120, 181, 217)
POINT_COLOR = (31, 119, 180, 200)


class ScatterView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        # ---- histogram: event count vs toff (dwell) ----
        self.hist = pg.PlotWidget()
        self.hist.setBackground("w")
        self.hist.showGrid(y=True, alpha=0.15)
        self.hist.setMouseEnabled(x=False, y=False)
        for ax in ("bottom", "left"):
            axis = self.hist.getAxis(ax)
            axis.setPen(pg.mkPen("k"))
            axis.setTextPen(pg.mkPen("k"))
        self.hist.getAxis("bottom").enableAutoSIPrefix(False)

        self._log_btn = QRadioButton("log10")
        self._lin_btn = QRadioButton("线性")
        self._lin_btn.setChecked(True)
        self._log_btn.toggled.connect(self._draw_hist)

        self._unit_box = QComboBox()
        self._unit_box.addItem(AUTO)
        self._unit_box.addItems(UNITS)
        self._unit_box.currentIndexChanged.connect(self._draw_hist)

        self._bars: pg.BarGraphItem | None = None
        self._tof: np.ndarray | None = None

        # ---- scatter: SD vs |dI| ----
        self.p2 = pg.PlotWidget()
        self.p2.setBackground("w")
        self.p2.showGrid(x=True, y=True, alpha=0.15)
        self.p2.setLabel("bottom", "|ΔI|", units="pA")
        self.p2.setLabel("left", "SD", units="pA")
        for ax in ("bottom", "left"):
            axis = self.p2.getAxis(ax)
            axis.setPen(pg.mkPen("k"))
            axis.setTextPen(pg.mkPen("k"))
        self.s2 = pg.ScatterPlotItem(
            size=6, pen=None, brush=pg.mkBrush(*POINT_COLOR))
        self.p2.addItem(self.s2)

        hist_row = QVBoxLayout()
        hist_row.setContentsMargins(4, 2, 4, 0)
        hist_row.addWidget(self._lin_btn)
        hist_row.addWidget(self._log_btn)
        hist_row.addWidget(self._unit_box)
        hist_row.addStretch(1)

        lay.addLayout(hist_row)
        lay.addWidget(self.hist)
        lay.addWidget(self.p2)

        self._df = None

    # ---- data ----
    def set_data(self, df) -> None:
        self._df = df
        self._tof = None
        self.s2.clear()
        if df is None or len(df) == 0:
            self._replace_bars(None)
            return
        tof = df["toff"].to_numpy(dtype=float)
        self._tof = tof[np.isfinite(tof) & (tof > 0)]
        self._draw_hist()
        self._draw_scatter()

    # ---- histogram ----
    def _unit(self) -> str:
        """Selected unit, or the auto one for the current dwell span."""
        choice = self._unit_box.currentText()
        if choice != AUTO:
            return choice
        span_s = float(self._tof.max()) / 1e3 if self._tof is not None else 0.0
        return auto_unit(span_s)

    def _replace_bars(self, bars: pg.BarGraphItem | None) -> None:
        if self._bars is not None:
            self.hist.removeItem(self._bars)
        self._bars = bars
        if bars is not None:
            self.hist.addItem(bars)

    def _draw_hist(self) -> None:
        tof = self._tof
        if tof is None or tof.size == 0:
            return
        unit = self._unit()
        vals_disp = (tof / 1e3) * per_second(unit)   # toff is ms
        use_log = self._log_btn.isChecked()
        if use_log:
            vals = np.log10(vals_disp[vals_disp > 0])
            lo, hi = np.floor(vals.min()), np.ceil(vals.max())
            # half-decade bins when the range is narrow, whole decades otherwise,
            # so the histogram never collapses to a couple of bars
            step = 0.5 if (hi - lo) <= 4.0 else 1.0
            edges = np.arange(lo, hi + step / 2.0, step)
            if edges.size < 2:
                edges = np.array([lo, lo + step])
            self.hist.setLabel("bottom", "log10 toff", units=unit)
            # label only whole decades; half-decade bin edges stay unticked
            ticks = [(float(e), f"{10.0 ** e:g}")
                     for e in np.arange(np.ceil(lo), hi + 0.5, 1.0)]
            self.hist.getAxis("bottom").setTicks([ticks] if ticks else None)
        else:
            vals = vals_disp
            vmax = float(vals.max())
            nbins = int(np.clip(np.ceil(np.sqrt(vals.size) * 2), 8, 60))
            edges = np.linspace(0.0, vmax if vmax > 0 else 1.0, nbins + 1)
            self.hist.setLabel("bottom", "toff", units=unit)
            self.hist.getAxis("bottom").setTicks(None)

        counts, _ = np.histogram(vals, bins=edges)
        widths = np.diff(edges)
        self._replace_bars(pg.BarGraphItem(
            x0=edges[:-1], x1=edges[1:], y0=0, height=counts,
            brush=pg.mkBrush(*HIST_COLOR), pen=pg.mkPen(*HIST_COLOR)))

        x0 = float(edges[0])
        self.hist.setXRange(x0, float(edges[-1]) or 1.0, padding=0.02)
        self.hist.setYRange(0, max(int(counts.max()), 1), padding=0.02)
        self.hist.setTitle(
            f"事件数量 – dwell (n={int(tof.size)}, {len(edges) - 1} bins, "
            f"w={widths[-1]:.3g} {unit})")

    # ---- scatter ----
    def _draw_scatter(self) -> None:
        df = self._df
        x = np.abs(df["mean"].to_numpy())
        y = df["std"].to_numpy()

        data = [{"idx": i} for i in range(len(df))]
        self.s2.setData(x, y, data=data)
        self.p2.getViewBox().autoRange()

    def _click(self, scatter, points) -> None:
        if not points:
            return
        idx = points[0].data()["idx"]
        bus.event_selected.emit(int(idx))

    def highlight(self, idx: int) -> None:
        """Ring the selected point in the SD-|dI| scatter (no-op if absent)."""
        if self._df is None or idx < 0 or idx >= len(self._df):
            return
        x = abs(float(self._df["mean"].to_numpy()[idx]))
        y = float(self._df["std"].to_numpy()[idx])
        self.s2.addPoints([x], [y], symbol="o", size=14, pen=pg.mkPen("#f4a300", width=2))
