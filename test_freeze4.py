import sys
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication, QHeaderView
from app.ui.components.organize_dialog import OrganizePreviewDialog
from PySide6.QtCore import Qt
import time

app = QApplication.instance() or QApplication(sys.argv)

groups = []
for i in range(10):
    group = {
        "original_root": f"C:/test/group_{i}",
        "app_name": f"App_{i}",
        "suggested_category": "工具",
        "sub_items": [{"relative_path": f"file_{j}.txt", "size": 100} for j in range(5000)]
    }
    groups.append(group)

dlg = OrganizePreviewDialog(classification_items=groups, destination_root="D:/归档备份")
dlg.tree.itemChanged.disconnect(dlg.on_tree_item_changed) # Disable the manual handler!

# DISABLE ResizeToContents!
header = dlg.tree.header()
header.setSectionResizeMode(5, QHeaderView.Interactive)
dlg.tree.setColumnWidth(5, 80)
header.setSectionResizeMode(6, QHeaderView.Interactive)
dlg.tree.setColumnWidth(6, 40)
header.setSectionResizeMode(7, QHeaderView.Interactive)
dlg.tree.setColumnWidth(7, 80)
header.setSectionResizeMode(8, QHeaderView.Interactive)
dlg.tree.setColumnWidth(8, 80)

dlg.show()
app.processEvents()

t0 = time.time()
print(f"{time.time() - t0:.4f}s: Expanding item...", flush=True)
top_item = dlg.tree.topLevelItem(0)
dlg.tree.expandItem(top_item)

print(f"{time.time() - t0:.4f}s: Expanding item done, processing events...", flush=True)
app.processEvents()
print(f"{time.time() - t0:.4f}s: Item expanded and repainted.", flush=True)
