import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication
from app.ui.components.organize_dialog import OrganizePreviewDialog
from app.core.app_detector import AppDetector


def test_gui_dialog():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance() or QApplication(sys.argv)

    mock_files = [
        {"name": "index.js", "path": r"C:\Users\Administrator\.npm\package\index.js", "size": 1024},
        {"name": "package.json", "path": r"C:\Users\Administrator\.npm\package\package.json", "size": 512},
        {"name": "config.yaml", "path": r"C:\Users\Administrator\.npm\settings\config.yaml", "size": 256},
        {"name": "test.txt", "path": r"D:\docs\test.txt", "size": 2048}
    ]

    grouped_units = AppDetector.group_files_by_parent_or_tool(mock_files, r"D:\归档备份")
    dialog = OrganizePreviewDialog(grouped_units, destination_root=r"D:\归档备份")
    
    assert dialog.tree.topLevelItemCount() == 2, f"Expected 2 top-level tree items, got {dialog.tree.topLevelItemCount()}"
    
    # 模拟点击全选和仅选安全项
    dialog._set_all_checked_state(True)
    dialog._select_safe_only()
    
    print("✅ GUI OrganizePreviewDialog (QTreeWidget) 离线实例化与操作测试全部通过！")


if __name__ == "__main__":
    test_gui_dialog()
