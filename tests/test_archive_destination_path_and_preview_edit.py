import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem
from PySide6.QtCore import Qt

from app.core.domain_models import (
    ArchiveDestinationPath,
    HistorySuggestionProvider,
    ArchivePlanningUnit
)
from app.ui.components.organize_dialog import OrganizePreviewDialog, TreeInplaceItemDelegate
from app.core.app_detector import AppDetector


def test_archive_destination_path_deduplication():
    """验证 ArchiveDestinationPath 折叠相邻重复段，彻底消除形如 ~/发票/发票/XXX 的嵌套"""
    # 1. 基础相邻重复段折叠
    parts = ["D:", "归档", "发票", "发票", "08月发票"]
    collapsed = ArchiveDestinationPath.collapse_duplicate_segments(parts)
    assert collapsed == ["D:", "归档", "发票", "08月发票"]

    # 2. 大小写不敏感折叠 (例如 live2d / Live2D)
    parts_case = ["live2d", "Live2D", "角色模型"]
    collapsed_case = ArchiveDestinationPath.collapse_duplicate_segments(parts_case)
    assert len(collapsed_case) == 2
    assert collapsed_case[0].lower() == "live2d"
    assert collapsed_case[1] == "角色模型"

    # 3. 带有复合斜杠的段落折叠 (例如 '发票/2026' 与 '2026')
    parts_slash = ["发票/2026", "2026", "08月发票"]
    collapsed_slash = ArchiveDestinationPath.collapse_duplicate_segments(parts_slash)
    assert collapsed_slash == ["发票", "2026", "08月发票"]

    # 4. 面向对象 build 构建：当 category='发票', subpath='发票', entity_name='08月发票'
    dest = ArchiveDestinationPath.build(
        dest_root=r"D:\归档目标",
        category="发票",
        subpath="发票",
        entity_name="08月发票",
        is_dir=True
    )
    norm_dest = dest.raw_path.replace("\\", "/")
    assert "发票/发票" not in norm_dest
    assert norm_dest.endswith("发票/08月发票")

    # 5. 面向对象 build 构建：当 entity_name 与 subpath 相同 (例如目录名就叫发票)
    dest_same = ArchiveDestinationPath.build(
        dest_root=r"D:\归档目标",
        category="财务报表",
        subpath="发票",
        entity_name="发票",
        is_dir=True
    )
    norm_same = dest_same.raw_path.replace("\\", "/")
    assert norm_same.endswith("财务报表/发票")
    assert "发票/发票" not in norm_same

    # 6. 面向对象 build 构建：当 dest_root 结尾与 category 相同 (例如 D:\发票 与 发票)
    dest_root_dup = ArchiveDestinationPath.build(
        dest_root=r"D:\发票",
        category="发票",
        subpath="2026",
        entity_name="08月",
        is_dir=True
    )
    norm_root_dup = dest_root_dup.raw_path.replace("\\", "/")
    assert "发票/发票" not in norm_root_dup
    assert norm_root_dup == "D:/发票/2026/08月"


def test_archive_destination_path_relative_join_and_safety():
    """验证 relative_join 子文件相对派生与路径安全性校验"""
    base = ArchiveDestinationPath(r"D:\归档目标\发票\2026")
    
    # 子文件拼接
    f1 = base.relative_join("0801_inv.pdf")
    assert f1.replace("\\", "/").endswith("发票/2026/0801_inv.pdf")

    # 相对深层子目录拼接
    f2 = base.relative_join(r"subfolder\data.xlsx")
    assert f2.replace("\\", "/").endswith("发票/2026/subfolder/data.xlsx")

    # 点或空相对路径保全自身
    assert base.relative_join(".") == str(base)
    assert base.relative_join("") == str(base)

    # 安全性检验
    safe, msg = base.is_safe()
    assert safe is True

    # 危险路径拦截 (根目录或遍历跨盘)
    unsafe_root = ArchiveDestinationPath(r"C:")
    safe_root, _ = unsafe_root.is_safe()
    assert safe_root is False

    unsafe_traverse = ArchiveDestinationPath(r"D:\归档\..\..\Windows")
    safe_trav, _ = unsafe_traverse.is_safe()
    assert safe_trav is False


def test_history_suggestion_provider(tmp_path):
    """验证历史数据供给服务的联想候选生成与历史记录去重"""
    # 记录历史路径
    HistorySuggestionProvider.record_path(r"D:\归档\发票\历史2025")
    HistorySuggestionProvider.record_path(r"D:\归档\财务\商务合同")
    
    # 再次记录同一路径不会重复出现
    HistorySuggestionProvider.record_path(r"D:\归档\发票\历史2025")
    assert HistorySuggestionProvider._recent_paths.count(str(Path(r"D:\归档\发票\历史2025"))) == 1

    # 获取分类候选建议
    cats = HistorySuggestionProvider.get_category_suggestions()
    assert len(cats) >= 8
    assert "未分类/待人工确认" in cats

    # 创建物理目录测试
    dest_dir = tmp_path / "归档目标"
    dest_dir.mkdir()
    (dest_dir / "已有发票库").mkdir()
    (dest_dir / "已有合同库").mkdir()

    paths = HistorySuggestionProvider.get_path_suggestions(
        dest_root=str(dest_dir),
        current_cat="发票凭证",
        app_name="8月发票"
    )
    # 应包含推荐路径及物理子目录
    paths_str = [p.replace("\\", "/") for p in paths]
    assert any("已有发票库" in p for p in paths_str)
    assert any("发票凭证" in p for p in paths_str)


def test_archive_planning_unit_oop():
    """验证 ArchivePlanningUnit 面向对象实体行为"""
    unit = ArchivePlanningUnit(
        group_id="grp_001",
        original_root=r"D:\待整理\发票\7月发票",
        app_name="7月发票",
        suggested_category="财务商务",
        target_root=r"D:\归档\财务商务\发票\7月发票",
        recommended_subpath="发票",
        is_directory_group=True,
        sub_items=[
            {"original_path": r"D:\待整理\发票\7月发票\inv01.pdf", "relative_path": "inv01.pdf", "target_path": ""}
        ]
    )

    # 字典兼容协议
    assert unit["group_id"] == "grp_001"
    assert unit.get("app_name") == "7月发票"

    # 修改分类并级联重新计算目标规划路径 (防发票/发票重复)
    unit.update_category("发票", dest_root=r"D:\归档")
    assert unit.effective_category == "发票"
    assert unit.source == "User"
    norm_t = unit.target_root.replace("\\", "/")
    assert "发票/发票" not in norm_t
    assert norm_t.endswith("发票/7月发票")
    # 子项同步更新
    assert unit.sub_items[0]["target_path"].replace("\\", "/").endswith("发票/7月发票/inv01.pdf")


def test_organize_preview_dialog_inplace_editing():
    """验证 OrganizePreviewDialog 就地编辑、防清空重写与全域同构级联更新"""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance() or QApplication(sys.argv)

    mock_group = {
        "group_id": "grp_001",
        "original_root": r"D:\原始目录\发票\8月发票",
        "app_name": "8月发票",
        "suggested_category": "文档与电子书 (Documents & Books)",
        "effective_category": "文档与电子书 (Documents & Books)",
        "target_root": r"D:\归档备份\文档与电子书 (Documents & Books)\发票\8月发票",
        "recommended_subpath": "发票",
        "is_directory_group": True,
        "source": "AI",
        "risk_level": "低风险",
        "confidence": 0.95,
        "action": "建议归档",
        "rationale": "命中发票凭证",
        "require_confirmation": False,
        "sub_items": [
            {
                "original_path": r"D:\原始目录\发票\8月发票\0801.pdf",
                "name": "0801.pdf",
                "size": 1024,
                "relative_path": "0801.pdf",
                "target_path": r"D:\归档备份\文档与电子书 (Documents & Books)\发票\8月发票\0801.pdf"
            }
        ]
    }

    dialog = OrganizePreviewDialog([mock_group], destination_root=r"D:\归档备份")
    assert dialog.tree.topLevelItemCount() == 1
    top_item = dialog.tree.topLevelItem(0)

    # 1. 验证第 2 列与第 3 列初始文本与可编辑标志
    assert top_item.flags() & Qt.ItemIsEditable
    assert top_item.text(2) == "文档与电子书 (Documents & Books)"
    assert r"发票\8月发票" in top_item.text(3)

    # 2. 验证防清空重写契约 (Zero-clearing Rule)
    delegate = dialog.tree_delegate
    # 模拟编辑第 3 列
    index_col3 = dialog.tree.model().index(0, 3)
    editor_col3 = delegate.createEditor(dialog.tree, None, index_col3)
    delegate.setEditorData(editor_col3, index_col3)

    # 核心检验：编辑框必须完整预填充原文本，绝不可清空！且处于全选就绪状态
    assert editor_col3.text() == mock_group["target_root"]
    assert editor_col3.selectedText() == mock_group["target_root"]

    # 3. 验证就地修改建议归档分类 (第 2 列)
    # 将分类改为 '发票'
    dialog._on_category_edited(top_item, "发票")
    assert top_item.text(2) == "发票"
    assert "User" in top_item.text(1)
    new_t = top_item.text(3).replace("\\", "/")
    # 必须去除 '发票/发票' 重复段
    assert "发票/发票" not in new_t
    assert new_t.endswith("发票/8月发票")
    # sub_items 同步更新
    assert mock_group["sub_items"][0]["target_path"].replace("\\", "/").endswith("发票/8月发票/0801.pdf")

    # 4. 验证就地修改目标规划路径 (第 3 列)
    custom_target = r"D:\归档备份\财务中心\2026年单据\8月发票"
    dialog._on_path_edited(top_item, custom_target)
    assert top_item.text(3) == custom_target
    assert mock_group["target_root"] == custom_target
    # 子文件目标相对派生同步更新
    assert mock_group["sub_items"][0]["target_path"] == os.path.join(custom_target, "0801.pdf")
