"""Per-event feature extraction, producing the lab feature-table columns.

Column names and definitions follow the lab feature-table specification:

    mean, %mean, std, skew, kurt, toff, Label, I0, t1, t2, MAD, CV,
    q1, q2, q3, iqr, outlier_ratio  (+ ton added here)

Column semantics:
- I0 (open-pore reference column) is record-scope: the open-pore current at the
  start of the record, taken from the window just before the first event (and
  falling back to the fitted level0 when a record has no events).
- Io (per-event open-pore reference) follows the dynamic baseline when an
  ``I0Profile`` from :mod:`nanopore.baseline_i0` is supplied — it is the median
  of the profile baseline over the event window, immune to a preceding long
  blockage being mistaken for the open pore. Without a profile, Io falls back
  to the max of the pre/post window means, with the detector's drift-following
  ``level0_ref`` clamping the ``|Io - I0| > 5 pA`` continuity rule.
- Blockade current aa = raw event samples - Io, with the event body taken after
  trimming the pre/after transition margins off both ends.
- 3-sigma despike: outlier_ratio = fraction of aa beyond mean(aa) +/- 3*std(aa),
  then outliers are removed before computing the remaining statistics.
- toff = event duration; ton = gap to the next event's start.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .detect import DetectionResult


def classify_exclusions(
    df: pd.DataFrame,
    regions: list,
    min_toff_ms: float | None,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Annotate ``drop_reason`` on a full feature table and split kept/excluded.

    Returns ``(df_kept, df_excluded)``. ``df_kept`` drops the ``drop_reason``
    column (the per-file feature table); ``df_excluded`` keeps it so the drop
    is traceable. A row is excluded when it overlaps an anomaly region (any
    kind except ``baseline_step``) or, when ``min_toff_ms`` is given, when its
    ``toff`` is below it. Empty input returns ``(df, None)``.
    """
    if len(df) == 0:
        return df, None
    from .anomaly import invalid_region_reasons

    reasons = invalid_region_reasons(
        df["t1"].to_numpy(), df["t2"].to_numpy(), regions or []
    )
    reasons = np.asarray(reasons, dtype=object)
    if min_toff_ms is not None:
        short = df["toff"].to_numpy() <= min_toff_ms
        reasons = np.where(
            short,
            np.where(reasons == "", "toff<min", reasons + ",toff<min"),
            reasons,
        )
    df["drop_reason"] = reasons
    keep = df["drop_reason"] == ""
    df_excluded = df[~keep].reset_index(drop=True)
    df_kept = df[keep].reset_index(drop=True).drop(columns=["drop_reason"])
    return df_kept, df_excluded


def compute_features(
    result: DetectionResult,
    current: np.ndarray,
    sample_rate_hz: float,
    label: str = "",
    pre_event_ms: float = 25.0,
    after_event_ms: float = 0.8,
    dr_pA: float = 5.0,
    min_toff_ms: float | None = None,
    i0_profile=None,
) -> pd.DataFrame:
    """Build the per-event feature table for one recording.

    result: detection output whose events index into `current`.

    ``i0_profile`` (optional ``I0Profile`` from nanopore.baseline_i0) supplies
    a per-sample open-pore baseline. When given, ``Io`` is the dynamic
    open-pore current at the event (median of the baseline over the event
    window), which is immune to a preceding long blockage being mistaken for
    the open pore. When omitted, the pre/post window fallback (max of the two
    window means, clamped by ``dr_pA``) is used to preserve callers that do not
    build the profile.
    """
    sr = sample_rate_hz
    dt = 1.0 / sr
    pre_n = int(round(pre_event_ms * 1e-3 * sr))
    body_pre = int(round((pre_event_ms + after_event_ms) * 1e-3 * sr))

    n = len(current)
    events = result.events
    rows = []

    # I0: open-pore current at record start, read from the window just before
    # the first event; a record with no events falls back to the fitted level0
    if events:
        i0_lo = max(0, int(events[0].start_s * sr) - pre_n)
        i0_hi = max(i0_lo + 1, int(events[0].start_s * sr))
        I0 = float(np.mean(current[i0_lo:i0_hi]))
    else:
        I0 = float(result.level0_final)

    prev_Io = I0
    for k, ev in enumerate(events):
        s = int(round(ev.start_s * sr))
        e = int(round(ev.end_s * sr))

        if i0_profile is not None:
            # per-event open-pore reference from the dynamic baseline, which is
            # built only from quiet open-pore windows (immune to a preceding
            # long blockage drifting the reference down to the blocked level)
            seg_base = i0_profile.baseline[s:e]
            Io = float(np.median(seg_base)) if seg_base.size else float(I0)
            if not (np.isfinite(Io) and Io != 0):
                Io = float(I0)
        else:
            # Io: max(pre-window mean, post-window mean), clamped to the
            # previous value when it deviates from the drift-following reference
            # (detector level0_ref) by more than dr_pA. Clamping against the
            # local reference instead of the record-start I0 preserves the
            # intent (reject a corrupted pre/post window) while letting Io
            # follow slow open-pore drift.
            pre_lo, pre_hi = max(0, s - pre_n), s
            post_lo, post_hi = e, min(n, e + pre_n)
            means = []
            if pre_hi > pre_lo:
                means.append(float(np.mean(current[pre_lo:pre_hi])))
            if post_hi > post_lo:
                means.append(float(np.mean(current[post_lo:post_hi])))
            Io_raw = max(means) if means else ev.level0_ref_pA
            ref = float(ev.level0_ref_pA) if np.isfinite(ev.level0_ref_pA) else I0
            Io = Io_raw if abs(Io_raw - ref) <= dr_pA else prev_Io
        prev_Io = Io

        # blockade body after trimming transition margins
        b_lo = s + body_pre
        b_hi = e - body_pre
        if b_hi - b_lo < 5:
            b_lo, b_hi = s, max(s + 1, e)
        aa = current[b_lo:b_hi] - Io

        a = float(np.mean(aa))
        c = float(np.std(aa))
        outliers = (aa > a + 3 * c) | (aa < a - 3 * c)
        outlier_ratio = float(np.count_nonzero(outliers) / len(aa))
        bb = aa[~outliers]

        mean_v = float(np.mean(bb))
        rows.append(
            {
                "mean": mean_v,
                "%mean": mean_v / Io if Io != 0 else np.nan,
                "std": float(np.std(bb)),
                "skew": float(pd.Series(bb).skew()) if len(bb) >= 3 else 0.0,
                "kurt": float(pd.Series(bb).kurt()) if len(bb) >= 4 else 0.0,
                "toff": ev.dwell_s * 1e3,           # ms
                "ton": np.nan,                       # filled below
                "Label": label,
                "I0": I0,
                "t1": ev.start_s,                    # s
                "t2": ev.end_s,
                "Io": Io,
                "MAD": float(np.median(np.abs(np.median(bb) - bb))),
                "CV": float(np.std(bb)) / mean_v if mean_v != 0 else np.nan,
                "q1": float(np.percentile(bb, 25)),
                "q2": float(np.median(bb)),
                "q3": float(np.percentile(bb, 75)),
                "iqr": float(np.percentile(bb, 75) - np.percentile(bb, 25)),
                "outlier_ratio": outlier_ratio,
                "state": ev.state,
            }
        )

    df = pd.DataFrame(rows)
    if len(df):
        # ton = time from this event's end to the next event's start; the last
        # event has no successor -> NaN
        starts = df["t1"].to_numpy()
        ends = df["t2"].to_numpy()
        ton = np.full(len(df), np.nan)
        ton[:-1] = starts[1:] - ends[:-1]
        df["ton"] = ton * 1e3  # ms

        # Export filter (keep toff > min_toff_ms). Moved to the caller
        # as an exclusion reason; here we only filter when explicitly asked,
        # so callers that annotate drop reasons get the full table first.
        if min_toff_ms is not None:
            keep = df["toff"] > min_toff_ms
            df = df[keep].reset_index(drop=True)
    return df
