"""Voltage-channel recovery tests.

The six lab samples in ``abf数据案例/abf数据案例/`` are 2-channel recordings
(IN 0 = pA current, IN 1 = mV command/holding voltage). read_abf must keep its
existing single-channel (current) contract while exposing the voltage trace so
the anomaly stage can distinguish manual (reverse-voltage) recovery from
spontaneous blockage recovery.
"""
from pathlib import Path

import numpy as np

CASE = Path("abf数据案例/abf数据案例")


def _have_cases() -> bool:
    return (CASE / "Ala.abf").exists()


def test_two_channel_samples_expose_voltage():
    if not _have_cases():
        import pytest

        pytest.skip("lab sample data not present")
    from nanopore.io import read_abf

    for name in ("Ala.abf", "Asp.abf", "Gln.abf", "His.abf",
                 "ac-Thr+Thr mixture.abf", "pore2 ARNKRS 2Mm_0000.abf"):
        rec = read_abf(CASE / name)
        assert rec.current_channel == 0
        assert rec.units == "pA", f"{name}: expected pA, got {rec.units!r}"
        assert rec.n_channels == 2, f"{name}: expected 2 channels"
        assert rec.voltage is not None, f"{name}: voltage trace missing"
        assert rec.voltage_channel == 1
        assert len(rec.voltage) == len(rec.current), f"{name}: voltage/current length mismatch"
        assert np.isfinite(rec.voltage).all()
        assert rec.data is not None and rec.data.shape[1] == 2
        # current and voltage are distinct physical traces
        assert not np.array_equal(rec.current, rec.voltage)


def test_reverse_voltage_segment_detectable_in_ala():
    """Ala has an operator-applied reverse-voltage segment (说明.txt): the voltage
    channel must swing negative somewhere so the anomaly stage can find it."""
    if not _have_cases():
        import pytest

        pytest.skip("lab sample data not present")
    from nanopore.io import read_abf

    rec = read_abf(CASE / "Ala.abf")
    assert rec.voltage.min() < -50.0, "expected a reverse-voltage segment in Ala"
    # the whole trace is 527 s at 25 kHz; the negative segment is multi-second
    neg = np.flatnonzero(rec.voltage < -50.0)
    assert neg.size > 0
    # segment duration in seconds via run-length of the sign change
    runs = np.split(neg, np.flatnonzero(np.diff(neg) > 1) + 1)
    assert max(len(r) for r in runs) / rec.sample_rate_hz > 1.0


def test_constant_voltage_sample_has_no_reverse_segment():
    """Gln/ARNKRS hold +100 mV the whole recording (no manual reversal)."""
    if not _have_cases():
        import pytest

        pytest.skip("lab sample data not present")
    from nanopore.io import read_abf

    rec = read_abf(CASE / "Gln.abf")
    # held at ~+100 mV with small ADC noise; never reverses below ~0
    assert abs(float(np.median(rec.voltage)) - 100.0) < 1.0
    assert rec.voltage.min() > 0.0
