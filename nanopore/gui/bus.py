"""Cross-view event-selection bus.

A single :class:`Bus` instance connects the waveform, scatter, table and
search panels. Selecting an event in any view emits ``event_selected`` and the
other views highlight/sync to it, so a selection made anywhere is reflected
everywhere.
"""

from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal


class Bus(QObject):
    event_selected = pyqtSignal(int)          # row index into the current events DataFrame
    region_selected = pyqtSignal(float, float)  # anomaly region [start_s, end_s] — focus waveform
    file_loaded = pyqtSignal(str)             # absolute path of the loaded .abf
    detection_finished = pyqtSignal()         # all views should refresh their data
    roi_rerun = pyqtSignal(float, float)      # request ROI analysis on [start_s, end_s]
    roi_finished = pyqtSignal(object, tuple)  # roi df + (start_s, end_s) span
    status = pyqtSignal(str)                  # status-bar text


bus = Bus()
