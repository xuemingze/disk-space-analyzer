import os
import json
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QPushButton, QLabel, QMessageBox
)
from PySide6.QtCore import Qt
from app.utils.file_helper import format_size
from app.core.cleaner import ARCHIVE_MANIFEST_DIR
from app.core.rollback_worker import RollbackWorker, SnapshotDeleteWorker

class RollbackWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rollback_worker = None
        self.current_manifest = None
        self.init_ui()
        
        from app.core.events import event_bus
        event_bus.files_state_changed.connect(self.on_global_files_changed, Qt.QueuedConnection)

    def on_global_files_changed(self, event_type: str, processed_paths: list, task_id: str, payload: dict):
        if event_type in ("archived", "rollbacked", "snapshots_deleted"):
            self.load_manifests()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        splitter = QSplitter(Qt.Horizontal)
        
        # 左侧：列表
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        self.list_widget.itemSelectionChanged.connect(self.on_manifest_selected)
        
        btn_refresh = QPushButton("🔄 刷新快照列表")
        btn_refresh.clicked.connect(self.load_manifests)
        
        left_layout.addWidget(QLabel("📂 历史归档/备份记录"))
        left_layout.addWidget(self.list_widget)
        left_layout.addWidget(btn_refresh)
        
        self.btn_delete_selected = QPushButton("🗑️ 删除选中快照")
        self.btn_delete_selected.clicked.connect(self.delete_selected_snapshots)
        self.btn_clean_all = QPushButton("🧹 一键清理无用快照")
        self.btn_clean_all.clicked.connect(self.clean_all_snapshots)
        
        left_layout.addWidget(self.btn_delete_selected)
        left_layout.addWidget(self.btn_clean_all)
        
        # 右侧：树状详情
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(["文件/目录", "当前归档路径", "预计恢复路径", "大小", "回滚状态", "详情"])
        self.tree_widget.setColumnWidth(0, 250)
        self.tree_widget.setColumnWidth(1, 200)
        self.tree_widget.setColumnWidth(2, 200)
        self.tree_widget.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree_widget.itemChanged.connect(self.on_tree_item_changed)
        
        self.lbl_info = QLabel("请选择左侧归档记录")
        
        btn_layout = QHBoxLayout()
        self.btn_select_all = QPushButton("全选可回滚项")
        self.btn_select_all.clicked.connect(self.select_all_rollbackable)
        self.btn_rollback_selected = QPushButton("🔙 回滚选中项")
        self.btn_rollback_selected.clicked.connect(self.execute_selective_rollback)
        self.btn_rollback_all = QPushButton("⏪ 回滚整个归档")
        self.btn_rollback_all.clicked.connect(self.execute_full_rollback)
        self.btn_rollback_all.setStyleSheet("background-color: #EF4444; color: white;")
        
        btn_layout.addWidget(self.btn_select_all)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_rollback_selected)
        btn_layout.addWidget(self.btn_rollback_all)
        
        right_layout.addWidget(self.lbl_info)
        right_layout.addWidget(self.tree_widget)
        right_layout.addLayout(btn_layout)
        
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([300, 700])
        
        layout.addWidget(splitter)
        self.load_manifests()
        
    def load_manifests(self):
        self.list_widget.clear()
        self.tree_widget.clear()
        self.current_manifest = None
        self.lbl_info.setText("请选择左侧归档记录")
        
        if not ARCHIVE_MANIFEST_DIR.exists():
            return
            
        manifest_files = list(ARCHIVE_MANIFEST_DIR.glob("manifest_*.json"))
        manifest_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        for file in manifest_files:
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    item = QListWidgetItem()
                    
                    b_id = data.get("backup_id", "Unknown")
                    c_time = data.get("created_at", 0)
                    import datetime
                    c_time_str = datetime.datetime.fromtimestamp(c_time).strftime("%Y-%m-%d %H:%M")
                    status = data.get("rollback_status", "NONE")
                    
                    item.setText(f"{c_time_str} | {b_id}\\n状态: {status}")
                    item.setData(Qt.UserRole, str(file))
                    self.list_widget.addItem(item)
            except:
                pass

    def on_manifest_selected(self):
        selected = self.list_widget.selectedItems()
        if not selected:
            return
            
        file_path = selected[0].data(Qt.UserRole)
        self.tree_widget.clear()
        self.current_manifest = file_path
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self.lbl_info.setText(f"读取快照失败: {e}")
            return
            
        items = data.get("items", [])
        
        # 统计
        total_size = sum(it.get("size", 0) for it in items)
        total_count = len(items)
        rollbackable = sum(1 for it in items if it.get("operation_status") == "success" and it.get("rollback_status") != "success")
        
        self.lbl_info.setText(
            f"归档目录: {data.get('destination_root')}\\n"
            f"文件数: {total_count} | 总大小: {format_size(total_size)} | "
            f"可回滚: {rollbackable}"
        )
        
        # 构建树
        root_nodes = {}
        for it in items:
            orig = it.get("original_path", "")
            arch = it.get("archived_path") or it.get("target_path", "")
            size = format_size(it.get("size", 0))
            op_status = it.get("operation_status", "")
            rb_status = it.get("rollback_status", "")
            e_id = it.get("entry_id", "")
            
            p = Path(orig)
            parent = str(p.parent)
            
            # Find or create parent node
            if parent not in root_nodes:
                p_node = QTreeWidgetItem(self.tree_widget)
                p_node.setText(0, parent)
                p_node.setFlags(p_node.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                p_node.setCheckState(0, Qt.Unchecked)
                root_nodes[parent] = p_node
                
            node = QTreeWidgetItem(root_nodes[parent])
            node.setText(0, p.name)
            node.setText(1, arch)
            node.setText(2, orig)
            node.setText(3, size)
            
            status_text = f"归档:{op_status} 回滚:{rb_status}"
            node.setText(4, status_text)
            node.setText(5, it.get("error_message", ""))
            node.setData(0, Qt.UserRole, e_id)
            
            # 如果可以回滚，允许勾选
            if op_status == "success" and rb_status != "success":
                node.setFlags(node.flags() | Qt.ItemIsUserCheckable)
                node.setCheckState(0, Qt.Unchecked)
            else:
                node.setFlags(node.flags() & ~Qt.ItemIsUserCheckable)
                if rb_status == "success":
                    node.setForeground(0, Qt.green)
                else:
                    node.setForeground(0, Qt.red)
                    
        self.tree_widget.expandAll()

    def on_tree_item_changed(self, item, column):
        pass

    def select_all_rollbackable(self):
        iterator = QTreeWidget.QTreeWidgetItemIterator(self.tree_widget)
        while iterator.value():
            item = iterator.value()
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(0, Qt.Checked)
            iterator += 1

    def execute_selective_rollback(self):
        if not self.current_manifest:
            return
            
        selected_ids = []
        iterator = QTreeWidget.QTreeWidgetItemIterator(self.tree_widget)
        while iterator.value():
            item = iterator.value()
            if item.childCount() == 0 and item.checkState(0) == Qt.Checked:
                e_id = item.data(0, Qt.UserRole)
                if e_id:
                    selected_ids.append(e_id)
            iterator += 1
            
        if not selected_ids:
            QMessageBox.warning(self, "提示", "未选中任何可回滚文件")
            return
            
        reply = QMessageBox.question(self, "确认", f"确定要回滚选中的 {len(selected_ids)} 个文件吗？")
        if reply == QMessageBox.Yes:
            self.do_rollback(selected_ids)

    def execute_full_rollback(self):
        if not self.current_manifest:
            return
            
        reply = QMessageBox.question(self, "确认", "确定要回滚当前归档下的所有可回滚文件吗？\\n警告: 此操作将撤销该批次的所有归档操作！")
        if reply == QMessageBox.Yes:
            self.do_rollback(None)
            
    def do_rollback(self, selected_ids):
        self.rollback_worker = RollbackWorker(self.current_manifest, selected_ids)
        from app.core.task_manager import global_task_manager, TaskType, TaskStatus
        self.current_task_id = global_task_manager.create_task("回滚还原快照", TaskType.CLEANUP, self.rollback_worker).task_id
        self.rollback_worker.finished_signal.connect(self.on_rollback_finished)
        self.rollback_worker.start()
        
    def on_rollback_finished(self, success, summary):
        if hasattr(self, "current_task_id") and self.current_task_id:
            from app.core.task_manager import global_task_manager, TaskStatus
            global_task_manager.set_task_status(self.current_task_id, TaskStatus.COMPLETED if success else TaskStatus.FAILED)
        msg = f"回滚完成！\\n成功: {summary['success_count']}，失败: {summary['failed_count']}，跳过: {summary['skipped_count']}"
        if success:
            QMessageBox.information(self, "回滚成功", msg)
        else:
            QMessageBox.warning(self, "回滚存在异常", msg)
        self.on_manifest_selected()

    def delete_selected_snapshots(self):
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "提示", "请先选择要删除的快照！")
            return
            
        paths = [item.data(Qt.UserRole) for item in selected_items]
        
        # Format confirmation message
        msg = f"确定要删除选中的 {len(paths)} 个归档快照吗？\\n注意：正在回滚中的快照将自动跳过。"
        if QMessageBox.question(self, "删除确认", msg) != QMessageBox.Yes:
            return
            
        self._start_delete_worker(paths, clean_all=False)
        
    def clean_all_snapshots(self):
        msg = "确定要一键清理所有已失效或完全回滚的无用快照吗？\\n（已完成回滚或已取消的快照将被彻底删除，未回滚的快照将被保留。）"
        if QMessageBox.question(self, "清理确认", msg) != QMessageBox.Yes:
            return
            
        self._start_delete_worker([], clean_all=True)
        
    def _start_delete_worker(self, paths, clean_all):
        self.btn_delete_selected.setEnabled(False)
        self.btn_clean_all.setEnabled(False)
        
        self.delete_worker = SnapshotDeleteWorker(paths, clean_all=clean_all)
        from app.core.task_manager import global_task_manager, TaskType, TaskStatus
        self.current_del_task_id = global_task_manager.create_task("清理归档快照", TaskType.CLEANUP, self.delete_worker).task_id
        
        self.delete_worker.finished_signal.connect(self.on_delete_finished)
        self.delete_worker.start()
        
    def on_delete_finished(self, success, summary):
        self.btn_delete_selected.setEnabled(True)
        self.btn_clean_all.setEnabled(True)
        
        if hasattr(self, "current_del_task_id") and self.current_del_task_id:
            from app.core.task_manager import global_task_manager, TaskStatus
            global_task_manager.set_task_status(self.current_del_task_id, TaskStatus.COMPLETED)
            
        QMessageBox.information(self, "清理完成", f"操作完成！\\n成功删除: {summary['success_count']} 个\\n跳过/占用: {summary['skipped_count']} 个\\n失败: {summary['failed_count']} 个")
