# 贡献指南

本仓库为课题组内部私有仓库。**`main` 不接受任何直接推送**——所有改动一律经分支 + Pull Request，由维护者审查后合并。以下流程对所有人生效；协作者请先读「协作方式」。

## 协作方式（协作者必读）

协作者账号对本仓库是**只读（read）权限**，无法直接推送分支或改动 `main`。请按 fork 流程贡献：

1. **Fork** 本仓库到你自己的账号（私有 fork，只有你能看到）。
2. 在 fork 上建分支、提交：

   ```bash
   git clone https://github.com/<你的用户名>/Self-Driving-Huang-Lab.git
   cd Self-Driving-Huang-Lab
   git remote add upstream https://github.com/1moltry/Self-Driving-Huang-Lab.git
   git checkout -b feat/xxx
   # ... 改动 ...
   git push origin feat/xxx
   ```

3. 向本仓库的 `main` 开 **Pull Request**（PR 模板会自动带出检查清单）。
4. 维护者审查；若需修改，你 push 到同一分支，PR 会自动更新。
5. 维护者合并（squash）后，源分支删除。

> 在 fork 上工作期间若 `main` 已前进，用 `git fetch upstream && git rebase upstream/main` 同步后再 push 回自己的分支。

> 直接把文件传到网页（GitHub 的 "Add files via upload"）会绕过分支与 PR，也不会经过 CI——请不要这样做，改动请走上面的流程。

## 环境准备

```bash
git clone https://github.com/1moltry/Self-Driving-Huang-Lab.git
cd Self-Driving-Huang-Lab
pip install -e ".[dev]"
```

实验数据 `.abf` 不入库，按 [`data/README.md`](data/README.md) 从共享盘拷贝到 `abf数据案例/`。

## 分支

`main` 禁止直接推送（协作者为只读权限，见「协作方式」）。每个改动开一条短生命周期分支，用完即删：

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

## 评审与合并

- 由维护者审查并合并；CI 必须绿。
- 用 **squash merge**，保持 `main` 线性历史（仓库设置已禁用 merge 与 rebase 两种合并方式）。
- 合并后源分支会自动删除。

## 版本号与发布

**版本号由维护者统一分配，协作者不自行打 tag 或建 Release。**

- 合并进 `main` 只代表代码进入主线；是否发版、发哪个版本号，由维护者在合并后决定。
- 发布方式：注解标签 `vN`（`git tag -a`）+ GitHub Release，说明该版内容与已知问题。
- 当前版本线：

  | 标签 | 提交 | 内容 |
  |------|------|------|
  | `v1` | `42118fa` | 命令行管线 + PyQt5 交互复核界面 |
  | `v2` | `37b0356` | 整合版：先验增强引擎 + 统一启动器 |

- 回退到某个版本：`git checkout v1`。

> **关于强制保护**：本仓库是 Free 套餐的私有仓库，GitHub 不允许启用分支保护或
> ruleset（该功能要求 Pro 套餐，API 返回 `403 Upgrade to GitHub Pro`）。
>
> 因此本项目用**权限**代替服务端保护：协作者账号为 **read（只读）**，从机制上无法
> 直推 `main`，只能走 fork + PR；维护者账号仍可直接推送（用于文档、发版等）。
> CI 在 PR 与 `main` 上都会运行。
>
> 若日后升级到 Pro，应改为开启 `main` 的分支保护（要求 CI 检查通过 + 禁止强推），
> 届时本条说明相应调整。

## 不要提交的东西

`.gitignore` 已覆盖，但请知悉**为什么**这些不入库：

| 路径 | 原因 |
|------|------|
| `abf数据案例/` | 实验数据，单文件可达 140 MB（超出 GitHub 100 MB 限制） |
| `pCLAMP11.2/` | 商业软件，仅作对照查看器 |
| `_tmp/` | Clampfit 帮助文档提取文本，版权资料 |
| `output/` | 运行产物 |
| `.claude/settings.local.json` | 本机配置 |
