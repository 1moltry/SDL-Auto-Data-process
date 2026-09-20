"""Regression tests for the event-stability (plateau) gate.

A fast flicker — a run that keeps returning to baseline for sub-ignore blips —
merges into ONE event whose body oscillates across levels. The plain spike/
dwell checks pass it, but its "plateau fraction" (samples dwelling on the single
level nearest the body median) is ~0.5, while a flat blockade sits at ~1.0.
``plateau_min_frac`` rejects the oscillator; 0 (default) leaves everything alone.
"""

from __future__ import annotations

import numpy as np

from nanopore.detect import detect_events

SR = 10_000.0
BASE, LEVEL = 100.0, 50.0     # 50 pA downward blockade on a 100 pA baseline


def _sig(duration_s: float, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(duration_s * SR)
    return BASE + rng.normal(0.0, 0.8, n)


def _detect(sig, plateau: float):
    return detect_events(sig, SR, BASE, LEVEL, polarity=-1, cutoff_hz=None,
                         plateau_min_frac=plateau)


def test_flat_blockade_survives_the_gate():
    """A clean flat blockade (plateau ~1.0) is kept whether the gate is on or off."""
    sig = _sig(2.0)
    sig[int(1.0 * SR):int(1.1 * SR)] = LEVEL          # 100 ms flat blockade
    off = _detect(sig, 0.0).events
    on = _detect(sig, 0.85).events

    assert len(off) == 1 and len(on) == 1, (len(off), len(on))
    assert abs(off[0].dwell_s - 0.1) < 5e-3


def test_flicker_is_rejected_by_the_gate_only():
    """A 100 ms run whose excursions dwell at the event level (3 ms) with short
    sub-ignore returns to baseline (1.5 ms) merges into ONE event; the gate
    (0.85) rejects it, the default (0) keeps it."""
    sig = _sig(2.0)
    a, b = int(1.0 * SR), int(1.1 * SR)
    osc = np.tile(np.concatenate([np.full(30, LEVEL), np.full(15, BASE)]), 50)
    sig[a:b] = osc[: b - a]

    off = _detect(sig, 0.0).events
    on = _detect(sig, 0.85).events

    assert len(off) >= 1, "sanity: the flicker must be detected when the gate is off"
    assert len(on) == 0, f"gate should reject the flicker, kept {[e.dwell_s for e in on]}"


def test_gate_default_is_off():
    """Omitting plateau_min_frac must reproduce the ungated result exactly."""
    sig = _sig(2.0)
    sig[int(1.0 * SR):int(1.1 * SR)] = LEVEL
    default = detect_events(sig, SR, BASE, LEVEL, polarity=-1, cutoff_hz=None).events
    off = _detect(sig, 0.0).events

    assert [(e.start_s, e.end_s) for e in default] == [(e.start_s, e.end_s) for e in off]
