import re

with open('app/ui/components/organize_dialog.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace _on_item_expanded
old_on_expanded = '''    def _on_item_expanded(self, item):
        if item.childCount() == 1 and item.child(0).text(0) == "加载中...":
            u_data = item.data(0, Qt.UserRole)
            if not u_data or u_data.get("type") != "group": return
            
            # Remove dummy
            item.removeChild(item.child(0))
            
            group = u_data["data"]
            risk = group.get("risk_level", "未知风险")
            if "低风险" in risk:
                risk_color = QColor("#10B981")
            elif "中风险" in risk:
                risk_color = QColor("#F59E0B")
            else:
                risk_color = QColor("#EF4444")
                
            self.tree.setUpdatesEnabled(False)
            new_children = []
            for sub in group.get("sub_items", []):
                child_item = QTreeWidgetItem()
                child_item.setFlags(child_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                child_item.setCheckState(0, item.checkState(0))
                
                child_item.setData(0, Qt.UserRole, {"type": "file", "data": sub})
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
                child_item.setText(7, risk)
                child_item.setTextAlignment(7, Qt.AlignCenter)
                child_item.setForeground(7, QBrush(risk_color))
                child_item.setText(8, group.get("action", ""))
                child_item.setTextAlignment(8, Qt.AlignCenter)
                child_item.setText(9, f"R:{group.get('report_id','-')} | T:{group.get('task_id','-')}")
                new_children.append(child_item)
            item.addChildren(new_children)
            self.tree.setUpdatesEnabled(True)'''

new_on_expanded = '''    def _on_item_expanded(self, item):
        if item.childCount() == 1 and item.child(0).text(0) == "加载中...":
            u_data = item.data(0, Qt.UserRole)
            if not u_data or u_data.get("type") != "group": return
            
            item.removeChild(item.child(0))
            group = u_data["data"]
            sub_items = group.get("sub_items", [])
            total_files = len(sub_items)
            
            use_progress = total_files > 500
            progress = None
            if use_progress:
                progress = QProgressDialog("正在加载当前目录项...", "取消", 0, total_files, self)
                progress.setWindowTitle("节点展开")
                progress.setWindowModality(Qt.WindowModal)
                progress.setMinimumDuration(0)
            
            risk = group.get("risk_level", "未知风险")
            if "低风险" in risk: risk_color = QColor("#10B981")
            elif "中风险" in risk: risk_color = QColor("#F59E0B")
            else: risk_color = QColor("#EF4444")
                
            self.tree.setUpdatesEnabled(False)
            new_children = []
            files_processed = 0
            batch_size = 500
            
            from app.utils.file_helper import format_size
            
            try:
                for i, sub in enumerate(sub_items):
                    if use_progress and progress.wasCanceled():
                        break
                        
                    child_item = QTreeWidgetItem()
                    child_item.setFlags(child_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                    child_item.setCheckState(0, item.checkState(0))
                    
                    child_item.setData(0, Qt.UserRole, {"type": "file", "data": sub})
                    child_item.setText(0, sub.get("relative_path", ""))
                    child_item.setText(1, "-")
                    child_item.setText(2, group.get("effective_category", group.get("suggested_category", "")))
                    child_item.setText(3, sub.get("target_path", ""))
                    child_item.setText(4, "包含在目录单元中")
                    child_item.setText(5, format_size(sub.get("size", 0)))
                    child_item.setTextAlignment(5, Qt.AlignRight | Qt.AlignVCenter)
                    child_item.setText(6, "-")
                    child_item.setTextAlignment(6, Qt.AlignCenter)
                    child_item.setText(7, risk)
                    child_item.setTextAlignment(7, Qt.AlignCenter)
                    child_item.setForeground(7, QBrush(risk_color))
                    child_item.setText(8, group.get("action", ""))
                    child_item.setTextAlignment(8, Qt.AlignCenter)
                    child_item.setText(9, f"R:{group.get('report_id','-')} | T:{group.get('task_id','-')}")
                    new_children.append(child_item)
                    
                    if len(new_children) >= batch_size:
                        item.addChildren(new_children)
                        new_children = []
                        files_processed += batch_size
                        if use_progress:
                            progress.setValue(files_processed)
                            QApplication.processEvents()
                            
                if new_children:
                    item.addChildren(new_children)
                    files_processed += len(new_children)
                    if use_progress:
                        progress.setValue(files_processed)
            finally:
                self.tree.setUpdatesEnabled(True)
                if use_progress and progress:
                    progress.setValue(total_files)

    def _expand_all_with_progress(self):
        self.tree.itemExpanded.disconnect(self._on_item_expanded)
        groups_to_expand = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if not item.isExpanded():
                groups_to_expand.append(item)
                
        if not groups_to_expand:
            self.tree.itemExpanded.connect(self._on_item_expanded)
            return

        total_files = 0
        for item in groups_to_expand:
            u_data = item.data(0, Qt.UserRole)
            if u_data and u_data.get("type") == "group":
                total_files += len(u_data["data"].get("sub_items", []))

        progress = QProgressDialog("正在分批展开目录树...", "取消", 0, total_files, self)
        progress.setWindowTitle("批量展开")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        
        from app.utils.file_helper import format_size
        files_processed = 0
        batch_size = 500
        self.tree.setUpdatesEnabled(False)
        
        try:
            for item in groups_to_expand:
                if progress.wasCanceled():
                    break
                u_data = item.data(0, Qt.UserRole)
                if not u_data or u_data.get("type") != "group":
                    continue
                
                if item.childCount() == 1 and item.child(0).text(0) == "加载中...":
                    item.removeChild(item.child(0))
                    group = u_data["data"]
                    risk = group.get("risk_level", "未知风险")
                    if "低风险" in risk: risk_color = QColor("#10B981")
                    elif "中风险" in risk: risk_color = QColor("#F59E0B")
                    else: risk_color = QColor("#EF4444")
                    
                    sub_items = group.get("sub_items", [])
                    new_children = []
                    for i, sub in enumerate(sub_items):
                        if progress.wasCanceled():
                            break
                        child_item = QTreeWidgetItem()
                        child_item.setFlags(child_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                        child_item.setCheckState(0, item.checkState(0))
                        
                        child_item.setData(0, Qt.UserRole, {"type": "file", "data": sub})
                        child_item.setText(0, sub.get("relative_path", ""))
                        child_item.setText(1, "-")
                        child_item.setText(2, group.get("effective_category", group.get("suggested_category", "")))
                        child_item.setText(3, sub.get("target_path", ""))
                        child_item.setText(4, "包含在目录单元中")
                        child_item.setText(5, format_size(sub.get("size", 0)))
                        child_item.setTextAlignment(5, Qt.AlignRight | Qt.AlignVCenter)
                        child_item.setText(6, "-")
                        child_item.setTextAlignment(6, Qt.AlignCenter)
                        child_item.setText(7, risk)
                        child_item.setTextAlignment(7, Qt.AlignCenter)
                        child_item.setForeground(7, QBrush(risk_color))
                        child_item.setText(8, group.get("action", ""))
                        child_item.setTextAlignment(8, Qt.AlignCenter)
                        child_item.setText(9, f"R:{group.get('report_id','-')} | T:{group.get('task_id','-')}")
                        new_children.append(child_item)
                        
                        if len(new_children) >= batch_size:
                            item.addChildren(new_children)
                            new_children = []
                            files_processed += batch_size
                            progress.setValue(files_processed)
                            QApplication.processEvents()
                            
                    if new_children:
                        item.addChildren(new_children)
                        files_processed += len(new_children)
                        progress.setValue(files_processed)
                        QApplication.processEvents()
                item.setExpanded(True)
        finally:
            self.tree.setUpdatesEnabled(True)
            self.tree.itemExpanded.connect(self._on_item_expanded)
            progress.setValue(total_files)'''

content = content.replace(old_on_expanded, new_on_expanded)

# Change expandAll binding
content = content.replace(
    'self.btn_expand_all.clicked.connect(lambda: self.tree.expandAll())',
    'self.btn_expand_all.clicked.connect(self._expand_all_with_progress)'
)

with open('app/ui/components/organize_dialog.py', 'w', encoding='utf-8') as f:
    f.write(content)
