import sys
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication, QHeaderView, QTreeWidgetItem
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
dlg.tree.itemChanged.disconnect(dlg.on_tree_item_changed)
header = dlg.tree.header()
header.setSectionResizeMode(5, QHeaderView.Interactive)
header.setSectionResizeMode(6, QHeaderView.Interactive)
header.setSectionResizeMode(7, QHeaderView.Interactive)
header.setSectionResizeMode(8, QHeaderView.Interactive)
dlg.show()
app.processEvents()

top_item = dlg.tree.topLevelItem(0)

print("Starting manual expand", flush=True)
item = top_item
t0 = time.time()
u_data = item.data(0, Qt.UserRole)
group = u_data["data"]
item.removeChild(item.child(0))
print(f"{time.time() - t0:.4f}s: removed dummy", flush=True)

dlg.tree.setUpdatesEnabled(False)
new_children = []
for sub in group.get("sub_items", []):
    child_item = QTreeWidgetItem()
    child_item.setFlags(child_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
    child_item.setCheckState(0, item.checkState(0))
    new_children.append(child_item)

print(f"{time.time() - t0:.4f}s: created objects", flush=True)

item.addChildren(new_children)
print(f"{time.time() - t0:.4f}s: added children", flush=True)

dlg.tree.setUpdatesEnabled(True)
print(f"{time.time() - t0:.4f}s: updates enabled", flush=True)

app.processEvents()
print(f"{time.time() - t0:.4f}s: processed events", flush=True)

sys.exit(0)
