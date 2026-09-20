"""App state + background analysis worker.

Reuses the existing pipeline functions (read_abf -> estimate_levels ->
detect_events -> detect_anomalies -> compute_features) in a worker thread so a
large .abf never blocks the Qt event loop.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PyQt5.QtCore import QObject, QThread, pyqtSignal

from ..anomaly import (detect_anomalies, detect_artifact_segments,
                       merge_anomaly_results)
from ..baseline import estimate_levels
from ..config import PipelineConfig
from ..detect import detect_events
from ..features import compute_features
from ..io import read_abf
from .bus import bus


class AnalysisWorker(QThread):
    done = pyqtSignal(object, object, object, object, object)   # rec, lv, df, df_excluded, (anom, det)
    failed = pyqtSignal(str)

    def __init__(self, path: str | Path, cfg: PipelineConfig):
        super().__init__()
        self.path = Path(path)
        self.cfg = cfg

    def run(self) -> None:
        try:
            rec = read_abf(self.path)
            lv = estimate_levels(
                rec.current,
                hist_bins=self.cfg.hist_bins,
                baseline=self.cfg.level0,
                event_level=self.cfg.level1,
            )
            filtered = rec.current
            cutoff = self.cfg.filter_lowpass_hz
            if cutoff:
                from ..preprocess import lowpass

                filtered = lowpass(rec.current, rec.sample_rate_hz, cutoff)
            det = detect_events(
                filtered,
                rec.sample_rate_hz,
                lv.level0,
                lv.level1,
                ignore_duration_ms=self.cfg.ignore_duration_ms,
                ignore_event_duration_ms=self.cfg.ignore_event_duration_ms,
                level_contribution=self.cfg.level_contribution,
                update_levels=self.cfg.update_levels,
                polarity=lv.polarity,
                cutoff_hz=cutoff,
                pre_event_ms=self.cfg.pre_event_ms,
                dwell_min_frac=self.cfg.dwell_min_frac,
                plateau_min_frac=self.cfg.event_plateau_min_frac,
            )
            i0_profile = None
            if self.cfg.dynamic_i0_enabled:
                from ..baseline_i0 import build_dynamic_baseline

                i0_profile = build_dynamic_baseline(rec.current, rec.sample_rate_hz,
                                                    anchor_level=lv.level0)
            anom = None
            if self.cfg.anomaly_enabled:
                from ..anomaly import ArtifactConfig

                macro = detect_anomalies(
                    rec.current,
                    rec.sample_rate_hz,
                    open_pore=lv.level0,
                    noise_sigma=lv.noise_sigma,
                    event_levels=lv.levels,
                    jump_min_ms=self.cfg.jump_min_ms,
                    jitter_mult=self.cfg.noise_sigma_mult,
                    jitter_min_ms=self.cfg.jitter_min_ms,
                    jitter_level_frac_max=self.cfg.refined_jitter_level_frac_max,
                )
                refined = None
                if self.cfg.refined_anomaly_enabled:
                    acfg = ArtifactConfig(
                        jitter_window_ms=self.cfg.refined_jitter_window_ms,
                        jitter_mild_ratio=self.cfg.refined_jitter_mild_ratio,
                        jitter_severe_ratio=self.cfg.refined_jitter_severe_ratio,
                        jitter_osc_floor=self.cfg.refined_jitter_osc_floor,
                        blockage_min_ms=self.cfg.refined_blockage_min_ms,
                        blockage_fraction=self.cfg.refined_blockage_fraction,
                        rupture_iqr_min_pA=self.cfg.refined_rupture_iqr_min_pA,
                        rupture_noise_min_ratio=self.cfg.refined_rupture_noise_min_ratio,
                        rupture_level_frac_max=self.cfg.refined_rupture_level_frac_max,
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
                label=self.cfg.label or self.path.stem,
                pre_event_ms=self.cfg.pre_event_ms,
                dr_pA=self.cfg.dr_pA,
                i0_profile=i0_profile,
            )
            # exclusion with a traceable reason, split kept/excluded
            from ..features import classify_exclusions

            df, df_excluded = classify_exclusions(
                df, anom.regions if anom else [], self.cfg.min_toff_ms
            )
            self.done.emit(rec, lv, df, df_excluded, (anom, det))
        except Exception as exc:  # surface as a status message, keep the app alive
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class RoiWorker(QThread):
    """Segment-local (Cursor) analysis for a user-selected region."""
    done = pyqtSignal(object, tuple)   # roi df, (start_s, end_s)
    failed = pyqtSignal(str)

    def __init__(self, rec, cfg, start_s: float, end_s: float):
        super().__init__()
        self.rec = rec
        self.cfg = cfg
        self.start_s = start_s
        self.end_s = end_s

    def run(self) -> None:
        try:
            from ..roi import analyze_roi

            df, _det, _lv = analyze_roi(
                self.rec.current, self.rec.sample_rate_hz,
                self.start_s, self.end_s, self.cfg,
            )
            self.done.emit(df, (self.start_s, self.end_s))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class Controller(QObject):
    """Holds the currently loaded recording + analysis results."""

    def __init__(self) -> None:
        super().__init__()
        self.rec = None
        self.lv = None
        self.df = None
        self.df_excluded = None
        self.anom = None
        self.det = None
        self.cfg: PipelineConfig = PipelineConfig()
        self._worker: AnalysisWorker | None = None
        self._roi_worker: RoiWorker | None = None
        self.roi_df = None
        self.roi_span = None

    def load(self, path: str | Path, cfg: PipelineConfig | None = None) -> None:
        if cfg is not None:
            self.cfg = cfg
        self._start(path)

    def set_config(self, cfg: PipelineConfig) -> None:
        self.cfg = cfg

    def rerun(self) -> None:
        if self.rec is not None:
            self._start(self.rec.path)

    def rerun_roi(self, start_s: float, end_s: float) -> None:
        """Analyse a user-selected region independently (Cursor semantics)."""
        if self.rec is None:
            bus.status.emit("请先打开一个 .abf 文件")
            return
        self._roi_worker = RoiWorker(self.rec, self.cfg, start_s, end_s)
        self._roi_worker.done.connect(self._on_roi_done)
        self._roi_worker.failed.connect(self._on_failed)
        bus.status.emit(f"ROI 分析 [{start_s:.2f}, {end_s:.2f}]s …")
        self._roi_worker.start()

    def _on_roi_done(self, df, span) -> None:
        self.roi_df = df
        self.roi_span = span
        n = 0 if df is None else len(df)
        bus.status.emit(f"ROI [{span[0]:.2f}, {span[1]:.2f}]s: {n} 事件")
        bus.roi_finished.emit(df, span)

    def _start(self, path: str | Path) -> None:
        self._worker = AnalysisWorker(path, self.cfg)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        bus.status.emit(f"分析中: {Path(path).name} …")
        self._worker.start()

    def _on_done(self, rec, lv, df, df_excluded, anom_det) -> None:
        self.rec, self.lv, self.df = rec, lv, df
        self.df_excluded = df_excluded
        self.anom, self.det = anom_det
        n_removed = len(df_excluded) if df_excluded is not None else 0
        bus.status.emit(f"完成: {rec.path.name}\t保留 {len(df)} / 剔除 {n_removed}（明细见异常面板）")
        bus.file_loaded.emit(str(rec.path))
        bus.detection_finished.emit()

    def _on_failed(self, msg: str) -> None:
        bus.status.emit(f"错误: {msg}")


controller = Controller()
