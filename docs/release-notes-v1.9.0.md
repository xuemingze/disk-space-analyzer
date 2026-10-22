# Release Notes - v1.9.0

## 🚀 版本亮点 (Highlights)

本版本专注于**环境拓扑路由表（TopologyRoutingTable）与网络级最长前缀匹配（LPM）**、**原材料/中转容器路径彻底剥离**、**AI 资产报送契约（AIAssetPayloadBuilder）与 9 大 PE 元数据零遗漏交付**、**归档目标路径值对象（ArchiveDestinationPath）防嵌套消除**与**全域 178 项自动化回归测试**：

1. **环境拓扑路由表与最长前缀匹配机制 (TopologyRoutingTable & LPM Architecture)**：
   - 践行面向对象思维，建立系统级拓扑路由领域模型 [`TopologyRole`](file:///D:/项目/空间全景深度分析与冗余文件扫描/app/core/domain_models.py)（`STAGING_BUCKET`、`APP_COLLECTIVE`、`WORKSPACE`、`VAULT`）与 [`TopologyPolicy`](file:///D:/项目/空间全景深度分析与冗余文件扫描/app/core/domain_models.py)（`STRIP_CONTAINER`、`PRESERVE_ATOMIC` 等）；
   - 实现线程安全单例 [`TopologyRoutingTable`](file:///D:/项目/空间全景深度分析与冗余文件扫描/app/core/domain_models.py)，支持网络级最长前缀匹配（LPM），精准区分外层中转容器与内层解压应用目录；
   - 离线与在线 AI 双向对称架构：离线规则 0 Token 极速研判目录角色，阻断中转容器误捆绑伪集体；在线 AI 注入 `<= 50` Tokens 紧凑环境拓扑上下文，并支持动态自沉淀学习新路由至 `~/.disk_space_analyzer/environment_topology.json`，越用越准。

2. **原材料与中转容器路径彻底剥离 (Raw Material & Staging Container Purging)**：
   - 彻底解决原材料/中转容器目录名（如 `共用文件`、`Downloads`、`待整理` 等）被硬编码或错误渗入规划路径的缺陷（如 `D:\归档备份\07_系统工具\共用文件`）；
   - 原材料目录仅作为源环境定位参考，绝对禁止注入到建议归档路径（`recommended_subpath` / `suggested_category`）；
   - 严格划分泛式中转集合与独立资产：中转目录内的散装安装包独立打散为单文件资产，解压绿色运行时（如 `AweSun`）严格保持密封原子集体；
   - `_normalize_umbrella_name` 与 `extract_source_umbrella` 阻断中转容器名充当业务泛目录锚点。

3. **归档目标规划路径值对象与防嵌套折叠 (`ArchiveDestinationPath`)**：
   - 全面落地不可变领域值对象 [`ArchiveDestinationPath`](file:///D:/项目/空间全景深度分析与冗余文件扫描/app/core/domain_models.py)，统一路径构建、路径安全性校验与子路径相对派生；
   - 实现相邻重复段与包含嵌套智能折叠，彻底消除形如 `~/发票/发票/XXX` 的重复段嵌套 Bug；
   - 彻底移除任何特定企业专有名词（如经控），实现全局业务通用化规范。

4. **AI 资产报送契约构建器与 9 大 PE 元数据零遗漏交付 (`AIAssetPayloadBuilder`)**：
   - 统一构建器消除多处组装冗余，严格保障 9 大核心元数据 100% 完整交付给大模型：
     - `software_name`（规范软件真名）
     - `product_version`（产品版本）
     - `publisher`（厂商）
     - `domain_sector`（有序业务领域分类）
     - `is_obfuscated_name`（混淆乱码标识）
     - `normalized_name`（标准化还原名）
     - `morphology`（物理形态：原子实体集体 vs 独立单项）
     - `file_count`（内部文件数）
     - `size_mb` / `total_size_mb`（容量指标）；
   - 0 Token 碎文件阻断，仅输出高价值关键元数据。

5. **AI 目录树归档计划预览就地微调与自沉淀 (In-place Tree Editing & Auto-Precipitation)**：
   - 全面支持列 2（归档分类）与列 3（目标规划路径）双击/F2 就地编辑，`setText` + `selectAll` 绝不清空原值；
   - 集成 `QCompleter` 历史候选联想与父子级联即时传播；
   - 修复表格列宽过窄省略号截断与超长文本完整展示。

---

## 🛠️ Bug 修复与体验调优 (Bug Fixes & Refinements)

- **修复**：中转容器（如 `共用文件`）内的散装安装包被错误捆绑为一个名为 `共用文件` 的伪目录集体；
- **修复**：归档建议目标路径尾部硬编码渗入原材料中转容器目录名的缺陷；
- **修复**：业务路径中相邻同名目录（如 `发票/发票`）重复嵌套的问题；
- **修复**：私有业务命名出现在全局托底脚本中的问题，确立全局通用面向对象机制；
- **优化**：大模型研判数据投递统一标准化，杜绝元数据遗漏与散落字典键名不一致风险。

---

## 🧪 自动化测试验证 (Testing)

- 自动化测试用例集扩充至 **178 项全部 PASS**（`178 passed in 8.14s`）：
  - 覆盖 TopologyRoutingTable LPM 匹配、动态学习与本地持久化重载；
  - 覆盖 ArchiveDestinationPath 中转容器剔除与重复段折叠；
  - 覆盖原材料中转目录内散装单项打散与解压应用原子集体保全；
  - 覆盖 AIAssetPayloadBuilder 9 大 PE 元数据与形态字段 100% 完整报送；
  - 覆盖全工程既有 171 项单元测试与回归测试用例。
