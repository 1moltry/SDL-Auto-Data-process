"""Tests for preprocessing filters."""

import numpy as np

from tests.synth import make_signal


def test_lowpass_none_is_identity():
    from nanopore.preprocess import lowpass

    sig = make_signal([], duration_s=1.0, sample_rate_hz=10_000)
    out = lowpass(sig.current, sig.sample_rate_hz, None)
    assert out is sig.current


def test_lowpass_attenuates_high_frequency_hum():
    from nanopore.preprocess import lowpass

    sr = 25_000.0
    t = np.arange(int(sr)) / sr
    clean = np.full(len(t), 100.0)
    hum = 20.0 * np.sin(2 * np.pi * 2000.0 * t)  # 2 kHz hum
    noisy = clean + hum
    out = lowpass(noisy, sr, 500.0)
    residual = out[1000:-1000] - 100.0
    # after filtering, 2kHz component should be strongly attenuated
    assert np.std(residual) < 2.0


def test_lowpass_preserves_dc_level():
    from nanopore.preprocess import lowpass

    sr = 25_000.0
    rng = np.random.default_rng(1)
    noisy = 100.0 + rng.normal(0, 2.0, int(sr))
    out = lowpass(noisy, sr, 500.0)
    assert abs(np.mean(out) - 100.0) < 0.5
