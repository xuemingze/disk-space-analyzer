import sys
import time
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem
from PySide6.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)
tree = QTreeWidget()
parent = QTreeWidgetItem(tree)
parent.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate | Qt.ItemIsEnabled)
parent.setCheckState(0, Qt.Checked)
parent.setText(0, "Parent")

items = []
for i in range(5000):
    item = QTreeWidgetItem()
    item.setText(0, f"Child {i}")
    item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate | Qt.ItemIsEnabled)
    item.setCheckState(0, Qt.Checked)
    items.append(item)
parent.addChildren(items)

tree.show()
tree.expandItem(parent)
app.processEvents()

print("Starting benchmark with visible tree...")
start = time.time()
parent.setCheckState(0, Qt.Unchecked)
app.processEvents()
print(f"Time taken: {time.time() - start:.4f}s")
