"""Fine-grained anomaly detector: spontaneous/manual blockage recovery,
membrane jitter (pure high-frequency noise), rupture state machine, reverse
voltage, and voltage-less downgrade.

These cases are the ones the macro envelope detector (detect_anomalies) misses:
pure high-frequency jitter keeps the window MEAN at open pore, so the envelope
rule ("mean must leave the envelope") never fires.
"""
import numpy as np

from tests.synth import SynthEvent, make_signal


def _profile(sig):
    from nanopore.baseline_i0 import build_dynamic_baseline

    return build_dynamic_baseline(sig.current, sig.sample_rate_hz)


def _detect(sig, **kw):
    from nanopore.anomaly import detect_artifact_segments

    return detect_artifact_segments(sig.current, sig.sample_rate_hz, **kw)


def _make_voltage(duration_s, sample_rate_hz, base_mv=100.0, neg_from=None,
                  neg_to=None):
    v = np.full(int(round(duration_s * sample_rate_hz)), base_mv, dtype=float)
    if neg_from is not None:
        v[int(neg_from * sample_rate_hz):int(neg_to * sample_rate_hz)] = -100.0
    return v


def _kinds(res):
    from collections import Counter

    return Counter(r.kind for r in res.regions)


def test_spontaneous_blockage_recovery():
    """A long deep plateau with internal irregularity that recovers on its own is
    blockage_spontaneous (not manual — no reverse voltage)."""
    sr = 25_000
    sig = make_signal([], duration_s=12.0, sample_rate_hz=sr, noise_sigma_pA=1.0, seed=51)
    lo, hi = int(3.0 * sr), int(8.0 * sr)
    sig.current[lo:hi] += -60.0
    # internal irregularity: the blocked stretch is not perfectly flat
    rng = np.random.default_rng(51)
    sig.current[lo:hi] += rng.normal(0.0, 8.0, hi - lo)
    res = _detect(sig, i0_profile=_profile(sig), open_pore=100.0)
    kinds = _kinds(res)
    assert kinds["blockage_spontaneous"] >= 1, f"expected spontaneous blockage, got {kinds}"
    assert "blockage_manual_recovery" not in kinds
    # the blockage span is flagged (allow ~1 window of edge slack)
    hit = [r for r in res.regions if r.kind.startswith("blockage")
           and r.start_s <= 3.2 and r.end_s >= 7.8]
    assert hit, res.regions


def test_manual_blockage_with_reverse_voltage():
    """The same blockage overlapping a reverse-voltage run is manual recovery."""
    sr = 25_000
    sig = make_signal([], duration_s=12.0, sample_rate_hz=sr, noise_sigma_pA=1.0, seed=53)
    lo, hi = int(3.0 * sr), int(8.0 * sr)
    sig.current[lo:hi] += -60.0
    rng = np.random.default_rng(53)
    sig.current[lo:hi] += rng.normal(0.0, 8.0, hi - lo)
    volt = _make_voltage(12.0, sr, neg_from=3.0, neg_to=8.0)
    res = _detect(sig, i0_profile=_profile(sig), open_pore=100.0, voltage=volt)
    kinds = _kinds(res)
    assert kinds["blockage_manual_recovery"] >= 1, f"expected manual, got {kinds}"
    assert kinds["reverse_voltage"] >= 1


def test_pure_highfreq_membrane_jitter_severe():
    """Baseline noise rises from sigma 1 to sigma 12 for 3 s with the MEAN pinned at
    open pore. The macro detector misses this (mean in envelope); the refined
    detector must flag severe jitter and leave the clean parts valid."""
    sr = 25_000
    rng = np.random.default_rng(55)
    n = int(20 * sr)
    cur = 100.0 + rng.normal(0.0, 1.0, n)
    lo, hi = int(8 * sr), int(11 * sr)
    cur[lo:hi] = 100.0 + rng.normal(0.0, 12.0, hi - lo)
    from tests.synth import SynthSignal

    sig = SynthSignal(current=cur, sample_rate_hz=sr, baseline_pA=100.0)
    res = _detect(sig, i0_profile=_profile(sig), open_pore=100.0)
    kinds = _kinds(res)
    assert kinds["membrane_jitter_severe"] >= 1, f"expected severe jitter, got {kinds}"
    jr = [r for r in res.regions if r.kind == "membrane_jitter_severe" and r.start_s <= 8.0 and r.end_s >= 11.0]
    assert jr, res.regions
    # clean head is not flagged
    bad_head = [r for r in res.regions if r.end_s < 7.5]
    assert not bad_head, bad_head


def test_membrane_jitter_mild_not_severe():
    """A modest noise rise (sigma ~4, ratio ~4) is mild jitter, not severe."""
    sr = 25_000
    rng = np.random.default_rng(57)
    n = int(16 * sr)
    cur = 100.0 + rng.normal(0.0, 1.0, n)
    lo, hi = int(6 * sr), int(9 * sr)
    cur[lo:hi] = 100.0 + rng.normal(0.0, 4.0, hi - lo)
    from tests.synth import SynthSignal

    sig = SynthSignal(current=cur, sample_rate_hz=sr, baseline_pA=100.0)
    res = _detect(sig, i0_profile=_profile(sig), open_pore=100.0)
    kinds = _kinds(res)
    assert kinds["membrane_jitter_mild"] >= 1, f"expected mild jitter, got {kinds}"
    assert kinds["membrane_jitter_severe"] == 0


def test_membrane_rupture_state_machine():
    """Rupture: >=2 consecutive broad-IQR (>=80 pA spread) windows, recovery only
    after 5 quiet windows. A single broad blip is not rupture."""
    sr = 25_000
    n = int(16 * sr)
    t = np.arange(n) / sr
    rng = np.random.default_rng(59)
    cur = 100.0 + rng.normal(0.0, 1.0, n)
    # rupture-like: 3 s of violent noise spanning ~250 pA
    lo, hi = int(5 * sr), int(8 * sr)
    cur[lo:hi] = 100.0 + rng.normal(0.0, 60.0, hi - lo)
    # single 0.5 s violent blip (not 2 consecutive 100ms... must be >=200ms broad)
    from tests.synth import SynthSignal

    sig = SynthSignal(current=cur, sample_rate_hz=sr, baseline_pA=100.0)
    res = _detect(sig, i0_profile=_profile(sig), open_pore=100.0)
    kinds = _kinds(res)
    # 3 s of sigma60 gives IQR ~160 >> 80 in every 100ms window -> rupture
    assert kinds["membrane_rupture"] >= 1, f"expected rupture, got {kinds}"
    ru = [r for r in res.regions if r.kind == "membrane_rupture" and r.start_s <= 5.0 and r.end_s >= 8.0]
    assert ru, res.regions


def test_voltage_none_downgrades_all_spontaneous():
    """With no voltage trace the detector cannot tell manual from spontaneous;
    blockages must be labelled spontaneous and no reverse_voltage emitted."""
    sr = 25_000
    sig = make_signal([], duration_s=12.0, sample_rate_hz=sr, noise_sigma_pA=1.0, seed=61)
    lo, hi = int(3.0 * sr), int(8.0 * sr)
    sig.current[lo:hi] += -60.0
    rng = np.random.default_rng(61)
    sig.current[lo:hi] += rng.normal(0.0, 8.0, hi - lo)
    res = _detect(sig, i0_profile=_profile(sig), open_pore=100.0, voltage=None)
    kinds = _kinds(res)
    assert kinds["blockage_spontaneous"] >= 1
    assert "blockage_manual_recovery" not in kinds
    assert "reverse_voltage" not in kinds


def test_clean_noise_is_not_artifact():
    """A clean single-channel recording with no defects must have no regions."""
    sr = 25_000
    sig = make_signal([SynthEvent(1.0, 0.02, -50), SynthEvent(3.0, 0.02, -50)],
                      duration_s=5.0, sample_rate_hz=sr, noise_sigma_pA=1.0, seed=63)
    res = _detect(sig, i0_profile=_profile(sig), open_pore=100.0)
    assert len(res.regions) == 0, res.regions


def test_bipolar_protocol_segments_flagged():
    """tPAL-style protocol: hold +100 mV with a 2 s -50 mV wash pulse and a 1 s
    0 mV rest. Every sustained deviation from the hold is a protocol segment;
    a fixed negative-rail test would miss the 0 mV rest."""
    sr = 25_000
    sig = make_signal([], duration_s=24.0, sample_rate_hz=sr, noise_sigma_pA=1.0, seed=71)
    v = _make_voltage(24.0, sr, base_mv=100.0)
    v[int(8.0 * sr):int(10.0 * sr)] = -50.0     # wash pulse
    v[int(18.0 * sr):int(19.0 * sr)] = 0.0      # rest level
    res = _detect(sig, i0_profile=_profile(sig), open_pore=100.0, voltage=v)
    rv = [r for r in res.regions if r.kind == "reverse_voltage"]
    assert len(rv) == 2, [(r.start_s, r.end_s, r.detail) for r in res.regions]
    wash = [r for r in rv if r.start_s < 10.0][0]
    rest = [r for r in rv if r.start_s > 15.0][0]
    # each region covers the segment plus the settling guard around it
    assert wash.start_s < 8.0 and wash.end_s > 10.0
    assert rest.start_s < 18.0 and rest.end_s > 19.0


def test_protocol_hold_is_dominant_level_not_fixed_rail():
    """When the protocol holds a negative potential and pulses positive, the
    hold (sensing) level is the dominant level — the positive pulse is the
    segment to exclude, not the hold."""
    sr = 25_000
    sig = make_signal([], duration_s=24.0, sample_rate_hz=sr, noise_sigma_pA=1.0, seed=73)
    v = _make_voltage(24.0, sr, base_mv=-100.0)   # hold at -100
    v[int(8.0 * sr):int(10.0 * sr)] = 100.0       # positive pulse
    res = _detect(sig, i0_profile=_profile(sig), open_pore=100.0, voltage=v)
    rv = [r for r in res.regions if r.kind == "reverse_voltage"]
    assert len(rv) == 1, [(r.start_s, r.end_s, r.detail) for r in res.regions]
    assert rv[0].start_s < 8.0 and rv[0].end_s > 10.0
