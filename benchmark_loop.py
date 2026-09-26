import sys
import time
from PySide6.QtWidgets import QApplication, QTreeWidgetItem
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush

app = QApplication.instance() or QApplication(sys.argv)
risk_color = QColor("#10B981")
group = {"effective_category": "Tool", "suggested_category": "Tool", "action": "Move", "report_id": "r1", "task_id": "t1"}

start = time.time()
new_children = []
for i in range(5000):
    sub = {"relative_path": f"file_{i}.txt", "size": 1024, "target_path": "D:/test"}
    child_item = QTreeWidgetItem()
    child_item.setFlags(child_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
    child_item.setCheckState(0, Qt.Checked)
    
    child_item.setData(0, Qt.UserRole, {"type": "file", "data": sub, "group": group})
    child_item.setText(0, sub.get("relative_path", ""))
    child_item.setText(1, "-")
    child_item.setText(2, group.get("effective_category", group.get("suggested_category", "")))
    child_item.setText(3, sub.get("target_path", ""))
    child_item.setText(4, "包含在目录单元中")
    from app.utils.file_helper import format_size
    child_item.setText(5, format_size(sub.get("size", 0)))
    child_item.setTextAlignment(5, Qt.AlignRight | Qt.AlignVCenter)
    child_item.setText(6, "-")
    child_item.setTextAlignment(6, Qt.AlignCenter)
    child_item.setText(7, "低风险")
    child_item.setTextAlignment(7, Qt.AlignCenter)
    child_item.setForeground(7, QBrush(risk_color))
    child_item.setText(8, group.get("action", ""))
    child_item.setTextAlignment(8, Qt.AlignCenter)
    child_item.setText(9, f"R:{group.get('report_id','-')} | T:{group.get('task_id','-')}")
    new_children.append(child_item)

print(f"Time taken to create 5000 items: {time.time() - start:.4f}s")
