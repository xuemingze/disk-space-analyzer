# v1.2.0 · 空间全景深度分析与冗余文件扫描

> 本次发布聚焦**可运维性**：让程序崩溃时不再"静默消失"，让测试命令真实可用，让公开发布物可一键复现。

---

## 📥 下载

| 文件 | 说明 |
| --- | --- |
| **`DiskSpaceAnalyzer-1.2.0-win64-portable.zip`** | **推荐**。目录版便携包，解压后双击 `DiskSpaceAnalyzer.exe` 即可运行，**无需安装 Python**。 |
| `DiskSpaceAnalyzer-1.2.0-win64.exe` | 单文件版，双击即用；首次启动稍慢（自解压属正常现象）。 |

> 系统要求：Windows 10 / 11 64 位。
> 程序运行日志与错误日志写入可执行文件同级的 `logs/` 目录。

---

## ✨ 本次更新

### 1. 全局错误拦截 + 异常独立落盘（重要）

此前程序在窗口模式下崩溃时**拿不到任何堆栈**——`logger` 只向 stdout 输出，而打包为 `--noconsole` 后 stdout 为 `None`，日志被静默吞掉。

现在：

- 新增**主线程 / 子线程 / 解释器退出**三处全局异常拦截；
- 未捕获异常的**完整堆栈**静默写入 `logs/error.log`，
  并额外生成独立崩溃快照 `logs/crash-<时间戳>.log`；
- Qt 自身警告/致命消息接入日志系统（`qInstallMessageHandler`）；
- `warnings` 模块告警一并持久化；
- 启动阶段致命错误会尽力弹窗提示，并告知日志目录；
- 日志目录自动回退：环境变量 `DISK_ANALYZER_LOG_DIR` → exe 同级 `logs/` → `~/.disk_space_analyzer/logs`。

### 2. 测试套件修复：`pytest tests/` 曾完全不可用

`tests/test_tree_freeze.py` 在**导入期**执行 `sys.exit(0)`，导致 pytest 收集阶段直接 `INTERNALERROR` 崩溃，**0 个用例被执行**（而 README 一直宣称该命令可用）。

现在该文件已改造为标准 pytest 用例，同时保留两种模式：

- 常规：`pytest tests/`（小规模，快速回归）
- 压测：`python tests/test_tree_freeze.py` 或 `set TREE_FREEZE_SCALE=large`（5 万节点）

全量 **17 项测试通过**。

### 3. 可复现的一键构建链路

```bash
python build_release.py            # 目录版 + 便携 zip
python build_release.py --onefile  # 额外构建单文件 exe
```

- 构建全过程写入 `logs/build_release.log`，失败必留完整堆栈到 `logs/build_release_error.log`；
- 版本号从 `main.py` 的 `APP_VERSION` 自动读取，制品名与代码版本强制一致；
- 精确剔除 PyInstaller 过度收集的重型无关依赖（实测会拖入 torch / onnxruntime / pandas / scipy 等 GB 级包）。

### 4. 应用图标与仓库治理

- 新增程序图标 `assets/app.ico`（多尺寸，磁盘占用环形图主题）；
- 移除 **33 个开发期临时脚本**（`patch_*.py` 会直接改写源码、`fix_*.py`、`benchmark_*.py`、根级 `test_*.py`，以及未被引用的 `model.py`）；
- 新增 [docs/使用说明.md](https://github.com/xuemingze/disk-space-analyzer/blob/main/docs/使用说明.md)：清理 C 盘的正确姿势与风险提示。

---

## ⚠️ 升级提示

- 配置与归档清单存放于 `~/.disk_space_analyzer/`，本版本**不改变**其结构，可直接覆盖升级。
- 若你的自动化流程依赖根目录下的 `patch_*.py` / `benchmark_*.py` 等脚本，请从 git 历史中取回（`git show v1.1.0:patch_org7.py`）。

---

## 📄 完整提交范围

自 `v1.1.0` 以来的 9 个提交（AI 目录树智能规划、全局分类管理器、手动分类覆盖、GUI 卡死专项修复等）
**全部包含**在本版本中，另叠加上述 4 项发布工程改进。

**Full Changelog**: https://github.com/xuemingze/disk-space-analyzer/compare/v1.1.0...v1.2.0
