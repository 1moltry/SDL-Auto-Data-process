"""Automatic Level0 (baseline) and event-level estimation.

Replaces the manual marker-dragging step: levels are derived from the trace
itself instead of being typed in by hand.

Method (all-points amplitude histogram):
- Baseline (level 0) = strongest histogram peak; the "baseline region" is the
  contiguous span around it where the smoothed histogram stays above 20% of
  its maximum (captures smeared/drifting baselines as one region).
- Event levels = histogram local maxima outside the baseline region whose
  3-bin population significantly exceeds the Gaussian-tail expectation
  (4x expected + 3). Candidates within max(3*sigma, 2% of range) of each
  other are clustered (count-weighted mean) so one physical level is not
  split into neighbouring bins.
- Noise sigma = IQR/1.349 of samples inside the baseline region.
- Polarity: +1/-1 when candidate levels exist on only one side of baseline,
  0 when both sides have candidates (bidirectional search).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm


@dataclass
class Levels:
    level0: float              # baseline current (pA)
    levels: list[float]        # all levels: [level0, *event_levels]
    level1: float              # dominant (farthest) event level; == level0 when none found
    threshold: float           # 50% crossing between level0 and level1
    polarity: int              # +1 above baseline, -1 below, 0 both / none
    noise_sigma: float
    hist_x: np.ndarray
    hist_y: np.ndarray


def _smooth(y: np.ndarray, k: int) -> np.ndarray:
    if k < 3:
        return y
    kernel = np.ones(k) / k
    return np.convolve(y, kernel, mode="same")


def set_polarity(lv: "Levels", polarity: int) -> None:
    """Apply a manual search-direction override to an estimated level set.

    Keeps ``level1`` on the chosen side: ``detect_events`` builds its level grid
    from (level0, level1, polarity) but derives the wrong-sign rejection from
    ``sign(level1 - level0)``; if a manual "downward" left level1 above the
    baseline the two disagree and every event is rejected. polarity=0
    (bidirectional / multi-level) leaves level1 alone — the grid spans both
    sides symmetrically.
    """
    lv.polarity = polarity
    if polarity != 0 and np.sign(lv.level1 - lv.level0) != polarity:
        lv.level1 = lv.level0 + polarity * abs(lv.level1 - lv.level0)


def estimate_levels(
    current: np.ndarray,
    hist_bins: int = 200,
    min_step_sigma: float = 3.0,
    baseline: float | None = None,
    event_level: float | None = None,
) -> Levels:
    """Estimate baseline and event levels from the all-points histogram.

    Passing `baseline`/`event_level` skips the automatic search for that
    quantity (manual override path, same as typing a value into the level
    field by hand).
    """
    finite = current[np.isfinite(current)]
    n_total = len(finite)
    lo, hi = np.percentile(finite, [0.05, 99.95])
    margin = 0.10 * (hi - lo)
    lo, hi = lo - margin, hi + margin
    hist_y, edges = np.histogram(finite, bins=hist_bins, range=(lo, hi))
    centers = 0.5 * (edges[:-1] + edges[1:])
    raw = hist_y.astype(float)
    width = max(1, hist_bins // 50)
    smooth = _smooth(raw, width)

    if baseline is None:
        imode = int(np.argmax(smooth))
        baseline = float(centers[imode])

        # baseline region: contiguous bins around the mode above 20% of max
        region_thr = 0.2 * smooth.max()
        i0 = imode
        while i0 > 0 and smooth[i0 - 1] >= region_thr:
            i0 -= 1
        i1 = imode
        while i1 < len(smooth) - 1 and smooth[i1 + 1] >= region_thr:
            i1 += 1
    else:
        # region around the manual baseline: bins within 2 sigma (estimated iteratively)
        sigma_w = (hi - lo) / 20.0
        for _ in range(3):
            near = finite[np.abs(finite - baseline) < 3 * sigma_w]
            if near.size < 100:
                break
            q25, q75 = np.percentile(near, [25, 75])
            sigma_w = max((q75 - q25) / 1.349, 1e-6)
        i0 = int(np.searchsorted(centers, baseline - 2 * sigma_w))
        i1 = int(np.searchsorted(centers, baseline + 2 * sigma_w))
        i0, i1 = max(i0, 0), min(i1, len(centers) - 1)
        imode = int(np.argmin(np.abs(centers - baseline)))

    # noise sigma from baseline-region samples (IQR is robust to the small
    # event tail; the region hugs the mode so truncation is mild)
    in_region = finite[(finite >= edges[i0]) & (finite <= edges[i1 + 1])]
    if in_region.size >= 100:
        q25, q75 = np.percentile(in_region, [25, 75])
        noise_sigma = max((q75 - q25) / 1.349, 1e-6)
    else:
        noise_sigma = max(float(np.std(finite)), 1e-6)

    if event_level is not None:
        event_levels = [float(event_level)]
    else:
        # candidate event levels: local maxima (over +/-3 bins) of the raw
        # histogram outside the baseline region, statistically significant
        # against the Gaussian tail expected around the baseline
        region_bins = np.zeros(len(raw), dtype=bool)
        region_bins[i0:i1 + 1] = True
        cands: list[tuple[float, float]] = []
        for i in range(3, len(raw) - 3):
            if region_bins[i] or raw[i] < 2:
                continue
            if raw[i] < raw[i - 3:i + 4].max():
                continue
            e_lo, e_hi = edges[max(0, i - 1)], edges[min(len(edges) - 1, i + 2)]
            z_lo, z_hi = (e_lo - baseline) / noise_sigma, (e_hi - baseline) / noise_sigma
            p_win = float(norm.cdf(max(z_lo, z_hi)) - norm.cdf(min(z_lo, z_hi)))
            expected = n_total * p_win
            w3 = float(raw[i - 1:i + 2].sum())
            if w3 >= max(3.0, 4.0 * expected):
                cands.append((float(centers[i]), w3))

        # cluster candidates closer than max(3 sigma, 2% of range).
        # Keep (value, weight) in parallel lists so the count-weighted running
        # mean uses the true accumulated weight.
        event_levels: list[float] = []
        event_weights: list[float] = []
        merge_dist = max(3.0 * noise_sigma, 0.02 * (hi - lo))
        for v, w in sorted(cands):
            if event_levels and abs(v - event_levels[-1]) <= merge_dist:
                prev_v, prev_w = event_levels[-1], event_weights[-1]
                merged_w = prev_w + w
                event_levels[-1] = (prev_v * prev_w + v * w) / merged_w
                event_weights[-1] = merged_w
            else:
                event_levels.append(v)
                event_weights.append(w)

        event_levels = [v for v in event_levels
                        if abs(v - baseline) >= min_step_sigma * noise_sigma]

    all_levels = [float(baseline)] + sorted(event_levels)
    if len(all_levels) == 1:
        level1 = float(baseline)
        polarity = 0
    else:
        # level1 selection: prefer the significant level (>= 2% of samples)
        # nearest the baseline — the dominant sensing species; when no
        # candidate is significant (small-signal traces), take the candidate
        # with the largest population (deepest peaks are then artifacts).
        def frac(v: float) -> float:
            return float(np.mean(np.abs(finite - v) < 3.0 * noise_sigma))

        significant = [v for v in event_levels if frac(v) >= 0.02]
        if significant:
            level1 = min(significant, key=lambda v: abs(v - baseline))
        else:
            level1 = max(event_levels, key=frac)
        above = any(v > baseline for v in event_levels)
        below = any(v < baseline for v in event_levels)
        # polarity from the side level1 sits on; bidirectional when both sides
        # carry significant populations
        sig_above = [v for v in event_levels if v > baseline and frac(v) >= 0.02]
        sig_below = [v for v in event_levels if v < baseline and frac(v) >= 0.02]
        polarity = 0 if (sig_above and sig_below) else (1 if level1 > baseline else -1)

    return Levels(
        level0=float(baseline),
        levels=all_levels,
        level1=float(level1),
        threshold=0.5 * (float(baseline) + float(level1)),
        polarity=polarity,
        noise_sigma=float(noise_sigma),
        hist_x=centers,
        hist_y=hist_y,
    )
