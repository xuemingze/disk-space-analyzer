import re

with open('app/ui/components/organize_dialog.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remove the connection of itemChanged to on_tree_item_changed
content = content.replace('self.tree.itemChanged.connect(self.on_tree_item_changed)', 'self.tree.itemChanged.connect(self._schedule_update_stats)')

# 2. Add debounce timer and update_stats method
stats_methods = '''
    def _schedule_update_stats(self, item, column):
        if column != 0: return
        if not hasattr(self, '_stats_timer'):
            from PySide6.QtCore import QTimer
            self._stats_timer = QTimer(self)
            self._stats_timer.setSingleShot(True)
            self._stats_timer.timeout.connect(self.update_stats)
        self._stats_timer.start(50) # 50ms debounce

    def update_stats(self):
        selected_count = 0
        total_bytes = 0
        
        def recurse(item):
            nonlocal selected_count, total_bytes
            u_data = item.data(0, Qt.UserRole) or {}
            if u_data.get("type") == "file" and item.checkState(0) == Qt.Checked:
                selected_count += 1
                sub = u_data.get("data", {})
                total_bytes += sub.get("size", 0)
            for i in range(item.childCount()):
                recurse(item.child(i))
                
        for i in range(self.tree.topLevelItemCount()):
            recurse(self.tree.topLevelItem(i))
            
        from app.utils.file_helper import format_size
        self.lbl_auto_checked.setText(f"已勾选: {selected_count}项 ({format_size(total_bytes)})")

    def get_selected_items(self):
'''
content = content.replace('    def get_selected_items(self):', stats_methods)

# 3. Fix the massive memory leak and freeze in _on_item_expanded
content = content.replace('child_item.setData(0, Qt.UserRole, {"type": "file", "data": sub, "group": group})', 'child_item.setData(0, Qt.UserRole, {"type": "file", "data": sub})')

# 4. Fix usages of group from child's UserRole
content = content.replace('g_info = u_data.get("data", {}) if u_data.get("type") == "group" else u_data.get("group", {})', 
'''if u_data.get("type") == "group":
                  g_info = u_data.get("data", {})
              else:
                  p = item.parent()
                  p_data = p.data(0, Qt.UserRole) if p else {}
                  g_info = p_data.get("data", {})''')

content = content.replace('''                sub_info = u_data.get("data", {})
                group_data = u_data.get("group", {})''', 
'''                sub_info = u_data.get("data", {})
                p = item.parent()
                p_data = p.data(0, Qt.UserRole) if p else {}
                group_data = p_data.get("data", {})''')

with open('app/ui/components/organize_dialog.py', 'w', encoding='utf-8') as f:
    f.write(content)
