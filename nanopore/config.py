"""Pipeline parameters, savable/loadable as JSON (a reusable analysis protocol)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass
class PipelineConfig:
    # --- preprocessing ---
    filter_lowpass_hz: float | None = None  # None = no extra digital filtering

    # --- baseline / level estimation (replaces manual marker dragging) ---
    level0: float | None = None  # manual override of baseline (pA)
    level1: float | None = None  # manual override of event level (pA, signed offset from baseline applied at runtime)
    hist_bins: int = 200         # all-points amplitude histogram bins for level estimation
    polarity: int | None = None  # event search direction: None = auto from the level
                                 # histogram; 1 = upward only; -1 = downward only;
                                 # 0 = both (multi-level peptides whose blockades fall on
                                 # either side of the open pore, e.g. ARNKRS). The
                                 # detector already walks a +/-8 step level grid, so 0
                                 # also enables multi-level detection within each side.

    # --- event detection (level/threshold single-channel search) ---
    ignore_duration_ms: float = 2.0    # Ignore duration (from baseline): out-of-level
                                       # time below this is spike-rejected, not registered
    ignore_event_duration_ms: float = 50.0  # Ignore duration (from event levels): deviations
                                            # out of an event level (incl. brief returns to
                                            # baseline) shorter than this continue the event
                                            # (event-level ignore duration)
    level_contribution: float = 0.10   # exponential update weight for level tracking (10%)
    update_levels: str = "baseline"    # "baseline" (keep deltas) or "all" (independent)
    dwell_min_frac: float = 0.30       # min fraction of trimmed body near a level step to keep an event
    event_plateau_min_frac: float = 0.0  # stability gate: min fraction of the event body dwelling on
                                         # ONE level (nearest integer level, +/-0.5 step). Below this
                                         # the event oscillates across levels (flicker/glitch) and is
                                         # rejected. 0 = disabled (a fast flicker passes the plain
                                         # dwell/spike checks; raising this removes it, but also
                                         # removes genuine multi-level events -> per-file knob).
    min_toff_ms: float = 10.0          # export filter: keep events with toff > this (ms)

    # --- anomaly detection ---
    anomaly_enabled: bool = True
    jump_min_ms: float = 50.0          # macro: sustained shift must persist at least this long
    noise_sigma_mult: float = 4.0      # macro: sliding noise std above this multiple of robust sigma marks jitter
    jitter_min_ms: float = 100.0
    # fine-grained artifact detector: reverse voltage / rupture / graded jitter /
    # irregular blockage with spontaneous-vs-manual recovery; needs the voltage
    # trace and the dynamic I0 baseline
    refined_anomaly_enabled: bool = True
    refined_jitter_window_ms: float = 100.0
    refined_jitter_mild_ratio: float = 3.0
    refined_jitter_severe_ratio: float = 8.0
    refined_jitter_osc_floor: float = 0.45
    refined_blockage_min_ms: float = 500.0
    refined_blockage_fraction: float = 0.45
    refined_rupture_iqr_min_pA: float = 80.0
    refined_rupture_noise_min_ratio: float = 2.0
    refined_rupture_level_frac_max: float = 0.28   # rupture window must have <= this fraction of
                                                   # samples near a significant level (dense event
                                                   # clusters are level-structured -> not rupture)
    refined_jitter_level_frac_max: float = 0.20    # macro jitter block must have <= this fraction of
                                                   # samples near a non-baseline level
    # slow baseline drift / instability (refined detector): a gradual,
    # irreversible displacement of the open-pore level that is ALSO accompanied
    # by high signal spread. Both keys required (see anomaly.ArtifactConfig).
    refined_drift_enabled: bool = True
    refined_drift_block_s: float = 15.0
    refined_drift_min_s: float = 20.0
    refined_drift_min_frac: float = 0.05
    refined_drift_iqr_ratio: float = 3.0
    refined_drift_step_pA: float = 6.0
    refined_drift_rupture_ratio: float = 4.0

    # --- features ---
    pre_event_ms: float = 25.0         # open-pore current window before the event
    dr_pA: float = 5.0                 # |Io(i)-I0|>5 pA fallback threshold for Io continuity
    dynamic_i0_enabled: bool = True    # per-event Io from a quiet-segment dynamic baseline
                                       # (immune to a long blockage being taken as open pore)

    # --- output ---
    label: str = ""                    # Label column value; defaults to file stem

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "PipelineConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid})
