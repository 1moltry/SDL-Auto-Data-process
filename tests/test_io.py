"""IO tests: float-ABF1 fallback reader against pCLAMP Sample Data.

pyabf refuses float ABF1 files; our fallback reader must load them with sane
sample rates / magnitudes. The Sample Data files ship with pCLAMP but are not
checked into the repo; tests self-skip when absent.
"""
from pathlib import Path

import numpy as np
import pytest

SAMPLE = Path("pCLAMP11.2/Sample Data")


def _have_float_samples() -> bool:
    return (SAMPLE / "kchann.abf").exists()


@pytest.mark.skipif(not _have_float_samples(), reason="pCLAMP Sample Data not present")
def test_float_abf1_reader_kchann():
    from nanopore.io import read_abf

    rec = read_abf(SAMPLE / "kchann.abf")
    assert rec.sample_rate_hz > 0
    assert rec.current.ndim == 1
    # kchann is a clean single-channel recording: signal in ~ tens of pA
    assert np.nanmedian(rec.current) > -20.0
    assert len(rec.current) > 1000


@pytest.mark.skipif(not _have_float_samples(), reason="pCLAMP Sample Data not present")
def test_float_abf1_reader_singles_sweeps():
    from nanopore.io import read_abf

    rec = read_abf(SAMPLE / "singles.abf")
    # singles.abf has 144 sweeps; read_abf concatenates -> long flat trace
    assert rec.sweep_count == 144
    assert rec.n_channels == 1
    assert len(rec.current) / rec.sample_rate_hz > 5.0
    assert np.isfinite(rec.current).all()


@pytest.mark.skipif(not _have_float_samples(), reason="pCLAMP Sample Data not present")
def test_read_abf_detects_events_in_kchann():
    """End-to-end: the pipeline should find clean openings in kchann.abf."""
    from nanopore.baseline import estimate_levels
    from nanopore.config import PipelineConfig
    from nanopore.detect import detect_events
    from nanopore.io import read_abf

    rec = read_abf(SAMPLE / "kchann.abf")
    lv = estimate_levels(rec.current, hist_bins=100)
    res = detect_events(
        rec.current, rec.sample_rate_hz, lv.level0, lv.level1,
        ignore_duration_ms=2.0, level_contribution=0.1,
        update_levels="baseline", polarity=lv.polarity,
        cutoff_hz=None, pre_event_ms=25.0,
    )
    # kchann is a classic single-channel opening recording: expect many events
    assert len(res.events) >= 10, f"kchann should have many openings, got {len(res.events)}"


@pytest.mark.skipif(not _have_float_samples(), reason="pCLAMP Sample Data not present")
def test_float_abf1_units_and_names_from_header():
    """Float reader must surface the recorded unit + channel name, not hardcoded pA."""
    from nanopore.io import read_abf

    for name, expect_unit in [("kchann.abf", "pA"), ("VMTestA.abf", "nA"), ("ecg.abf", "mV")]:
        rec = read_abf(SAMPLE / name)
        assert rec.units == expect_unit, f"{name}: expected unit {expect_unit!r}, got {rec.units!r}"
        assert rec.channel_names and rec.channel_names[0], f"{name}: missing channel name"
        assert not any("\x00" in u for u in rec.channel_units or []), f"{name}: NUL leak in units"


@pytest.mark.skipif(not (SAMPLE / "muscle.abf").exists(), reason="pCLAMP Sample Data not present")
def test_float_abf1_multichannel_per_channel():
    """muscle.abf is a 4-channel float ABF1; each channel must carry its own unit."""
    from nanopore.io import read_abf

    rec = read_abf(SAMPLE / "muscle.abf", channel=0)
    assert rec.n_channels == 4
    assert rec.units == "mV"
    assert rec.channel_units == ["mV", "V", "cm H20", "mm Hg"]
    assert rec.channel_names[0] == "EMG di"
    assert rec.sample_rate_hz == pytest.approx(2000.0, rel=0.02)

    ch1 = read_abf(SAMPLE / "muscle.abf", channel=1)
    assert ch1.units == "V"
    # channels are multiplexed: same sample count, different trace
    assert len(ch1.current) == len(rec.current)
    assert not np.array_equal(ch1.current, rec.current)

    with pytest.raises(ValueError, match="out of range"):
        read_abf(SAMPLE / "muscle.abf", channel=4)


@pytest.mark.skipif(not _have_float_samples(), reason="pCLAMP Sample Data not present")
def test_float_abf1_dispatch_by_signature(tmp_path):
    """Dispatch must not depend on pyabf exception text: even a header-only float
    file that pyabf could never parse routes to the self-reader."""
    import shutil
    from nanopore.io import read_abf

    src = SAMPLE / "kchann.abf"
    dst = tmp_path / "copy.abf"
    shutil.copy(src, dst)
    rec = read_abf(dst)
    assert len(rec.current) > 1000
    assert rec.units == "pA"


@pytest.mark.skipif(not _have_float_samples(), reason="pCLAMP Sample Data not present")
def test_truncated_float_abf1_diagnostics(tmp_path):
    """A float ABF1 whose data section was cut must raise a clear ValueError."""
    from nanopore.io import read_abf

    src = (SAMPLE / "kchann.abf").read_bytes()
    dst = tmp_path / "trunc.abf"
    dst.write_bytes(src[:10000])  # header intact, data truncated
    with pytest.raises(ValueError, match="corrupt or truncated"):
        read_abf(dst)


def test_not_an_abf_diagnostics(tmp_path):
    from nanopore.io import read_abf

    dst = tmp_path / "junk.abf"
    dst.write_bytes(b"this is definitely not an axon binary file format")
    with pytest.raises(ValueError, match="signature"):
        read_abf(dst)
