"""Explicit time units for the stats and waveform axes.

pyqtgraph's default ``autoSIPrefix`` renders large axis values with SI
prefixes the domain never uses — a 25 000 ms dwell axis reads "kms", a
1200 s trace reads "ks". We pick an explicit unit from μs/ms/s/min sized
to the file instead, and let the user override it.

Data is kept in seconds (or ms for ``toff``) at the call sites; only the
displayed ticks are expressed in the chosen unit.
"""

from __future__ import annotations

import pyqtgraph as pg

#: seconds per unit
SEC_PER_UNIT = {"μs": 1e-6, "ms": 1e-3, "s": 1.0, "min": 60.0}
UNITS = ("μs", "ms", "s", "min")
AUTO = "自动"


def auto_unit(span_s: float) -> str:
    """Smallest common unit that keeps ``span_s`` in a readable range."""
    if not (span_s > 0):          # also catches NaN
        return "ms"
    if span_s < 1e-3:
        return "μs"
    if span_s < 1.0:
        return "ms"
    if span_s < 120.0:
        return "s"
    return "min"


def per_second(unit: str) -> float:
    """Multiplier converting seconds into ``unit``."""
    return 1.0 / SEC_PER_UNIT[unit]


class TimeAxis(pg.AxisItem):
    """Bottom axis rendering seconds in an explicit unit, no SI prefixes.

    Ticks are chosen in display units (so "min" lands on round numbers) and
    mapped back to data seconds for positioning, so the plotted data and all
    second-based logic (ROI regions, focus spans) stay untouched.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.enableAutoSIPrefix(False)
        self._sec_per_unit = 1.0

    def set_time_unit(self, sec_per_unit: float) -> None:
        self._sec_per_unit = sec_per_unit
        self.picture = None
        self.update()

    def tickValues(self, minVal, maxVal, size):
        s = self._sec_per_unit
        levels = super().tickValues(minVal / s, maxVal / s, size)
        return [(spacing * s, [v * s for v in vals]) for spacing, vals in levels]

    def tickStrings(self, values, scale, spacing):
        s = self._sec_per_unit
        return [f"{v / s:g}" for v in values]
