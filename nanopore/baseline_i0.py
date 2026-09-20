"""Dynamic open-pore (I0) baseline built from quiet baseline segments.

Why this exists: the per-event open-pore reference
should be the *open-pore current at that moment*, not the mean of the last
pre-event baseline run. When a long blockage (> pre_event_ms) precedes an
event and is itself treated as a "baseline run", that reference drifts down
to the blocked level and the event depth is underestimated. Building I0(t)
only from *quiet* windows (low local noise, low intra-window drift) and
interpolating between them avoids following a multi-second abnormal plateau.

Built on plain numpy as a standalone function returning a small dataclass.
Windows shorter than ``baseline_window_s`` are too noisy to be a reliable
open-pore reference at 25 kHz; the algorithm deliberately ignores them and
interpolates across.

Algorithm:
- Slide a window of ``baseline_window_s`` over the trace.
- For each window compute median level, first-difference noise
  (robust_sigma(diff)/sqrt(2)) and half-window drift.
- reference_noise = 20% quantile of window noises (the "quiet" noise floor).
- A window is *quiet* when noise <= quiet_noise_mult * reference_noise and
  drift <= max(drift_floor_pA, drift_sigma_mult * reference_noise).
- Select quiet windows greedily from an anchor (the quiet window closest to
  ``anchor_level`` when one is given, else the first quiet window), tracking
  slow drift but rejecting a jump to another level that lasts one window.
- Median-filter accepted levels, then interpolate to a per-sample baseline
  and per-sample noise floor.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import median_filter


@dataclass
class I0Profile:
    baseline: np.ndarray        # per-sample open-pore current (pA), float32
    noise: np.ndarray           # per-sample local noise estimate (pA), float32
    reference_noise: float      # quiet-window noise floor used by detectors
    centers_s: np.ndarray       # window centre times (s)
    window_levels: np.ndarray   # median level per window (pA, may contain NaN)
    window_noise: np.ndarray    # first-difference noise per window
    quiet: np.ndarray           # bool per window that passed the quiet test


def robust_sigma(values: np.ndarray) -> float:
    """Robust Gaussian noise estimate: 1.4826 * median(|x - median(x)|)."""
    values = np.asarray(values, dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0
    med = float(np.median(finite))
    sigma = 1.4826 * float(np.median(np.abs(finite - med)))
    if sigma <= np.finfo(float).eps:
        sigma = float(np.std(finite)) if finite.size > 1 else 0.0
    return max(sigma, np.finfo(float).eps)


def build_dynamic_baseline(
    current: np.ndarray,
    sample_rate_hz: float,
    *,
    baseline_window_s: float = 1.0,
    noise_quantile: float = 0.20,
    quiet_noise_mult: float = 2.5,
    drift_floor_pA: float = 1.0,
    drift_sigma_mult: float = 3.0,
    min_window_samples: int = 20,
    smooth_windows: int = 5,
    anchor_level: float | None = None,
) -> I0Profile:
    sr = sample_rate_hz
    n = len(current)
    window = max(50, int(round(baseline_window_s * sr)))
    step = window  # non-overlapping; 900 s @25 kHz -> 900 windows, cheap

    centers: list[float] = []
    levels: list[float] = []
    noises: list[float] = []
    drifts: list[float] = []
    for start in range(0, n, step):
        end = min(n, start + step)
        x = current[start:end].astype(float)
        centers.append((start + end - 1) / 2.0 / sr)
        if x.size < max(min_window_samples, window // 10):
            levels.append(np.nan)
            noises.append(np.nan)
            drifts.append(np.nan)
            continue
        levels.append(float(np.median(x)))
        if x.size > 1:
            noises.append(robust_sigma(np.diff(x)) / np.sqrt(2.0))
        else:
            noises.append(np.nan)
        half = x.size // 2
        if half:
            drifts.append(abs(float(np.median(x[:half])) - float(np.median(x[half:]))))
        else:
            drifts.append(np.nan)

    centers_a = np.asarray(centers, dtype=float)
    levels_a = np.asarray(levels, dtype=float)
    noises_a = np.asarray(noises, dtype=float)
    drift_a = np.asarray(drifts, dtype=float)

    finite_noise = noises_a[np.isfinite(noises_a)]
    reference_noise = (
        float(np.quantile(finite_noise, noise_quantile)) if finite_noise.size else 0.0
    )
    if reference_noise <= 0 or not np.isfinite(reference_noise):
        reference_noise = float(np.median(noises_a[np.isfinite(noises_a)])) if np.isfinite(noises_a).any() else 1.0
    reference_noise = max(reference_noise, np.finfo(float).eps)

    # intra-window drift (|median(first half) - median(second half)|) feeds
    # the quiet test: a clean long plateau has low noise but may be an event,
    # so windows that drift mid-window are not open-pore references.
    quiet = (
        (noises_a <= quiet_noise_mult * reference_noise)
        & (drift_a <= max(drift_floor_pA, drift_sigma_mult * reference_noise))
        & np.isfinite(levels_a)
    )
    if not np.any(quiet):
        quiet = np.isfinite(levels_a)

    # Greedy acceptance from an anchor quiet window. Compare against the last
    # ACCEPTED window's median (not an EMA): an EMA lags a steady drift and
    # eventually trails far enough that a slow ramp is wrongly rejected. With
    # the last accepted level, adjacent quiet windows are accepted as long as
    # the drift between consecutive windows stays below maximum_step, while an
    # abrupt jump to a foreign plateau (one window, > maximum_step) is not.
    #
    # Anchor selection: when ``anchor_level`` (the record's open-pore level
    # from estimate_levels) is supplied, pick the QUIET window whose median is
    # closest to it. Without it, the first quiet window is used — but that can
    # be a quiet NON-open-pore segment (e.g. a flat gap in a tPAL voltage
    # protocol at ~0 pA, or a secondary pore state) that the chain then follows
    # for the whole record, corrupting Io. Anchoring near the dominant pore
    # current avoids that.
    quiet_idx = np.flatnonzero(quiet)
    if anchor_level is not None and quiet_idx.size:
        anchor_idx = quiet_idx[int(np.argmin(np.abs(levels_a[quiet_idx] - float(anchor_level))))]
    else:
        anchor_idx = int(quiet_idx[0])
    accepted = np.zeros_like(quiet, dtype=bool)
    accepted[anchor_idx] = True
    last_level = float(levels_a[anchor_idx])
    maximum_step = max(6.0, 5.0 * reference_noise)
    for i in range(anchor_idx + 1, len(levels_a)):
        if quiet[i] and abs(float(levels_a[i]) - last_level) <= maximum_step:
            accepted[i] = True
            last_level = float(levels_a[i])
    last_level = float(levels_a[anchor_idx])
    for i in range(anchor_idx - 1, -1, -1):
        if quiet[i] and abs(float(levels_a[i]) - last_level) <= maximum_step:
            accepted[i] = True
            last_level = float(levels_a[i])

    sel_centers = centers_a[accepted]
    sel_levels = levels_a[accepted]
    sel_noise = noises_a[accepted]
    if sel_levels.size == 0:
        sel_centers = centers_a[np.isfinite(levels_a)]
        sel_levels = levels_a[np.isfinite(levels_a)]
        sel_noise = noises_a[np.isfinite(noises_a)]
    if sel_levels.size > 2:
        sel_levels = median_filter(
            sel_levels, size=min(smooth_windows, sel_levels.size // 2 * 2 + 1),
            mode="nearest",
        )

    time = np.arange(n, dtype=float) / sr
    baseline = _interp(time, sel_centers, sel_levels, float(np.nanmedian(levels_a)))
    noise = _interp(time, sel_centers, sel_noise, reference_noise)
    noise = np.maximum(noise, reference_noise * 0.25).astype(np.float32)
    return I0Profile(
        baseline=baseline.astype(np.float32),
        noise=noise,
        reference_noise=reference_noise,
        centers_s=centers_a,
        window_levels=levels_a,
        window_noise=noises_a,
        quiet=quiet,
    )


def _interp(
    time: np.ndarray,
    centers: np.ndarray,
    values: np.ndarray,
    fallback: float,
) -> np.ndarray:
    good = np.isfinite(values)
    if not np.any(good):
        return np.full(time.size, fallback, dtype=float)
    return np.interp(time, centers[good], values[good]).astype(np.float32)
