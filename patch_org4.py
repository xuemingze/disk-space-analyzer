import re

with open('app/ui/components/organize_dialog.py', 'r', encoding='utf-8') as f:
    content = f.read()

stats_methods = '''    def _schedule_update_stats(self, item, column):
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
        from PySide6.QtCore import Qt
        
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

    def export_script(self):'''

content = content.replace('    def export_script(self):', stats_methods)

with open('app/ui/components/organize_dialog.py', 'w', encoding='utf-8') as f:
    f.write(content)
