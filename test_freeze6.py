import sys
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication, QHeaderView, QTreeWidgetItem
from app.ui.components.organize_dialog import OrganizePreviewDialog
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
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

dlg.tree.setUpdatesEnabled(False)
new_children = []
risk_color = QColor("#10B981")
for sub in group.get("sub_items", []):
    child_item = QTreeWidgetItem()
    child_item.setFlags(child_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
    child_item.setCheckState(0, item.checkState(0))
    child_item.setData(0, Qt.UserRole, {"type": "file", "data": sub, "group": group})
    child_item.setText(0, sub.get("relative_path", ""))
    child_item.setText(1, "-")
    child_item.setText(2, group.get("effective_category", group.get("suggested_category", "")))
    child_item.setText(3, sub.get("target_path", ""))
    child_item.setText(4, "包含在目录单元中")
    child_item.setText(5, "100 B")
    child_item.setTextAlignment(5, Qt.AlignRight | Qt.AlignVCenter)
    child_item.setText(6, "-")
    child_item.setTextAlignment(6, Qt.AlignCenter)
    child_item.setText(7, "低风险")
    child_item.setTextAlignment(7, Qt.AlignCenter)
    child_item.setForeground(7, QBrush(risk_color))
    child_item.setText(8, group.get("action", ""))
    child_item.setTextAlignment(8, Qt.AlignCenter)
    child_item.setText(9, f"R:- | T:-")
    new_children.append(child_item)

print(f"{time.time() - t0:.4f}s: created objects", flush=True)

item.addChildren(new_children)
print(f"{time.time() - t0:.4f}s: added children", flush=True)

dlg.tree.setUpdatesEnabled(True)
print(f"{time.time() - t0:.4f}s: updates enabled", flush=True)

app.processEvents()
print(f"{time.time() - t0:.4f}s: processed events", flush=True)
