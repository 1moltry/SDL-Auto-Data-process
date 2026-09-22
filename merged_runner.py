from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from nanopore_prior.config import AnalysisConfig
from nanopore_prior.pipeline import analyze_file


@dataclass
class FileResult:
    source_file: str
    source_path: str
    output_dir: str
    status: str
    event_count: int = 0
    candidate_event_count: int = 0
    invalid_segment_count: int = 0
    screening_rejected_count: int = 0
    elapsed_s: float = 0.0
    error: str = ""


def collect_abf_files(source: str | Path) -> list[Path]:
    source = Path(source)
    if source.is_file() and source.suffix.lower() == ".abf":
        return [source]
    if source.is_dir():
        return sorted(p for p in source.rglob("*.abf") if p.is_file())
    raise FileNotFoundError(f"输入路径不存在或不是 ABF 文件：{source}")


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _write_workbook(folder: Path, stem: str) -> None:
    sheets = {
        "events": _read_csv(folder / "事件特征.csv"),
        "event_times": _read_csv(folder / "事件起始结束事件点.csv"),
        "event_types": _read_csv(folder / "事件分型.csv"),
        "subplatforms": _read_csv(folder / "事件子平台.csv"),
        "invalid_segments": _read_csv(folder / "无效信号记录.csv"),
        "screening_rejected": _read_csv(folder / "数据分级筛选记录.csv"),
        "event_states": _read_csv(folder / "事件异常状态.csv"),
    }
    with pd.ExcelWriter(folder / f"{stem}_events.xlsx", engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)


def _summary_counts(folder: Path) -> dict:
    path = folder / "分析摘要.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_batch_outputs(output_root: Path, results: list[FileResult]) -> None:
    rows = [asdict(item) for item in results]
    with pd.ExcelWriter(output_root / "summary.xlsx", engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="summary", index=False)
    frames: list[pd.DataFrame] = []
    for item in results:
        if item.status != "ok":
            continue
        features = _read_csv(Path(item.output_dir) / "事件特征.csv")
        if features.empty:
            continue
        features = features.rename(columns={"%mean": "rel_mean", "t1": "t1_ms", "t2": "t2_ms"})
        features.insert(0, "source_file", item.source_file)
        features.insert(1, "source_path", item.source_path)
        frames.append(features)
    dataset = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["source_file", "source_path"]
    )
    dataset.to_csv(output_root / "dataset_all.csv", index=False, encoding="utf-8-sig")
    manifest = {
        "pipeline": "merged-prior-primary+interactive-review",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "files_total": len(results),
        "files_ok": sum(item.status == "ok" for item in results),
        "files_failed": sum(item.status != "ok" for item in results),
        "results": rows,
    }
    (output_root / "运行清单.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_analysis(
    source: str | Path,
    output_root: str | Path,
    config: AnalysisConfig,
    start_s: float | None = None,
    end_s: float | None = None,
    progress: Callable[[int, int, FileResult], None] | None = None,
) -> list[FileResult]:
    files = collect_abf_files(source)
    if not files:
        raise FileNotFoundError(f"未找到 ABF 文件：{source}")
    source = Path(source)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    batch = source.is_dir() or len(files) > 1
    results: list[FileResult] = []
    for index, abf_path in enumerate(files, 1):
        if batch and source.is_dir():
            folder = output_root / abf_path.relative_to(source).with_suffix("")
        else:
            folder = output_root / abf_path.stem if batch else output_root
        started = time.perf_counter()
        try:
            analyze_file(abf_path, folder, config, start_s, end_s)
            _write_workbook(folder, abf_path.stem)
            summary = _summary_counts(folder)
            item = FileResult(
                source_file=abf_path.name,
                source_path=str(abf_path.resolve()),
                output_dir=str(folder.resolve()),
                status="ok",
                event_count=int(summary.get("event_count", 0)),
                candidate_event_count=int(summary.get("candidate_event_count", 0)),
                invalid_segment_count=int(summary.get("invalid_segment_count", 0)),
                screening_rejected_count=len(_read_csv(folder / "数据分级筛选记录.csv")),
                elapsed_s=round(time.perf_counter() - started, 3),
            )
        except Exception as exc:
            item = FileResult(
                source_file=abf_path.name,
                source_path=str(abf_path.resolve()),
                output_dir=str(folder.resolve()),
                status="failed",
                elapsed_s=round(time.perf_counter() - started, 3),
                error=f"{type(exc).__name__}: {exc}",
            )
        results.append(item)
        if progress is not None:
            progress(index, len(files), item)
    _write_batch_outputs(output_root, results)
    return results
