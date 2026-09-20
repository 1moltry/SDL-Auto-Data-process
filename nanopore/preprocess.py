"""Optional low-pass filtering (Bessel, zero-phase)."""

from __future__ import annotations

import numpy as np
from scipy.signal import bessel, filtfilt


def lowpass(current: np.ndarray, sample_rate_hz: float, cutoff_hz: float | None) -> np.ndarray:
    """Apply a zero-phase Bessel low-pass. cutoff_hz=None (or >= Nyquist) returns input unchanged."""
    if cutoff_hz is None or cutoff_hz <= 0:
        return current
    nyq = sample_rate_hz / 2.0
    if cutoff_hz >= nyq:
        return current
    b, a = bessel(4, cutoff_hz / nyq, btype="low", norm="mag")
    return filtfilt(b, a, current)
