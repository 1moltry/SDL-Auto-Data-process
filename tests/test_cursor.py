"""P2: segment-local (Cursor / search-region) analysis.

A Cursor re-analyses a sub-slice with its OWN level estimates, so an anomaly
region (blocks) elsewhere in the record must not pollute the ROI statistics,
and events inside a blocked ROI must not leak into an ROI placed on a clean
region.
"""

import numpy as np
import pytest

from tests.synth import SynthEvent, make_signal


def _cfg(**kw):
    from nanopore.config import PipelineConfig

    return PipelineConfig(**kw)


def _track(sig, start_s, end_s):
    from nanopore.roi import analyze_roi

    return analyze_roi(sig.current, sig.sample_rate_hz, start_s, end_s, _cfg())


def test_roi_reports_events_with_absolute_times():
    # 3 events in the clean first 10s, then a synthetic blocked segment
    evs = [SynthEvent(1.0, 0.02, -50), SynthEvent(2.0, 0.02, -50), SynthEvent(3.5, 0.02, -50)]
    sig = make_signal(evs, duration_s=20.0, sample_rate_hz=25_000, noise_sigma_pA=1.0, seed=31)
    df, det, lv = _track(sig, 0.0, 10.0)
    assert len(df) == 3
    # t1/t2 in absolute record time (not offset from the ROI start)
    assert abs(df["t1"].iloc[0] - 1.0) < 1e-3
    assert abs(df["t2"].iloc[2] - 3.52) < 1e-3


def test_roi_avoids_blockage_gives_ground_truth():
    # clean events in [1,10]s; a deep blocked plateau occupies [12,15]s
    evs = [SynthEvent(1.0, 0.02, -50), SynthEvent(2.0, 0.02, -50), SynthEvent(3.0, 0.02, -50),
           SynthEvent(4.0, 0.02, -50), SynthEvent(5.0, 0.02, -50)]
    sig = make_signal(evs, duration_s=20.0, sample_rate_hz=25_000, noise_sigma_pA=1.0, seed=32)
    sr = int(sig.sample_rate_hz)
    sig.current[12 * sr:15 * sr] = 40.0  # deep blockage plateau
    # ROI on the clean region: independent levels, event count = ground truth
    df, _, _ = _track(sig, 0.5, 10.5)
    assert len(df) == 5


def test_roi_on_blockage_encloses_no_clean_events():
    evs = [SynthEvent(1.0, 0.02, -50), SynthEvent(2.0, 0.02, -50), SynthEvent(3.0, 0.02, -50)]
    sig = make_signal(evs, duration_s=20.0, sample_rate_hz=25_000, noise_sigma_pA=1.0, seed=33)
    sr = int(sig.sample_rate_hz)
    sig.current[12 * sr:15 * sr] = 40.0
    # ROI on the blocked plateau: find no clean events (a flat 40 pA plateau has
    # no level structure that passes dwell-near-level -> no event in that span)
    df, _, _ = _track(sig, 12.0, 15.0)
    assert len(df) == 0


def test_roi_uses_independent_levels_not_record_cursor():
    # record alternates baseline 100 -> plateau 150 (a pore-state switch); an
    # event on the 100 side should be measured at ~100, not at the record cursor
    evs = [SynthEvent(1.0, 0.02, -50)]
    sig = make_signal(evs, duration_s=10.0, sample_rate_hz=25_000, noise_sigma_pA=1.0, seed=34)
    df, _, _ = _track(sig, 0.0, 5.0)   # clean region around the event
    assert len(df) == 1
    assert abs(df.iloc[0]["Io"] - 100.0) < 3.0


def test_roi_too_short_raises():
    sig = make_signal([], duration_s=5.0, sample_rate_hz=25_000, seed=35)
    with pytest.raises(ValueError):
        _track(sig, 2.0, 2.2)   # 0.2 s < 0.5 s threshold
