"""GUI right-panel smoke test (offscreen): toff histogram + SD-|dI| scatter.

Sets QT_QPA_PLATFORM=offscreen so PyQt5 runs headless. Verifies data wiring
(histogram counts sum to the number of valid toffs, log/linear toggle changes
binning, scatter point count, click emits event_selected, highlight no-op
safety); visual look is confirmed by the user on a real machine.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PyQt5")
pytest.importorskip("pyqtgraph")

from nanopore.gui.bus import bus
from nanopore.gui.scatterview import ScatterView


@pytest.fixture(scope="session")
def qapp():
    # one QApplication per session — see test_gui_anomaly.py qapp comment
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    return app


def _df() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    n = 200
    toff = 10.0 ** rng.uniform(-0.5, 2.5, n)          # ~0.3 .. ~300 ms
    return pd.DataFrame({
        "toff": toff,
        "mean": -rng.uniform(5, 60, n),
        "std": rng.uniform(0.5, 8, n),
        "Io": rng.uniform(90, 110, n),
    })


def test_histogram_counts_sum_to_valid_toffs(qapp):
    view = ScatterView()
    view.set_data(_df())
    bars = view._bars
    assert bars is not None
    counts = np.asarray(bars.opts["height"], dtype=float)
    valid = int(np.count_nonzero(np.isfinite(view._tof) & (view._tof > 0)))
    assert counts.sum() == valid


def test_histogram_log_toggle_changes_binning(qapp):
    view = ScatterView()
    view.set_data(_df())

    view._lin_btn.setChecked(True)
    assert view._lin_btn.isChecked()
    edges_lin = np.asarray(view._bars.opts["x0"])
    assert edges_lin[0] == 0.0
    assert "dwell" in view.hist.plotItem.titleLabel.text

    view._log_btn.setChecked(True)
    edges_log = np.asarray(view._bars.opts["x0"])
    assert len(edges_log) != len(edges_lin)
    assert "dwell" in view.hist.plotItem.titleLabel.text
    # log mode installs decade ticks in pyqtgraph's [[(pos, label), ...]] form;
    # a flat list raises inside AxisItem.paint and blanks the whole histogram
    ticks = view.hist.getAxis("bottom")._tickLevels
    assert ticks and all(isinstance(pair, tuple) and len(pair) == 2
                         for pair in ticks[0])


def test_histogram_renders_in_both_scales(qapp):
    """Both scales must survive a real paint pass (guards the axis-tick format)
    and leave visible bars for a multi-decade dwell distribution."""
    from PyQt5.QtGui import QImage, QPainter

    rng = np.random.default_rng(3)
    toff = 10.0 ** rng.uniform(0.5, 3.0, 150)     # 3 ms .. 1 s
    df = pd.DataFrame({"toff": toff, "mean": -rng.uniform(5, 60, 150),
                       "std": rng.uniform(0.5, 8, 150), "Io": np.full(150, 100.0)})
    for log in (False, True):
        view = ScatterView()
        view._log_btn.setChecked(log)
        view.set_data(df)
        img = QImage(600, 400, QImage.Format_ARGB32)
        img.fill(0xFFFFFFFF)
        painter = QPainter(img)
        view.hist.render(painter)          # raises if the tick format is wrong
        painter.end()
        ptr = img.constBits()
        ptr.setsize(img.byteCount())
        px = np.frombuffer(ptr, np.uint8).reshape(400, 600, 4)[:, :, :3]
        assert np.count_nonzero(np.abs(px.astype(int) - 255).sum(axis=2) > 60) > 200, \
            f"histogram is blank (log={log})"


def test_histogram_bins_are_not_degenerate(qapp):
    """A dwell range spanning decades must not collapse into one huge bin: the
    linear scale uses a sqrt-rule bin count, the log scale keeps several bins."""
    rng = np.random.default_rng(5)
    toff = 10.0 ** rng.uniform(0.5, 3.0, 150)
    df = pd.DataFrame({"toff": toff, "mean": np.full(150, -40.0),
                       "std": np.full(150, 3.0), "Io": np.full(150, 100.0)})
    view = ScatterView()
    view.set_data(df)
    counts = np.asarray(view._bars.opts["height"], dtype=float)
    assert np.count_nonzero(counts) >= 5, "linear bins collapsed"
    assert counts.max() / counts.sum() < 0.5, "one bin swallowed nearly all events"

    view._log_btn.setChecked(True)
    counts = np.asarray(view._bars.opts["height"], dtype=float)
    assert counts.size >= 4, f"too few log bins: {counts.size}"
    assert np.count_nonzero(counts) >= 4


def test_scatter_point_count_and_click_signal(qapp):
    view = ScatterView()
    df = _df()
    view.set_data(df)
    assert len(view.s2.data) == len(df)

    got = []
    bus.event_selected.connect(got.append)
    spots = view.s2.points()[0]
    view._click(view.s2, [spots])
    assert got == [0]

    # highlight out of range must not raise
    view.highlight(-1)
    view.highlight(len(df) + 10)
    view.highlight(3)


def test_histogram_bars_are_visible(qapp):
    """Guards the transparent-brush regression: pyqtgraph's mkBrush reads a
    float 4-tuple as a colour *width*, so ``mkBrush(0.12, 0.47, 0.71, 0.85)``
    silently yields an alpha-0 brush and paints nothing."""
    from PyQt5.QtGui import QImage, QPainter

    from nanopore.gui.scatterview import HIST_COLOR

    assert HIST_COLOR[3] > 0, "histogram colour must be opaque"

    view = ScatterView()
    view.resize(600, 400)
    view.set_data(_df())
    img = QImage(600, 400, QImage.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    painter = QPainter(img)
    view.hist.render(painter)
    painter.end()

    r, g, b, _ = HIST_COLOR
    hits = sum(
        1
        for y in range(30, 380, 2)
        for x in range(40, 590, 2)
        if img.pixelColor(x, y).getRgb()[2] > g > img.pixelColor(x, y).getRgb()[0]
        and img.pixelColor(x, y).getRgb()[2] > 120
    )
    assert hits > 100, "histogram bars did not paint (transparent brush?)"


def test_scatter_uses_single_colour(qapp):
    """Reference-only cloud: every point shares one colour (no Io/state map)."""
    view = ScatterView()
    view.set_data(_df())
    colours = {tuple(p.brush().color().getRgb()) for p in view.s2.points()}
    assert len(colours) == 1


def test_histogram_unit_adapts_and_overrides(qapp):
    view = ScatterView()
    view.set_data(_df())          # toff ~0.3 .. ~300 ms
    assert view._unit() == "ms"
    assert view.hist.getAxis("bottom").labelUnits == "ms"
    # an explicit choice wins over the auto unit
    view._unit_box.setCurrentText("s")
    assert view._unit() == "s"
    assert view.hist.getAxis("bottom").labelUnits == "s"
    # no SI prefix on the tick axis, so "s" never renders as "ks"
    assert view.hist.getAxis("bottom").autoSIPrefix is False


def test_empty_and_none_data_no_crash(qapp):
    view = ScatterView()
    view.set_data(None)
    view.set_data(pd.DataFrame({"toff": [], "mean": [], "std": [], "Io": []}))
    assert view._bars is None
    assert len(view.s2.data) == 0
