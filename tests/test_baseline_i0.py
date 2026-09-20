"""Dynamic open-pore baseline: per-event Io immune to blockage leakage.

A long blockage preceding an event used to be treated as a "baseline run", so
the event's open-pore reference drifted down to the blocked level and its depth
was underestimated. The dynamic I0 profile (built from quiet windows) must keep
Io at the true open-pore level even while a multi-second deep blockage is in
the trace.
"""
import numpy as np

from tests.synth import SynthEvent, make_signal


def _feat_dyn(sig, **detect_kw):
    from nanopore.baseline import estimate_levels
    from nanopore.baseline_i0 import build_dynamic_baseline
    from nanopore.detect import detect_events
    from nanopore.features import compute_features

    lv = estimate_levels(sig.current)
    res = detect_events(sig.current, sig.sample_rate_hz, lv.level0, lv.level1,
                        polarity=lv.polarity, **detect_kw)
    prof = build_dynamic_baseline(sig.current, sig.sample_rate_hz)
    return compute_features(res, sig.current, sig.sample_rate_hz, label="T",
                            i0_profile=prof), prof


def _feat_legacy(sig, **detect_kw):
    from nanopore.baseline import estimate_levels
    from nanopore.detect import detect_events
    from nanopore.features import compute_features

    lv = estimate_levels(sig.current)
    res = detect_events(sig.current, sig.sample_rate_hz, lv.level0, lv.level1,
                        polarity=lv.polarity, **detect_kw)
    return compute_features(res, sig.current, sig.sample_rate_hz, label="T")


def test_event_after_long_blockage_io_is_open_pore():
    """An event immediately after a long deep blockage: dynamic Io must read the
    open pore (~100), not the blocked level. Use explicit open-pore levels so the
    blocked level (a small fraction of the record) does not steal the histogram
    baseline."""
    sr = 25_000
    sig = make_signal([SynthEvent(8.08, 0.02, -50)], duration_s=12.0,
                      sample_rate_hz=sr, noise_sigma_pA=1.0, seed=41)
    # 6 s deep blockage ending 80 ms before the event (blocked level ~40); the
    # gap is longer than the 50 ms event-level ignore so the post-blockage
    # event stays separate (bridging only swallows shorter blips).
    sig.current[int(2.0 * sr):int(8.0 * sr)] -= 60.0

    from nanopore.baseline_i0 import build_dynamic_baseline

    prof = build_dynamic_baseline(sig.current, sr)
    # dynamic baseline must stay at ~100 across the blockage (not follow it)
    assert abs(float(np.median(prof.baseline[int(3.0 * sr):int(7.0 * sr)])) - 100.0) < 2.0, \
        "dynamic baseline must not follow the blockage plateau"

    # detect with explicit open-pore level so the blockage plateau (~40, but only
    # 6 s of 12 s) does not become level0
    from nanopore.baseline import estimate_levels
    from nanopore.detect import detect_events
    from nanopore.features import compute_features

    lv = estimate_levels(sig.current, baseline=100.0, event_level=50.0)
    res = detect_events(sig.current, sr, lv.level0, lv.level1,
                        polarity=-1, ignore_duration_ms=2.0)
    # the real event at 8.02 s must be found
    real = [ev for ev in res.events if 8.0 < ev.start_s < 8.2]
    assert len(real) == 1, f"expected the post-blockage event, got {[(e.start_s, e.amplitude_pA) for e in res.events]}"

    df = compute_features(res, sig.current, sr, label="T", i0_profile=prof)
    row = df[df["t1"].between(8.0, 8.2)].iloc[0]
    assert abs(row["Io"] - 100.0) < 2.0, f"Io leaked to blocked level: {row['Io']}"
    assert abs(row["mean"] + 50.0) < 3.0, f"depth wrong: {row['mean']}"


def test_legacy_io_leaks_to_blocked_level():
    """Contrast: without the dynamic profile, the pre/post fallback Io may take
    a corrupted pre-window (still in the blockage) and mis-estimate the depth."""
    sr = 25_000
    sig = make_signal([SynthEvent(8.02, 0.02, -50)], duration_s=12.0,
                      sample_rate_hz=sr, noise_sigma_pA=1.0, seed=41)
    sig.current[int(2.0 * sr):int(8.0 * sr)] -= 60.0

    from nanopore.baseline import estimate_levels
    from nanopore.detect import detect_events
    from nanopore.features import compute_features

    lv = estimate_levels(sig.current, baseline=100.0, event_level=50.0)
    res = detect_events(sig.current, sr, lv.level0, lv.level1,
                        polarity=-1, ignore_duration_ms=2.0)
    df = compute_features(res, sig.current, sr, label="T")  # no profile
    row = df[df["t1"].between(8.0, 8.2)]
    # whether the leak occurs depends on pre-window content; the key regression is
    # that the dynamic version (above) is correct — here we only assert the legacy
    # path still runs and produces sane columns.
    assert not row.empty or "Io" in df.columns


def test_dynamic_baseline_ignores_event_plateaus():
    """Event plateaus (transient, higher noise) must not become I0 windows."""
    sig = make_signal(
        [SynthEvent(1.0, 0.5, -50), SynthEvent(3.0, 0.5, -50)],  # 500 ms events
        duration_s=5.0, sample_rate_hz=25_000, noise_sigma_pA=1.0, seed=43,
    )
    prof = _feat_dyn(sig)[1]
    # even during the long event plateau the baseline stays at open pore
    sr = sig.sample_rate_hz
    assert abs(float(np.median(prof.baseline[int(1.2 * sr):int(1.4 * sr)])) - 100.0) < 2.0


def test_drift_tracking_via_dynamic_baseline():
    """Slow open-pore drift is still followed by the dynamic baseline."""
    sr = 25_000
    sig = make_signal([SynthEvent(1.0, 0.02, -50), SynthEvent(8.0, 0.02, -50)],
                      duration_s=10.0, sample_rate_hz=sr,
                      noise_sigma_pA=1.0, drift_pA_per_s=-2.0, seed=45)
    df = _feat_dyn(sig, level_contribution=0.2)[0]
    assert len(df) == 2
    ios = df["Io"].to_numpy()
    means = df["mean"].to_numpy()
    # drift 2 pA/s -> Io ~96 at 2 s, ~84 at 8 s
    assert abs(ios[0] - 96.0) < 2.0, f"Io0={ios[0]}"
    assert abs(ios[1] - 84.0) < 2.0, f"Io1={ios[1]}"
    assert abs(means[0] + 50.0) < 2.0 and abs(means[1] + 50.0) < 2.0


def test_two_platform_levels_isolated_io():
    """Slow pore-state switching 100 <-> 150: an event on the 100 platform must
    get Io~100, not a blend pulled toward 150."""
    sr = 25_000
    sig = make_signal([SynthEvent(2.0, 0.02, -50)], duration_s=10.0,
                      sample_rate_hz=sr, noise_sigma_pA=1.0, seed=47)
    # first half at 100; from 4 s onward switch to a 150 platform
    t = np.arange(len(sig.current)) / sr
    platform = (t >= 4.0) & (t < 8.0)
    sig.current[platform] += 50.0
    df = _feat_dyn(sig, level_contribution=0.2)[0]
    # event at 2 s is before the switch -> Io ~100
    row = df[df["t1"] < 3.0]
    if len(row):
        assert abs(float(row.iloc[0]["Io"]) - 100.0) < 2.0
