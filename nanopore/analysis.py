"""Per-file outputs (xlsx + PNGs) and batch summary report.

Per input file:
- <name>_events.xlsx : feature table (spec column names) + anomaly regions sheet
  + (when events were excluded) an ``excluded`` sheet listing dropped events with
  their ``drop_reason`` so removals are traceable
- <name>_overview.png: full-trace block means with event markers and anomaly shading
- <name>_scatter.png : 2x2 scatters (dwell/time vs depth, dwell/time vs Io);
  depth is split by sign (blockades go either way) on a linear axis
- <name>_hist.png    : depth and dwell histograms

Batch:
- summary.xlsx   : one row per file (event counts, validity, anomaly log)
- dataset_all.csv: every file's kept events concatenated into one ML-facing table
                   with MATLAB-legal column names (see build_combined_dataset)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def write_events_xlsx(df: pd.DataFrame, anomalies: list, path: Path,
                      excluded: pd.DataFrame | None = None) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="events", index=False)
        if excluded is not None and len(excluded):
            excluded.to_excel(xw, sheet_name="excluded", index=False)
        if anomalies:
            adf = pd.DataFrame(
                [{"kind": r.kind, "start_s": r.start_s, "end_s": r.end_s, "detail": r.detail}
                 for r in anomalies]
            )
            adf.to_excel(xw, sheet_name="anomalies", index=False)


def plot_overview(
    current: np.ndarray,
    sample_rate_hz: float,
    events_start_s: np.ndarray,
    events_end_s: np.ndarray,
    anomaly_result,
    levels,
    path: Path,
    label: str = "",
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sr = sample_rate_hz
    n = len(current)
    # 2 ms display blocks, capped so very long records stay printable
    nblk = max(int(sr * 0.002), int(n / 300_000))
    nb = n // nblk
    if nb < 2:
        nb, nblk = n, 1
    tm = np.arange(nb) * (nblk / sr)
    seg = current[: nb * nblk].reshape(nb, nblk).astype(float)
    disp = seg.mean(axis=1)
    lo = seg.min(axis=1)
    hi = seg.max(axis=1)

    fig, ax = plt.subplots(figsize=(16, 5), facecolor="white")
    ax.set_facecolor("white")

    # anomaly shading (back layer) — hard anomalies only; baseline_step and the
    # pore-state boundaries stay table-only (matches the GUI)
    _colors = {
        "breakdown": "red", "blockage": "orange", "jitter": "purple",
        "reverse_voltage": "dodgerblue", "membrane_rupture": "red",
        "membrane_jitter_mild": "violet", "membrane_jitter_severe": "purple",
        "blockage_spontaneous": "darkorange", "blockage_manual_recovery": "dodgerblue",
        "baseline_drift": "peru",
    }
    for r in anomaly_result.regions:
        color = _colors.get(r.kind)
        if color is None:
            continue
        ax.axvspan(r.start_s, r.end_s, color=color, alpha=0.18, zorder=0)

    # full-signal block-mean line: baseline and its jitter stay visible
    ax.plot(tm, disp, lw=0.3, color="0.20", zorder=2)

    # idealized event trace (blue square pulses) over the full signal
    if len(events_start_s):
        order = np.argsort(np.asarray(events_start_s))
        xs = [0.0]
        ys = [float(levels.level0)]
        for s, e in zip(np.asarray(events_start_s)[order], np.asarray(events_end_s)[order]):
            amp = float(current[int(s * sr):int(e * sr)].mean())
            xs += [float(s), float(s), float(e), float(e)]
            ys += [float(levels.level0), amp, amp, float(levels.level0)]
        xs += [float(tm[-1])]
        ys += [float(levels.level0)]
        ax.plot(xs, ys, color="#1f77b4", lw=1.1, zorder=4)

    # robust y-range: show baseline + noise band + events, not rare giant spikes
    vlo = float(np.percentile(lo, 0.5))
    vhi = float(np.percentile(hi, 99.5))
    vlo = min(vlo, float(levels.level0))
    vhi = max(vhi, float(levels.level0))
    pad = 0.04 * (vhi - vlo) or 1.0
    ax.set_ylim(vlo - pad, vhi + pad)
    ax.set_xlim(0, tm[-1])
    ax.set_xlabel("time (s)")
    ax.set_ylabel("current (pA)")
    ax.set_title(f"overview: {label}")

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _padded(lim, log: bool = False):
    """Add a small margin so points do not sit on the frame."""
    if lim is None:
        return None
    lo, hi = lim
    if hi <= lo:
        return None
    if log:
        if lo <= 0:
            return None
        f = (hi / lo) ** 0.04
        return lo / f, hi * f
    pad = 0.04 * (hi - lo)
    return lo - pad, hi + pad


def _spans_decades(values) -> bool:
    """True when positive values cover more than one decade (worth a log axis)."""
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v) & (v > 0)]
    return v.size >= 2 and float(v.max()) / float(v.min()) > 10.0


# ΔI (depth) is signed: a blockade can push the current either way relative to
# the open pore, and the two populations often sit far apart. Colouring by sign
# keeps that structure readable even when each level is a tight cluster.
_NEG_COLOR = "#1f77b4"
_POS_COLOR = "#d62728"


def _full_range(values):
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return None
    return float(v.min()), float(v.max())


def build_scatter_figure(df: pd.DataFrame, label: str = ""):
    """Build the 2x2 sign-split scatter figure (``None`` for an empty table).

    Split out from :func:`plot_scatter` so the axis choices are testable.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if len(df) == 0:
        return None
    toff = df["toff"].to_numpy(dtype=float)
    depth = df["mean"].to_numpy(dtype=float)
    io = df["Io"].to_numpy(dtype=float)
    t1 = df["t1"].to_numpy(dtype=float)

    down = depth < 0
    up = ~down

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))

    def split_panel(ax, x, xlabel):
        ax.scatter(x[down], depth[down], s=6, alpha=0.5, color=_NEG_COLOR,
                   label="ΔI < 0")
        ax.scatter(x[up], depth[up], s=6, alpha=0.5, color=_POS_COLOR,
                   label="ΔI ≥ 0")
        ax.set_xlabel(xlabel)
        ax.set_ylabel("depth / ΔI (pA)")
        ax.legend(loc="best", fontsize=8)

    # depth over dwell (the classic scatter) and over time
    split_panel(axes[0][0], toff, "toff (ms)")
    split_panel(axes[1][0], t1, "t1 (s)")
    # open-pore current, whose drift is the thing to watch over time
    for ax, x, xlabel in ((axes[0][1], toff, "toff (ms)"),
                          (axes[1][1], t1, "t1 (s)")):
        ax.scatter(x, io, s=6, alpha=0.5, color="0.45")
        ax.set_xlabel(xlabel)
        ax.set_ylabel("Io (pA)")

    # dwell spans decades -> log x. ΔI keeps a *linear* y: it is signed and its
    # levels can sit far apart, so symlog/log would squash the populations into
    # a sliver (measured: 4-6% of the axis vs 9-30% with a linear axis).
    panels = [(axes[0][0], toff, depth, True), (axes[0][1], toff, io, True),
              (axes[1][0], t1, depth, False), (axes[1][1], t1, io, False)]
    for ax, xv, yv, want_logx in panels:
        logx = want_logx and _spans_decades(xv)
        if logx:
            ax.set_xscale("log")
        lim = _padded(_full_range(xv), log=logx)
        if lim:
            ax.set_xlim(*lim)
        lim = _padded(_full_range(yv))
        if lim:
            ax.set_ylim(*lim)

    fig.suptitle(f"scatter: {label}")
    fig.tight_layout()
    return fig


def plot_scatter(df: pd.DataFrame, path: Path, label: str = "") -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = build_scatter_figure(df, label)
    if fig is None:
        return
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_hist(df: pd.DataFrame, path: Path, label: str = "") -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if len(df) == 0:
        return
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    axes[0].hist(df["mean"], bins=60, color="tab:blue", alpha=0.8)
    axes[0].set_xlabel("depth (pA)")
    axes[0].set_ylabel("count")
    axes[1].hist(np.log10(df["toff"].clip(lower=0.01)), bins=60, color="tab:red", alpha=0.8)
    axes[1].set_xlabel("log10 toff (ms)")
    axes[1].set_ylabel("count")
    fig.suptitle(f"histograms: {label}")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# MATLAB-legal column names for the training export. The per-file *_events.xlsx
# keeps the spec column names verbatim; this table is the ML-facing one, so it
# renames only what MATLAB cannot ingest or would silently misread:
#   %mean -> rel_mean : "%" is not a valid MATLAB identifier (readtable would
#                       silently rename it to x_mean and name-based access breaks)
#   t1/t2 -> t1_s/t2_s: seconds here, whereas the lab feature table writes ms
_MATLAB_ALIASES = {"%mean": "rel_mean", "t1": "t1_s", "t2": "t2_s"}


def build_combined_dataset(pairs) -> pd.DataFrame:
    """Concatenate per-file event tables into one ML-facing table.

    ``pairs`` yields ``(source_name, df)``; ``df`` is a recording's kept-event
    table. Returns a single frame with a leading ``source_file`` column and
    MATLAB-legal column names (see ``_MATLAB_ALIASES``). Empty input yields an
    empty frame.
    """
    frames = []
    for name, df in pairs:
        if df is None or len(df) == 0:
            continue
        d = df.rename(columns=_MATLAB_ALIASES).copy()
        d.insert(0, "source_file", name)
        frames.append(d)
    if not frames:
        return pd.DataFrame(columns=["source_file"])
    return pd.concat(frames, ignore_index=True)


def write_combined_dataset(df: pd.DataFrame, path: Path) -> None:
    # utf-8-sig: Excel needs the BOM to read non-ASCII labels; MATLAB readtable
    # auto-detects it.
    df.to_csv(path, index=False, encoding="utf-8-sig")


def write_summary(rows: list[dict], path: Path) -> None:
    df = pd.DataFrame(rows)
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="summary", index=False)
