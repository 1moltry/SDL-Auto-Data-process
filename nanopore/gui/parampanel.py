"""Detection/feature parameter panel (the search configuration).

Edits a :class:`PipelineConfig`, saves/loads it as JSON (a reusable analysis
protocol) and triggers a background re-run.
"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                             QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QVBoxLayout, QWidget)

from ..config import PipelineConfig
from .bus import bus


def _spin(minimum: float, maximum: float, value: float, suffix: str = "",
          step: float = 0.1) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(minimum, maximum)
    s.setDecimals(3)
    s.setSingleStep(step)
    s.setValue(value)
    s.setSuffix(suffix)
    return s


def _tip(widget, text: str):
    """Attach a hover help text with the parameter's meaning / effect / when to tune."""
    widget.setToolTip(text)
    return widget


class ParamPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.ignore = _spin(0.0, 100.0, 2.0, " ms", 0.5)
        self.pre = _spin(0.0, 500.0, 25.0, " ms", 1.0)
        self.contrib = _spin(0.01, 1.0, 0.10, "", 0.01)
        self.lowpass = _spin(0.0, 20000.0, 0.0, " Hz", 100.0)
        self.min_toff = _spin(0.0, 100.0, 10.0, " ms", 0.5)
        self.plateau = _spin(0.0, 1.0, 0.0, "", 0.05)
        self.dr = _spin(0.0, 100.0, 5.0, " pA", 0.5)
        self.anom = QCheckBox("启用异常检测")
        self.anom.setChecked(True)
        self.drift_en = QCheckBox("启用慢漂移检测")
        self.drift_en.setChecked(True)
        self.drift_frac = _spin(0.0, 1.0, 0.05, "", 0.01)
        self.drift_iqr = _spin(1.0, 20.0, 3.0, " x", 0.5)
        self.lab = QLineEdit()

        self.l0_en = QCheckBox("手动 Level0")
        self.l0 = _spin(-10000.0, 10000.0, 0.0, " pA", 1.0)
        self.l1_en = QCheckBox("手动 Level1")
        self.l1 = _spin(-10000.0, 10000.0, 0.0, " pA", 1.0)

        self.polarity = QComboBox()
        for label, value in (("自动", None), ("向上", 1), ("向下", -1), ("双向", 0)):
            self.polarity.addItem(label, value)

        _tip(self.ignore, "Ignore duration（基线尖峰抑制）\n"
                          "离开基线短于该时长的偏离不注册为事件（滤毛刺）。\n"
                          "调大：更狠地滤短毛刺；调小：保留更短的偏离。")
        _tip(self.pre, "pre_event（开孔电流参考窗）\n"
                        "事件前取多长一段作为开孔电流参考。\n"
                        "一般不用改；基线漂移明显时可略调。")
        _tip(self.contrib, "Level contribution（电平跟踪权重）\n"
                            "电平流式更新的步长比例。\n"
                            "调大：电平跟随快、对噪声敏感；调小：更稳但滞后。")
        _tip(self.lowpass, "低通滤波\n"
                            "0=关。非零时先做零相位低通再检测。\n"
                            "噪声大时可开；会加宽事件前后沿。")
        _tip(self.min_toff, "最短 toff（dwell 过滤，仅导出）\n"
                             "dwell 短于该值的事件不进保留表（记入 excluded）。\n"
                             "短肽事件（毫秒级）需调小，如 2 ms。")
        _tip(self.plateau, "事件平台占比下限（毛刺/闪烁门控）\n"
                            "事件体驻留单一电平（最近整数电平 ±0.5 步）的样本占比低于此值\n"
                            "判为毛刺剔除。0=关（默认，不改动任何文件）。\n"
                            "开：TRP 这类密集毛刺文件可设 0.85~0.95；\n"
                            "注意会同时剔除多电平/混合样文件（T3、DQ混合样等）的真事件。")
        _tip(self.dr, "Io 漂移容差\n"
                       "逐事件开孔电流 |Io−参考| 超过该值时沿用前一事件 Io。\n"
                       "pA；一般不用改。")
        _tip(self.anom, "异常检测\n"
                         "开：标记反压/炸膜/膜抖/慢漂移区间并剔除其中事件（记入 drop_reason）。")
        _tip(self.drift_en, "慢漂移检测\n"
                             "开：自动标记『缓慢、不可逆、且伴随高散布』的开孔电平漂移区间\n"
                             "（如 TRP 尾部基线抬升 + 炸膜），并剔除区间内事件。\n"
                             "稳定的孔态阶跃与可恢复的瞬态不会误报。")
        _tip(self.drift_frac, "漂移位移阈值\n"
                               "块中值偏离记录头锚点 ≥ 此比例 ×|锚点| 才算位移。\n"
                               "调大：更保守（只标明显漂移）；调小：更灵敏。")
        _tip(self.drift_iqr, "漂移不稳定阈值\n"
                              "区间 IQR ÷ 记录头 IQR ≥ 此倍数才算『不稳定』。\n"
                              "与位移阈值同时满足才判漂移（防止把平稳的孔态变化当漂移）。")
        _tip(self.lab, "Label：导出表 Label 列的值，留空用文件名。")
        _tip(self.l0_en, "勾选后跳过自动基线估计，用右侧值作 Level0。")
        _tip(self.l1_en, "勾选后跳过自动事件电平估计，用右侧值作 Level1。")
        _tip(self.polarity, "事件极性（搜索方向）\n"
                             "自动：按电平直方图推断（默认，与现状一致）。\n"
                             "双向：允许基线两侧的阻孔，并自动多电平（探测器按 ±8 步\n"
                             "电平网格判定）——ARNKRS 这类『基线上下波动』的肽信号\n"
                             "需要它才能检出深/向上阻孔。\n"
                             "注意：双向对部分文件会过检（噪声侧被当成事件），\n"
                             "建议逐文件确认后再开。")

        box = QGroupBox("参数")
        form = QFormLayout(box)
        form.addRow("Ignore duration", self.ignore)
        form.addRow("pre_event", self.pre)
        form.addRow("Level contribution", self.contrib)
        form.addRow("低通滤波 (0=关)", self.lowpass)
        form.addRow("最短 toff (ms)", self.min_toff)
        form.addRow("事件平台占比 (0=关)", self.plateau)
        form.addRow("Io 漂移容差", self.dr)
        form.addRow("", self.anom)
        form.addRow("", self.drift_en)
        form.addRow("漂移位移阈值", self.drift_frac)
        form.addRow("漂移不稳定阈值", self.drift_iqr)
        form.addRow("Label", self.lab)
        form.addRow(self.l0_en, self.l0)
        form.addRow(self.l1_en, self.l1)
        form.addRow("事件极性", self.polarity)

        self.run = QPushButton("重跑检测")
        self.save = QPushButton("存参数")
        self.load = QPushButton("读参数")
        self.run.clicked.connect(self._run)
        self.save.clicked.connect(self._save)
        self.load.clicked.connect(self._load)

        btns = QHBoxLayout()
        btns.addWidget(self.run)
        btns.addWidget(self.save)
        btns.addWidget(self.load)

        lay = QVBoxLayout(self)
        lay.addWidget(box)
        lay.addLayout(btns)
        lay.addStretch(1)

    def build_config(self) -> PipelineConfig:
        return PipelineConfig(
            filter_lowpass_hz=self.lowpass.value() or None,
            level0=self.l0.value() if self.l0_en.isChecked() else None,
            level1=self.l1.value() if self.l1_en.isChecked() else None,
            polarity=self.polarity.currentData(),
            ignore_duration_ms=self.ignore.value(),
            level_contribution=self.contrib.value(),
            min_toff_ms=self.min_toff.value(),
            event_plateau_min_frac=self.plateau.value(),
            anomaly_enabled=self.anom.isChecked(),
            refined_drift_enabled=self.drift_en.isChecked(),
            refined_drift_min_frac=self.drift_frac.value(),
            refined_drift_iqr_ratio=self.drift_iqr.value(),
            pre_event_ms=self.pre.value(),
            dr_pA=self.dr.value(),
            label=self.lab.text(),
        )

    def load_config(self, cfg: PipelineConfig) -> None:
        self.ignore.setValue(cfg.ignore_duration_ms)
        self.pre.setValue(cfg.pre_event_ms)
        self.contrib.setValue(cfg.level_contribution)
        self.lowpass.setValue(cfg.filter_lowpass_hz or 0.0)
        self.min_toff.setValue(cfg.min_toff_ms)
        self.plateau.setValue(cfg.event_plateau_min_frac)
        self.dr.setValue(cfg.dr_pA)
        self.anom.setChecked(cfg.anomaly_enabled)
        self.drift_en.setChecked(cfg.refined_drift_enabled)
        self.drift_frac.setValue(cfg.refined_drift_min_frac)
        self.drift_iqr.setValue(cfg.refined_drift_iqr_ratio)
        self.lab.setText(cfg.label)
        self.l0_en.setChecked(cfg.level0 is not None)
        self.l1_en.setChecked(cfg.level1 is not None)
        if cfg.level0 is not None:
            self.l0.setValue(cfg.level0)
        if cfg.level1 is not None:
            self.l1.setValue(cfg.level1)
        idx = self.polarity.findData(cfg.polarity)
        self.polarity.setCurrentIndex(idx if idx >= 0 else 0)

    def _run(self) -> None:
        from .controller import controller

        if controller.rec is None:
            bus.status.emit("请先打开一个 .abf 文件")
            return
        controller.set_config(self.build_config())
        controller.rerun()

    def _save(self) -> None:
        from .controller import controller

        path, _ = QFileDialog.getSaveFileName(self, "保存参数", "params.json", "JSON (*.json)")
        if path:
            controller.set_config(self.build_config())
            controller.cfg.save(path)
            bus.status.emit(f"参数已保存: {path}")

    def _load(self) -> None:
        from .controller import controller

        path, _ = QFileDialog.getOpenFileName(self, "读取参数", "", "JSON (*.json)")
        if path:
            cfg = PipelineConfig.load(Path(path))
            controller.set_config(cfg)
            self.load_config(cfg)
            bus.status.emit(f"参数已读取: {path}")
