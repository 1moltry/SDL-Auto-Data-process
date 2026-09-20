"""Anomaly detection tests on synthetic signals with known defects."""

import numpy as np

from tests.synth import SynthEvent, make_signal


def _anom(sig, **kw):
    from nanopore.anomaly import detect_anomalies

    return detect_anomalies(sig.current, sig.sample_rate_hz, **kw)


def test_clean_trace_no_anomalies():
    sig = make_signal([SynthEvent(1.0, 0.02, -50), SynthEvent(2.0, 0.02, -50)],
                      duration_s=5.0, sample_rate_hz=25_000, noise_sigma_pA=1.0, seed=31)
    res = _anom(sig, open_pore=100.0, noise_sigma=1.0)
    assert len(res.regions) == 0
    assert res.valid.all()


def test_blockage_region_detected():
    # sustained -60 pA blockage from 2s to 3s (deeper than events)
    sig = make_signal([SynthEvent(1.0, 0.02, -50)], duration_s=5.0,
                      sample_rate_hz=25_000, noise_sigma_pA=1.0, seed=33)
    i0, i1 = int(2.0 * 25_000), int(3.0 * 25_000)
    sig.current[i0:i1] -= 60.0
    res = _anom(sig, open_pore=100.0, noise_sigma=1.0)
    kinds = {r.kind for r in res.regions}
    assert "blockage" in kinds or "breakdown" in kinds
    hit = [r for r in res.regions if r.start_s <= 2.0 and r.end_s >= 3.0]
    assert hit, res.regions
    assert not res.valid.all()


def test_breakdown_at_end():
    sig = make_signal([SynthEvent(1.0, 0.02, -50)], duration_s=5.0,
                      sample_rate_hz=25_000, noise_sigma_pA=1.0, seed=35)
    i0 = int(4.5 * 25_000)
    sig.current[i0:] -= 500.0  # membrane burst
    res = _anom(sig, open_pore=100.0, noise_sigma=1.0)
    kinds = {r.kind for r in res.regions}
    assert "breakdown" in kinds, res.regions


def test_events_overlapping_anomaly_flagged():
    from nanopore.anomaly import events_in_invalid_regions
    from nanopore.anomaly import AnomalyRegion

    starts = np.array([0.5, 1.9, 3.5])
    ends = np.array([0.6, 2.5, 3.6])
    regions = [AnomalyRegion("blockage", 2.0, 3.0)]
    bad = events_in_invalid_regions(starts, ends, regions)
    assert bad.tolist() == [False, True, False]


def test_baseline_step_switching():
    # slow state switching 100 <-> 150 every 2s (Gln-like oscillation)
    sig = make_signal([], duration_s=10.0, sample_rate_hz=25_000, noise_sigma_pA=1.0, seed=37)
    t = np.arange(len(sig.current)) / 25_000
    state = (np.floor(t / 2.0) % 2) * 50.0
    sig.current += state
    res = _anom(sig, open_pore=100.0, noise_sigma=1.0)
    # switching regions should be found as baseline_step or blockage, not missed
    assert len(res.regions) >= 2, res.regions


def test_sparse_peptide_blockade_not_flagged():
    """No level clears the 2% population bar, so the envelope must span ALL the
    discrete levels rather than collapsing to 8*sigma. A clean deep blockade is
    the analyte signal, not a breakdown. Regression for ARNKRS (pore2)."""
    # 1.5 s blockage in a 100 s record = 1.5% of samples, below the 2% bar
    sig = make_signal([SynthEvent(10.0, 1.5, -80)],
                      duration_s=100.0, sample_rate_hz=25_000,
                      baseline_pA=100.0, noise_sigma_pA=1.0, seed=41)
    res = _anom(sig, open_pore=100.0, noise_sigma=1.0,
                event_levels=[100.0, 20.0, 150.0])
    kinds = {r.kind for r in res.regions}
    assert "breakdown" not in kinds, res.regions
    assert "blockage" not in kinds, res.regions
    assert res.valid.all()


def test_excursion_beyond_all_levels_still_flagged():
    """Widening the envelope to the level span must not blind the detector: a
    genuine breakdown past every discrete level is still caught (Asp end-of-
    record rupture)."""
    sig = make_signal([SynthEvent(10.0, 1.5, -80), SynthEvent(60.0, 3.0, -450)],
                      duration_s=100.0, sample_rate_hz=25_000,
                      baseline_pA=100.0, noise_sigma_pA=1.0, seed=43)
    res = _anom(sig, open_pore=100.0, noise_sigma=1.0,
                event_levels=[100.0, 20.0, 150.0])
    hit = [r for r in res.regions if r.kind == "breakdown"
           and r.end_s > 60.0 and r.start_s < 63.0]
    assert hit, res.regions
