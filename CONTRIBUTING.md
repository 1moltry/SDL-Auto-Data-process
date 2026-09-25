# 贡献指南

本仓库由 **Yize Liu（1moltry）** 与 **Junjie Wen** 共同开发，由 **Huang Lab** 提供资金支持。以 MIT 协议开源。

改动经 Pull Request 提交，由维护者审查后合并。协作机制（权限模型、版本号分配）见 [`DEVLOG.md`](DEVLOG.md)。

## 环境准备

```bash
git clone https://github.com/1moltry/SDL-Auto-Data-process.git
cd SDL-Auto-Data-process
pip install -e ".[dev]"
```

实验数据 `.abf` 不入库，按 [`data/README.md`](data/README.md) 从共享盘拷贝到 `abf数据案例/`。

## 分支

每个改动开一条短生命周期分支，用完即删：

| 前缀 | 用途 |
|------|------|
| `feat/` | 新功能 |
| `fix/` | 修 bug |
| `docs/` | 文档 |
| `refactor/` | 重构（不改变行为） |
| `chore/` | 构建 / CI / 依赖 |

例：`fix/anomaly-drift-boundary`、`feat/multi-level-detection`

## 提交信息

遵循 Conventional Commits：

```
<type>: <简短说明>
```

`type` 取 `feat` / `fix` / `docs` / `refactor` / `test` / `chore`。

正文写**为什么**这么改——「改了什么」看 diff 就够了，写进提交信息只是重复。

```
fix: 漂移判据漏掉只位移不增散的开孔电平抬升

TRP 尾部基线抬升伴随 IQR 增大才被判出，但个别记录只有位移、
散布正常。改为位移与不稳定双键取或后，TRP 命中、DQARNKR 良性
漂移仍不误报。
```

## 提交前

```bash
python -m pytest tests/ -q      # 必须全绿
```

算法改动**必须**配套 `tests/` 回归。本项目的做法是用合成信号构造已知真值（`tests/synth.py`），而不是只看实样跑出来像不像——实样没有真值，肉眼判断无法回归。

## PR 检查清单

- [ ] `pytest` 全绿
- [ ] 算法变更配套 `tests/` 回归（合成信号解析真值）
- [ ] 接口 / 参数 / 用法变化已同步 `README.md`
- [ ] 已在 `DEVLOG.md` 追加一条（变更 / 测试 / 下一步）
- [ ] `git status` 干净——没有误纳实验数据、商业软件或本机配置

PR 模板会自动带出这份清单。

## 不要提交的东西

`.gitignore` 已覆盖，但请知悉**为什么**这些不入库：

| 路径 | 原因 |
|------|------|
| `abf数据案例/` | 实验数据，单文件可达 140 MB（超出 GitHub 100 MB 限制） |
| `pCLAMP11.2/` | 商业软件，仅作对照查看器 |
| `_tmp/` | 参考文档提取文本，版权资料 |
| `output/` | 运行产物 |
| `.claude/settings.local.json` | 本机配置 |
