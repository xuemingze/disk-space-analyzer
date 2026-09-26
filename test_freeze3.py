import sys
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication
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
dlg.tree.itemChanged.disconnect(dlg.on_tree_item_changed) # Disable old handler

# Disable AutoTristate on all items
for i in range(dlg.tree.topLevelItemCount()):
    item = dlg.tree.topLevelItem(i)
    item.setFlags(item.flags() & ~Qt.ItemIsAutoTristate)
    if item.childCount() > 0:
        item.child(0).setFlags(item.child(0).flags() & ~Qt.ItemIsAutoTristate)

dlg.show()
app.processEvents()

top_item = dlg.tree.topLevelItem(0)
dlg.tree.expandItem(top_item)
# Disable AutoTristate on new children
for i in range(top_item.childCount()):
    top_item.child(i).setFlags(top_item.child(i).flags() & ~Qt.ItemIsAutoTristate)
app.processEvents()

def manual_item_changed(item, column):
    if column != 0: return
    dlg.tree.setUpdatesEnabled(False)
    dlg.tree.blockSignals(True)
    state = item.checkState(0)
    if item.childCount() > 0:
        for i in range(item.childCount()):
            item.child(i).setCheckState(0, state)
    parent = item.parent()
    if parent:
        checked_count = 0
        partial_count = 0
        for i in range(parent.childCount()):
            ch_state = parent.child(i).checkState(0)
            if ch_state == Qt.Checked: checked_count += 1
            elif ch_state == Qt.PartiallyChecked: partial_count += 1
        if checked_count == parent.childCount(): parent.setCheckState(0, Qt.Checked)
        elif checked_count > 0 or partial_count > 0: parent.setCheckState(0, Qt.PartiallyChecked)
        else: parent.setCheckState(0, Qt.Unchecked)
    dlg.tree.blockSignals(False)
    dlg.tree.setUpdatesEnabled(True)

dlg.tree.itemChanged.connect(manual_item_changed)

start_time = time.time()
print("Setting check state...")
top_item.setCheckState(0, Qt.Unchecked)
manual_item_changed(top_item, 0) # Call manually since signals were blocked internally maybe? Actually setCheckState emits if blockSignals is false.
app.processEvents()
print(f"Time taken: {time.time() - start_time:.4f}s")
