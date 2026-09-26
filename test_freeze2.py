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

t0 = time.time()
print(f"{time.time() - t0:.4f}s: Creating dialog...", flush=True)
dlg = OrganizePreviewDialog(classification_items=groups, destination_root="D:/归档备份")

print(f"{time.time() - t0:.4f}s: Showing dialog...", flush=True)
dlg.show()
app.processEvents()

print(f"{time.time() - t0:.4f}s: Expanding item...", flush=True)
top_item = dlg.tree.topLevelItem(0)
dlg.tree.expandItem(top_item)

print(f"{time.time() - t0:.4f}s: Expanding item done, processing events...", flush=True)
app.processEvents()
print(f"{time.time() - t0:.4f}s: Item expanded and repainted.", flush=True)

start_time = time.time()
print(f"{time.time() - t0:.4f}s: Setting check state...", flush=True)
top_item.setCheckState(0, Qt.Unchecked)

print(f"{time.time() - t0:.4f}s: Check state set, processing events...", flush=True)
app.processEvents()
print(f"{time.time() - t0:.4f}s: Time taken to uncheck parent with 5000 children (without slot): {time.time() - start_time:.4f}s", flush=True)
sys.exit(0)
