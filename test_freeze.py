import sys
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication
from app.ui.components.organize_dialog import OrganizePreviewDialog
from PySide6.QtCore import Qt
import time

app = QApplication.instance() or QApplication(sys.argv)

# Generate a large fake tree
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
dlg.show()
app.processEvents()

# Expand first group to load children
top_item = dlg.tree.topLevelItem(0)
dlg.tree.expandItem(top_item)
app.processEvents()

# Test check state change
start_time = time.time()
print("Setting check state...")
top_item.setCheckState(0, Qt.Unchecked)
app.processEvents()
print(f"Time taken to uncheck parent with 5000 children: {time.time() - start_time:.4f}s")
