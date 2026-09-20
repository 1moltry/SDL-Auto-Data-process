# CLAUDE.md — SDL 纳米孔自动化管线

## 项目约定

1. **维护 DEVLOG**：用简洁的语言维护DEVLOG，不要让其繁杂冗长。每次开发会话结束前在 `DEVLOG.md` 追加一条（变更 / 测试 / 下一步）。README 在接口或用法变化时同步更新。
2. **参照 Clampfit 语义**：算法实现优先查阅 `_tmp/chm_clampfit/`（帮助文档提取）与 `_tmp/pclamp_ch10_single_channel.txt`、`_tmp/pclamp_amplitude_algorithm.txt`（用户指南提取）。遇到"应该怎么算"的问题，先看 Clampfit 怎么做。**`_tmp/` 仅在本地，不入库。**
3. **特征对齐**：特征定义与列名遵循课题组既定特征表规范（见 README「输出」一节），Label 列 = 文件标签。
4. **不修改 pCLAMP11.2/ 目录**：商业软件，仅作对照查看器与文档来源，**不入库**。
5. **测试先行**：算法变更配套 tests/ 回归（合成信号解析真值），交付前 `pytest` 全绿。
6. **视觉调用规则**：需要模型看图（截图/PNG/PDF 视觉页）时，**先确认当前模型具备视觉能力**再上传图片；**单次最多上传并处理 3 张图片**（超出请分批）。若模型声明无视觉能力，跳过所有视觉依赖，用文字/结构信息代替，并请用户人工过目。
7. **协作流程**：分支命名 / 提交规范 / PR 检查清单见 `CONTRIBUTING.md`。实验数据、商业软件、反编译资料、本机配置一律不入库（见 `.gitignore`）。

## 常用命令

```bash
python -m pytest tests/ -q                                  # 全部测试
python -m nanopore run "abf数据案例/abf数据案例" -o output    # 批处理样例
    nanopore run "abf数据案例/abf数据案例" -o output              # 同上（console 入口；需 pip install -e . 且 Scripts 在 PATH）
```

## 样例数据异常场景（验收对照，来自样例数据目录的 说明.txt；数据不入库）

| 文件 | 场景 |
|------|------|
| Ala.abf | 中间一段阻孔，人为切反向电压后恢复 |
| Asp.abf | 多次阻孔，末端炸膜 |
| Gln.abf | 膜抖动 |
| His.abf | 两种信号 |
| ac-Thr+Thr mixture.abf | 苏氨酸+乙酰苏氨酸混合，两种信号 |
| pore2 ARNKRS 2Mm_0000.abf | 肽信号，基线上下波动 |
