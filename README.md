# SDL 纳米孔数据自动化分析管线

全自动处理纳米孔传感 .abf 数据：事件分割、特征提取、异常检测、分析可视化——替代原有「Clampfit 手动找事件 → MATLAB 提特征 → Origin 作图」的人工流程。

## 背景

实验室用膜片钳固定纳米孔并实时监测分析物过孔时的电流信号。原流程是人工设基线/事件电平来找事件，本管线**自动估计电平并分割事件**，pCLAMP 软件保留作对照查看器与文档来源。

## 安装

需要 Python ≥ 3.11（开发环境 3.13）。

```bash
# 可编辑安装（含开发依赖 pytest）
pip install -e ".[dev]"
```

依赖由 `pyproject.toml` 声明：numpy / scipy / pandas / matplotlib / openpyxl / pyabf / PyQt5 / pyqtgraph。

## 数据准备

实验数据 `.abf` **不入库**（体积大、属实验产物）。从实验室共享盘拷贝到本地 `abf数据案例/` 即可——代码与文档中的示例路径都基于该目录名，同事克隆后只需放好数据就能跑。目录约定与各样例对应的异常场景见 `data/README.md`。

## 快速开始

```bash
# 批处理整个目录（默认输出到 ./output）
python -m nanopore run "abf数据案例/abf数据案例"

# 指定输出目录与参数文件
python -m nanopore run <目录> -o <输出目录> --config params.json

# 单文件处理
python -m nanopore run "abf数据案例/abf数据案例/Ala.abf"

# 手动指定电平（双态孔/双物种数据推荐；不给则自动估计）
python -m nanopore run His.abf --level0 185 --level1 116

# 双向/多电平检测（肽信号基线上下波动，如 ARNKRS）
python -m nanopore run "pore2 ARNKRS 2Mm_0000.abf" --polarity both

# 导出当前参数为 JSON（作为后续 --config 模板）
python -m nanopore run <目录> --save-config params.json
```

## 图形界面（GUI，v2）

交互式桌面程序（PyQt5 + pyqtgraph），波形 + 事件表 + 异常/参数面板布局：

**双击启动（推荐）**：双击桌面快捷方式 `SDL纳米孔分析`（或项目根目录的 `启动界面.bat`）即可打开 GUI，无需命令行。启动器用 Anaconda 的 `pythonw` 无控制台窗口运行；若双击后无反应，改双击 `启动界面-调试.bat`，它会保留控制台显示报错。

也可以用命令行启动：

```bash
# 启动 GUI（不带参数，用工具栏「打开」选择文件）
python -m nanopore gui

# 启动并直接载入一个文件
python -m nanopore gui "abf数据案例/abf数据案例/Ala.abf"
```

功能：波形浏览（滚轮缩放/拖动平移/自动缩放，30M 样本自适应降采样）、**蓝色理想化事件方波线**叠加全信号（基线抖动可见）、硬异常淡色带、**统计面板**（事件数量-dwell time 直方图，横轴线性/log10 可切换，x 轴时间单位随文件在 μs/ms/s/min 间自适应并可手动指定；SD-|ΔI| 散点图，统一单色参考云，点击散点跳转原始事件波形）、事件结果表（按 State 过滤）、**异常/剔除面板**（列出异常区间与每区剔除的事件数，点击跳转波形）、**Cursor 选区**（可拖拽区域 + 对区间重跑，用独立电平重析该子区间）、参数面板（改参数重跑，存/读 JSON 协议）、**批量处理**（工具栏「批量处理…」：添加多个 .abf 文件或文件夹递归搜集，选输出目录后后台线程跑批，显示逐文件进度与汇总）。图形统一白底、只用蓝色突出事件，无其它强调元素。

## 双态孔与多物种数据说明

部分样例（Ala/Asp/Gln）存在慢速孔态切换（如 110↔180 pA 间分钟级驻留），切换边界以 `baseline_step` 异常标记（不判无效）。自动模式取**离基线最近的显著电平**为事件电平；若需分析另一态或另一物种，用 `--level0/--level1` 手动指定（如 His：`--level0 185 --level1 116` 得到深阻断物种事件）。多电平同时检测排在 v2。

## 用 pCLAMP 自带样例做测试

pCLAMP 11.2 安装在 `pCLAMP11.2/`（**该目录不入库**，本地保留作对照查看器），其 `Sample Data/` 自带约 35 个 `.abf` 演示数据（含干净单通道 `kchann.abf`、`burst.abf` 等）。pyabf 不支持其中 **float 格式 ABF1**（"Support for float data is not implemented"）；`io.read_abf` 先嗅探文件签名，float-ABF1 走内建读取器（含多通道/真实单位/损坏校验），其余交 pyabf，可直接处理全部样例：

```bash
python -m nanopore run "pCLAMP11.2/Sample Data" -o output_pclamp
```

回归测试 `tests/test_io.py` 在 pCLAMP 样例存在时自动启用（否则 skip），验证 float-ABF1 读取与 kchann 事件检测。注意：多数 Sample Data 是电压钳/宏演示，不是单通道电流数据，检测到的事件数仅供参考；只有事件类样例（kchann/singles/burst/4level）有分析意义。

## 输出

每个输入文件生成：

| 文件 | 内容 |
|------|------|
| `<名>_events.xlsx` | 事件特征表（events sheet，列名遵循课题组既定特征表规范）+ **excluded sheet**（被剔除事件及其 `drop_reason`，如 `membrane_rupture`/`baseline_drift`/`jitter`/`toff<min`）+ 异常区间表（anomalies sheet，含细粒度 kind：reverse_voltage/membrane_rupture/baseline_drift/membrane_jitter_mild·severe/blockage_spontaneous·manual） |
| `<名>_overview.png` | 全程轨迹（块均值）+ 蓝色理想化事件线 + 硬异常淡色带（红=breakdown/炸膜 橙=blockage 紫=jitter 蓝=反压/人工恢复 棕=baseline_drift；baseline_step 仅在异常表，不画） |
| `<名>_scatter.png` | 2×2 散点：dwell/时间 × ΔI、dwell/时间 × Io。**ΔI 按正负分色**（ΔI<0 蓝、ΔI≥0 红），纵轴保持线性并**保留全部事件**（含远离主群的真实电平）；toff 跨度超一个数量级时横轴转对数 |
| `<名>_hist.png` | 深度直方图 + log10 时长直方图 |

批次级：

| 文件 | 内容 |
|------|------|
| `summary.xlsx` | 每文件事件数、brief 数、有效率、level0、极性、噪声 σ、异常计数、错误、耗时 |
| `dataset_all.csv` | 全部文件的保留事件纵向拼接（每行一个事件），供 MATLAB / 机器学习使用，含 `source_file` 列回溯来源 |

### 导入 MATLAB / 机器学习

`dataset_all.csv` 即为此准备（UTF-8 BOM，`readtable` 直接可读）：

```matlab
T = readtable('output/dataset_all.csv');
X = T{:, {'mean','rel_mean','std','skew','kurt','toff','MAD','CV', ...
          'q1','q2','q3','iqr','outlier_ratio'}};
y = categorical(T.Label);          % 分类目标（物种/样本）
```

该表对列名做了两处规范化（**仅此表**；`_events.xlsx` 保持课题组特征表规范列名不变）：

- `%mean` → **`rel_mean`**：`%` 不是合法 MATLAB 标识符，`readtable` 会把它静默改成 `x_mean`，按名取列会取错；
- `t1`/`t2` → **`t1_s`/`t2_s`**：本管线为**秒**，课题组特征表规范为**毫秒**，改名以免无声差 1000 倍。

做特征时应排除 `t1_s`/`t2_s`（时间戳，会造成时间泄漏）与 `I0`（逐记录常数）。

## 参数说明

| 参数 | 含义 | 默认 |
|------|------|------|
| `ignore_duration_ms` | 基线电平上下文：偏离基线短于此时长的尖峰抑制（不注册为事件） | 2 ms |
| `ignore_event_duration_ms` | 事件电平上下文：同电平事件之间基线间隙短于此时长的合并为一个事件（长阻孔内的噪声槽不切碎） | 50 ms |
| `level_contribution` | 电平跟踪的指数更新权重 | 0.10 |
| `dwell_min_frac` | 尖峰抑制：事件 body 需 ≥30% 样本落在某电平邻域 | 0.30 |
| `event_plateau_min_frac` | **事件稳定性门控**（毛刺/闪烁）：事件体驻留**单一**电平（最近整数电平 ±0.5 步）的样本占比低于此值即剔除。快闪烁这一占比约 0.5、真阻孔约 1.0。**默认 0=关**（单一标量无法既剔毛刺又保住多电平文件；TRP 这类密集毛刺文件手动设 0.85~0.95） | 0 |
| `--level0/--level1` | 人工指定电平（不给则算法自动估计） | 自动 |
| `--polarity` / `polarity` | **事件极性（搜索方向）**：`auto`=按电平直方图推断（默认）；`up`/`down`=仅向上/向下；`both`=双向（基线两侧阻孔都算，并自动多电平）。ARNKRS 这类"基线上下波动"的肽信号需 `both` 才能检出深阻孔。注意 `both` 对部分文件会过检（噪声侧被当事件），建议逐文件确认 | auto |
| 电平中点阈值 | 50% crossing（两电平中点） | — |
| 短事件判定（brief） | < 4τ（滤波时间常数），State 列标 B | 自动 |
| `pre_event_ms` | 特征提取的开孔电流窗口（与特征表规范一致） | 25 ms |
| `min_toff_ms` | 导出过滤：保留 toff > 阈值的事件 | 10 ms |
| `hold_voltage_mV` | 电压 protocol 的保持电平；不给则取电压轨迹中位数 | 自动 |
| `refined_drift_enabled` | **慢漂移/不稳定区间检测**（新 kind `baseline_drift`）：缓慢、**不可逆**、且伴随高散布的开孔电平位移（如 TRP 尾部基线抬升 + 炸膜）。需位移**且**不稳定两个键同时满足——稳定的孔态阶跃、可恢复的瞬态、以及"位移但仍在出正常事件"的良性漂移都不会误报 | 开 |
| `refined_drift_min_frac` | 位移键：块中值偏离记录头锚点 ≥ 此比例 ×\|锚点\| | 0.05 |
| `refined_drift_iqr_ratio` | 不稳定键：区间 IQR ÷ 记录头 IQR ≥ 此倍数 | 3.0 |
| `refined_drift_block_s` / `_min_s` | 块长（s）/ 漂移段最短时长（s） | 15 / 20 |

## 电压 protocol 与异常区间

电压信息有两个来源，按优先级使用：

1. **电压 ADC 通道**（`IN 1` 等，与电流等长）——多数 2 通道记录（Ala/His/T3/Asp…）
2. **命令电压波形**（ABF 头里的 protocol/epoch 表，pyabf `sweepC`）——tPAL 这类只录电流、但带电压 protocol 的文件也能取到

判定规则：**保持电平 = 电压轨迹的中位数**（主导电平即传感段），任何持续偏离保持电平的区段（反压、tPAL 的排出/静息段、0 mV 段）都记为异常区间 `reverse_voltage`，落在其中的事件被剔除（`drop_reason` 可查），切换处带一段瞬态保护窗。因此不预设"反压=负电压"，正脉冲、0 mV 静息段同样会被识别。

### 慢漂移/不稳定区间（`baseline_drift`）

与电压无关的第二类结构性异常。判据取自动态 I0 基线的**逐 1 s 窗中值**（含非安静窗——安静窗链会跟随漂移而看不到它），聚合成 15 s 块中值，标注同时满足以下四条的**末端**区间：

1. **位移**：块中值偏离记录头锚点 ≥ `refined_drift_min_frac × |锚点|`（默认 5%）
2. **不稳定**：区间 IQR ÷ 记录头 IQR ≥ `refined_drift_iqr_ratio`（默认 3.0）
3. **渐进**：块间最大跳变 ≤ `max(6 pA, 5% × |锚点|)`——拒绝 110↔180 那样的孔态阶跃
4. **持续不可逆**：长度 ≥ `refined_drift_min_s`，且不回到位移带内——拒绝可恢复的瞬态

**位移与不稳定必须同时满足**：良性慢漂移（有位移、仍在出正常事件、散布正常）不判；密集事件团（散布大、但基线不位移）也不判。区间内事件剔除；不稳定度达到炸膜级别（IQR ≥ 4× 记录头）时，尾部再嵌套标一个 `membrane_rupture`，异常面板可区分"漂移"与"漂移导致的炸膜"。

## 项目结构

```
nanopore/          Python 包
├── io.py          读取：签名嗅探分发 + 内建 float-ABF1 读取器 + pyabf；双通道样例自动读入电压通道
├── preprocess.py  可选低通滤波
├── baseline.py    自动 Level0/Level1 估计
├── baseline_i0.py 动态 I0(t) 开孔电流基线（逐事件 Io 免疫阻孔漂移）
├── detect.py      事件检测（电平/阈值法，逐事件电平跟踪）
├── anomaly.py     异常检测（宏块包络 + 细粒度：电压 protocol 段/分级膜抖/炸膜）
├── features.py    特征提取（列名遵循课题组既定特征表规范）
├── roi.py         Cursor 局部分析（子区间独立电平重析）
├── analysis.py    可视化与批次报告
├── cli.py         命令行入口（run / gui）
├── config.py      参数管理
└── gui/           交互式桌面 GUI（PyQt5 + pyqtgraph）
    ├── main_window.py  主窗口 + 工具栏（打开/重跑/全览/批量处理）
    ├── waveview.py     波形 + 事件理想化线 + Cursor 选区
    ├── scatterview.py  统计面板（toff 直方图 + SD-|ΔI| 散点，统一单色）
    ├── units.py        时间轴单位（μs/ms/s/min 自适应 + 手动选择，无 SI 前缀）
    ├── eventtable.py   事件结果表
    ├── anomalyview.py  异常/剔除面板
    └── batchdialog.py  批量处理对话框（多文件/文件夹 + 输出目录 + 进度）
tests/             合成信号回归测试
.github/           CI 工作流 + PR / issue 模板
pyproject.toml     依赖声明、打包与 console 入口（`nanopore`）
CONTRIBUTING.md    协作流程：分支命名 / 提交规范 / PR 检查清单
data/README.md     数据获取方式与目录约定
启动界面.bat        双击启动 GUI（桌面快捷方式 `SDL纳米孔分析` 指向它）
启动界面-调试.bat   同款启动但保留控制台，用于排查启动报错
```

以下为**本地目录，不入库**（见 `.gitignore`）：`abf数据案例/`（实验数据，见 `data/README.md`）、`pCLAMP11.2/`（商业软件，对照查看器）、`_tmp/`（Clampfit 帮助提取文本，本地查阅）、`output/`（默认输出目录）。

## 开发约定

- 每次开发会话在 `DEVLOG.md` 追加一条记录（变更、测试状态、下一步）。
- 算法实现以实样数据 + 合成真值测试为准；本地 `_tmp/` 下的对照资料（含 Clampfit 帮助文本，**不入库**）可查阅参考，但不作为依据。
- 运行 `pytest` 全绿后再交付；CI 在 ubuntu 与 windows 上跑同一套测试。
- 分支、提交与 PR 流程见 `CONTRIBUTING.md`。

## 路线图

- **v1（完成）**：基础任务全项——双向事件分割、异常检测剔除、逐事件开孔电流漂移补偿、17 特征、散点/直方图、CLI 批处理。
- **v2**：交互式 GUI（已启动，见上）、多电流平台/混合信号、近基线 Template matching（Clements & Bekkers 1997）、tPAL 多电压 protocol。
- **电压通道与细粒度异常（完成）**：io 电压通道读取 → 动态 I0(t) 开孔电流基线，逐事件 Io 免疫阻孔漂移（`dynamic_i0_enabled` 默认开）→ 异常精筛：反压恢复（spontaneous/manual）区分 + 分级膜抖 + 炸膜状态机（`refined_anomaly_enabled` 默认开）→ Cursor 局部分析（GUI Cursor 选区）。测试先行（tests/ 合成真值）。
- **P1 剔除可追溯 + 参数接通（完成）**：每个被剔除事件带 `drop_reason`（xlsx excluded sheet / GUI 异常面板可查）；`min_toff_ms` 可调（GUI/CLI）。
- **P2 Cursor 局部分析（完成）**：GUI Cursor 选区 + 对区间重跑（子区间独立电平）。
- **P3 判据实证修正（完成）**：炸膜电平结构门控（密集事件团不再误判）、宏块 jitter 门控、动态基线锚定到开孔电平（`anchor_level`）。
