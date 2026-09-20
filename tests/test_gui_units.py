"""Time-axis units + waveform overlay brushes (offscreen).

Covers the two shared-regression classes:
- explicit μs/ms/s/min units with no pyqtgraph SI prefix (no "ks"/"kms");
- overlay brushes built from int RGBA, so bands are not silently transparent.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PyQt5")
pytest.importorskip("pyqtgraph")

from nanopore.anomaly import AnomalyRegion
from nanopore.gui.units import AUTO, SEC_PER_UNIT, TimeAxis, auto_unit, per_second
from nanopore.gui.waveview import ANOM_COLORS, WaveView


@pytest.fixture(scope="session")
def qapp():
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    return app


# ---- unit helper ---------------------------------------------------------
def test_auto_unit_picks_common_units():
    assert auto_unit(5e-4) == "μs"       # 0.5 ms
    assert auto_unit(0.05) == "ms"       # 50 ms
    assert auto_unit(25.5) == "s"        # the mixture dwell span
    assert auto_unit(1235.5) == "min"    # the longest sample trace
    assert auto_unit(0.0) == "ms"        # degenerate span falls back


def test_per_second_inverts_sec_per_unit():
    for unit in SEC_PER_UNIT:
        assert per_second(unit) == pytest.approx(1.0 / SEC_PER_UNIT[unit])


def test_time_axis_labels_round_numbers_without_si_prefix(qapp):
    axis = TimeAxis(orientation="bottom")
    assert axis.autoSIPrefix is False
    axis.set_time_unit(SEC_PER_UNIT["min"])
    levels = axis.tickValues(0.0, 1235.5, 800)
    labels = axis.tickStrings(levels[0][1], 1.0, levels[0][0])
    assert labels[:5] == ["0", "5", "10", "15", "20"]


# ---- waveform overlay brushes --------------------------------------------
def test_anomaly_colors_are_not_transparent():
    for kind, rgba in ANOM_COLORS.items():
        assert rgba[3] > 0, f"{kind} overlay is transparent"


def _rec(n=50000, sr=40.0):
    return type("R", (), {"current": np.zeros(n), "sample_rate_hz": sr})()


def _empty_df():
    return pd.DataFrame({"t1": [], "t2": [], "Io": [], "mean": []})


def test_wave_axis_unit_follows_record_length(qapp):
    view = WaveView()
    view.set_data(_rec(sr=40.0), None, _empty_df(), None)   # 1250 s
    assert view._unit_box.currentText() == AUTO
    assert view.plot.getAxis("bottom").labelUnits == "min"

    view._unit_box.setCurrentText("s")                      # manual override
    assert view.plot.getAxis("bottom").labelUnits == "s"


def test_anomaly_bands_are_visible(qapp):
    regions = [AnomalyRegion("membrane_rupture", 10.0, 12.0)]
    view = WaveView()
    view.set_data(_rec(), None, _empty_df(),
                  type("A", (), {"regions": regions})())
    assert len(view._anom_regions) == 1
    assert view._anom_regions[0].brush.color().getRgb()[3] > 0
