import sys
import os
import time
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication
from app.ui.components.organize_dialog import OrganizePreviewDialog
from PySide6.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)

print("=== AI 归档目录树防卡死专项测试 ===", flush=True)
groups = []
for i in range(10):
    group = {
        "original_root": f"C:/test/group_{i}",
        "app_name": f"App_{i}",
        "suggested_category": "工具",
        "sub_items": [{"relative_path": f"file_{j}.txt", "size": 100, "target_path": "D:/test"} for j in range(5000)]
    }
    groups.append(group)

t0 = time.time()
dlg = OrganizePreviewDialog(classification_items=groups, destination_root="D:/归档备份")
dlg.show()
app.processEvents()
print(f"1. 弹窗加载耗时 (50,000项数据): {time.time() - t0:.4f}s", flush=True)

print("2. 测试全部展开...", flush=True)
t1 = time.time()
# Fix disconnect warning
try:
    dlg.tree.itemExpanded.disconnect(dlg._on_item_expanded)
except:
    pass
dlg.tree.itemExpanded.connect(dlg._on_item_expanded)

dlg._expand_all_with_progress()
print(f"   展开 50,000 节点完成，总耗时: {time.time() - t1:.4f}s", flush=True)

t2 = time.time()
top_item = dlg.tree.topLevelItem(0)
top_item.setCheckState(0, Qt.Unchecked)
app.processEvents()
print(f"3. 取消勾选父节点 (级联 5,000 子节点) 耗时: {time.time() - t2:.4f}s", flush=True)

print("ALL TESTS PASSED!", flush=True)
sys.exit(0)
