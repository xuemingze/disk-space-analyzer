# 🚀 空间全景深度分析与 AI 智能文件治理系统 (Disk Space Panorama Analyzer)

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PySide6 / Qt6](https://img.shields.io/badge/GUI-PySide6%20%2F%20Qt6-brightgreen.svg)](https://pypi.org/project/PySide6/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows%2010%2B-blueviolet.svg)](https://www.microsoft.com/windows)
[![AI Orchestrated](https://img.shields.io/badge/AI-OpenAI%20%7C%20DeepSeek%20%7C%20MiniMax%20%7C%20Ollama-orange.svg)](https://github.com/xuemingze/disk-space-analyzer)
[![Test Suite: 116 Passed](https://img.shields.io/badge/Tests-116%20Passed%20(100%25)-brightgreen.svg)](./tests/)

---

## 📥 下载与使用

**➡️ [最新版本 Release (v1.7.0)](https://github.com/xuemingze/disk-space-analyzer/releases/latest)** · [历史版本](https://github.com/xuemingze/disk-space-analyzer/releases) · [使用说明与安全须知](./docs/使用说明.md)

| 文件 | 大小 | 适用场景 | 下载 |
| --- | ---: | --- | :---: |
| **`DiskSpaceAnalyzer-1.7.0-win64-portable.zip`** | ~80 MB | **推荐**。绿色便携包，解压到任意位置双击 `DiskSpaceAnalyzer.exe` 即可运行，**无需安装 Python**，秒级启动。 | [⬇️ 下载](https://github.com/xuemingze/disk-space-analyzer/releases/latest/download/DiskSpaceAnalyzer-1.7.0-win64-portable.zip) |
| `DiskSpaceAnalyzer-1.7.0-win64.exe` | ~80 MB | 单文件版，双击直接运行、无需手动解压；首次启动会有瞬时自解压过程。 | [⬇️ 下载](https://github.com/xuemingze/disk-space-analyzer/releases/latest/download/DiskSpaceAnalyzer-1.7.0-win64.exe) |
| 源码包（`.zip` / `.tar.gz`） | — | 源码运行：`pip install -r requirements.txt && python main.py` | [Releases 页面](https://github.com/xuemingze/disk-space-analyzer/releases/latest) |

> 🖥️ **系统要求**：Windows 10 / 11 64 位。预编译可执行文件内置完整运行环境。  
> ⚙️ **默认工作路径**：默认归档备份目录为 `D:\归档备份`，软件与文件迁移目录为 `D:\软件与文件迁移`（若无 D 盘则自动安全回退至系统用户主目录）。首次使用建议在 **系统配置 (Settings)** 中根据实际磁盘分区调整。  
> 📝 **全链路日志保全**：运行时日志、`error.log` 及未捕获异常崩溃快照自动持久化于 `logs/` 目录下，杜绝静默闪退。

---

> **专为 Windows 深度空间治理与生命周期治理打造的高性能桌面系统**：确立 **“AI 为核心编排器架构”** 与 **“GUI 永久一致性法则”** 两大根本原则，贯通 **“三大整理核心原则”**；集成了 **2~3 级分类拓扑树本地示范目录骨架捕捉**、**建议归档路径就地编辑与 <1 秒极速微契约 AI 审核自沉淀**、**双击列职责分流交互规范**、**全域同构级联联动**、**三阶段非阻塞异步扫描**、**自动化常驻守护（被占用安全防护）** 与 **三种重复文件治理模式**。

[English Documentation](./README.md) | [中文说明文档](./README_ZH.md)

---

## 📢 最新版本更新说明 (Changelog)

### 🔥 v1.7.0 重大特性（AI 核心编排不越权原则、资产>100诊断决策、规划路径就地编辑保全原路径、高对比度视觉）

- 🧠 **准则一深化：AI 为核心编排架构与用户决策权保全 (AI-First & Non-Overreach Contract)**：
  - **杜绝离线越权替代**：彻底纠正了大模型请求超时或失败时本地离线兜底直接越权篡夺 AI 编排主导权的架构缺陷，确立“AI 为核心、用户定夺、绝不越权”交互原则；
  - **独立资产 > 100 项架构诊断决策**：扫描识别出散落独立资产超过 100 项时，研判给出“80% 可能性为集合判断错误”诊断，暂停静默向 AI 倾泻碎片，唤起统一面向对象诊断卡片；
  - **全屏最大化明细工作台联动**：推荐选项【🔍 查看全局扫描资产明细 (推荐并最大化)】直接无感切换至全局资产明细并一键全屏最大化，引导用户就地右键「向上收拢转集合」，从根本上消解离散碎片；
  - **显式授权强制 AI 分析**：保留【⚡ 强制 AI 总结 / 强制 AI 整理】选项，由用户定夺是否忽略碎片风险立即执行 AI 智能全景分析，严禁后台未经授权私自调用大模型或静默兜底越权覆盖。
- 🧩 **面向对象统一诊断决策组件 (`AIDecisionBannerWidget`)**：
  - 将诊断与决策卡片封装为面向对象统一独立组件，同构深度复用于主控全景扫描看板 (`HomeView`) 与 AI 智能文件整理中心 (`OrganizerView`)，实现跨视图路由联动与明细调阅。
- ✏️ **规划路径就地编辑原路径保全与高保真微调 (In-Place Path Preserving Edit)**：
  - **彻底消灭先清空缺陷**：明细表格第 3 列挂载专有就地编辑委托 `PlanningPathItemDelegate`，支持 `Qt.EditRole`，双击或 `F2` 进入编辑时 100% 预填并保全既有建议归档路径文本，并默认全选高亮，用户可直接就地在原路径上增删微调或回车提交极速自沉淀。
- 🎨 **全局高对比度视觉重塑与排版无障碍规范 (High-Contrast UI & Dark Theme Accessibility)**：
  - 严禁列表及树组件出现白底白字或黑底黑字，禁用黑白交叉斑马纹；
  - 分类拓扑树全面重构为蓝底亮白字（`#38BDF8`）、绿底亮白字（`#10B981`）与深邃暗底纯亮白文本（`#F8FAFC`），搭配 44px 黄金行高锁定，视觉对比度鲜明清晰。
- 🛡️ **Shiboken6 C++ 对象生命周期与日志安全隔离 (Memory & Lifecycle Hardening)**：
  - 针对 PySide6/Shiboken 组件销毁后全局日志句柄调用已释放 `QTextEdit` 的异常隐患实施生命周期保护与自解耦机制，杜绝崩溃。
- 🧪 **自动化测试套件扩充至 116 项，100% 全部通过**。

---

### 🌲 v1.6.0 历史特性（2~3 级分类拓扑树、归档路径就地编辑与 1 秒极速自沉淀）

- 🧠 **两大根本开发准则与架构确立**：
  - **准则一：AI 为核心编排器架构 (AI-First Orchestration Contract)**：本地客户端仅作为原始物理特征的采集者与结构化执行清单的最终落轨者。给 AI 明确的标准微契约，由 AI 统揽全局构建分类树并对变更决策实施语义审核与规则抽象；
  - **准则二：GUI 永久一致性法则 (GUI Invariable Law)**：全场景表格行高严格锁死 44px（`verticalHeader().setDefaultSectionSize(44)` + `QHeaderView.Fixed`），严禁被行内编辑器或特殊内容挤压变形；控件排版、操作栏视觉规范永久保持一致。
- 🌲 **2~3 级分类拓扑树与本地示范目录捕捉 (Category Tree & Skeleton Capture)**：
  - 支持指定任意本地功能性分类目录（如 `F:\运维工具`、`D:\开发套件`）；
  - **0-Token 碎文件阻断技术**：本地扫描器递归提取 2~3 级目录骨架与关键代表性执行体样本，彻底阻断成千上万琐碎日志与依赖文件进入契约，Prompt 极致紧凑；
  - AI 编排器统揽全局，秒级创作标准 2~3 级结构化分类树，一字不差入轨落盘至 `global_categories.json`。
- ⚡ **建议归档规划路径就地编辑与 <1s 极速自沉淀 (In-Place Edit & Self-Precipitation)**：
  - **表格行内微编辑**：全景明细表格第 3 列（目标规划路径）支持鼠标双击或快捷键 `F2` 直接进入就地编辑模式；
  - **极速微契约与 HTTP Keep-Alive 连接池**：内置单例 `requests.Session` 保持长连接池，微契约 Prompt 严格压缩至 150 Tokens 内，AI 紧凑输出限额 120 Tokens，关闭思考慢链，**端到端审核与沉淀耗时全面压入 1 秒以内 (< 1s)**；
  - **独立双轨落盘与五级匹配栈**：全局预设树（`global_categories.json`）与自沉淀规则库（`precipitated_rules.json`）独立持久化。资产匹配实施五级严格优先级：`用户手改沉淀规则 (Level 1) > AI 历史沉淀规则 (Level 2) > 全局分类树预设 (Level 3) > 启发式规则 (Level 4) > 默认兜底 (Level 5)`，重启软件 100% 完整继承。
- 🖱️ **双击列职责分流交互规范 (Zero-Conflict Interaction)**：
  - **第 3 列（建议目标路径）**：双击/F2 激活就地微编辑与 AI 自沉淀；
  - **其他所有列（文件名、原始路径、分类、体积等）**：双击 100% 保持原生系统体验，直接唤起 Windows 文件资源管理器打开所在目录并高亮定位实体资产，零操作冲突。
- 🔄 **全域同构级联联动 (Omnipresent Synchronization)**：
  - 分类树或规则沉淀更新后，全局分类管理看板（树状展开/折叠、增删改）、四大表格分类列（多级路径标签渲染）、右键上下文菜单（树状级联分类）、空间分布统计（多级聚合）实时无损刷新，无需重新执行磁盘扫描。
- 🧪 **测试套件规模化跃升**：
  - 覆盖单例连接池、UNC 共享路径防回环、就地微编辑、1 秒 AI 审核时延、示范目录骨架提取与自沉淀继承等，**全工程 109 项测试 100% PASS**。

---

### 🛡️ v1.5.0 历史特性（自动化中心守护与重复文件三模式治理）

- **自动化中心 (Automation Center)**：
  - 支持定时周期扫描与 Windows 实时目录文件监控（Watcher）；
  - **文件被占用安全防护 (In-Use Protection)**：在归档与清理前，深度检测文件句柄独占与正在运行的进程依赖，防止移动活跃使用的文档与程序；
  - 磁盘高水位预警与无感后台轻量巡检。
- **三种重复文件治理模式 (Dedup & Merge Schemes)**：
  - **方案一（安全归档模式）**：智能识别主副本并保留最新版本，其余冗余副本流式打包归档；
  - **方案二（零空间硬链接/联接模式）**：同盘文件创建 NTFS Hardlink，跨盘目录创建 NTFS Junction，文件系统层合二为一，瞬间释放重复占用；
  - **方案三（原子隔离清理模式）**：带有可逆恢复凭证的安全删除与隔离。

---

### 📐 v1.4.0 历史特性（三大整理核心原则架构贯通）

- **原则一：防御性递归原则 (Defensive Recursion Principle)**：
  - 扫描栈遍历到原子狭义集体（绿色独立软件、开发工程、独立工具链等）立即封包汇总、源头剪枝（Pruning），严禁成千上万碎文件与运行时依赖泄露入栈；全生命周期作为独立原子资产治理。
- **原则二：泛式大抽屉与狭义实体拓扑法则 (Broad vs. Narrow Topology Law)**：
  - 父子语义落差优先裁决，大抽屉（`MovedApps`, `backups`, `财务`, `Live2D`, `多媒体` 等）向下强行赋权上位语义；解禁非系统盘一级独立软件，纠偏备份目录下的快照反客为主识别为代码工程的问题。
- **原则三：同源同宿——源路径同构保全在全链条的贯通 (Source Umbrella Consistency)**：
  - 全链条推荐子路径保持源泛目录命名结构同构映射；备份大抽屉下完整归档压缩包（如 `.tar.gz`）严禁误标为“冗余归档包”，全方位保全用户备份资产。

---

## 🌟 核心架构与技术实现

### 1. 🧠 AI 核心编排器与 2~3 级分类树体系

本系统彻底颠覆传统文件管理工具“机械规则匹配”模式，确立了 **AI 为核心编排器** 的架构理念：

```mermaid
flowchart TD
    subgraph Local [本地执行与特征提取层]
        A[选择本地示范目录\n如 F:\运维工具] -->|0-Token 碎文件阻断| B[目录骨架与关键执行体样本]
        C[全景明细表格\n第 3 列建议路径] -->|双击 / F2 手改| D[提取资产特征 + 手改目标路径]
    end

    subgraph AI [AI 核心编排器 (< 1s 极速微契约)]
        B -->|单例 Keep-Alive 连接池\nPrompt < 150 Tokens| E[AI 统揽 2~3 级分类建树]
        D -->|极简 JSON 限制 <= 120 Tokens\n关闭思考慢链| F[AI 合法性审核 / 分类吸附 / 规则抽象]
    end

    subgraph Storage [双独立持久化与全域入轨]
        E -->|落盘| G[(global_categories.json\n2~3级全局分类树)]
        F -->|自沉淀| H[(precipitated_rules.json\n五级自沉淀规则库)]
        G --> I[全域同构联动\n看板展开树 / 表格多级标签 / 右键级联 / 空间分布]
        H --> I
    end
```

#### 极速微契约机制 (< 1 秒端到端保障)
1. **单例 HTTP Keep-Alive 连接池**：内置单例 `requests.Session`（`pool_connections=20, pool_maxsize=50`），消除重复握手 TCP/TLS 延迟；
2. **极简微契约 Prompt 设计**：严格压缩至 150 Tokens 以内，剥离繁杂系统说明，直击核心语义；
3. **输出限额与快链关闭**：强制 `max_tokens <= 120`，显式设置 `extra_body={"thinking": {"type": "disabled"}}` 阻断思考慢链；
4. **超短阶段超时与智能本地降级**：网络超时严格设为连接 0.3s、读取 0.5s，遇网络抖动毫秒级无感降级至本地拓扑规则，绝不卡死界面。

---

### 2. ⚡ 三阶段异步非阻塞扫描引擎 (3-Phase Scanning)

```mermaid
flowchart LR
    A[选择盘符 / 扫描路径] --> B[阶段 1: os.scandir 高速流式快照]
    B --> C[阶段 2: 3级哈希查重 + SQLite 持久化缓存]
    C --> D[阶段 3: 冗余聚合 & AI 深度治理报告]
    D --> E[AI 树状规划 / 自动化跨盘迁移 / 一键归档]
```

- **阶段一（毫秒级全景快照）**：采用高效 `os.scandir` 流式遍历，瞬间呈现磁盘占用环形图/柱状图、文件类型分布与 **全局 Top 100 超大文件明细表**；
- **阶段二（并发分块哈希查重）**：
  - 首创 **“大小初筛 + 头部 8KB 样本哈希 + 并发全量哈希”** 三级过滤机制；
  - 内置 **SQLite 持久化哈希缓存**，二次扫描瞬间完成；
  - 深度防御 64 位超大文件字节溢出，支持 TB 级大文件安全校验；
- **阶段三（智能汇总与全景治理报告）**：汇聚重复副本与启发式冗余项，可一键调用 OpenAI 兼容大模型生成专业的《磁盘存储全景深度分析与治理报告》。

---

### 3. 🖱️ 双击列职责分流与 GUI 永久一致性法则

为解决“编辑目标规划路径”与“打开定位文件”之间的操作冲突，系统制定了严密的交互分流与排版铁律：

| 目标列 | 交互动作 | 响应行为 | 设计目的 |
| :--- | :--- | :--- | :--- |
| **第 3 列（建议规划路径）** | 鼠标双击 / 按下 `F2` | 激活就地微编辑输入框，回车自动触发 AI 微契约审核并增量自沉淀 | 快速修正归档目标，无需繁琐弹窗 |
| **其他所有列（第 0, 1, 2, 4~7 列）** | 鼠标双击 | 调用 Windows 原生 Shell，在文件资源管理器中精准打开并高亮定位 | 保持原生操作系统使用习惯，零学习成本 |

> 📐 **GUI 永久一致性铁律**：  
> 全景表格垂直行高全局锁死为 **44px**（`verticalHeader().setDefaultSectionSize(44)` 并设置 `QHeaderView.Fixed`），严禁被行内输入框、多级徽章标签或长文本挤压变形。

---

### 4. 📦 智能跨盘迁移、NTFS 联接与安全回滚机制

- **NTFS 目录联接（Junction `mklink /J`）**：跨盘迁移大型独立应用或开发库后，自动创建透明目录联接，主程序运行完全无感知；
- **快捷方式与注册表自动同步**：
  - 自动扫描桌面与开始菜单关联的 `.lnk` 快捷方式并同步重定向；
  - 探测关联的 `HKCU` / `HKLM` 注册表安装与卸载键值，支持勾选安全更新；
- **原子自动回滚与 Manifest 凭据**：
  - 操作遇突发异常或用户中断时，自动触发原子级回滚恢复；
  - 每次归档与迁移均在本地生成带有原/目标路径哈希映射的 Manifest JSON 快照凭据，支持随时一键原路逆向复原。

---

### 5. 🤖 自动化中心与被占用安全防护 (Automation Center)

- **常驻后台守护**：支持指定目录变更监听（基于 Windows 文件系统变动通知）；
- **文件被占用安全阻断 (In-Use Protection)**：执行物理归档或清理前，调用底层系统 API 校验文件句柄占用状态（锁定句柄探测），对正在被进程读写的文件实施强制阻断跳过，避免写入损坏；
- **磁盘水位监控**：监控分区余量，水位告警时按既定自沉淀策略自动推送整理建议。

---

## 📂 项目工程目录结构

```text
空间全景深度分析与冗余文件扫描/
├── app/
│   ├── config.py                      # 三级配置继承体系管理器 (Default/Global/Profile)
│   ├── automation/                    # 自动化中心守护子系统
│   │   ├── archive_executor.py        # 自动化归档执行器
│   │   ├── cli_generator.py           # 批处理 / CLI 任务生成器
│   │   ├── manager.py                 # 自动化中心调度与任务编排管理器
│   │   ├── models.py                  # 自动化任务与规则数据结构
│   │   ├── quick_organizer.py         # 极速轻量整理引擎
│   │   ├── scheduler.py               # 定时调度器
│   │   └── watcher.py                 # 目录文件系统变动监听器
│   ├── core/                          # 核心业务与底层计算引擎
│   │   ├── ai_parser.py               # AI 报告解析与结构清洗
│   │   ├── ai_service.py              # AI 编排器客户端、Keep-Alive 连接池与 <1s 微契约
│   │   ├── app_detector.py            # 应用识别、三大原则拓扑判定与原子分组引擎
│   │   ├── category_manager.py        # 2~3 级分类拓扑树、示范目录捕捉与五级自沉淀规则库
│   │   ├── cleaner.py                 # 流式归档与安全物理删除 Worker
│   │   ├── hash_cache.py              # SQLite 3 级并发持久化哈希缓存数据库
│   │   ├── migrator.py                # 跨盘迁移、NTFS Junction 联接与快捷方式/注册表同步
│   │   ├── rollback_worker.py         # 原子回滚工作线程与 Manifest 凭据解析
│   │   ├── scanner.py                 # 三阶段非阻塞全景扫描主引擎
│   │   └── task_manager.py            # 后台统一任务调度器 (速度/ETA/暂停/恢复)
│   ├── ui/                            # 现代化 PySide6 界面展现层
│   │   ├── main_window.py             # 侧边栏主窗口骨架与导航流转
│   │   ├── home_view.py               # 全景扫描看板、报告面板与空间分布视图
│   │   ├── organizer_view.py          # AI 智能整理中心与规划确认视图
│   │   ├── settings_view.py           # 配置中心 (三层配置、模型拉取、忽略路径维护)
│   │   ├── styles.py                  # 现代化暗色主题 QSS 样式表与调色板
│   │   ├── components/                # 业务可复用 UI 高性能组件
│   │   │   ├── category_dialog.py     # 2~3 级分类树管理看板与本地示范目录捕捉向导
│   │   │   ├── data_table.py          # 44px 行高锁定、就地编辑与双击分流高性能表格
│   │   │   ├── migration_dialog.py    # 跨盘迁移向导与关联项同步弹窗
│   │   │   ├── organize_dialog.py     # 10 列目录树 AI 规划确认向导
│   │   │   └── task_manager_widget.py # 后台任务监控与实时排障面板
│   │   └── dedup/                     # 重复文件治理三模式交互向导
│   │       ├── dedup_merge_view.py    # 重复文件查重与治理主视图
│   │       ├── directory_select_step.py # 目录选定步骤
│   │       ├── scan_progress_step.py  # 并发哈希进度步骤
│   │       ├── review_table_step.py   # 重复项核查步骤
│   │       └── merge_execute_step.py  # 三模式合并执行步骤
│   └── utils/
│       ├── file_helper.py             # 系统保护白名单、格式化与扩展名映射
│       ├── lock_detector.py           # 文件/进程占用状态深度安全探测 (In-Use Guard)
│       └── logger.py                  # 日志滚动持久化、全局异常拦截与崩溃快照
├── tests/                             # 自动化单元测试与集成回归套件 (116 项)
│   ├── test_category_tree_and_self_precipitation.py # 分类树建树、<1s微契约、就地编辑自沉淀专项测试
│   ├── test_restart_inheritance_and_select_recommended.py # 重启继承与安全推荐项勾选测试
│   ├── test_three_core_principles_unified.py       # 三大整理核心原则全场景测试
│   ├── test_automation_center.py                   # 自动化中心调度与被占用防护测试
│   ├── test_dedup_and_merge.py                     # 三大去重模式专项测试
│   ├── test_collective_promotion_and_app_manager.py# 狭义实体集体提升测试
│   ├── test_ai_service_and_pipeline.py             # AI 接口微契约、清洗防幻觉与重试测试
│   └── ...                                         # 更多系统测试 (详见 tests/ 目录)
├── build_release.py                   # 一键产出便携版 zip 与单文件 exe 构建脚本
├── main.py                            # 应用程序启动入口 (全局异常捕获与配置注入)
├── requirements.txt                   # 生产运行依赖清单
└── requirements-dev.txt               # 开发与测试套件依赖清单
```

---

## 🚀 快速上手与运行

### 1. 开发环境准备
推荐使用 **Python 3.10 及以上**（已在 Python 3.10 / 3.11 / 3.12 深度验证）：
```bash
# 1. 克隆代码仓库
git clone https://github.com/xuemingze/disk-space-analyzer.git
cd disk-space-analyzer

# 2. 创建并激活 Python 虚拟环境 (推荐)
python -m venv .venv
.venv\Scripts\activate

# 3. 安装依赖项
pip install -r requirements.txt
```

### 2. 启动桌面客户端
```bash
python main.py
```

### 3. 运行全量自动化测试套件
```bash
# 执行全部 116 项单元与集成测试（约 17 秒全部通过）
python -m pytest tests/ -v
```

---

## 🤖 大模型 (LLM) 编排配置指南

在软件左侧导航栏点击 **“系统配置 (Settings)”**：
1. **Base URL**：输入任意 OpenAI 兼容的服务端点（例如 `https://api.openai.com/v1`、DeepSeek `https://api.deepseek.com/v1`、MiniMax、Qwen 或 本地 Ollama `http://localhost:11434/v1`）；
2. **API Key**：填写对应的身份鉴权密钥；
3. **拉取与选择模型**：点击 **“🔄 拉取可用模型”** 自动同步线上模型清单（如 `deepseek-chat`、`gpt-4o`、`MiniMax-Text-01` 等）；
4. **连通性校验**：点击 **“⚡ 测试连通性”**，验证成功后保存配置。

> 💡 **离线无缝降级保护**：  
> 若未配置 API Key 或处于断网环境，系统将全自动、毫秒级平稳降级至内置的高精度离线拓扑规则引擎，所有本地建树、就地编辑与分类归档功能依然 100% 正常运作。

---

## 🩺 诊断日志与故障排查

客户端在主线程、异步工作线程及解释器退出阶段均挂载了全局异常拦截器，所有关键信息独立落盘：

| 日志文件 | 记录内容 | 滚动策略 |
| :--- | :--- | :--- |
| `logs/app.log` | 系统常规运行追踪与扫描调度全流程记录 | 单文件 2 MB，最多保留 3 份 |
| `logs/error.log` | 错误告警与带完整堆栈追踪的异常排障信息 | 单文件 1 MB，最多保留 5 份 |
| `logs/crash-*.log` | 严重崩溃快照（包含未捕获异常上下文与系统环境变量） | 每次独立保存，不被覆盖 |

如在使用中遇到任何异常，请将 `logs/error.log` 或最新的 `logs/crash-*.log` 提交至 Issue 反馈。

---

## 📄 开源许可证

本项目遵循 [MIT License](LICENSE) 开源协议。
