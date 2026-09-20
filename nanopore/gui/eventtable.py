"""Results table (event feature sheet) with a state filter.

Rows carry the original DataFrame index in ``Qt.UserRole`` so the table can be
filtered by state while still emitting the correct event index on selection.
"""

from __future__ import annotations

import numpy as np
from PyQt5.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt5.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QTableView,
                             QVBoxLayout, QWidget)

from .bus import bus

COLS = ["t1", "t2", "toff", "mean", "%mean", "Io", "std", "skew", "kurt",
        "MAD", "CV", "q1", "q2", "q3", "iqr", "outlier_ratio", "ton", "state"]


class EventsModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._df = None
        self._mask = None
        self._rows = np.array([], dtype=int)

    def set_df(self, df) -> None:
        self.beginResetModel()
        self._df = df
        self._mask = np.ones(len(df), dtype=bool) if df is not None else None
        self._refresh_rows()
        self.endResetModel()

    def set_state_filter(self, state: str) -> None:
        if self._df is None:
            return
        if state in ("", "all"):
            self._mask = np.ones(len(self._df), dtype=bool)
        else:
            self._mask = (self._df["state"] == state).to_numpy()
        self.beginResetModel()
        self._refresh_rows()
        self.endResetModel()

    def _refresh_rows(self) -> None:
        self._rows = np.flatnonzero(self._mask) if self._mask is not None else np.array([], dtype=int)

    def rowCount(self, parent=QModelIndex()) -> int:
        return int(len(self._rows))

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return COLS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or self._df is None:
            return None
        if index.row() >= len(self._rows):
            return None
        orig = int(self._rows[index.row()])
        if role == Qt.UserRole:
            return orig
        if role == Qt.DisplayRole:
            val = self._df.iloc[orig][COLS[index.column()]]
            if isinstance(val, float):
                if val != val:  # NaN
                    return "nan"
                return f"{val:.4g}"
            return str(val)
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None


class EventTable(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.model = EventsModel()
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setSelectionBehavior(QTableView.SelectRows)
        self.view.setSelectionMode(QTableView.SingleSelection)
        self.view.setSortingEnabled(False)
        self.view.horizontalHeader().setStretchLastSection(True)

        self.state_combo = QComboBox()
        self.state_combo.addItems(["all", "A", "B"])
        self.state_combo.currentTextChanged.connect(self._state_changed)

        top = QHBoxLayout()
        top.addWidget(QLabel("State:"))
        top.addWidget(self.state_combo)
        top.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(top)
        lay.addWidget(self.view)

        self.view.selectionModel().currentChanged.connect(self._row_changed)

    def set_data(self, df) -> None:
        self.model.set_df(df)
        self.view.resizeColumnsToContents()

    def _state_changed(self, text: str) -> None:
        self.model.set_state_filter(text)

    def _row_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        if current.isValid():
            orig = self.model.data(current, Qt.UserRole)
            bus.event_selected.emit(int(orig))

    def select_row(self, orig_idx: int) -> None:
        rows = self.model._rows
        if len(rows) == 0:
            return
        pos = int(np.searchsorted(rows, orig_idx))
        if pos < len(rows) and rows[pos] == orig_idx:
            self.view.selectRow(pos)
