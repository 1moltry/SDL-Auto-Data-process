"""Regression tests for event detection against analytic ground truth."""

import numpy as np

from tests.synth import SynthEvent, make_signal


def _detect(sig, **kw):
    from nanopore.baseline import estimate_levels
    from nanopore.detect import detect_events

    lv = estimate_levels(sig.current, baseline=sig.baseline_pA if "baseline" in () else None)
    lv = estimate_levels(sig.current)
    pol = lv.polarity
    return detect_events(
        sig.current,
        sig.sample_rate_hz,
        lv.level0,
        lv.level1,
        polarity=pol,
        **kw,
    ), lv


def test_level_estimation_square_pulses():
    sig = make_signal(
        [SynthEvent(1.0, 0.02, -50), SynthEvent(3.0, 0.02, -50)],
        duration_s=5.0, sample_rate_hz=10_000, noise_sigma_pA=2.0, seed=3,
    )
    lv = _detect(sig)[1]
    assert abs(lv.level0 - 100.0) < 2.0
    assert abs(lv.level1 - 50.0) < 2.0
    assert lv.polarity == -1


def test_detect_positions_and_amplitude():
    events = [SynthEvent(1.0, 0.02, -50), SynthEvent(2.0, 0.03, -50), SynthEvent(4.0, 0.01, -50)]
    sig = make_signal(events, duration_s=6.0, sample_rate_hz=10_000, noise_sigma_pA=1.0, seed=5)
    res, lv = _detect(sig)
    assert len(res.events) == 3, f"expected 3 events, got {len(res.events)}"
    for ev, truth in zip(res.events, events):
        assert abs(ev.start_s - truth.start_s) < 2e-3, (ev.start_s, truth.start_s)
        assert abs(ev.end_s - (truth.start_s + truth.duration_s)) < 2e-3
        assert abs(ev.depth_pA - truth.amplitude_pA) < 2.0


def test_polarity_selects_search_side():
    """polarity gates the search direction: up-only / down-only / both. The
    multi-level requirement of sparse peptides (ARNKRS blockades on both sides)
    is met by polarity=0."""
    from nanopore.detect import detect_events

    events = [SynthEvent(1.0, 0.02, -50), SynthEvent(2.0, 0.02, 50),
              SynthEvent(3.0, 0.02, -50), SynthEvent(4.0, 0.02, 50)]
    sig = make_signal(events, duration_s=6.0, sample_rate_hz=10_000,
                      baseline_pA=100.0, noise_sigma_pA=1.0, seed=7)

    def n(level1, pol):
        return len(detect_events(sig.current, sig.sample_rate_hz, 100.0, level1,
                                 polarity=pol).events)

    assert n(150.0, 1) == 2, "upward-only should find the two +50 events"
    assert n(50.0, -1) == 2, "downward-only should find the two -50 events"
    assert n(150.0, 0) == 4, "bidirectional should find both sides"


def test_set_polarity_keeps_level1_on_chosen_side():
    """A manual direction that disagrees with level1 must re-side level1, else
    detect_events' sign gate rejects everything (grid and gate disagree)."""
    from nanopore.baseline import estimate_levels, set_polarity

    sig = make_signal([SynthEvent(1.0, 0.02, 50), SynthEvent(3.0, 0.02, 50)],
                      duration_s=5.0, sample_rate_hz=10_000,
                      baseline_pA=100.0, noise_sigma_pA=1.0, seed=9)
    lv = estimate_levels(sig.current)
    assert lv.level1 > lv.level0          # estimated as an upward trace
    set_polarity(lv, -1)
    assert lv.polarity == -1
    assert lv.level1 < lv.level0          # re-sided below the baseline
    assert abs((lv.level0 - lv.level1) - 50.0) < 3.0


def test_config_polarity_roundtrip(tmp_path):
    from nanopore.config import PipelineConfig

    cfg = PipelineConfig(polarity=0)
    path = tmp_path / "p.json"
    cfg.save(path)
    assert PipelineConfig.load(path).polarity == 0
    assert PipelineConfig().polarity is None   # default = auto (unchanged)


def test_detect_upward_events():
    events = [SynthEvent(1.0, 0.02, +30), SynthEvent(2.5, 0.02, +30)]
    sig = make_signal(events, duration_s=4.0, sample_rate_hz=10_000, noise_sigma_pA=1.0, seed=7)
    res, lv = _detect(sig)
    assert lv.polarity == 1
    assert len(res.events) == 2
    for ev, truth in zip(res.events, events):
        assert abs(ev.depth_pA - 30.0) < 2.0


def test_bidirectional_events():
    events = [SynthEvent(1.0, 0.02, -40), SynthEvent(2.0, 0.02, +40)]
    sig = make_signal(events, duration_s=4.0, sample_rate_hz=10_000, noise_sigma_pA=1.0, seed=9)
    res, lv = _detect(sig)
    # both sides carry equal event populations -> levels found on both sides
    above = [v for v in lv.levels if v > lv.level0 + 3 * lv.noise_sigma]
    below = [v for v in lv.levels if v < lv.level0 - 3 * lv.noise_sigma]
    assert above and below, lv.levels
    assert len(res.events) >= 1
    depths = sorted(ev.depth_pA for ev in res.events)
    assert all(abs(abs(d) - 40.0) < 2.5 for d in depths)


def test_drift_tracking():
    # 2 pA/s downward drift over 10 s = 20 pA; event depths should stay ~-50
    events = [SynthEvent(2.0, 0.02, -50), SynthEvent(8.0, 0.02, -50)]
    sig = make_signal(events, duration_s=10.0, sample_rate_hz=10_000,
                      noise_sigma_pA=1.0, drift_pA_per_s=-2.0, seed=11)
    res, _ = _detect(sig, level_contribution=0.2)
    assert len(res.events) == 2
    for ev in res.events:
        assert abs(ev.depth_pA + 50.0) < 3.0, ev.depth_pA


def test_ignore_duration_glitch():
    # a 0.5 ms glitch must not create a spurious event (ignore_duration 2 ms)
    sr = 10_000
    events = [SynthEvent(1.0, 0.02, -50)]
    sig = make_signal(events, duration_s=3.0, sample_rate_hz=sr, noise_sigma_pA=0.5, seed=13)
    i0 = int(2.0 * sr)
    sig.current[i0:i0 + 5] -= 60.0  # 0.5 ms glitch
    res, _ = _detect(sig, ignore_duration_ms=2.0)
    assert len(res.events) == 1
    assert abs(res.events[0].start_s - 1.0) < 2e-3


def test_no_events_clean_baseline():
    sig = make_signal([], duration_s=3.0, sample_rate_hz=10_000, noise_sigma_pA=1.0, seed=15)
    res, _ = _detect(sig)
    assert len(res.events) == 0


def test_sweepy_pulses_recall():
    sig = make_sweepy_square_pulses = None
    from tests.synth import make_sweepy_square_pulses
    sig = make_sweepy_square_pulses(n_events=20, duration_s=20.0, sample_rate_hz=10_000,
                                    noise_sigma_pA=1.5, seed=17)
    res, _ = _detect(sig)
    recall = len(res.events) / len(sig.events)
    assert recall >= 0.9, f"recall {recall:.2f} ({len(res.events)}/{len(sig.events)})"


def test_tall_overshoot_spike_rejected():
    # a huge +1000 pA glitch (12x the event depth) must not create an event:
    # it overshoots Clampfit's level range and its body does not dwell near a level.
    sr = 10_000
    sig = make_signal([SynthEvent(1.0, 0.02, -50)], duration_s=3.0,
                      sample_rate_hz=sr, noise_sigma_pA=0.5, seed=21)
    i0 = int(2.0 * sr)
    sig.current[i0:i0 + 60] += 1000.0  # 6 ms, 20x-depth overshoot spike
    res, _ = _detect(sig)
    assert len(res.events) == 1, f"overshoot spike leaked in: {len(res.events)} events"
    assert abs(res.events[0].start_s - 1.0) < 2e-3


def test_opposite_polarity_spike_rejected():
    # upward spikes while the real events go down (polarity=-1) are not events
    sr = 10_000
    sig = make_signal([SynthEvent(1.0, 0.02, -50)], duration_s=3.0,
                      sample_rate_hz=sr, noise_sigma_pA=0.5, seed=23)
    i0 = int(2.0 * sr)
    sig.current[i0:i0 + 60] += 120.0  # wrong-sign excursion above baseline
    res, _ = _detect(sig)
    assert len(res.events) == 1
    assert abs(res.events[0].start_s - 1.0) < 2e-3


def test_real_blockade_events_preserved():
    # 0.65-depth blockades (partial / sub-level events, e.g. ARNKRS) survive
    sr = 10_000
    events = [SynthEvent(1.0, 0.02, -30), SynthEvent(2.0, 0.02, -30), SynthEvent(3.0, 0.02, -30)]
    sig = make_signal(events, duration_s=4.0, sample_rate_hz=sr, noise_sigma_pA=1.0, seed=25)
    res, _ = _detect(sig)
    assert len(res.events) == 3, f"0.65-depth events lost: {len(res.events)}"
    for ev, truth in zip(res.events, events):
        assert abs(ev.depth_pA - truth.amplitude_pA) < 2.5


def test_long_blockade_with_baseline_blips_merges():
    # T3 pattern: long blockades chopped by 5-20 ms brief returns to baseline.
    # Event-level ignore (50 ms) bridges them: each blockade stays ONE event.
    sr = 25_000
    events = [SynthEvent(1.0, 2.0, -60), SynthEvent(5.0, 2.0, -60)]
    sig = make_signal(events, duration_s=9.0, sample_rate_hz=sr, noise_sigma_pA=1.0, seed=1)
    for t in [1.5, 1.8, 2.3, 2.9, 5.4, 5.9, 6.5]:
        i0 = int(t * sr)
        sig.current[i0:i0 + int(0.01 * sr)] = sig.baseline_pA  # 10 ms blip
    res, _ = _detect(sig)
    assert len(res.events) == 2, f"blips shredded the blockade: {len(res.events)} events"
    for ev, truth in zip(res.events, events):
        assert abs(ev.start_s - truth.start_s) < 2e-3
        assert abs(ev.end_s - (truth.start_s + truth.duration_s)) < 2e-3
        assert abs(ev.depth_pA - truth.amplitude_pA) < 2.0


def test_short_ms_events_survive_event_level_ignore():
    # pore2 pattern: genuine 3 ms peptide events must NOT be swallowed by the
    # 50 ms event-level ignore (deviations FROM baseline always register).
    sr = 25_000
    events = [SynthEvent(1.0, 0.003, -50), SynthEvent(2.0, 0.003, -50),
              SynthEvent(3.0, 0.003, -50)]
    sig = make_signal(events, duration_s=4.5, sample_rate_hz=sr, noise_sigma_pA=0.8, seed=2)
    res, _ = _detect(sig)
    assert len(res.events) == 3, f"short events lost: {len(res.events)}"
    for ev, truth in zip(res.events, events):
        assert abs(ev.start_s - truth.start_s) < 1e-3
        assert abs(ev.depth_pA - truth.amplitude_pA) < 2.5


def test_above_baseline_noise_does_not_drag_level0():
    # SLR pattern: an above-baseline noise population must not pull level0 up
    # (which flips baseline samples into "events"). The baseline-update guard
    # (0.15 step) keeps level0 at the open pore.
    sr = 25_000
    events = [SynthEvent(2.0, 0.02, -70), SynthEvent(4.0, 0.02, -70)]
    sig = make_signal(events, duration_s=8.0, sample_rate_hz=sr, noise_sigma_pA=1.0, seed=3)
    sig.current[int(6.0 * sr):int(6.5 * sr)] += 45.0  # above-baseline burst
    from nanopore.detect import detect_events as _de

    # manual levels (as the user would set them in Clampfit): the +45 burst is
    # NOT the event level; downward -70 events are.
    res = _de(sig.current, sig.sample_rate_hz, 100.0, 30.0, polarity=-1)
    assert len(res.events) == 2
    for ev, truth in zip(res.events, events):
        assert abs(ev.depth_pA - truth.amplitude_pA) < 3.0
    assert abs(res.level0_final - 100.0) < 3.0, \
        f"level0 drifted: 100.0 -> {res.level0_final}"


def test_amplitude_step_across_blip_bridges_same_level():
    # Clampfit merged all-level semantics: within one level class, a brief
    # open-pore blip does not end the blockade. A deep blockage followed by
    # a 20 ms blip and then a shallower stretch at the same level index is
    # ONE bridged event (dwell-weighted amplitude).
    sr = 25_000
    sig = make_signal([SynthEvent(2.82, 0.02, -50)], duration_s=6.0,
                      sample_rate_hz=sr, noise_sigma_pA=1.0, seed=51)
    sig.current[int(1.0 * sr):int(2.8 * sr)] -= 60.0   # deep blockage at -60
    res, _ = _detect(sig)
    assert len(res.events) == 1, f"expected one bridged event, got {len(res.events)}"
    ev = res.events[0]
    assert abs(ev.start_s - 1.0) < 2e-3
    # dwell-weighted amplitude: blockage (1.8 s) dominates the 20 ms shallower bit
    assert abs(ev.amplitude_pA - 40.0) < 1.5, ev.amplitude_pA
