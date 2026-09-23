import os
import subprocess
from datetime import datetime
from typing import List, Dict, Any, Optional, Set

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QMenu, QLineEdit, QLabel, QPushButton, QAbstractItemView,
    QApplication
)
from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtGui import QAction, QColor, QBrush

from app.utils.file_helper import format_size


class NumericTableWidgetItem(QTableWidgetItem):
    """支持按真实数值而非字符串排序的表格项"""
    def __init__(self, display_text: str, numeric_value: float):
        super().__init__(display_text)
        self.numeric_value = numeric_value

    def __lt__(self, other):
        if isinstance(other, NumericTableWidgetItem):
            return self.numeric_value < other.numeric_value
        return super().__lt__(other)


class FileDataGridWidget(QWidget):
    """
    极速响应、低延迟数据表格组件
    采用 O(1) 增量选中追踪、单信号防抖节流与批量行更新机制
    """
    selection_changed_signal = Signal(object, object) # (选中数量, 选中字节总数)
    migrate_requested_signal = Signal(list)            # (选中的路径列表)

    def __init__(self, is_selectable: bool = True, parent=None):
        super().__init__(parent)
        self.is_selectable = is_selectable
        self.all_data_items: List[Dict[str, Any]] = []
        
        # O(1) 选中项增量计数缓存 (避免万级数据下的全表扫描)
        self._checked_paths: Set[str] = set()
        self._checked_bytes: int = 0
        
        # 信号防抖定时器 (20ms 节流)
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(20)
        self._debounce_timer.timeout.connect(self._emit_selection_stats)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # 顶层工具过滤条
        filter_bar = QHBoxLayout()
        filter_bar.setContentsMargins(0, 0, 0, 0)
        filter_bar.setSpacing(8)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 输入关键词快速过滤文件名、绝对路径、分类或处理阶段...")
        self.search_input.textChanged.connect(self.apply_filter)
        
        self.stats_label = QLabel("共 0 个项目")
        self.stats_label.setStyleSheet("color: #94A3B8; font-size: 12px;")
        
        filter_bar.addWidget(self.search_input, 1)
        filter_bar.addWidget(self.stats_label)
        
        layout.addLayout(filter_bar)
        
        # 表格本体
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "勾选", "文件名", "分类", "大小", "处理阶段", "冗余/推荐标记", "查重分组", "修改时间", "完整绝对路径"
        ])
        
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 50)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.setColumnWidth(1, 190)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Interactive)
        self.table.setColumnWidth(5, 130)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.Stretch)
        
        self.table.itemChanged.connect(self.on_item_changed)
        
        layout.addWidget(self.table)

    def populate_data(self, data_list: List[Dict[str, Any]], total_scan_bytes: int = 0):
        """批量装填数据 (禁用局部重绘以获得极致性能)"""
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        
        self.all_data_items = data_list
        self._checked_paths.clear()
        self._checked_bytes = 0
        
        self.table.setRowCount(len(data_list))
        
        for row, item in enumerate(data_list):
            fpath = item.get("path", "")
            fsize = int(item.get("size", 0))
            is_rec = item.get("is_recommended", False)
            
            # 0. 勾选框
            chk_item = QTableWidgetItem()
            if self.is_selectable:
                chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if is_rec:
                    chk_item.setCheckState(Qt.Checked)
                    self._checked_paths.add(fpath)
                    self._checked_bytes += fsize
                else:
                    chk_item.setCheckState(Qt.Unchecked)
            else:
                chk_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk_item.setData(Qt.UserRole, item)
            self.table.setItem(row, 0, chk_item)
            
            # 1. 文件名
            name_item = QTableWidgetItem(item["name"])
            name_item.setToolTip(fpath)
            self.table.setItem(row, 1, name_item)
            
            # 2. 分类
            cat_item = QTableWidgetItem(item.get("category", "其他"))
            cat_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, cat_item)
            
            # 3. 大小 (数值排序)
            size_item = NumericTableWidgetItem(format_size(fsize), fsize)
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 3, size_item)
            
            # 4. 处理阶段状态
            phase_status = item.get("phase_status", "阶段一: 大小已归类")
            phase_item = QTableWidgetItem(phase_status)
            phase_item.setTextAlignment(Qt.AlignCenter)
            if "哈希已确认" in phase_status:
                phase_item.setForeground(QBrush(QColor("#10B981")))
            elif "规则" in phase_status:
                phase_item.setForeground(QBrush(QColor("#38BDF8")))
            else:
                phase_item.setForeground(QBrush(QColor("#94A3B8")))
            self.table.setItem(row, 4, phase_item)
            
            # 5. 冗余标记 / 推荐理由
            tag = item.get("tag", "-")
            tag_item = QTableWidgetItem(tag)
            tag_item.setToolTip(item.get("reason", ""))
            
            if "重复副本" in tag:
                tag_item.setForeground(QBrush(QColor("#F59E0B")))
            elif "安全可清理" in tag or "临时" in tag:
                tag_item.setForeground(QBrush(QColor("#10B981")))
            elif "归档" in tag:
                tag_item.setForeground(QBrush(QColor("#38BDF8")))
            self.table.setItem(row, 5, tag_item)
            
            # 6. 查重分组
            dup_gid = item.get("duplicate_group_id", "")
            dup_item = QTableWidgetItem(dup_gid if dup_gid else "-")
            dup_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 6, dup_item)

            # 7. 修改时间
            mtime = item.get("mtime", 0)
            mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M") if mtime > 0 else "-"
            mtime_item = NumericTableWidgetItem(mtime_str, mtime)
            mtime_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 7, mtime_item)
            
            # 8. 完整绝对路径
            path_item = QTableWidgetItem(fpath)
            path_item.setToolTip(fpath)
            self.table.setItem(row, 8, path_item)

        self.table.setSortingEnabled(True)
        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)
        
        self.stats_label.setText(f"共 {len(data_list)} 个项目")
        self._schedule_selection_update()

    def on_item_changed(self, item: QTableWidgetItem):
        """O(1) 极速增量处理单项勾选变更"""
        if item.column() == 0:
            finfo = item.data(Qt.UserRole)
            if finfo:
                fpath = finfo.get("path", "")
                fsize = int(finfo.get("size", 0))
                if item.checkState() == Qt.Checked:
                    if fpath not in self._checked_paths:
                        self._checked_paths.add(fpath)
                        self._checked_bytes += fsize
                else:
                    if fpath in self._checked_paths:
                        self._checked_paths.remove(fpath)
                        self._checked_bytes -= fsize
                self._schedule_selection_update()

    def _schedule_selection_update(self):
        """通过防抖定时器合并短时间内的多次刷新"""
        self._debounce_timer.start()

    def _emit_selection_stats(self):
        self.selection_changed_signal.emit(len(self._checked_paths), self._checked_bytes)

    def select_all(self, checked: bool = True):
        """批量全选/清空 (单次内存遍历，避免逐行回刷)"""
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        
        self._checked_paths.clear()
        self._checked_bytes = 0
        
        target_state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                chk = self.table.item(row, 0)
                if chk and (chk.flags() & Qt.ItemIsUserCheckable):
                    chk.setCheckState(target_state)
                    if checked:
                        finfo = chk.data(Qt.UserRole)
                        if finfo:
                            self._checked_paths.add(finfo["path"])
                            self._checked_bytes += int(finfo.get("size", 0))

        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)
        self._schedule_selection_update()

    def invert_selection(self):
        """批量反选"""
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        
        self._checked_paths.clear()
        self._checked_bytes = 0
        
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                chk = self.table.item(row, 0)
                if chk and (chk.flags() & Qt.ItemIsUserCheckable):
                    new_state = Qt.Unchecked if chk.checkState() == Qt.Checked else Qt.Checked
                    chk.setCheckState(new_state)
                    if new_state == Qt.Checked:
                        finfo = chk.data(Qt.UserRole)
                        if finfo:
                            self._checked_paths.add(finfo["path"])
                            self._checked_bytes += int(finfo.get("size", 0))

        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)
        self._schedule_selection_update()

    def select_recommended_only(self):
        """仅勾选推荐项"""
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        
        self._checked_paths.clear()
        self._checked_bytes = 0
        
        for row in range(self.table.rowCount()):
            chk = self.table.item(row, 0)
            if chk and (chk.flags() & Qt.ItemIsUserCheckable):
                finfo = chk.data(Qt.UserRole) or {}
                if finfo.get("is_recommended", False):
                    chk.setCheckState(Qt.Checked)
                    self._checked_paths.add(finfo["path"])
                    self._checked_bytes += int(finfo.get("size", 0))
                else:
                    chk.setCheckState(Qt.Unchecked)

        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)
        self._schedule_selection_update()

    def select_ai_recommended_paths(self, ai_paths: List[str]):
        """根据 AI 返回结果精准批量勾选"""
        path_set = {os.path.normpath(p).lower() for p in ai_paths}
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        
        self._checked_paths.clear()
        self._checked_bytes = 0
        
        for row in range(self.table.rowCount()):
            chk = self.table.item(row, 0)
            if chk and (chk.flags() & Qt.ItemIsUserCheckable):
                finfo = chk.data(Qt.UserRole) or {}
                fpath = os.path.normpath(finfo.get("path", "")).lower()
                if fpath in path_set:
                    chk.setCheckState(Qt.Checked)
                    self._checked_paths.add(finfo["path"])
                    self._checked_bytes += int(finfo.get("size", 0))

        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)
        self._schedule_selection_update()

    def get_checked_paths(self) -> List[str]:
        return list(self._checked_paths)

    def remove_paths(self, paths_to_remove: List[str]):
        """高效批量移除已处理的行"""
        remove_set = {os.path.normpath(p).lower() for p in paths_to_remove}
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        
        for row in range(self.table.rowCount() - 1, -1, -1):
            chk = self.table.item(row, 0)
            if chk:
                finfo = chk.data(Qt.UserRole) or {}
                fpath = os.path.normpath(finfo.get("path", "")).lower()
                if fpath in remove_set:
                    if finfo.get("path", "") in self._checked_paths:
                        self._checked_paths.remove(finfo["path"])
                        self._checked_bytes -= int(finfo.get("size", 0))
                    self.table.removeRow(row)
                    
        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)
        self.stats_label.setText(f"共 {self.table.rowCount()} 个项目")
        self._schedule_selection_update()

    def apply_filter(self, keyword: str):
        kw = keyword.strip().lower()
        visible_count = 0
        self.table.setUpdatesEnabled(False)
        for row in range(self.table.rowCount()):
            if not kw:
                self.table.setRowHidden(row, False)
                visible_count += 1
                continue
                
            name = self.table.item(row, 1).text().lower()
            cat = self.table.item(row, 2).text().lower()
            phase = self.table.item(row, 4).text().lower()
            tag = self.table.item(row, 5).text().lower()
            path = self.table.item(row, 8).text().lower()
            
            if kw in name or kw in cat or kw in phase or kw in tag or kw in path:
                self.table.setRowHidden(row, False)
                visible_count += 1
            else:
                self.table.setRowHidden(row, True)
                
        self.table.setUpdatesEnabled(True)
        self.stats_label.setText(f"显示 {visible_count} / {self.table.rowCount()} 个项目")

    def show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item:
            return
            
        row = item.row()
        path_item = self.table.item(row, 8)
        if not path_item:
            return
            
        file_path = path_item.text()
        
        menu = QMenu(self)
        action_open_dir = QAction("📂 在文件资源管理器中定位", self)
        action_open_dir.triggered.connect(lambda: self._locate_in_explorer(file_path))
        
        action_open_file = QAction("📄 打开文件", self)
        action_open_file.triggered.connect(lambda: self._open_file(file_path))
        
        action_migrate = QAction("📦 智能迁移此项 (含快捷方式/注册表同步)", self)
        action_migrate.triggered.connect(lambda: self.migrate_requested_signal.emit([file_path]))
        
        action_copy_path = QAction("📋 复制绝对路径", self)
        action_copy_path.triggered.connect(lambda: QApplication.clipboard().setText(file_path))
        
        menu.addAction(action_open_dir)
        menu.addAction(action_open_file)
        menu.addSeparator()
        menu.addAction(action_migrate)
        menu.addSeparator()
        menu.addAction(action_copy_path)
        
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _locate_in_explorer(self, file_path: str):
        norm = os.path.normpath(file_path)
        if os.path.exists(norm):
            subprocess.Popen(f'explorer.exe /select,"{norm}"')

    def _open_file(self, file_path: str):
        norm = os.path.normpath(file_path)
        if os.path.exists(norm):
            os.startfile(norm)
