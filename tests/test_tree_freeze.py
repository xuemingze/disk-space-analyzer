"""AI 归档目录树防卡死专项测试。

pytest 可收集版本：模块导入期不执行任何重活，也不调用 ``sys.exit``，
因此可以安全地被 ``pytest tests/`` 收集。

大规模压测（默认 10 组 x 5000 项 = 50,000 节点）通过以下两种方式触发：

* 直接运行脚本：``python tests/test_tree_freeze.py``
* 环境变量：``set TREE_FREEZE_SCALE=large`` 后再跑 pytest
"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.components.organize_dialog import OrganizePreviewDialog  # noqa: E402


def build_groups(group_count: int, items_per_group: int):
    """构造与 AppDetector/AIService 输出同构的目录聚合单元列表。"""
    groups = []
    for i in range(group_count):
        groups.append(
            {
                "original_root": f"C:/test/group_{i}",
                "app_name": f"App_{i}",
                "suggested_category": "工具",
                "sub_items": [
                    {
                        "relative_path": f"file_{j}.txt",
                        "size": 100,
                        "target_path": "D:/test",
                    }
                    for j in range(items_per_group)
                ],
            }
        )
    return groups


def resolve_scale():
    """返回 (组数, 每组项数, 展开耗时预算秒)。"""
    if os.environ.get("TREE_FREEZE_SCALE", "").strip().lower() == "large":
        return 10, 5000, 120.0
    return 4, 400, 30.0


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_expand_all_and_cascade_uncheck(qapp):
    """批量展开不得卡死，父子勾选级联必须正确且足够快。"""
    group_count, items_per_group, budget = resolve_scale()
    total_items = group_count * items_per_group
    groups = build_groups(group_count, items_per_group)

    dialog = OrganizePreviewDialog(
        classification_items=groups, destination_root="D:/归档备份"
    )
    try:
        dialog.show()
        qapp.processEvents()

        assert dialog.tree.topLevelItemCount() == group_count

        started = time.time()
        dialog._expand_all_with_progress()
        qapp.processEvents()
        expand_elapsed = time.time() - started

        assert expand_elapsed < budget, (
            f"展开 {total_items} 节点耗时 {expand_elapsed:.2f}s，超出预算 {budget}s"
        )

        for i in range(dialog.tree.topLevelItemCount()):
            assert dialog.tree.topLevelItem(i).childCount() == items_per_group

        # 父节点取消勾选 -> 子节点级联取消（原生 AutoTristate 路径）
        started = time.time()
        top_item = dialog.tree.topLevelItem(0)
        top_item.setCheckState(0, Qt.Unchecked)
        qapp.processEvents()
        cascade_elapsed = time.time() - started

        assert cascade_elapsed < budget, (
            f"级联取消勾选 {items_per_group} 子节点耗时 {cascade_elapsed:.2f}s，超出预算 {budget}s"
        )
        for j in range(top_item.childCount()):
            assert top_item.child(j).checkState(0) == Qt.Unchecked
    finally:
        dialog.tree.clear()
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


if __name__ == "__main__":
    # 独立压测模式：固定 50,000 节点，输出可读耗时报表
    os.environ["TREE_FREEZE_SCALE"] = "large"
    started = time.time()
    exit_code = pytest.main([__file__, "-v", "-s", "-p", "no:cacheprovider"])
    print(f"\n=== 压测总耗时: {time.time() - started:.2f}s ===", flush=True)
    raise SystemExit(exit_code)
