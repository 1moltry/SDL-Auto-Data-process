# 数据存放说明

实验数据 `.abf` **不入库**——单文件可达 140 MB（超出 GitHub 100 MB 硬限制），且属实验产物，不适合放进 git。

## 获取

从实验室共享盘 / Lab 服务器拷贝到仓库根目录下的 `abf数据案例/`：

```
Self-Driving-Huang-Lab/
└── abf数据案例/                ← 本地目录，已被 .gitignore 忽略
    ├── abf数据案例/             6 个常规样例
    └── abf数据案例2/
        └── abf数据案例2/
            ├── tPAL/            4 个（多电压 protocol 数据）
            ├── 生物胺/          3 个
            ├── 甲状腺激素/      4 个
            └── 肽/              9 个
```

代码与文档中的示例路径都基于 `abf数据案例/` 这个目录名，放好即可直接运行：

```bash
python -m nanopore run "abf数据案例/abf数据案例" -o output
python -m nanopore run "abf数据案例/abf数据案例2" -o output   # 递归子目录
```

## 常规样例的场景对照

来自样例目录自带的 `说明.txt`，用作验收参照：

| 文件 | 场景 |
|------|------|
| Ala.abf | 中间一段阻孔，人为切反向电压后恢复 |
| Asp.abf | 多次阻孔，末端炸膜 |
| Gln.abf | 膜抖动 |
| His.abf | 两种信号 |
| ac-Thr+Thr mixture.abf | 苏氨酸+乙酰苏氨酸混合，两种信号 |
| pore2 ARNKRS 2Mm_0000.abf | 肽信号，基线上下波动 |

## 其它本地参考数据

| 路径 | 说明 |
|------|------|
| `pCLAMP11.2/` | 商业软件，仅作对照查看器与文档来源，不入库。其 `Sample Data/` 有约 35 个演示 `.abf` |
| `_tmp/` | Clampfit 帮助文档与用户指南的提取文本，本地查阅用，不入库 |

`tests/test_io.py` 里的 pCLAMP 样例测试在 `pCLAMP11.2/` 存在时自动启用，否则 skip——所以没有这份数据也能跑通全部测试。
