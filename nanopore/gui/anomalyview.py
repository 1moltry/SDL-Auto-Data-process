"""Anomaly/exclusion panel: lists anomaly regions with the events each removed.

Clicking a region focuses the waveform on that time span (traceability of the
``drop_reason`` recorded on the excluded events). This mirrors the
"what was removed and why" review step.
"""

from __future__ import annotations

import numpy as np
from PyQt5.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt5.QtWidgets import (QLabel, QTableView, QVBoxLayout, QWidget)

from .bus import bus

COLS = ["kind", "start_s", "end_s", "removed", "detail"]


class AnomalyModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._rows = []  # list[AnomalyRegion]
        self._excluded = None

    def set_data(self, anom, excluded) -> None:
        self.beginResetModel()
        self._rows = list(anom.regions) if anom is not None else []
        self._excluded = excluded
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return COLS[section]
        return None

    def _removed_count(self, r) -> int:
        if self._excluded is None or len(self._excluded) == 0:
            return 0
        t1 = self._excluded["t1"].to_numpy()
        t2 = self._excluded["t2"].to_numpy()
        return int(np.count_nonzero((t1 < r.end_s) & (t2 > r.start_s)))

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        r = self._rows[index.row()]
        if role == Qt.UserRole:
            return r
        if role == Qt.DisplayRole:
            col = index.column()
            if col == 0:
                return r.kind
            if col == 1:
                return f"{r.start_s:.2f}"
            if col == 2:
                return f"{r.end_s:.2f}"
            if col == 3:
                return str(self._removed_count(r))
            return r.detail
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None


class AnomalyView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.model = AnomalyModel()
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setSelectionBehavior(QTableView.SelectRows)
        self.view.setSelectionMode(QTableView.SingleSelection)
        self.view.horizontalHeader().setStretchLastSection(True)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.summary)
        lay.addWidget(self.view)

        self.view.selectionModel().currentChanged.connect(self._row_changed)

    def set_data(self, anom, excluded) -> None:
        self.model.set_data(anom, excluded)
        self.view.resizeColumnsToContents()
        n_excluded = 0 if excluded is None else len(excluded)
        if excluded is not None and len(excluded):
            by_kind = excluded["drop_reason"].value_counts()
            reasons = ", ".join(f"{k}x{v}" for k, v in by_kind.items())
        else:
            reasons = "（无）"
        self.summary.setText(f"剔除事件 {n_excluded}：「{reasons}」")

    def _row_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        if not current.isValid():
            return
        r = self.model.data(current, Qt.UserRole)
        if r is not None:
            bus.region_selected.emit(r.start_s, r.end_s)
