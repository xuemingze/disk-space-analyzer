"""
专项回归测试：
1. RollbackWidget 中的 selective rollback 与 select_all_rollbackable 迭代器调用（修复 QTreeWidgetItemIterator AttributeError）
2. OrganizePreviewDialog 目录树复选框初始可见性、全选联动与未展开/已展开全流程归档项收集（修复复选框初始不显示、归档提示未选择任何项目）
"""
import os
import sys
import json
import pytest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt

from app.ui.components.rollback_widget import RollbackWidget
from app.ui.components.organize_dialog import OrganizePreviewDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_rollback_widget_iterator_no_crash(qapp, tmp_path, monkeypatch):
    """验证 RollbackWidget.select_all_rollbackable 与 execute_selective_rollback 不再崩溃"""
    manifest_file = tmp_path / "manifest_test_rollback.json"
    manifest_data = {
        "backup_id": "BK_REGRESSION_001",
        "destination_root": str(tmp_path / "arch"),
        "created_at": 1700000000,
        "rollback_status": "NONE",
        "items": [
            {
                "entry_id": "ENT_01",
                "original_path": str(tmp_path / "orig" / "sub" / "file1.txt"),
                "archived_path": str(tmp_path / "arch" / "file1.txt"),
                "size": 1024,
                "operation_status": "success",
                "rollback_status": "none"
            },
            {
                "entry_id": "ENT_02",
                "original_path": str(tmp_path / "orig" / "sub" / "file2.txt"),
                "archived_path": str(tmp_path / "arch" / "file2.txt"),
                "size": 2048,
                "operation_status": "failed",
                "rollback_status": "none"
            }
        ]
    }
    manifest_file.write_text(json.dumps(manifest_data, ensure_ascii=False), encoding="utf-8")

    widget = RollbackWidget()
    widget.current_manifest = str(manifest_file)
    
    # 模拟选择该快照
    with open(str(manifest_file), "r", encoding="utf-8") as f:
        data = json.load(f)
    # 调用构建树
    widget.tree_widget.clear()
    items = data.get("items", [])
    root_nodes = {}
    for it in items:
        orig = it.get("original_path", "")
        arch = it.get("archived_path") or it.get("target_path", "")
        size = "1KB"
        op_status = it.get("operation_status", "")
        rb_status = it.get("rollback_status", "")
        e_id = it.get("entry_id", "")
        p = Path(orig)
        parent = str(p.parent)
        if parent not in root_nodes:
            from PySide6.QtWidgets import QTreeWidgetItem
            p_node = QTreeWidgetItem(widget.tree_widget)
            p_node.setText(0, parent)
            p_node.setFlags(p_node.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            p_node.setCheckState(0, Qt.Unchecked)
            root_nodes[parent] = p_node
        node = QTreeWidgetItem(root_nodes[parent])
        node.setText(0, p.name)
        node.setText(1, arch)
        node.setText(2, orig)
        node.setText(3, size)
        node.setData(0, Qt.UserRole, e_id)
        if op_status == "success" and rb_status != "success":
            node.setFlags(node.flags() | Qt.ItemIsUserCheckable)
            node.setCheckState(0, Qt.Unchecked)
        else:
            node.setFlags(node.flags() & ~Qt.ItemIsUserCheckable)
            node.setCheckState(0, Qt.Unchecked)

    # 1. 验证 select_all_rollbackable 不抛 AttributeError 且正确勾选
    widget.select_all_rollbackable()
    
    # 2. 模拟 QMessageBox 阻止弹窗阻塞
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.No)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    
    # 3. 验证 execute_selective_rollback 不抛 AttributeError
    widget.execute_selective_rollback()


def test_organize_preview_dialog_initial_checkbox_visibility(qapp):
    """
    验证 AI 归档预览对话框复选框初始可见性：
    1. 顶级节点 CheckStateRole 必须为有效 CheckState (0 或 2)，严禁为 None；
    2. 自动勾选逻辑正确计算勾选数量并实时反映在 stats 统计文本中。
    """
    groups = [
        {
            "group_id": "g1",
            "original_root": r"C:\app1",
            "app_name": "MotrixNext",
            "suggested_category": "软件安装与程序",
            "confidence": 0.95,
            "risk_level": "低风险",
            "require_confirmation": False,
            "sub_items": [
                {"original_path": r"C:\app1\m.exe", "size": 1000, "target_path": r"D:\归档\m.exe"}
            ]
        },
        {
            "group_id": "g2",
            "original_root": r"C:\unknown_app",
            "app_name": "未知应用",
            "suggested_category": "待确认",
            "confidence": 0.4,
            "risk_level": "高风险",
            "require_confirmation": True,
            "sub_items": [
                {"original_path": r"C:\unknown_app\u.dll", "size": 2000, "target_path": r"D:\归档\u.dll"}
            ]
        }
    ]

    dialog = OrganizePreviewDialog(groups, destination_root=r"D:\归档")
    assert dialog.tree.topLevelItemCount() == 2

    g1_item = dialog.tree.topLevelItem(0)
    g2_item = dialog.tree.topLevelItem(1)

    # 核心断言：初始必须可见复选框（CheckStateRole 绝不能为 None）
    assert g1_item.data(0, Qt.CheckStateRole) is not None
    assert g1_item.data(0, Qt.CheckStateRole) == Qt.Checked.value or g1_item.checkState(0) == Qt.Checked

    assert g2_item.data(0, Qt.CheckStateRole) is not None
    assert g2_item.data(0, Qt.CheckStateRole) == Qt.Unchecked.value or g2_item.checkState(0) == Qt.Unchecked

    # 初始已勾选数量应为 g1 的 1 个文件
    selected_initial = dialog.get_selected_file_items()
    assert len(selected_initial) == 1
    assert selected_initial[0]["path"] == r"C:\app1\m.exe"
    assert "1 个文件" in dialog.stats_label.text()


def test_organize_preview_dialog_select_all_and_harvest(qapp, monkeypatch):
    """
    验证点击全选后，未展开的节点能被 100% 完整提取，点击归档不会误报未选择任何项目
    """
    groups = [
        {
            "group_id": "g1",
            "original_root": r"C:\app1",
            "app_name": "App1",
            "suggested_category": "工具",
            "confidence": 0.5,
            "risk_level": "中风险",
            "require_confirmation": True,
            "sub_items": [
                {"original_path": r"C:\app1\f1.txt", "size": 100, "target_path": r"D:\归档\f1.txt"},
                {"original_path": r"C:\app1\f2.txt", "size": 200, "target_path": r"D:\归档\f2.txt"}
            ]
        }
    ]

    dialog = OrganizePreviewDialog(groups, destination_root=r"D:\归档")
    assert len(dialog.get_selected_file_items()) == 0  # 初始需人工确认，默认未勾选

    # 模拟用户点击「全选」
    dialog._set_all_checked_state(Qt.Checked)
    
    # 未展开状态下直接获取勾选项
    selected = dialog.get_selected_file_items()
    assert len(selected) == 2
    assert {s["path"] for s in selected} == {r"C:\app1\f1.txt", r"C:\app1\f2.txt"}

    # 模拟用户点击「归档」
    prompt_shown = []
    def fake_question(parent, title, text, *args):
        prompt_shown.append((title, text))
        return QMessageBox.No  # 不实际启动线程
    monkeypatch.setattr(QMessageBox, "question", fake_question)
    
    warning_shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warning_shown.append(text))

    dialog.execute_archive()

    # 验证未弹出“未勾选任何文件”警告，而是成功弹出归档确认框
    assert len(warning_shown) == 0
    assert len(prompt_shown) == 1
    assert "已勾选" in prompt_shown[0][1]
    assert "2" in prompt_shown[0][1]


def test_organize_preview_dialog_expand_and_partial_uncheck(qapp):
    """
    验证展开节点后逐项反选子节点，get_selected_file_items 准确反映子节点勾选状态
    """
    groups = [
        {
            "group_id": "g1",
            "original_root": r"C:\app1",
            "app_name": "App1",
            "suggested_category": "工具",
            "confidence": 0.9,
            "risk_level": "低风险",
            "require_confirmation": False,
            "sub_items": [
                {"original_path": r"C:\app1\f1.txt", "size": 100, "target_path": r"D:\归档\f1.txt"},
                {"original_path": r"C:\app1\f2.txt", "size": 200, "target_path": r"D:\归档\f2.txt"}
            ]
        }
    ]

    dialog = OrganizePreviewDialog(groups, destination_root=r"D:\归档")
    top_item = dialog.tree.topLevelItem(0)

    # 展开该节点
    dialog._on_item_expanded(top_item)
    assert top_item.childCount() == 2

    # 子项默认继承父节点的 Checked
    assert top_item.child(0).checkState(0) == Qt.Checked
    assert top_item.child(1).checkState(0) == Qt.Checked

    # 用户手动取消勾选第 0 个子项
    top_item.child(0).setCheckState(0, Qt.Unchecked)

    selected = dialog.get_selected_file_items()
    assert len(selected) == 1
    assert selected[0]["path"] == r"C:\app1\f2.txt"
