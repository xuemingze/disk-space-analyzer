import sys
import os
import time
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication, QTreeWidgetItem
from PySide6.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)
group = {
    "name": "Test",
    "sub_items": [{"path": f"file_{j}.txt", "size": 100} for j in range(5000)]
}

start = time.time()
item = QTreeWidgetItem()
for i in range(500):
    item.setData(0, Qt.UserRole, {"type": "file", "group": group})

print(f"Time for 500 setData calls: {time.time() - start:.4f}s")
