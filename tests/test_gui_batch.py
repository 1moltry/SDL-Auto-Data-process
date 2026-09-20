"""GUI batch dialog smoke test (offscreen): file/folder expansion and wiring.

Verifies that a mixed list of .abf files and folders expands recursively into a
sorted, de-duplicated file list, and that the dialog reports an empty selection
instead of starting a run.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

pytest.importorskip("PyQt5")

from nanopore.gui.batchdialog import BatchDialog, collect_abf_files


@pytest.fixture(scope="session")
def qapp():
    from PyQt5.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


CASE2 = Path("abf数据案例/abf数据案例2/abf数据案例2")


def test_collect_files_expands_folders_recursively(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.abf").write_bytes(b"x")
    (tmp_path / "sub" / "b.abf").write_bytes(b"x")
    (tmp_path / "not_abf.txt").write_text("skip")

    files = collect_abf_files([str(tmp_path)])
    assert [f.name for f in files] == ["a.abf", "b.abf"]


def test_collect_files_dedupes_and_keeps_order(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.abf").write_bytes(b"x")
    (tmp_path / "sub" / "b.abf").write_bytes(b"x")

    # the same file reached both directly and through the folder
    files = collect_abf_files([str(tmp_path), str(tmp_path / "a.abf")])
    assert [f.name for f in files] == ["a.abf", "b.abf"]


def test_collect_files_matches_lab_folder_layout():
    if not CASE2.exists():
        pytest.skip("second sample set not present")
    files = collect_abf_files([str(CASE2)])
    names = {f.name for f in files}
    assert "TREFETSC.abf" in names and "T3.abf" in names
    assert len(files) >= 15


def test_dialog_reports_empty_selection(qapp):
    from nanopore.config import PipelineConfig

    dlg = BatchDialog(PipelineConfig())
    assert dlg.selected_files() == []
    dlg._run()                       # must not start a worker
    assert "没有可处理的" in dlg.log.toPlainText()
    assert dlg._worker is None


def test_dialog_selects_folder_and_runs_worker(qapp, tmp_path):
    from nanopore.config import PipelineConfig

    (tmp_path / "one.abf").write_bytes(b"not a real abf")
    out = tmp_path / "out"
    dlg = BatchDialog(PipelineConfig())
    dlg.files.addItem(str(tmp_path))
    dlg.out_edit.setText(str(out))
    assert [f.name for f in dlg.selected_files()] == ["one.abf"]
    dlg._run()
    assert dlg._worker is not None
    dlg._worker.wait(20000)
    for _ in range(20):          # flush the worker's queued cross-thread signals
        qapp.processEvents()
    text = dlg.log.toPlainText()
    # the bogus file fails on its own without aborting the batch, and the
    # worker still reports a summary line
    assert "one.abf" in text
    assert "完成" in text or "失败" in text
    assert dlg.run_btn.isEnabled()
