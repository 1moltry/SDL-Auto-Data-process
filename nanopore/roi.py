"""Segment-local (search-region / Cursor) analysis.

Re-analyses a sub-slice of the recording with its *own* level estimates — it does
not inherit the full-record level cursors — so the sub-region's level structure
and statistics are measured independently. Event times are reported in absolute
record coordinates.

Anomaly detection is intentionally skipped: the region is small and
statistically unstable for the 100 ms-window detectors, and the user is curating
a specific window.
"""

from __future__ import annotations

import numpy as np

from .baseline import estimate_levels
from .detect import detect_events
from .features import compute_features


def analyze_roi(
    current: np.ndarray,
    sample_rate_hz: float,
    start_s: float,
    end_s: float,
    cfg,
    label: str = "",
) -> tuple:
    """Detect + feature-extract events within ``[start_s, end_s]``.

    Returns ``(df, det, levels)`` where ``df`` uses the record's absolute
    time base (``t1``/``t2`` offset by ``start_s``). Raises ``ValueError`` if
    the region is too short for a reliable histogram level estimate.
    """
    sr = sample_rate_hz
    n = len(current)
    i0 = max(0, int(start_s * sr))
    i1 = min(n, int(end_s * sr))
    if i1 - i0 < max(1, int(0.5 * sr)):
        raise ValueError(f"ROI 过短 ({i1 - i0} samples < 0.5 s)，电平估计不可靠")

    seg = current[i0:i1]
    lv = estimate_levels(
        seg,
        hist_bins=cfg.hist_bins,
        baseline=cfg.level0,
        event_level=cfg.level1,
    )
    if cfg.polarity is not None:
        from .baseline import set_polarity

        set_polarity(lv, cfg.polarity)   # manual search-direction override
    filtered = seg
    cutoff = cfg.filter_lowpass_hz
    if cutoff:
        from .preprocess import lowpass

        filtered = lowpass(seg, sr, cutoff)

    det = detect_events(
        filtered,
        sr,
        lv.level0,
        lv.level1,
        ignore_duration_ms=cfg.ignore_duration_ms,
        ignore_event_duration_ms=cfg.ignore_event_duration_ms,
        level_contribution=cfg.level_contribution,
        update_levels=cfg.update_levels,
        polarity=lv.polarity,
        cutoff_hz=cutoff,
        pre_event_ms=cfg.pre_event_ms,
        dwell_min_frac=cfg.dwell_min_frac,
        plateau_min_frac=cfg.event_plateau_min_frac,
    )
    df = compute_features(
        det,
        filtered,
        sr,
        label=label,
        pre_event_ms=cfg.pre_event_ms,
        dr_pA=cfg.dr_pA,
    )
    if len(df):
        df["t1"] = df["t1"] + i0 / sr
        df["t2"] = df["t2"] + i0 / sr
    return df, det, lv
