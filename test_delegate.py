import sys
import time
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication, QTreeView, QStyledItemDelegate, QComboBox
from PySide6.QtCore import Qt, QAbstractItemModel, QModelIndex
from model import ArchiveTreeModel

class CategoryDelegate(QStyledItemDelegate):
    def __init__(self, active_categories, parent=None):
        super().__init__(parent)
        self.active_categories = active_categories

    def createEditor(self, parent, option, index):
        if not index.internalPointer()['is_group']: return None
        combo = QComboBox(parent)
        cats = ["未分类/待人工确认"] + [c["name"] for c in self.active_categories]
        combo.addItems(cats)
        return combo

    def setEditorData(self, editor, index):
        editor.setCurrentText(index.data(Qt.DisplayRole))

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)

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

print("Init model", flush=True)
model = ArchiveTreeModel(groups, [{"name": "工具"}, {"name": "文档"}])
tree = QTreeView()
tree.setModel(model)
delegate = CategoryDelegate([{"name": "工具"}, {"name": "文档"}], tree)
tree.setItemDelegateForColumn(2, delegate)

print("Open persistent editors", flush=True)
for r in range(model.rowCount()):
    idx = model.index(r, 2)
    tree.openPersistentEditor(idx)

print("Show tree", flush=True)
tree.show()
app.processEvents()

print("Expand all", flush=True)
t0 = time.time()
tree.expandAll()
app.processEvents()
print(f"ExpandAll time: {time.time() - t0:.4f}s", flush=True)
sys.exit(0)
