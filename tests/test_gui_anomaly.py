"""P1: GUI anomaly panel smoke test (offscreen).

Sets QT_QPA_PLATFORM=offscreen so PyQt5 runs headless. Only verifies the
structural wiring (panel rows == anomaly regions, excluded count shown); the
visual look is confirmed by the user on a real machine.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PyQt5")

from nanopore.anomaly import AnomalyRegion
from nanopore.gui.anomalyview import AnomalyView


@pytest.fixture(scope="session")
def qapp():
    from PyQt5.QtWidgets import QApplication

    # session scope: one QApplication for the whole run — a mid-run teardown
    # (module scope) destroys Qt's app object and kills module-level QObject
    # singletons (gui.bus), breaking later GUI tests.
    app = QApplication.instance() or QApplication(sys.argv)
    return app


def _panel(qapp):
    regions = [
        AnomalyRegion("blockage_spontaneous", 10.0, 12.0, "dev -80pA"),
        AnomalyRegion("membrane_rupture", 30.0, 31.0),
    ]
    excluded = pd.DataFrame({
        "t1": [10.5, 30.2], "t2": [11.0, 30.8],
        "drop_reason": ["blockage_spontaneous", "membrane_rupture"],
    })
    view = AnomalyView()
    view.set_data(type("A", (), {"regions": regions})(), excluded)
    return view


def test_anomaly_panel_row_count_matches_regions(qapp):
    view = _panel(qapp)
    assert view.model.rowCount() == 2


def test_anomaly_panel_removed_counts(qapp):
    view = _panel(qapp)
    # removed count per region: one excluded event overlaps each region
    assert view.model._removed_count(view.model._rows[0]) == 1
    assert view.model._removed_count(view.model._rows[1]) == 1


def test_anomaly_panel_summary_qapp(qapp):
    view = _panel(qapp)
    assert "剔除事件 2" in view.summary.text()
    assert "blockage_spontaneous" in view.summary.text()
    assert "membrane_rupture" in view.summary.text()


def test_anomaly_panel_empty_excluded(qapp):
    view = AnomalyView()
    view.set_data(type("A", (), {"regions": []})(), None)
    assert view.model.rowCount() == 0
    assert "剔除事件 0" in view.summary.text()
