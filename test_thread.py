import sys
import time
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem
from PySide6.QtCore import Qt, QThread, Signal

class BuilderThread(QThread):
    finished = Signal(list)
    def run(self):
        items = []
        for i in range(5000):
            item = QTreeWidgetItem()
            item.setText(0, f"Child {i}")
            items.append(item)
        self.finished.emit(items)

app = QApplication.instance() or QApplication(sys.argv)
tree = QTreeWidget()
parent = QTreeWidgetItem(tree)
parent.setText(0, "Parent")
tree.show()

def on_finished(items):
    print("Received items in main thread")
    parent.addChildren(items)
    print("Added to tree")
    app.quit()

thread = BuilderThread()
thread.finished.connect(on_finished)
thread.start()

app.exec()
print("Success")
