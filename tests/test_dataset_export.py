"""Training-export (dataset_all.csv) and scatter-axis regression tests.

The combined export is the MATLAB/ML-facing table: column names must be legal
MATLAB identifiers (``%mean`` is not) and a leading ``source_file`` must tie each
row back to its recording.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from nanopore.analysis import (
    _full_range, _padded, _spans_decades,
    build_combined_dataset, build_scatter_figure, plot_scatter,
    write_combined_dataset,
)

MATLAB_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

# the per-file events table, incl. the names that are not MATLAB-legal
EVENT_COLS = ["mean", "%mean", "std", "skew", "kurt", "toff", "ton", "Label",
              "I0", "t1", "t2", "Io", "MAD", "CV", "q1", "q2", "q3", "iqr",
              "outlier_ratio", "state"]


def _frame(n: int = 3) -> pd.DataFrame:
    return pd.DataFrame({c: np.arange(n, dtype=float) + 1.0 for c in EVENT_COLS}) \
        .assign(Label="Ala", state="A")


def test_renames_only_the_non_matlab_legal_columns():
    out = build_combined_dataset([("Ala.abf", _frame())])
    assert "rel_mean" in out.columns and "%mean" not in out.columns
    assert "t1_s" in out.columns and "t2_s" in out.columns
    assert "toff" in out.columns          # feature name kept for the ML spec
    assert out.columns[0] == "source_file"


def test_every_exported_column_is_a_legal_matlab_identifier():
    out = build_combined_dataset([("Ala.abf", _frame())])
    bad = [c for c in out.columns if not MATLAB_IDENT.match(c)]
    assert bad == []


def test_concatenates_files_and_tags_each_row():
    out = build_combined_dataset([("Ala.abf", _frame(2)), ("Asp.abf", _frame(3))])
    assert len(out) == 5
    assert list(out["source_file"]) == ["Ala.abf"] * 2 + ["Asp.abf"] * 3


def test_skips_empty_and_missing_frames():
    out = build_combined_dataset([("a.abf", _frame(0)), ("b.abf", None),
                                  ("c.abf", _frame(4))])
    assert len(out) == 4
    assert set(out["source_file"]) == {"c.abf"}


def test_empty_input_yields_empty_frame_with_header():
    out = build_combined_dataset([])
    assert len(out) == 0 and "source_file" in out.columns


def test_write_roundtrip_preserves_columns(tmp_path):
    out = build_combined_dataset([("Ala.abf", _frame())])
    p = tmp_path / "dataset_all.csv"
    write_combined_dataset(out, p)
    back = pd.read_csv(p, encoding="utf-8-sig")
    assert list(back.columns) == list(out.columns)
    assert len(back) == len(out)


# ---- scatter axis helpers ----

def test_full_range_keeps_every_event():
    # real levels can sit far apart (enkephalin has a -103 pA cluster 4% wide);
    # the axis must span them all, so no tail is trimmed
    v = np.array([-103.6, 60.6, 62.8, 64.5, 67.2, 96.7])
    assert _full_range(v) == (-103.6, 96.7)


def test_full_range_ignores_non_finite():
    assert _full_range([1.0, np.nan, 3.0, np.inf]) == (1.0, 3.0)


def test_full_range_empty_is_none():
    assert _full_range([]) is None


def test_spans_decades_detects_dwell_span():
    assert _spans_decades([15.0, 26_000.0])       # 3 decades -> log axis
    assert not _spans_decades([110.0, 112.0])     # narrow -> linear axis
    assert not _spans_decades([0.0, 5.0])         # non-positive -> not log


def test_padded_log_margin_is_multiplicative():
    lo, hi = _padded((10.0, 1000.0), log=True)
    assert lo > 0 and lo < 10 and hi > 1000


def test_scatter_keeps_linear_delta_i_and_every_level():
    # signed ΔI with two far-apart real levels (enkephalin-like): the y axis
    # must stay linear and span both, never log/symlog-compress them
    df = _frame(40)
    df["mean"] = np.r_[np.full(20, -103.0), np.full(20, 63.0)]
    df["toff"] = np.r_[np.full(20, 15.0), np.full(20, 26_000.0)]
    fig = build_scatter_figure(df, label="t")
    try:
        ax = fig.axes[0]                       # upper-left: dwell vs ΔI
        assert ax.get_yscale() == "linear"
        assert ax.get_xscale() == "log"        # dwell spans >1 decade
        lo, hi = ax.get_ylim()
        assert lo <= -103.0 and hi >= 63.0     # neither level clipped away
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_scatter_splits_points_by_sign():
    df = _frame(40)
    df["mean"] = np.r_[np.full(20, -103.0), np.full(20, 63.0)]
    fig = build_scatter_figure(df, label="t")
    try:
        ax = fig.axes[0]
        assert len(ax.collections) == 2        # one scatter per sign
        labels = [t.get_text() for t in ax.get_legend().get_texts()]
        assert labels == ["ΔI < 0", "ΔI ≥ 0"]
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_plot_scatter_writes_png_for_signed_data(tmp_path):
    df = _frame(40)
    df["toff"] = np.linspace(10.0, 26_000.0, 40)
    df["mean"] = np.linspace(-103.0, 96.0, 40)
    p = tmp_path / "scatter.png"
    plot_scatter(df, p, label="t")
    assert p.exists() and p.stat().st_size > 0
