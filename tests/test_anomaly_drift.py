"""Regression tests for the slow baseline-drift / instability detector.

The detector must flag a GRADUAL, IRREVERSIBLE displacement of the open-pore
level that is ALSO accompanied by high spread (TRP tail: baseline creeps up
~10% while the noise IQR grows 4x, ending in a rupture) — and must NOT flag:

- a stable pore-state step (Ala/Asp 110<->180): displacement but abrupt,
- a transient excursion that recovers (ACTH): displaced but reversible,
- a benign slow shift that keeps producing normal events (DQARNKR): displaced
  but NOT unstable.

It reads the open-pore window levels from an I0Profile, so the tests build one.
"""

from __future__ import annotations

import numpy as np

from nanopore.anomaly import ArtifactConfig, detect_artifact_segments
from nanopore.baseline_i0 import build_dynamic_baseline

SR = 2500.0          # low rate keeps the synthetic records fast (windows are 1 s)


def _profile(sig: np.ndarray, sr: float = SR):
    return build_dynamic_baseline(sig, sr)


def _drift_kinds(sig: np.ndarray, sr: float = SR) -> list:
    prof = _profile(sig, sr)
    res = detect_artifact_segments(sig, sr, i0_profile=prof, open_pore=float(np.median(sig[: int(0.2 * len(sig))])),
                                   event_levels=[float(np.median(sig[: int(0.2 * len(sig))]))],
                                   cfg=ArtifactConfig())
    return [r for r in res.regions if r.kind == "baseline_drift"]


def _record(duration_s: float, level: np.ndarray, sigma: np.ndarray, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return level + rng.normal(0.0, 1.0, level.size) * sigma


def test_gradual_drift_with_unstable_tail_is_flagged():
    """Baseline creeps up ~35% while the noise IQR grows ~5x at the end -> one
    baseline_drift region running to the record end."""
    n = int(200 * SR)
    t = np.arange(n) / SR
    level = np.full(n, 100.0)
    ramp = t > 120.0
    level[ramp] += 0.5 * (t[ramp] - 120.0)          # +40 pA by 200 s
    sigma = np.full(n, 1.5)
    sigma[t > 150.0] = 9.0                          # IQR ~ 5x the head
    sig = _record(200.0, level, sigma, seed=7)

    dr = _drift_kinds(sig)
    assert len(dr) == 1, [(r.kind, r.start_s, r.end_s) for r in dr]
    assert dr[0].start_s < 190.0, f"drift start too late: {dr[0].start_s}"
    assert dr[0].end_s >= 195.0


def test_stable_pore_state_step_is_not_drift():
    """A clean sustained level step (100 -> 180) is a state switch, not drift."""
    n = int(200 * SR)
    level = np.full(n, 100.0)
    level[int(100 * SR):] = 180.0
    sig = _record(200.0, level, np.full(n, 1.5), seed=11)

    assert _drift_kinds(sig) == []


def test_transient_excursion_that_recovers_is_not_drift():
    """A deep noisy excursion that returns to baseline is reversible -> not drift."""
    n = int(200 * SR)
    level = np.full(n, 100.0)
    level[int(80 * SR):int(120 * SR)] = 40.0
    sigma = np.full(n, 1.5)
    sigma[int(80 * SR):int(120 * SR)] = 9.0
    sig = _record(200.0, level, sigma, seed=13)

    assert _drift_kinds(sig) == []


def test_displacement_without_instability_is_not_drift():
    """A benign slow shift that keeps a clean, stable level (DQARNKR-like):
    displaced but not unstable -> not drift."""
    n = int(200 * SR)
    t = np.arange(n) / SR
    level = np.full(n, 100.0)
    ramp = t > 120.0
    level[ramp] += 0.15 * (t[ramp] - 120.0)         # +12 pA by 200 s (> 5% anchor)
    sig = _record(200.0, level, np.full(n, 1.4), seed=17)

    assert _drift_kinds(sig) == []
