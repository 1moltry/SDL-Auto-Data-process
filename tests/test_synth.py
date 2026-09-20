"""Sanity tests for the synthetic signal generator."""


def test_make_signal_shape_and_baseline():
    import numpy as np

    from tests.synth import SynthEvent, make_signal

    sig = make_signal([SynthEvent(1.0, 0.01, -50)], duration_s=2.0, sample_rate_hz=10_000, noise_sigma_pA=0.0)
    assert len(sig.current) == 20_000
    assert abs(np.median(sig.current) - 100.0) < 1e-9
    # event region shifted by -50
    i0, i1 = 10_000, 10_100
    assert abs(np.median(sig.current[i0:i1]) - 50.0) < 1e-9


def test_make_sweepy_pulses_count():
    from tests.synth import make_sweepy_square_pulses

    sig = make_sweepy_square_pulses(n_events=10, duration_s=20.0)
    assert 5 <= len(sig.events) <= 10
