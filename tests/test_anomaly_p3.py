"""P3: empirical detector fixes.

F1 — a dense burst of DISCRETE events (peptide cluster) must not be flagged
     membrane_rupture, even though its 100 ms windows are broad-IQR and noisy;
     the region-level level-structure gate rejects it. A genuinely diffuse
     rupture must still be kept.
F2 — macro jitter must not fire on a level-structured block (dense events).
F3 — the dynamic I0 baseline must anchor near the open-pore level, not the
     first quiet window (which can be a non-pore flat gap or secondary state).
"""
import numpy as np
import pytest

from tests.synth import SynthSignal


def _level(sig):
    from nanopore.baseline import estimate_levels

    return estimate_levels(sig.current)


def _profile(sig, **kw):
    from nanopore.baseline_i0 import build_dynamic_baseline

    return build_dynamic_baseline(sig.current, sig.sample_rate_hz, **kw)


def _ref(sig, **kw):
    from nanopore.anomaly import ArtifactConfig, detect_artifact_segments

    return detect_artifact_segments(sig.current, sig.sample_rate_hz, **kw)


def _macro(sig, levels, **kw):
    from nanopore.anomaly import detect_anomalies

    return detect_anomalies(sig.current, sig.sample_rate_hz,
                            open_pore=levels.level0, noise_sigma=levels.noise_sigma,
                            event_levels=levels.levels, **kw)


def _kinds(res):
    from collections import Counter

    return Counter(r.kind for r in res.regions)


# ---- F1: dense discrete event cluster is NOT a rupture ----
def test_dense_event_cluster_not_rupture():
    """Rapid discrete pulses between two levels: broad-IQR + noisy windows, but
    samples sit at the discrete levels (region-level level-structure frac high)
    -> not a membrane rupture."""
    sr = 25_000
    rng = np.random.default_rng(71)
    n = int(10 * sr)
    cur = 100.0 + rng.normal(0.0, 1.0, n)
    lo, hi = int(4 * sr), int(7 * sr)   # 3 s dense burst region
    seg = cur[lo:hi]
    # dense square-ish pulses between open pore (100) and event level (~15)
    for i in range(0, len(seg), 400):   # every 16 ms toggle for ~0.5 ms dwell
        e = i + 12
        if e >= len(seg):
            break
        seg[i:e] = 15.0 + rng.normal(0.0, 2.0, e - i)
    # a few events are so dense the window IQR (~85) clears the broad threshold
    from collections import Counter

    sig = SynthSignal(current=cur, sample_rate_hz=sr, baseline_pA=100.0)
    lv = _level(sig)
    prof = _profile(sig, anchor_level=lv.level0)
    res = _ref(sig, i0_profile=prof, open_pore=lv.level0, event_levels=lv.levels)
    assert "membrane_rupture" not in _kinds(res), res.regions


def test_diffuse_rupture_still_flagged():
    """A truly diffuse rupture (no level structure, broad noise) must be excluded —
    as rupture or severe jitter (both are invalidating regions). The precise label
    depends on how many spurious levels estimate_levels found in the noise."""
    sr = 25_000
    rng = np.random.default_rng(73)
    n = int(8 * sr)
    cur = 100.0 + rng.normal(0.0, 1.0, n)
    lo, hi = int(4 * sr), int(6 * sr)
    cur[lo:hi] = 100.0 + rng.normal(0.0, 60.0, hi - lo)
    sig = SynthSignal(current=cur, sample_rate_hz=sr, baseline_pA=100.0)
    lv = _level(sig)
    prof = _profile(sig, anchor_level=lv.level0)
    res = _ref(sig, i0_profile=prof, open_pore=lv.level0, event_levels=lv.levels)
    kinds = _kinds(res)
    # the diffuse burst is recognised as an artifact (rupture or severe jitter)
    assert ("membrane_rupture" in kinds) or ("membrane_jitter_severe" in kinds), res.regions
    assert "blockage_spontaneous" not in kinds  # it is not a clean blocked plateau
    hit = [r for r in res.regions
           if r.kind in ("membrane_rupture", "membrane_jitter_severe")
           and r.end_s > 4.5 and r.start_s < 5.5]
    assert hit, res.regions


# ---- F2: macro jitter gate ----
def test_macro_jitter_level_structured_block_not_flagged():
    """A block stuffed with dense discrete events (raised std AND mean leaves the
    envelope) is a level-structured event burst, not membrane jitter."""
    sr = 25_000
    rng = np.random.default_rng(75)
    n = int(8 * sr)
    cur = 100.0 + rng.normal(0.0, 1.0, n)
    lo, hi = int(3 * sr), int(5 * sr)
    seg = cur[lo:hi]
    for i in range(0, len(seg), 600):
        e = i + 20
        if e >= len(seg):
            break
        seg[i:e] = 15.0 + rng.normal(0.0, 2.0, e - i)
    sig = SynthSignal(current=cur, sample_rate_hz=sr, baseline_pA=100.0)
    lv = _level(sig)
    res = _macro(sig, lv)
    assert "jitter" not in _kinds(res), res.regions


# ---- F3: dynamic baseline anchor ----
def test_baseline_anchors_near_open_pore_not_first_quiet():
    """Record starts with a quiet NON-pore flat segment (~0 pA) then settles at
    the true open pore (100). The dynamic baseline must anchor near 100, not
    follow the leading 0 pA gap (which a first-quiet-window anchor would)."""
    sr = 25_000
    rng = np.random.default_rng(77)
    n = int(10 * sr)
    cur = np.ones(n) * 100.0
    # first 2 s = flat near-zero gap (quiet but NOT open pore)
    cur[:2 * sr] = 0.0 + rng.normal(0.0, 0.5, 2 * sr)
    cur += rng.normal(0.0, 1.0, n)
    sig = SynthSignal(current=cur, sample_rate_hz=sr, baseline_pA=100.0)
    lv = _level(sig)
    # with anchor_level=100, baseline near open pore; without, it anchors at 0
    prof_a = _profile(sig, anchor_level=lv.level0)
    prof_b = _profile(sig)
    assert abs(np.median(prof_a.baseline[:sr]) - 100.0) < 15.0, \
        f"anchored baseline {np.median(prof_a.baseline[:sr]):.1f} should be ~100"
