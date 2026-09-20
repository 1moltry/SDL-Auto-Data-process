"""Feature math validation against analytic ground truth on synthetic signals."""

import numpy as np

from tests.synth import SynthEvent, make_signal


def _feat(sig, **kw):
    from nanopore.baseline import estimate_levels
    from nanopore.detect import detect_events
    from nanopore.features import compute_features

    lv = estimate_levels(sig.current)
    res = detect_events(sig.current, sig.sample_rate_hz, lv.level0, lv.level1, polarity=lv.polarity, **kw)
    return compute_features(res, sig.current, sig.sample_rate_hz, label="T")


def test_feature_values_square_pulse():
    # single -50 pA, 20 ms blockade on 100 pA baseline
    sig = make_signal([SynthEvent(1.0, 0.02, -50)], duration_s=3.0,
                      sample_rate_hz=25_000, noise_sigma_pA=1.0, seed=21)
    df = _feat(sig)
    assert len(df) == 1
    row = df.iloc[0]
    assert abs(row["mean"] + 50.0) < 1.5          # blockade depth
    assert abs(row["%mean"] + 0.5) < 0.02          # mean/Io
    assert abs(row["toff"] - 20.0) < 0.5           # ms
    assert abs(row["t1"] - 1.0) < 1e-3
    assert abs(row["t2"] - 1.02) < 1e-3
    assert row["std"] < 2.0
    assert abs(row["I0"] - 100.0) < 2.0
    assert abs(row["Io"] - 100.0) < 2.0
    assert row["Label"] == "T"
    assert np.isnan(row["ton"])                    # single event -> no ton


def test_ton_computation():
    evs = [SynthEvent(1.0, 0.02, -50), SynthEvent(2.0, 0.02, -50), SynthEvent(3.5, 0.02, -50)]
    sig = make_signal(evs, duration_s=5.0, sample_rate_hz=25_000, noise_sigma_pA=1.0, seed=23)
    df = _feat(sig)
    assert len(df) == 3
    ton = df["ton"].to_numpy()
    assert abs(ton[0] - (2.0 - 1.02) * 1e3) < 1.0
    assert abs(ton[1] - (3.5 - 2.02) * 1e3) < 1.0
    assert np.isnan(ton[2])


def test_despike_and_outlier_ratio():
    # event with injected spike outlier inside the body
    sig = make_signal([SynthEvent(1.0, 0.05, -50)], duration_s=3.0,
                      sample_rate_hz=25_000, noise_sigma_pA=1.0, seed=25)
    sr = sig.sample_rate_hz
    i0 = int(1.02 * sr)
    sig.current[i0:i0 + 10] -= 100.0  # 0.4 ms spike, 4x depth
    df = _feat(sig)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["outlier_ratio"] > 0.0
    # despike keeps mean near true depth
    assert abs(row["mean"] + 50.0) < 2.0


def test_min_toff_filter():
    # compute_features with min_toff_ms=None (default) keeps ALL events; the
    # export filter is applied by the caller (pipeline) as a drop_reason.
    evs = [SynthEvent(1.0, 0.02, -50), SynthEvent(2.0, 0.005, -50)]  # 20ms + 5ms
    sig = make_signal(evs, duration_s=4.0, sample_rate_hz=25_000, noise_sigma_pA=0.5, seed=27)
    df = _feat(sig)
    assert len(df) == 2  # filter no longer applied inside compute_features

    # explicit min_toff_ms still filters (backward-compatible)
    from nanopore.baseline import estimate_levels
    from nanopore.detect import detect_events
    from nanopore.features import compute_features

    lv = estimate_levels(sig.current)
    res = detect_events(sig.current, sig.sample_rate_hz, lv.level0, lv.level1,
                        polarity=lv.polarity)
    df2 = compute_features(res, sig.current, sig.sample_rate_hz, label="T", min_toff_ms=10.0)
    assert len(df2) == 1
    assert abs(df2.iloc[0]["toff"] - 20.0) < 0.5


def test_drift_following_io():
    evs = [SynthEvent(2.0, 0.02, -50), SynthEvent(8.0, 0.02, -50)]
    sig = make_signal(evs, duration_s=10.0, sample_rate_hz=25_000,
                      noise_sigma_pA=1.0, drift_pA_per_s=-2.0, seed=29)
    df = _feat(sig, level_contribution=0.2)
    assert len(df) == 2
    # Io follows the local baseline (96 -> 84), so |mean| stays ~50 while
    # %mean = mean/Io grows in magnitude as the baseline drops
    means = df["mean"].to_numpy()
    ios = df["Io"].to_numpy()
    assert abs(means[0] + 50.0) < 2.0 and abs(means[1] + 50.0) < 2.0
    assert abs(ios[0] - 96.0) < 2.0 and abs(ios[1] - 84.0) < 2.0
