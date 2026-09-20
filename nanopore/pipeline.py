"""End-to-end batch pipeline: read -> detect -> anomalies -> features -> outputs."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .anomaly import (AnomalyRegion, AnomalyResult, detect_anomalies,
                      detect_artifact_segments, merge_anomaly_results)
from .analysis import (build_combined_dataset, plot_hist, plot_overview,
                       plot_scatter, write_combined_dataset, write_events_xlsx,
                       write_summary)
from .baseline import estimate_levels
from .config import PipelineConfig
from .detect import detect_events
from .features import compute_features
from .io import read_abf


@dataclass
class FileReport:
    file: str
    label: str
    duration_s: float
    n_events_raw: int
    n_events: int
    n_brief: int
    valid_pct: float
    level0: float
    levels: list[float] = field(default_factory=list)
    polarity: int = 0
    noise_sigma: float = 0.0
    anomalies: dict = field(default_factory=dict)
    removed: dict = field(default_factory=dict)
    error: str = ""
    elapsed_s: float = 0.0


def process_file(abf_path: Path, out_dir: Path, cfg: PipelineConfig) -> tuple[pd.DataFrame, FileReport]:
    t0 = time.perf_counter()
    label = cfg.label or abf_path.stem
    rec = read_abf(abf_path)

    lv = estimate_levels(
        rec.current,
        hist_bins=cfg.hist_bins,
        baseline=cfg.level0,
        event_level=cfg.level1,
    )
    if cfg.polarity is not None:
        from .baseline import set_polarity

        set_polarity(lv, cfg.polarity)   # manual search-direction override

    filtered = rec.current
    cutoff = cfg.filter_lowpass_hz
    if cutoff:
        from .preprocess import lowpass

        filtered = lowpass(rec.current, rec.sample_rate_hz, cutoff)

    det = detect_events(
        filtered,
        rec.sample_rate_hz,
        lv.level0,
        lv.level1,
        ignore_duration_ms=cfg.ignore_duration_ms,
        ignore_event_duration_ms=cfg.ignore_event_duration_ms,
        level_contribution=cfg.level_contribution,
        update_levels=cfg.update_levels,
        polarity=lv.polarity,
        cutoff_hz=cutoff,
        pre_event_ms=cfg.pre_event_ms,
        dwell_min_frac=cfg.dwell_min_frac,
        plateau_min_frac=cfg.event_plateau_min_frac,
    )

    # Dynamic open-pore baseline for per-event Io (immune to a long blockage
    # being mistaken for the open pore); features fall back to the pre/post
    # window rule when the profile is not requested.
    i0_profile = None
    if cfg.dynamic_i0_enabled:
        from .baseline_i0 import build_dynamic_baseline

        i0_profile = build_dynamic_baseline(rec.current, rec.sample_rate_hz,
                                            anchor_level=lv.level0)

    anom: AnomalyResult | None = None
    if cfg.anomaly_enabled:
        macro = detect_anomalies(
            rec.current,
            rec.sample_rate_hz,
            open_pore=lv.level0,
            noise_sigma=lv.noise_sigma,
            event_levels=lv.levels,
            jump_min_ms=cfg.jump_min_ms,
            jitter_mult=cfg.noise_sigma_mult,
            jitter_min_ms=cfg.jitter_min_ms,
            jitter_level_frac_max=cfg.refined_jitter_level_frac_max,
        )
        refined = None
        if cfg.refined_anomaly_enabled:
            from .anomaly import ArtifactConfig

            acfg = ArtifactConfig(
                jitter_window_ms=cfg.refined_jitter_window_ms,
                jitter_mild_ratio=cfg.refined_jitter_mild_ratio,
                jitter_severe_ratio=cfg.refined_jitter_severe_ratio,
                jitter_osc_floor=cfg.refined_jitter_osc_floor,
                blockage_min_ms=cfg.refined_blockage_min_ms,
                blockage_fraction=cfg.refined_blockage_fraction,
                rupture_iqr_min_pA=cfg.refined_rupture_iqr_min_pA,
                rupture_noise_min_ratio=cfg.refined_rupture_noise_min_ratio,
                rupture_level_frac_max=cfg.refined_rupture_level_frac_max,
                drift_enabled=cfg.refined_drift_enabled,
                drift_block_s=cfg.refined_drift_block_s,
                drift_min_s=cfg.refined_drift_min_s,
                drift_min_frac=cfg.refined_drift_min_frac,
                drift_iqr_ratio=cfg.refined_drift_iqr_ratio,
                drift_step_pA=cfg.refined_drift_step_pA,
                drift_rupture_ratio=cfg.refined_drift_rupture_ratio,
            )
            refined = detect_artifact_segments(
                rec.current,
                rec.sample_rate_hz,
                voltage=rec.protocol_voltage,
                i0_profile=i0_profile,
                open_pore=lv.level0,
                event_levels=lv.levels,
                cfg=acfg,
            )
        anom = merge_anomaly_results(macro, refined)

    df = compute_features(
        det,
        filtered,
        rec.sample_rate_hz,
        label=label,
        pre_event_ms=cfg.pre_event_ms,
        dr_pA=cfg.dr_pA,
        i0_profile=i0_profile,
    )

    # --- exclusion with a traceable reason, then split kept / excluded ---
    from .features import classify_exclusions

    df, df_excluded = classify_exclusions(df, anom.regions if anom else [],
                                          cfg.min_toff_ms)

    # outputs
    stem = abf_path.stem
    write_events_xlsx(df, anom.regions if anom else [], out_dir / f"{stem}_events.xlsx",
                      excluded=df_excluded)
    plot_overview(
        rec.current, rec.sample_rate_hz,
        df["t1"].to_numpy() if len(df) else np.array([]),
        df["t2"].to_numpy() if len(df) else np.array([]),
        anom if anom is not None else AnomalyResult([], np.ones(1, dtype=bool), np.array([]), 0.1, lv.level0),
        lv,
        out_dir / f"{stem}_overview.png",
        label=label,
    )
    plot_scatter(df, out_dir / f"{stem}_scatter.png", label=label)
    plot_hist(df, out_dir / f"{stem}_hist.png", label=label)

    n_anom: dict[str, int] = {}
    if anom is not None:
        for r in anom.regions:
            n_anom[r.kind] = n_anom.get(r.kind, 0) + 1

    # excluded-event breakdown (traceability): anomaly kinds toff<min
    removed: dict[str, int] = {}
    if df_excluded is not None and len(df_excluded):
        for reason in df_excluded["drop_reason"]:
            for part in str(reason).split(","):
                removed[part] = removed.get(part, 0) + 1

    report = FileReport(
        file=abf_path.name,
        label=label,
        duration_s=rec.duration_s,
        n_events_raw=len(det.events),
        n_events=len(df),
        n_brief=sum(1 for e in det.events if e.state == "B"),
        valid_pct=float(anom.valid.mean() * 100) if anom is not None else 100.0,
        level0=lv.level0,
        levels=[round(v, 1) for v in lv.levels],
        polarity=lv.polarity,
        noise_sigma=lv.noise_sigma,
        anomalies=n_anom,
        removed=removed,
        elapsed_s=time.perf_counter() - t0,
    )
    return df, report


def run_batch(files: list[Path], out_dir: Path, cfg: PipelineConfig,
              progress=None) -> list[FileReport]:
    """Process ``files`` into ``out_dir``, continuing past a bad file.

    ``progress`` (optional) is called as ``progress(i, total, file_name, report)``
    before each file finishes, so a GUI can show a live counter.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    reports: list[FileReport] = []
    dataset: list[tuple[str, pd.DataFrame]] = []   # (source_file, kept events)
    for i, f in enumerate(files, start=1):
        try:
            df, rep = process_file(f, out_dir, cfg)
            dataset.append((f.name, df))
        except Exception as exc:  # keep batch going on a bad file
            rep = FileReport(file=f.name, label=cfg.label or f.stem, duration_s=0.0,
                             n_events_raw=0, n_events=0, n_brief=0, valid_pct=0.0,
                             level0=0.0, error=f"{type(exc).__name__}: {exc}")
        reports.append(rep)
        status = f"err {rep.error}" if rep.error else (
            f"{rep.n_events} events (of {rep.n_events_raw} raw), valid {rep.valid_pct:.0f}%"
        )
        print(f"  {f.name}: {status} [{rep.elapsed_s:.1f}s]")
        if progress is not None:
            progress(i, len(files), f.name, rep)

    rows = []
    for rep in reports:
        rows.append({
            "file": rep.file, "label": rep.label, "duration_s": round(rep.duration_s, 1),
            "events": rep.n_events, "events_raw": rep.n_events_raw, "brief": rep.n_brief,
            "valid_pct": round(rep.valid_pct, 1),
            "level0_pA": round(rep.level0, 1), "n_levels": len(rep.levels),
            "polarity": rep.polarity, "noise_sigma_pA": round(rep.noise_sigma, 2),
            "anomalies": "; ".join(f"{k}x{v}" for k, v in rep.anomalies.items()),
            "removed": "; ".join(f"{k}x{v}" for k, v in rep.removed.items()),
            "error": rep.error, "elapsed_s": round(rep.elapsed_s, 1),
        })
    write_combined_dataset(build_combined_dataset(dataset), out_dir / "dataset_all.csv")
    write_summary(rows, out_dir / "summary.xlsx")
    return reports
