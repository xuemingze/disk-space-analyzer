import sys
import time
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem
from PySide6.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)
tree = QTreeWidget()
parent = QTreeWidgetItem(tree)
parent.setText(0, "Parent")

items = []
for i in range(5000):
    item = QTreeWidgetItem()
    item.setText(0, f"Child {i}")
    item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
    item.setCheckState(0, Qt.Checked)
    items.append(item)

parent.addChildren(items)

print("Starting benchmark...")
start = time.time()
tree.setUpdatesEnabled(False)
tree.blockSignals(True)
for i in range(parent.childCount()):
    parent.child(i).setCheckState(0, Qt.Unchecked)
tree.blockSignals(False)
tree.setUpdatesEnabled(True)
print(f"Time taken: {time.time() - start:.4f}s")
