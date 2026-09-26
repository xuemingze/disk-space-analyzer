import sys
import time
from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem
from PySide6.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)
tree = QTreeWidget()
parent = QTreeWidgetItem(tree)
parent.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate | Qt.ItemIsEnabled)
parent.setCheckState(0, Qt.Checked)
parent.setText(0, "Parent")
tree.show()
app.processEvents()

items = []
for i in range(5000):
    item = QTreeWidgetItem()
    item.setText(0, f"Child {i}")
    item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate | Qt.ItemIsEnabled)
    item.setCheckState(0, Qt.Checked)
    items.append(item)

start = time.time()
tree.setUpdatesEnabled(False)
parent.addChildren(items)
tree.setUpdatesEnabled(True)
app.processEvents()
print(f"Time taken to add 5000 children and process events: {time.time() - start:.4f}s")
