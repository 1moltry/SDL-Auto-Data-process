"""Voltage-protocol segments in files without a voltage ADC channel.

tPAL-style ABF files record only the current channel, but the ABF header still
carries the commanded protocol waveform (pyabf ``sweepC``). These tests cover
reading it and using it to block event detection in non-sensing segments.
"""
from pathlib import Path

import numpy as np
import pytest

TPAL = Path("abf数据案例/abf数据案例2/abf数据案例2/tPAL")
CASE = Path("abf数据案例/abf数据案例")


def _have_tpal() -> bool:
    return (TPAL / "TREFETSC.abf").exists()


def test_command_waveform_read_from_header():
    """Even with a single current channel, the commanded protocol is available."""
    if not _have_tpal():
        pytest.skip("tPAL sample data not present")
    from nanopore.io import read_abf

    rec = read_abf(TPAL / "TREFETSC.abf")
    assert rec.voltage is None, "this file must have no voltage ADC channel"
    assert rec.protocol_voltage is not None
    v = rec.command_voltage
    assert v is not None
    assert len(v) == len(rec.current), "command waveform must match the trace length"
    # +100 mV sensing hold with a -100 mV wash epoch each sweep
    levels = np.unique(np.round(v, 1))
    assert set(levels) <= {-100.0, 0.0, 100.0}, levels
    assert -100.0 in levels and 100.0 in levels


def test_command_waveform_none_for_constant_protocol():
    """A constant-hold file has no protocol steps to report."""
    if not (CASE / "Gln.abf").exists():
        pytest.skip("lab sample data not present")
    from nanopore.io import read_abf

    rec = read_abf(CASE / "Gln.abf")
    # Gln holds +100 mV throughout: the command waveform is flat
    assert rec.command_voltage is None or np.unique(np.round(rec.command_voltage, 1)).size == 1


def test_tpal_wash_segments_excluded_from_events():
    """The wash/rest part of each sweep must not appear as events, and no kept
    event may overlap a protocol segment."""
    if not _have_tpal():
        pytest.skip("tPAL sample data not present")
    import pandas as pd

    from nanopore.anomaly import detect_artifact_segments
    from nanopore.baseline import estimate_levels
    from nanopore.detect import detect_events
    from nanopore.features import classify_exclusions, compute_features
    from nanopore.io import read_abf

    rec = read_abf(TPAL / "TREFETSC.abf")
    sr = rec.sample_rate_hz
    lv = estimate_levels(rec.current)
    det = detect_events(rec.current, sr, lv.level0, lv.level1, polarity=lv.polarity)
    assert len(det.events) > 0

    res = detect_artifact_segments(rec.current, sr, voltage=rec.protocol_voltage,
                                   open_pore=lv.level0, event_levels=lv.levels)
    rv = [r for r in res.regions if r.kind == "reverse_voltage"]
    assert len(rv) >= 20, f"expected one region per sweep's non-sensing part, got {len(rv)}"

    df = compute_features(det, rec.current, sr, label="tPAL")
    kept, excluded = classify_exclusions(df, res.regions, min_toff_ms=None)
    assert excluded is not None and len(excluded) > 0
    assert all("reverse_voltage" in r for r in
               excluded.loc[excluded["drop_reason"].str.contains("reverse_voltage"),
                            "drop_reason"])
    # no kept event may overlap a protocol segment
    for r in rv:
        overlap = ((kept["t1"] < r.end_s) & (kept["t2"] > r.start_s))
        assert not overlap.any(), f"event kept inside protocol segment {r.start_s:.1f}-{r.end_s:.1f}s"
    # the spurious multi-second wash events are gone
    assert not (kept["toff"] > 1500).any()
