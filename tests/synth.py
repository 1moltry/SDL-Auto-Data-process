"""Synthetic nanopore signal generator for regression testing.

Produces known event positions/amplitudes/durations so detection and feature
math can be validated against analytic ground truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class SynthEvent:
    start_s: float
    duration_s: float
    amplitude_pA: float   # signed step relative to baseline; negative = blockade (typical)


@dataclass
class SynthSignal:
    current: np.ndarray
    sample_rate_hz: float
    events: list[SynthEvent] = field(default_factory=list)
    baseline_pA: float = 100.0

    @property
    def dt_s(self) -> float:
        return 1.0 / self.sample_rate_hz

    @property
    def duration_s(self) -> float:
        return len(self.current) / self.sample_rate_hz


def make_signal(
    events: list[SynthEvent],
    duration_s: float = 10.0,
    sample_rate_hz: float = 25_000.0,
    baseline_pA: float = 100.0,
    noise_sigma_pA: float = 2.0,
    drift_pA_per_s: float = 0.0,
    seed: int = 0,
) -> SynthSignal:
    """Baseline at baseline_pA; each event steps current by amplitude_pA for its duration."""
    rng = np.random.default_rng(seed)
    n = int(round(duration_s * sample_rate_hz))
    t = np.arange(n) / sample_rate_hz
    sig = np.full(n, baseline_pA, dtype=np.float64)
    for ev in events:
        i0 = int(round(ev.start_s * sample_rate_hz))
        i1 = i0 + int(round(ev.duration_s * sample_rate_hz))
        i0, i1 = max(i0, 0), min(i1, n)
        if i1 > i0:
            sig[i0:i1] += ev.amplitude_pA
    sig += drift_pA_per_s * t
    sig += rng.normal(0.0, noise_sigma_pA, n)
    return SynthSignal(current=sig, sample_rate_hz=sample_rate_hz, events=list(events), baseline_pA=baseline_pA)


def make_sweepy_square_pulses(
    n_events: int = 30,
    duration_s: float = 10.0,
    depth_pA: float = -50.0,
    dwell_range_s: tuple[float, float] = (0.005, 0.05),
    gap_range_s: tuple[float, float] = (0.05, 0.3),
    **kwargs,
) -> SynthSignal:
    """Random blockade pulses below baseline (typical nanopore sensing trace)."""
    rng = np.random.default_rng(kwargs.pop("seed", 0))
    sample_rate_hz = kwargs.get("sample_rate_hz", 25_000.0)
    events, t = [], 0.5
    for _ in range(n_events):
        dwell = rng.uniform(*dwell_range_s)
        if t + dwell > duration_s - 0.5:
            break
        events.append(SynthEvent(start_s=t, duration_s=dwell, amplitude_pA=depth_pA))
        t += dwell + rng.uniform(*gap_range_s)
    return make_signal(events, duration_s=duration_s, seed=kwargs.get("seed", 0), **kwargs)
