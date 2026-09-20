"""Anomaly detection: blockages, membrane breakdown, baseline-state boundaries,
and jitter; yields valid analysis windows.

Two detectors live here.

``detect_anomalies`` — the macro-block envelope detector:
- The trace's level structure (open pore + event levels, from the all-points
  histogram) defines an "envelope". Sustained block-mean deviations OUTSIDE
  the envelope are artifacts: breakdown when extreme (>= breakdown_mult x
  sigma beyond the envelope edge), blockage otherwise (deep blockade,
  reverse-voltage steps).
- The envelope spans the deepest SIGNIFICANT (>= 2% population) level. When no
  level is significant — a sparse peptide trace whose blockades are each rare —
  it spans ALL detected levels instead of collapsing to the bare noise margin,
  so the analyte's own deep blockades are not mistaken for breakdown (ARNKRS).
- Significant block populations at other levels are slow pore-state
  switching (Ala/Asp 110<->180 pA, Gln oscillation): valid data, but the
  step boundaries are reported as "baseline_step" regions for user review.
- Jitter: sliding noise std far above the record's robust sigma.

``detect_artifact_segments`` — fine-grained per-window detector. It catches
what the macro detector misses and distinguishes recovery mode:
- reverse_voltage: the command/holding voltage channel drops below a negative
  threshold (operator-applied reversal). Requires a voltage trace;
  without it this class is skipped.
- membrane_rupture: state machine over window IQR (>=2 consecutive broad-noise
  windows, recovery only after N quiet windows).
- membrane_jitter_{mild,severe}: per-window first-difference noise ratio to the
  quiet reference. This catches PURE high-frequency jitter whose window MEAN
  stays near open pore — the case the macro detector's "mean must leave the
  envelope" rule misses (e.g. Gln membrane wobble).
- blockage_spontaneous / blockage_manual_recovery: a long (>500 ms) smooth
  deviation from the open-pore baseline that is also internally IRREGULAR
  (noise ratio >= mild). Requiring internal irregularity avoids flagging a
  clean, stable pore-state switch (110<->180 pA) as a blockage. Recovery is
  manual when the segment overlaps a reverse-voltage run, else spontaneous.
- baseline_drift: a sustained, gradual, IRREVERSIBLE displacement of the
  open-pore level from its record-head anchor, accompanied by high signal
  spread (region IQR >= drift_iqr_ratio x the record-head IQR). BOTH keys are
  required: a benign slow shift that keeps producing normal events has
  displacement but no instability -> not flagged; a dense event burst has
  instability but no displacement -> not flagged. A stable pore-state step and
  a transient excursion that recovers are excluded by the gradual / irreversible
  keys. Where instability is extreme the tail is also labelled membrane_rupture.

``detect_artifact_segments`` runs at ~100 ms window resolution so cost is
independent of record length.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import uniform_filter1d

from .baseline_i0 import robust_sigma


@dataclass
class AnomalyRegion:
    kind: str          # macro: "blockage"|"breakdown"|"baseline_step"|"jitter"
                       # refined: "reverse_voltage"|"membrane_rupture"|
                       #   "membrane_jitter_mild"|"membrane_jitter_severe"|
                       #   "blockage_spontaneous"|"blockage_manual_recovery"|
                       #   "baseline_drift"
    start_s: float
    end_s: float
    detail: str = ""


@dataclass
class AnomalyResult:
    regions: list[AnomalyRegion]
    valid: np.ndarray          # bool per macro block: True = clean
    block_means: np.ndarray    # pA per macro block (diagnostics)
    block_s: float             # block duration in seconds
    open_pore: float           # open-pore reference used


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        return []
    brk = np.flatnonzero(np.diff(idx) > 1)
    return [(s[0], s[-1] + 1) for s in np.split(idx, brk + 1)]


def detect_anomalies(
    current: np.ndarray,
    sample_rate_hz: float,
    open_pore: float | None = None,
    noise_sigma: float | None = None,
    event_levels: list[float] | None = None,
    block_ms: float = 100.0,
    jump_min_ms: float = 50.0,
    step_min_sigma: float = 5.0,
    breakdown_mult: float = 3.0,
    jitter_mult: float = 4.0,
    jitter_min_ms: float = 100.0,
    state_min_frac: float = 0.02,
    jitter_level_frac_max: float = 0.20,
) -> AnomalyResult:
    sr = sample_rate_hz
    nblk_n = int(round(block_ms * 1e-3 * sr))
    nblk = len(current) // nblk_n
    if nblk < 4:
        bm = np.asarray(current[:nblk_n], dtype=float)
        return AnomalyResult([], np.ones(max(nblk, 1), dtype=bool), bm, block_ms * 1e-3,
                             float(open_pore) if open_pore is not None else float(np.median(current)))
    blocks = current[: nblk * nblk_n].reshape(nblk, nblk_n)
    bm = blocks.mean(axis=1)
    bstd = blocks.std(axis=1)

    if open_pore is None:
        hist, edges = np.histogram(bm, bins=100)
        open_pore = float(0.5 * (edges[np.argmax(hist)] + edges[np.argmax(hist) + 1]))
    open_pore = float(open_pore)
    if noise_sigma is None:
        q25, q75 = np.percentile(bm, [25, 75])
        noise_sigma = max((q75 - q25) / 1.349, 1e-6)
    noise_sigma = float(noise_sigma)

    # --- envelope from levels: significant populations widen the envelope.
    # Fraction thresholds: >= 2% of samples marks a real level (state or event
    # population); smaller populations are event tails or artifact spikes and do
    # not widen the envelope (so Asp's multi-second deep blockages, sample
    # fraction ~0.5%, register as anomalies).
    if event_levels:
        sig_levels = []
        for v in event_levels:
            if abs(v - open_pore) < 3.0 * noise_sigma:
                continue  # the open pore itself
            frac = float(np.mean(np.abs(current[: nblk * nblk_n] - v) < 3.0 * noise_sigma))
            if frac >= 0.02:
                sig_levels.append(v)
        if sig_levels:
            outer = max(abs(np.asarray(sig_levels) - open_pore))
        else:
            # No level clears the 2% population bar: a SPARSE peptide trace whose
            # discrete blockades are individually rare. The levels are still the
            # analyte's conducting states, so the envelope must span ALL of them.
            # The bare 8*sigma margin (~18 pA at 2 pA noise) collapses the
            # envelope and flags every deep peptide blockade as breakdown/blockage
            # (ARNKRS reaches -105..+97 pA; its deepest block mean is only
            # -97 pA, so a level-spanning envelope of ~123 pA clears it).
            cand = np.abs(np.asarray(
                [v for v in event_levels if abs(v - open_pore) >= 3.0 * noise_sigma],
                dtype=float) - open_pore)
            outer = float(cand.max()) if cand.size else 8.0 * noise_sigma
    else:
        outer = 8.0 * noise_sigma
    envelope = outer + 8.0 * noise_sigma   # beyond the deepest significant level

    dev = bm - open_pore
    absdev = np.abs(dev)
    extreme_thr = envelope + breakdown_mult * 5.0 * noise_sigma
    min_blocks = max(1, int(np.ceil(jump_min_ms / block_ms)))

    regions: list[AnomalyRegion] = []

    # breakdown: extreme sustained excursions well beyond the event envelope
    for s, e in _runs(absdev > extreme_thr):
        if (e - s) >= min_blocks:
            regions.append(AnomalyRegion("breakdown", s * block_ms * 1e-3, e * block_ms * 1e-3,
                                         f"|dev|>={extreme_thr:.0f}pA"))

    # blockage: sustained deviations beyond the envelope but below breakdown
    in_region = np.zeros(nblk, dtype=bool)
    for r in regions:
        i0, i1 = int(r.start_s / (block_ms * 1e-3)), int(np.ceil(r.end_s / (block_ms * 1e-3)))
        in_region[i0:i1] = True
    cand = (absdev > envelope) & ~in_region
    for s, e in _runs(cand):
        # blockages are macroscopic (seconds): require >= 3 macro blocks so
        # ordinary deep events (ms-scale, e.g. ARNKRS peptides) don't trigger
        if (e - s) >= max(min_blocks, 3):
            regions.append(AnomalyRegion("blockage", s * block_ms * 1e-3, e * block_ms * 1e-3,
                                         f"dev {dev[s:e].mean():+.0f}pA"))
            in_region[s:e] = True

    # state switching: significant block populations at non-open-pore levels
    # (blocks must be FLAT: intra-block std small, so event-containing blocks
    # don't count as a state); mark entry/exit boundaries as baseline_step
    flat = bstd < 3.0 * noise_sigma
    hist, edges = np.histogram(bm[flat], bins=max(30, nblk // 4))
    significant = hist >= state_min_frac * nblk
    away = (absdev > step_min_sigma * noise_sigma) & flat
    for s, e in _runs(away & np.array([
            significant[min(len(significant) - 1, max(0, np.searchsorted(edges, v) - 1))]
            for v in bm])):
        if (e - s) >= min_blocks:
            # boundary: extend by one block on each side for context
            regions.append(AnomalyRegion(
                "baseline_step",
                max(0.0, (s - 1) * block_ms * 1e-3),
                min(len(current) / sr, (e + 1) * block_ms * 1e-3),
                f"state {bm[s:e].mean():.0f}pA dur {(e - s) * block_ms:.0f}ms"))

    # jitter: sliding std above jitter_mult x sigma (not already inside a region).
    # Blocks containing ordinary events have high intra-block std by design —
    # only flag when the block mean ALSO departs from open pore (events sit at
    # a level within the envelope; jitter wanders without level structure).
    # Dense event clusters (short peptide bursts) also raise block std and dra
    # the mean outward, so additionally require the block to NOT be
    # level-structured: if a large fraction of its samples sit near a
    # non-baseline significant level it is a burst of discrete events, not
    # membrane jitter (enkephalin/ACTH pattern).
    nonbase = [v for v in (event_levels or []) if abs(v - open_pore) > 3.0 * noise_sigma]
    if nonbase:
        nl_arr = np.asarray(nonbase, dtype=float)
        b_lvl = np.empty(nblk)
        for bi in range(nblk):
            b_lvl[bi] = float(np.mean(
                np.min(np.abs(blocks[bi][:, None] - nl_arr[None, :]), axis=1) < 3.0 * noise_sigma))
    else:
        b_lvl = np.zeros(nblk)
    noisy = (bstd > jitter_mult * noise_sigma) & (absdev > envelope) & ~in_region \
        & (b_lvl < jitter_level_frac_max)
    min_jblocks = max(1, int(np.ceil(jitter_min_ms / block_ms)))
    for s, e in _runs(noisy):
        if (e - s) >= min_jblocks:
            regions.append(AnomalyRegion("jitter", s * block_ms * 1e-3, e * block_ms * 1e-3,
                                         f"std {bstd[s:e].mean():.1f}pA"))

    # valid mask: breakdown/blockage/jitter invalidate; baseline_step stays valid
    valid = np.ones(nblk, dtype=bool)
    for r in regions:
        if r.kind == "baseline_step":
            continue
        i0 = max(0, int(r.start_s / (block_ms * 1e-3)))
        i1 = min(nblk, int(np.ceil(r.end_s / (block_ms * 1e-3))))
        valid[i0:i1] = False

    regions.sort(key=lambda r: r.start_s)
    return AnomalyResult(regions=regions, valid=valid, block_means=bm,
                         block_s=block_ms * 1e-3, open_pore=open_pore)


def invalid_region_reasons(
    start_times_s,
    end_times_s,
    regions: list[AnomalyRegion],
) -> list[str]:
    """Per-event exclusion reason: '' = kept, else the ``|``-joined kinds of
    the invalid regions the event overlaps. Unlike
    :func:`events_in_invalid_regions`, overlapping *multiple* kinds report all
    of them so the drop is traceable. ``baseline_step`` never produces a
    reason (a pore-state boundary stays valid data).

    Matches :func:`events_in_invalid_regions` semantics (a reason is non-empty
    exactly when the mask would flag the event), so callers can use either.
    """
    if len(start_times_s) == 0:
        return []
    reasons = [""] * len(start_times_s)
    for r in regions:
        if r.kind == "baseline_step":
            continue
        hit = (start_times_s < r.end_s) & (end_times_s > r.start_s)
        for i in np.flatnonzero(hit):
            if r.kind not in reasons[i].split("|"):
                reasons[i] = reasons[i] + "|" + r.kind if reasons[i] else r.kind
    return reasons


def events_in_invalid_regions(
    start_times_s: np.ndarray,
    end_times_s: np.ndarray,
    regions: list[AnomalyRegion],
) -> np.ndarray:
    """Boolean mask: True = event overlaps an invalid (artifact) region."""
    return np.array([r != "" for r in invalid_region_reasons(start_times_s, end_times_s, regions)],
                    dtype=bool)


@dataclass
class ArtifactConfig:
    """Thresholds for :func:`detect_artifact_segments`.

    Defaults are the values validated against the lab's annotated recordings.
    """

    voltage_threshold_mV: float = -5.0        # (legacy) absolute negative-rail test, kept
                                              # for callers that pass a fixed threshold
    hold_voltage_mV: float | None = None      # recording hold voltage; None = median of the
                                              # voltage trace (the dominant protocol level, i.e.
                                              # the sensing segment). Any sustained deviation
                                              # from it is a protocol segment (reverse/wash).
    hold_tol_mV: float = 5.0                  # |V - hold| above this = out of hold
    protocol_transient_ms: float = 100.0      # skip this much after a protocol switch (settling)
    reverse_min_ms: float = 1.0               # reverse run must last this long
    jitter_window_ms: float = 100.0           # per-window noise/blockage resolution
    jitter_mild_ratio: float = 3.0            # window noise / reference_noise -> mild
    jitter_severe_ratio: float = 8.0          # -> severe
    jitter_osc_floor: float = 0.45            # min sign-change fraction of diff to call a
                                              # high-noise window jitter (dense discrete events
                                              # flip sign rarely, pure noise flips ~0.6)
    rupture_noise_min_ratio: float = 2.0      # a broad-IQR window is rupture only if it is ALSO
                                              # internally noisy (a clean level step of a voltage
                                              # protocol is broad but quiet -> not a rupture)
    rupture_iqr_min_pA: float = 80.0          # window IQR >= this = broad (rupture) noise
    rupture_quiet_windows: int = 5            # consecutive quiet windows to end rupture
    rupture_level_frac_max: float = 0.24      # a rupture window must have <= this fraction of
                                              # samples near a significant level. A dense burst
                                              # of discrete events (peptide cluster) is broad+IQR
                                              # but level-structured (frac high) -> NOT rupture.
                                              # A real rupture wanders diffusely (frac low).
    recovery_guard_ms: float = 100.0          # pad after a confirmed anomaly
    blockage_min_ms: float = 500.0            # deviation must persist >= this
    blockage_fraction: float = 0.45           # deviation magnitude vs |open pore|

    # --- slow baseline drift / instability (new kind "baseline_drift") ---
    # A sustained, gradual, IRREVERSIBLE displacement of the open-pore level from
    # its record-head anchor, that is ALSO accompanied by high signal spread.
    # Requires all of: displacement AND instability. Displacement alone (a benign
    # slow shift that keeps producing normal events) is NOT flagged; instability
    # alone (a dense event burst) is NOT flagged. Graded so a stable pore-state
    # step (Ala/Asp 110<->180) and a transient excursion that recovers (ACTH) are
    # excluded by the gradual / irreversible keys.
    drift_enabled: bool = True
    drift_block_s: float = 15.0               # windows are aggregated into blocks this long
    drift_min_s: float = 20.0                 # displaced run must last this long
    drift_min_frac: float = 0.05              # |block - anchor| >= this fraction of |anchor|
    drift_iqr_ratio: float = 3.0              # region IQR / record-head IQR, the instability key
    drift_step_pA: float = 6.0                # max block-to-block jump (gradual key), absolute floor
    drift_step_frac: float = 0.05             # ... relative part: max(drift_step_pA, frac*|anchor|)
    drift_anchor_frac: float = 0.20           # record-head fraction used as the anchor
    drift_rupture_ratio: float = 4.0          # region IQR ratio at/above which the tail is also
                                              # labelled membrane_rupture (extreme instability)
    # baseline used for the blockage deviation check: an I0Profile yields the
    # dynamic open-pore baseline; the record-head window_baseline[0] anchors the
    # slow multi-second plateau check (the dynamic profile would follow a long
    # blockage and hide it).
    # (the two runs below are merged.)


def detect_artifact_segments(
    current: np.ndarray,
    sample_rate_hz: float,
    *,
    voltage: np.ndarray | None = None,
    i0_profile=None,
    open_pore: float | None = None,
    event_levels: list[float] | None = None,
    cfg: ArtifactConfig | None = None,
) -> AnomalyResult:
    """Fine-grained anomaly detection (reverse voltage / rupture / jitter /
    irregular blockage) that distinguishes spontaneous vs manual recovery.

    Returns an :class:`AnomalyResult` whose ``regions`` carry the refined
    kinds listed in the module docstring. ``valid`` is per ~100 ms window.
    Unlike the macro detector this does NOT need the event-level envelope, so
    pure high-frequency jitter whose mean stays near open pore (Gln membrane
    wobble) is caught here.
    """
    c = cfg or ArtifactConfig()
    sr = sample_rate_hz
    n = len(current)
    if n < 20:
        return AnomalyResult([], np.ones(1, dtype=bool), np.asarray([], dtype=float),
                             1.0 / sr, float(open_pore) if open_pore is not None else float(np.median(current)))
    if open_pore is None:
        open_pore = float(np.median(current))
    open_pore = float(open_pore)

    # quiet reference: if we have an I0Profile use its reference_noise, else a
    # per-window robust noise floor.
    if i0_profile is not None and i0_profile.reference_noise > 0:
        reference_noise = float(i0_profile.reference_noise)
    else:
        jw0 = max(20, int(round(c.jitter_window_ms * sr / 1000)))
        _d = current.astype(float)
        _w = [robust_sigma(_d[a:a + jw0]) if len(_d[a:a + jw0]) > 1 else 0.0
              for a in range(0, n, jw0)]
        _w = np.asarray(_w, dtype=float)
        _w = _w[np.isfinite(_w) & (_w > 0)]
        reference_noise = float(np.quantile(_w, 0.20)) if _w.size else 1.0
    reference_noise = max(reference_noise, np.finfo(float).eps)

    jw = max(20, int(round(c.jitter_window_ms * sr / 1000)))
    win_start = list(range(0, n, jw))
    win_end = [min(n, a + jw) for a in win_start]
    nwin = len(win_start)
    # level set for the level-structure gate: significant event levels + open pore
    gate_levels = np.asarray(list(event_levels or []) + [open_pore], dtype=float)
    gate_levels = gate_levels[np.isfinite(gate_levels)]
    w_iqr = np.zeros(nwin)
    w_noise = np.zeros(nwin)
    w_med = np.zeros(nwin)
    w_base = np.zeros(nwin)
    w_osc = np.zeros(nwin)   # sign-change fraction of diff: 1=random noise, ~0.2=dense events
    w_lvl = np.zeros(nwin)   # fraction of samples within 3*ref_noise of a significant level
    ref3 = 3.0 * reference_noise
    for i, (a, b) in enumerate(zip(win_start, win_end)):
        x = current[a:b].astype(float)
        if b - a < 2:
            w_iqr[i] = w_noise[i] = w_med[i] = 0.0
            w_lvl[i] = 0.0
            continue
        w_iqr[i] = float(np.subtract(*np.quantile(x, [0.75, 0.25])))
        w_noise[i] = robust_sigma(np.diff(x)) / np.sqrt(2.0) if len(x) > 1 else 0.0
        w_med[i] = float(np.median(x))
        if gate_levels.size:
            # fraction of window samples close to any significant level: high for a
            # dense burst of discrete events, low for a diffuse membrane rupture
            w_lvl[i] = float(np.mean(np.min(np.abs(x[:, None] - gate_levels[None, :]), axis=1) < ref3))
        d = np.diff(x)
        if d.size > 1:
            sgn = np.sign(d)
            w_osc[i] = float(np.count_nonzero(sgn[1:] != sgn[:-1]) / (d.size - 1)) if d.size > 1 else 0.0
        if i0_profile is not None and i0_profile.baseline.size == n:
            w_base[i] = float(np.median(i0_profile.baseline[a:b])) if b > a else float(open_pore)
        else:
            w_base[i] = float(open_pore)
    excluded = np.zeros(n, dtype=bool)   # not used for gating; reverse overlap kept
    regions: list[AnomalyRegion] = []
    # window noise ratio vs the quiet reference (shared by rupture and jitter)
    ratio = np.divide(w_noise, reference_noise, out=np.zeros(nwin),
                      where=reference_noise > 0)

    def _add(kind: str, a: int, b: int, detail: str = "") -> None:
        regions.append(AnomalyRegion(kind, a / sr, min(n, b) / sr, detail))

    # --- protocol voltage segments (reverse voltage / wash) ---
    # Any sustained deviation of the command/holding voltage from its dominant
    # (sensing) level is a protocol segment: operator-applied reversal (Ala),
    # the tPAL +100/-50 wash cycle, or the 0 mV rest level. Events inside them
    # are not sensing events and are excluded.
    reverse_runs: list[tuple[int, int]] = []
    if voltage is not None:
        v = np.asarray(voltage, dtype=float)
        guard = int(round(c.recovery_guard_ms * sr / 1000))
        pre_guard = int(round(c.protocol_transient_ms * sr / 1000))
        hold = c.hold_voltage_mV if c.hold_voltage_mV is not None else float(np.median(v))
        min_rev = max(1, int(round(c.reverse_min_ms * sr / 1000)))
        for a, b in _runs(np.abs(v - hold) > c.hold_tol_mV):
            if b - a < min_rev:
                continue
            start = max(0, a - pre_guard)   # switching transient settles after the step
            end = min(n, b + guard)
            _add("reverse_voltage", start, end,
                 f"V={float(np.median(v[a:b])):.0f}mV (hold {hold:.0f}) dur {(b - a) / sr * 1e3:.0f}ms")
            reverse_runs.append((a, end))

    # --- rupture state machine: >=2 consecutive broad AND internally noisy
    #     windows, recovery only after `quiet_windows` quiet windows. A clean
    #     level step (e.g. a voltage-protocol segment boundary) is broad-IQR but
    #     internally quiet (noise ratio ~1), so it is NOT a rupture. A dense
    #     burst of discrete events (peptide cluster) is broad AND internally
    #     noisy, so it also needs the level-structure gate: if most samples sit
    #     near a significant level (w_lvl high) it is a real event cluster, not
    #     a diffuse rupture.
    broad = ((w_iqr >= c.rupture_iqr_min_pA) & (ratio >= c.rupture_noise_min_ratio)
             & (w_lvl <= c.rupture_level_frac_max))
    quiet_win = w_iqr < c.rupture_iqr_min_pA * 0.375
    guard_win = max(1, int(round(c.recovery_guard_ms / c.jitter_window_ms)))
    rupture_spans: list[tuple[int, int]] = []   # confirmed window [first, end_win)
    i = 0
    while i < nwin:
        if not broad[i]:
            i += 1
            continue
        j = i
        while j < nwin and broad[j]:
            j += 1
        if j - i >= 2:  # rupture confirmed
            k = j
            qc = 0
            while k < nwin:
                if quiet_win[k]:
                    qc += 1
                    if qc >= c.rupture_quiet_windows:
                        look = min(nwin, k + 1 + guard_win)
                        relapse = np.any(broad[k + 1:look])
                        if not relapse:
                            break
                        k = look - 1
                        qc = 0
                else:
                    qc = 0
                k += 1
            end_win = min(nwin, k + 1) if k < nwin else nwin
            a, b = win_start[i], win_end[end_win - 1]
            # Region-level level-structure gate: a dense burst of discrete events
            # has broad-IQR + noisy SINGLE windows, but over the WHOLE confirmed
            # span most samples sit at a significant level (drift-to-level, then
            # recovery to that level). A real rupture wanders diffusely across the
            # span. Re-checking at span granularity (not just per window) is more
            # robust: e.g. REFEFTRC 8.1-9.7 has per-window w_lvl<=0.24 but whole-
            # span frac 0.43 (event cluster) -> correctly rejected here.
            span = current[a:b].astype(float)
            if gate_levels.size and span.size:
                span_lvl = float(np.mean(
                    np.min(np.abs(span[:, None] - gate_levels[None, :]), axis=1) < ref3))
            else:
                span_lvl = 0.0
            if span_lvl < c.rupture_level_frac_max:
                _add("membrane_rupture", a, b,
                     f"IQR>={c.rupture_iqr_min_pA:.0f}pA {j - i} windows dur {(b - a) / sr * 1e3:.0f}ms")
                rupture_spans.append((i, end_win))
            i = end_win
            continue
        i = j

    # --- jitter: window first-difference noise ratio vs the quiet reference.
    # The rupture RECOVERY TAIL (windows between the last broad window and the
    # confirmed end_win) is still high-noise but no longer broad-IQR; it must be
    # consumed by the rupture region so it is not separately labelled jitter.
    consumed = broad.copy()
    for s0, e0 in rupture_spans:
        consumed[s0:e0] = True

    # --- slow baseline drift / instability ---
    # Uses the I0 profile's per-window levels (median per 1 s window, including
    # NON-quiet windows — the quiet chain deliberately follows drift and would
    # not see it). Windows are aggregated into drift_block_s blocks; a trailing
    # run of displaced blocks that is gradual and irreversible, AND whose span
    # has high spread (IQR ratio), is the drift region.
    drift_spans: list[tuple[float, float]] = []
    if c.drift_enabled and i0_profile is not None:
        wl = np.asarray(getattr(i0_profile, "window_levels", []), dtype=float)
        wc = np.asarray(getattr(i0_profile, "centers_s", []), dtype=float)
        ok = np.isfinite(wl) & np.isfinite(wc)
        wl, wc = wl[ok], wc[ok]
        if wl.size >= 3:
            blocks = np.floor(wc / c.drift_block_s).astype(int)
            nb = int(blocks[-1]) + 1
            B = np.full(nb, np.nan)
            for bk in range(nb):
                sel = wl[blocks == bk]
                if sel.size:
                    B[bk] = float(np.median(sel))
            head = np.flatnonzero(np.isfinite(B))
            if head.size:
                n_anchor = max(1, int(np.ceil(c.drift_anchor_frac * nb)))
                anchor = float(np.median(B[:n_anchor][np.isfinite(B[:n_anchor])])) \
                    if np.isfinite(B[:n_anchor]).any() else float(open_pore)
                scale = max(abs(anchor), 1.0)
                disp_thr = c.drift_min_frac * scale
                step_thr = max(c.drift_step_pA, c.drift_step_frac * scale)
                # record-head spread is the instability reference
                head_n = max(10, int(c.drift_anchor_frac * n))
                hq = np.percentile(current[:head_n], [75, 25]) if head_n > 10 else np.percentile(current, [75, 25])
                base_iqr = max(float(hq[0] - hq[1]), np.finfo(float).eps)
                # trailing run of displaced blocks (irreversible: it reaches the end)
                j = int(head[-1])
                start = j
                while start > 0:
                    if not (np.isfinite(B[start - 1]) and abs(B[start - 1] - anchor) >= disp_thr):
                        break
                    if abs(B[start] - B[start - 1]) > step_thr:   # a step, not a ramp
                        break
                    start -= 1
                if abs(B[j] - anchor) >= disp_thr:
                    in_blk = blocks == start
                    t_a = float(wc[np.flatnonzero(in_blk)[0]]) if in_blk.any() else float(start * c.drift_block_s)
                    dur = j * c.drift_block_s + c.drift_block_s - t_a
                    seg_s, seg_e = int(t_a * sr), min(n, int((j + 1) * c.drift_block_s * sr))
                    seg = current[seg_s:seg_e].astype(float)
                    seg_iqr = float(np.percentile(seg, 75) - np.percentile(seg, 25)) if seg.size > 4 else 0.0
                    if dur >= c.drift_min_s and seg_iqr >= c.drift_iqr_ratio * base_iqr:
                        _add("baseline_drift", seg_s, seg_e,
                             f"{B[start]:.0f}->{B[j]:.0f}pA (anchor {anchor:.0f}) "
                             f"IQRx {seg_iqr / base_iqr:.1f} dur {dur:.0f}s")
                        drift_spans.append((t_a, (j + 1) * c.drift_block_s))
                        # extreme instability at the tail -> also call it a rupture
                        if seg_iqr >= c.drift_rupture_ratio * base_iqr:
                            rw = max(20, int(round(2.0 * sr)))
                            k = seg_e
                            while k - rw > seg_s:
                                w = current[k - rw:k].astype(float)
                                wq = float(np.percentile(w, 75) - np.percentile(w, 25))
                                if wq < c.drift_rupture_ratio * base_iqr:
                                    break
                                k -= rw
                            if (seg_e - k) / sr >= 2.0:
                                _add("membrane_rupture", k, seg_e,
                                     f"IQRx {seg_iqr / base_iqr:.1f} (drift tail)")
                                consumed[max(0, int(k * sr) // jw):] = True
    for t_a, t_b in drift_spans:
        consumed[max(0, int(t_a * sr) // jw):min(nwin, int(np.ceil(t_b * sr / jw)))] = True
    rel_shift = np.divide(np.abs(w_med - w_base),
                          np.maximum(np.abs(w_base), 1.0), out=np.zeros(nwin))
    displaced = rel_shift >= c.blockage_fraction
    # Jitter is high-frequency CONTINUOUS noise: the first-difference sign flips
    # almost every sample (~0.6). A dense cluster of short discrete events also
    # raises the window noise, but its sign runs persist (fraction ~0.2-0.3), so
    # requiring both high noise AND near-random sign alternation keeps event
    # clusters from being mislabelled membrane jitter (e.g. ARNKRS peptide runs).
    oscillating = w_osc >= c.jitter_osc_floor
    for kind, cond in (
        ("membrane_jitter_severe", w_noise >= c.jitter_severe_ratio * reference_noise),
        ("membrane_jitter_mild", (w_noise >= c.jitter_mild_ratio * reference_noise)
         & (w_noise < c.jitter_severe_ratio * reference_noise)),
    ):
        flag = cond & oscillating & ~consumed & ~displaced
        for a, b in _runs(flag):
            _add(kind, win_start[a], win_end[b - 1],
                 f"noise_ratio {max(ratio[a:b]):.1f} osc {max(w_osc[a:b]):.2f}")

    # --- irregular blockage: long smooth deviation from open pore + internal
    #     irregularity. Deviation is checked two ways: against the dynamic I0(t)
    #     (catches departures while the baseline drifts) and anchored to the
    #     record open_pore (catches a slow multi-second plateau the dynamic
    #     profile itself follows). Requiring internal noise keeps a clean stable
    #     pore-state switch (110<->180) from being called a blockage.
    smooth_n = max(1, int(round(0.002 * sr)))
    smooth = uniform_filter1d(current.astype(float), size=smooth_n, mode="nearest")
    min_blk = max(1, int(round(c.blockage_min_ms * sr / 1000)))
    if i0_profile is not None and i0_profile.baseline.size == n:
        dev_base = np.asarray(i0_profile.baseline, dtype=float)
    else:
        dev_base = np.full(n, open_pore, dtype=float)
    dev_thr = c.blockage_fraction * max(abs(open_pore), 1.0)
    seen: list[AnomalyRegion] = []
    for dev in (np.abs(smooth - open_pore), np.abs(smooth - dev_base)):
        for a, b in _runs(dev >= dev_thr):
            if b - a < min_blk:
                continue
            # a stretch already claimed as slow drift / its rupture tail is not
            # a separate blockage
            if any(not (b <= ta * sr or a >= tb * sr) for ta, tb in drift_spans):
                continue
            # internal irregularity gates the blockage decision
            seg = current[a:b].astype(float)
            internal = robust_sigma(np.diff(seg)) / np.sqrt(2.0) if len(seg) > 1 else 0.0
            if internal < c.jitter_mild_ratio * reference_noise:
                continue
            # skip a stretch already claimed as a blockage (two dev checks overlap)
            if any((s < b) and (a < e) for r in seen for s, e in [(r.start_s * sr, r.end_s * sr)]):
                continue
            manual = any(rb >= a and ra <= b for ra, rb in reverse_runs)
            kind = "blockage_manual_recovery" if manual else "blockage_spontaneous"
            r = AnomalyRegion(
                kind, a / sr, b / sr,
                f"dev {float(np.mean(smooth[a:b]) - open_pore):+.0f}pA dur {(b - a) / sr * 1e3:.0f}ms "
                f"noise_ratio {internal / reference_noise:.1f} "
                f"mode={'manual' if manual else 'spontaneous'}")
            seen.append(r)
            regions.append(r)

    regions.sort(key=lambda r: r.start_s)
    # valid: per ~100 ms window that does not fall inside any region (drives
    # FileReport.valid_pct; event removal uses regions directly)
    valid = np.ones(nwin, dtype=bool)
    for r in regions:
        i0 = max(0, int(r.start_s * sr / jw))
        i1 = min(nwin, int(np.ceil(r.end_s * sr / jw)))
        valid[i0:i1] = False
    return AnomalyResult(regions=regions, valid=valid, block_means=w_med,
                         block_s=jw / sr, open_pore=open_pore)


def merge_anomaly_results(*results: AnomalyResult) -> AnomalyResult:
    """Union several :class:`AnomalyResult`s (e.g. the macro envelope detector
    and the refined artifact detector) into one, recomputing ``valid`` on a
    common ~100 ms grid. Events that fall inside ANY contributing region are
    removed by the caller via :func:`events_in_invalid_regions`."""
    regions: list[AnomalyRegion] = []
    for res in results:
        if res is not None:
            regions.extend(res.regions)
    regions.sort(key=lambda r: r.start_s)
    # open pore from the first non-empty result that carries one
    open_pore = float(np.median([r.open_pore for r in results if r is not None and np.isfinite(r.open_pore)])) if results else 0.0
    if not regions:
        block = results[0].block_s if results and results[0] is not None else 0.1
        return AnomalyResult([], np.ones(1, dtype=bool), np.asarray([], dtype=float),
                             block, open_pore)
    # canonical grid: ~100 ms resolution anchored at t=0
    grid_s = min((res.block_s for res in results if res is not None), default=0.1)
    end_s = max(r.end_s for r in regions)
    nwin = max(1, int(np.ceil(end_s / grid_s)))
    valid = np.ones(nwin, dtype=bool)
    for r in regions:
        if r.kind == "baseline_step":
            continue  # hint only: a pore-state boundary stays valid data
        i0 = max(0, int(r.start_s / grid_s))
        i1 = min(nwin, int(np.ceil(r.end_s / grid_s)))
        valid[i0:i1] = False
    return AnomalyResult(regions=regions, valid=valid,
                         block_means=np.asarray([], dtype=float),
                         block_s=grid_s, open_pore=open_pore)
