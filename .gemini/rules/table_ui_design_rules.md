---
description: 列表与表格模块 UI 设计铁律 (Table & List UI Design Rules)
globs: ["app/ui/**/*.py"]
---

# 列表与表格模块 UI 设计铁律 (强制执行规范)

在本项目（以及后续所有包含 QTableWidget / QTreeView / 列表的模块）中，严格禁止直接将裸按钮放入单元格或任由单元格高宽自由压缩变形。必须严格遵循以下设计规范：

## 1. 统一表格行高规范 (Vertical Header Sizing)
- 严禁使用 Qt 默认的 20~24px 极窄行高！
- 表格垂直表头必须统一定义行高为 **42px ~ 46px** (推荐 44px)，并锁定模式：
  ```python
  self.table.verticalHeader().setDefaultSectionSize(44)
  self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
  ```
- 保证每一行有充足、舒适的纵向呼吸空间，杜绝文字或按钮上下被挤压。

## 2. 列宽策略分层 (Horizontal Header Partitioning)
- **含点击控件列必须锁定固定宽度 (`QHeaderView.Fixed`)**：
  - 状态开关列 (Toggle Switch)：固定宽度 **90px**；
  - 整理模式 / 类型 / 周期等固定枚举列：固定宽度 **100px ~ 110px**；
  - 防抖秒数 / 时间 / 次数等短指标列：固定宽度 **80px ~ 120px**；
  - 2 按钮操作列：固定宽度 **150px ~ 160px**；
  - 3 按钮操作列：固定宽度 **210px ~ 230px**；
- **文本 / 路径列弹性自适应 (`QHeaderView.Stretch`)**：
  - 仅允许路径、文件名、描述等纯文本列伸缩；
  - 窗口缩放时，保证所有点击控件大小与位置恒定稳定，绝不随窗口缩放被压扁。

## 3. 标准化按钮容器与尺寸约束 (Action Cell Wrapper)
- **严禁直接把裸按钮塞入 `setCellWidget`！**
- 必须使用居中容器 `QWidget` + `QHBoxLayout` 包裹：
  - `layout.setContentsMargins(6, 4, 6, 4)`
  - `layout.setSpacing(8)`
  - `layout.setAlignment(Qt.AlignCenter)`
- **按钮尺寸硬性约束**：
  - 按钮高度必须显式指定 `btn.setFixedHeight(28)` (推荐 28px)；
  - 按钮最小宽度必须指定 `btn.setMinimumWidth(54)` ~ `64px`；
  - 状态开关按钮同理：高度 28px，宽度 72px，居中放置。

## 4. 视觉规范与交互反馈
- 必须具备 `:hover` 与 `:pressed` 伪类样式；
- 字体大小统一为 12px，圆角 `border-radius: 4px`；
- 状态开启/停用采用统一对比色规范（如启用 `#10B981`，停用 `#64748B`，主操作 `#0284C7`，次操作 `#3B82F6`，危险操作 `#EF4444`）。
