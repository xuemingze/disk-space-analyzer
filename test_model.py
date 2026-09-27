import sys
import time
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication, QTreeView, QStyledItemDelegate, QComboBox
from PySide6.QtCore import Qt, QAbstractItemModel, QModelIndex

class ArchiveTreeModel(QAbstractItemModel):
    def __init__(self, groups, parent=None):
        super().__init__(parent)
        self.groups = groups

    def index(self, row, column, parent=QModelIndex()):
        if not parent.isValid():
            return self.createIndex(row, column, self.groups[row])
        parent_group = parent.internalPointer()
        return self.createIndex(row, column, parent_group['sub_items'][row])

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        node = index.internalPointer()
        if 'sub_items' in node: # It's a group
            return QModelIndex()
        # It's a file, we need to find its group (slow if we don't store parent ref)
        # For performance, we can add a _parent key to files during init
        return self.createIndex(node['_parent_idx'], 0, node['_parent'])

    def rowCount(self, parent=QModelIndex()):
        if not parent.isValid():
            return len(self.groups)
        node = parent.internalPointer()
        if 'sub_items' in node:
            return len(node['sub_items'])
        return 0

    def columnCount(self, parent=QModelIndex()):
        return 10

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        node = index.internalPointer()
        if role == Qt.DisplayRole:
            return f"Node {index.row()} Col {index.column()}"
        return None

app = QApplication.instance() or QApplication(sys.argv)
groups = []
for i in range(10):
    g = {'sub_items': []}
    g['_idx'] = i
    for j in range(5000):
        g['sub_items'].append({'_parent': g, '_parent_idx': i})
    groups.append(g)

model = ArchiveTreeModel(groups)
tree = QTreeView()
tree.setModel(model)
tree.show()
app.processEvents()

t0 = time.time()
tree.expandAll()
app.processEvents()
print(f"Time to expandAll 50,000 items in QTreeView: {time.time() - t0:.4f}s")
