# Release Notes - v1.9.1

## 🚀 版本亮点 (Highlights)

本版本专注于修复真实归档与回滚交互场景下的两项核心严重缺陷，保障 GUI 交互健壮性与归档流程畅通：

1. **快照回滚部件 `QTreeWidgetItemIterator` 缺失异常修复 (Rollback Widget Iterator Fix)**：
   - 彻底修复 `rollback_widget.py` 中因引用错误的类命名空间 `QTreeWidget.QTreeWidgetItemIterator` 导致的 `AttributeError` 崩溃；
   - 规范从 `PySide6.QtWidgets` 顶级命名空间直接导入 `QTreeWidgetItemIterator`；
   - 完善叶子节点判断与勾选状态过滤，确保「回滚选中项」与「全选可回滚项」在各种快照数据状态下均能零崩溃平稳执行。

2. **AI 智能归档目录树复选框初始可见性与全流程收集修复 (Tree Checkbox Visibility & Harvest Fix)**：
   - **复选框初始不显示根因清障**：解决添加延迟加载占位节点（`dummy`）时，因 Qt `ItemIsAutoTristate` 特性导致顶级目录节点 CheckStateRole 被重置为 None 而使复选框隐身的问题；
   - **初始统计与显示对齐**：初始化加载后即时计算自动勾选推荐项数量与容量，并同步刷新顶部状态看板；
   - **延迟加载与归档提取解耦**：全新实现 `get_selected_file_items()`，完美支持未展开顶级目录（以父节点勾选状态自动提取全部 `sub_items`）与展开目录（逐项支持局部个性化勾选/反选），彻底解决“勾选后点击归档提示未选择任何项目”的交互阻塞；
   - **编辑委托精准作用域**：将 `TreeInplaceItemDelegate` 严格限制在第 2 列与第 3 列（`setItemDelegateForColumn(2/3)`），坚决不干扰第 0 列复选框与节点名称呈现。

---

## 🛠️ 质量与验证 (Quality & Verification)

- **回归测试覆盖**：新增专项回归测试 `tests/test_rollback_widget_and_tree_checkbox_regression.py`，完整覆盖回滚迭代器执行、复选框初始可见性（CheckStateRole）、未展开直接归档与展开局部反选全流程；
- **全工程用例通过率**：全域 182 项自动化测试 100% 全部通过。
