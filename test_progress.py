import sys
import time
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem, QProgressDialog
from PySide6.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)
tree = QTreeWidget()
parent = QTreeWidgetItem(tree)
parent.setText(0, "Parent")
tree.show()
app.processEvents()

def load_with_progress():
    progress = QProgressDialog("正在加载节点...", "取消", 0, 50000, tree)
    progress.setWindowModality(Qt.WindowModal)
    progress.setMinimumDuration(0)
    
    batch_size = 500
    for i in range(0, 50000, batch_size):
        if progress.wasCanceled():
            print("Cancelled!")
            break
            
        batch = []
        for j in range(i, min(i + batch_size, 50000)):
            item = QTreeWidgetItem()
            item.setText(0, f"Child {j}")
            batch.append(item)
            
        tree.setUpdatesEnabled(False)
        parent.addChildren(batch)
        tree.setUpdatesEnabled(True)
        
        progress.setValue(i + batch_size)
        app.processEvents()

t0 = time.time()
load_with_progress()
print(f"Time: {time.time() - t0:.4f}s")
