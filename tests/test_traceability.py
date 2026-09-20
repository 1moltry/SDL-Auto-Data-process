"""P1: traceable exclusion reasons + config wiring round-trips."""

import numpy as np
import pytest

from nanopore.anomaly import AnomalyRegion, events_in_invalid_regions, invalid_region_reasons
from nanopore.config import PipelineConfig


def _regions():
    return [
        AnomalyRegion("blockage", 10.0, 12.0),
        AnomalyRegion("baseline_step", 20.0, 21.0),  # must never produce a reason
        AnomalyRegion("membrane_rupture", 30.0, 31.0),
        AnomalyRegion("reverse_voltage", 0.0, 2.0),
    ]


def test_reasons_assign_each_kind():
    starts = np.array([0.5, 11.0, 20.5, 30.5, 50.0])
    ends = np.array([1.0, 11.5, 20.8, 30.8, 51.0])
    reasons = invalid_region_reasons(starts, ends, _regions())
    assert reasons[0].split("|") == ["reverse_voltage"]
    assert reasons[1].split("|") == ["blockage"]
    assert reasons[2] == ""           # baseline_step -> no reason
    assert reasons[3].split("|") == ["membrane_rupture"]
    assert reasons[4] == ""


def test_reasons_multiple_overlap_joined():
    starts = np.array([10.5])
    ends = np.array([30.2])
    # spans blockage (10-12) and membrane_rupture (30-31) only partially;
    # make a genuinely double-overlapping event:
    reasons = invalid_region_reasons(starts, ends, _regions())
    assert reasons[0].split("|") == ["blockage", "membrane_rupture"]


def test_reasons_empty_input():
    assert invalid_region_reasons(np.array([]), np.array([]), _regions()) == []


def test_mask_matches_reasons():
    starts = np.array([0.5, 20.5, 50.0])
    ends = np.array([1.0, 20.8, 51.0])
    mask = events_in_invalid_regions(starts, ends, _regions())
    reasons = invalid_region_reasons(starts, ends, _regions())
    assert list(mask) == [r != "" for r in reasons]
    assert list(mask) == [True, False, False]


def test_config_min_toff_present_and_dead_fields_removed():
    cfg = PipelineConfig()
    assert cfg.min_toff_ms == 10.0
    # fully-dead field removed; wired macro thresholds retained
    assert not hasattr(cfg, "min_event_ms")
    assert not hasattr(cfg, "baseline_jump_pA")
    assert cfg.jump_min_ms == 50.0
    assert cfg.noise_sigma_mult == 4.0
    assert cfg.jitter_min_ms == 100.0
    # the wired macro thresholds survive round-trip
    cfg2 = PipelineConfig(jump_min_ms=80.0, noise_sigma_mult=6.0, jitter_min_ms=200.0)
    assert cfg2.jump_min_ms == 80.0
    assert cfg2.noise_sigma_mult == 6.0
    assert cfg2.jitter_min_ms == 200.0


def test_config_json_roundtrip_with_min_toff(tmp_path):
    cfg = PipelineConfig(min_toff_ms=2.0, label="T")
    p = tmp_path / "params.json"
    cfg.save(p)
    loaded = PipelineConfig.load(p)
    assert loaded.min_toff_ms == 2.0
    assert loaded.label == "T"


def test_config_load_old_json_without_min_toff(tmp_path):
    # a JSON saved before min_toff_ms existed must load (unknown keys dropped,
    # missing key falls back to the dataclass default)
    p = tmp_path / "old.json"
    p.write_text('{"ignore_duration_ms": 3.0, "min_event_ms": 5.0}', encoding="utf-8")
    cfg = PipelineConfig.load(p)
    assert cfg.ignore_duration_ms == 3.0
    assert cfg.min_toff_ms == 10.0
    assert not hasattr(cfg, "min_event_ms")


def test_classify_exclusions_combines_anomaly_and_toff():
    import pandas as pd

    from nanopore.features import classify_exclusions

    df = pd.DataFrame({
        "t1": [10.5, 20.5, 30.5],
        "t2": [11.0, 20.8, 30.8],
        "toff": [0.5, 20.0, 5.0],   # ms; row0 short, row2 short
    })
    regions = [
        AnomalyRegion("blockage", 10.0, 12.0),
        AnomalyRegion("baseline_step", 20.0, 21.0),  # not a reason
    ]
    kept, excl = classify_exclusions(df, regions, min_toff_ms=10.0)
    # row0 overlaps blockage AND is short -> anomaly,toff<min; row1 overlaps
    # baseline_step only -> kept; row2 short only -> toff<min
    assert kept["t1"].tolist() == [20.5]
    assert excl["drop_reason"].tolist() == ["blockage,toff<min", "toff<min"]


def test_classify_exclusions_empty_df():
    import pandas as pd

    from nanopore.features import classify_exclusions

    kept, excl = classify_exclusions(pd.DataFrame(), [], None)
    assert kept.empty and excl is None
