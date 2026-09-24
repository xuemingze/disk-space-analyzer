import os
import subprocess
from datetime import datetime
from typing import List, Dict, Any, Optional, Set

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView,
    QHeaderView, QMenu, QLineEdit, QLabel, QPushButton, QAbstractItemView,
    QApplication, QStyledItemDelegate
)
from PySide6.QtCore import Qt, QObject, Signal, QTimer, QAbstractTableModel, QModelIndex, QSortFilterProxyModel
from PySide6.QtGui import QAction, QColor, QBrush

from app.utils.file_helper import format_size


class FileTableModel(QAbstractTableModel):
    def __init__(self, data_list: List[Dict[str, Any]], is_selectable: bool, parent=None):
        super().__init__(parent)
        self._data = data_list
        self._is_selectable = is_selectable
        self._headers = ["勾选", "文件名", "分类", "大小", "处理阶段", "冗余/推荐标记", "查重分组", "修改时间", "完整绝对路径"]
        self.checked_paths: Set[str] = set()
        self.checked_bytes: int = 0

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(self._headers)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._data)):
            return None
            
        item = self._data[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 1: return item.get("name", "")
            elif col == 2: return item.get("category", "其他")
            elif col == 3: return format_size(item.get("size", 0))
            elif col == 4: return item.get("phase_status", "阶段一: 大小已归类")
            elif col == 5: return item.get("tag", "-")
            elif col == 6: 
                gid = item.get("duplicate_group_id", "")
                return gid if gid else "-"
            elif col == 7:
                mtime = item.get("mtime", 0)
                return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M") if mtime > 0 else "-"
            elif col == 8: return item.get("path", "")
            
        elif role == Qt.UserRole:
            return item
            
        elif role == Qt.CheckStateRole and col == 0 and self._is_selectable:
            return Qt.Checked if item.get("path") in self.checked_paths else Qt.Unchecked
            
        elif role == Qt.TextAlignmentRole:
            if col in (2, 4, 6, 7): return int(Qt.AlignCenter)
            if col == 3: return int(Qt.AlignRight | Qt.AlignVCenter)
            
        elif role == Qt.ForegroundRole:
            if col == 4:
                status = item.get("phase_status", "")
                if "哈希已确认" in status: return QBrush(QColor("#10B981"))
                elif "规则" in status: return QBrush(QColor("#38BDF8"))
                else: return QBrush(QColor("#94A3B8"))
            elif col == 5:
                tag = item.get("tag", "")
                if "重复副本" in tag: return QBrush(QColor("#F59E0B"))
                elif "安全可清理" in tag or "临时" in tag: return QBrush(QColor("#10B981"))
                elif "归档" in tag: return QBrush(QColor("#38BDF8"))
                
        elif role == Qt.ToolTipRole:
            if col == 1 or col == 8: return item.get("path", "")
            if col == 5: return item.get("reason", "")
            
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self._headers[section]
        return None

    def flags(self, index):
        default_flags = super().flags(index)
        if index.column() == 0 and self._is_selectable:
            return default_flags | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
        return default_flags

    def setData(self, index, value, role=Qt.EditRole):
        if role == Qt.CheckStateRole and index.column() == 0 and self._is_selectable:
            item = self._data[index.row()]
            path = item.get("path", "")
            size = int(item.get("size", 0))
            if value == Qt.Checked or value == Qt.Checked.value:
                if path not in self.checked_paths:
                    self.checked_paths.add(path)
                    self.checked_bytes += size
            else:
                if path in self.checked_paths:
                    self.checked_paths.remove(path)
                    self.checked_bytes -= size
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            return True
        return False

    def update_data(self, new_data: List[Dict[str, Any]]):
        self.beginResetModel()
        self._data = new_data
        self.checked_paths.clear()
        self.checked_bytes = 0
        for item in self._data:
            if item.get("is_recommended", False):
                self.checked_paths.add(item.get("path", ""))
                self.checked_bytes += int(item.get("size", 0))
        self.endResetModel()

    def remove_paths(self, paths: Set[str]):
        new_data = []
        for item in self._data:
            if item.get("path", "").lower() not in paths:
                new_data.append(item)
            else:
                path = item.get("path", "")
                if path in self.checked_paths:
                    self.checked_paths.remove(path)
                    self.checked_bytes -= int(item.get("size", 0))
        self.beginResetModel()
        self._data = new_data
        self.endResetModel()

    def select_all(self, checked: bool):
        self.beginResetModel()
        self.checked_paths.clear()
        self.checked_bytes = 0
        if checked:
            for item in self._data:
                self.checked_paths.add(item.get("path", ""))
                self.checked_bytes += int(item.get("size", 0))
        self.endResetModel()

    def invert_selection(self):
        self.beginResetModel()
        new_checked_paths = set()
        new_checked_bytes = 0
        for item in self._data:
            path = item.get("path", "")
            if path not in self.checked_paths:
                new_checked_paths.add(path)
                new_checked_bytes += int(item.get("size", 0))
        self.checked_paths = new_checked_paths
        self.checked_bytes = new_checked_bytes
        self.endResetModel()

    def select_recommended_only(self):
        self.beginResetModel()
        self.checked_paths.clear()
        self.checked_bytes = 0
        for item in self._data:
            if item.get("is_recommended", False):
                self.checked_paths.add(item.get("path", ""))
                self.checked_bytes += int(item.get("size", 0))
        self.endResetModel()

    def select_ai_recommended_paths(self, ai_paths: List[str]):
        path_set = {os.path.normpath(p).lower() for p in ai_paths}
        self.beginResetModel()
        self.checked_paths.clear()
        self.checked_bytes = 0
        for item in self._data:
            path = item.get("path", "")
            if os.path.normpath(path).lower() in path_set:
                self.checked_paths.add(path)
                self.checked_bytes += int(item.get("size", 0))
        self.endResetModel()


class FileSortFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.filter_kw = ""

    def set_filter_keyword(self, kw: str):
        self.filter_kw = kw.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if not self.filter_kw:
            return True
        model = self.sourceModel()
        item = model._data[source_row]
        kw = self.filter_kw
        
        name = item.get("name", "").lower()
        cat = item.get("category", "").lower()
        phase = item.get("phase_status", "").lower()
        tag = item.get("tag", "").lower()
        path = item.get("path", "").lower()
        
        if kw in name or kw in cat or kw in phase or kw in tag or kw in path:
            return True
        return False

    def lessThan(self, left, right):
        col = left.column()
        model = self.sourceModel()
        left_item = model._data[left.row()]
        right_item = model._data[right.row()]
        
        if col == 3:
            return left_item.get("size", 0) < right_item.get("size", 0)
        elif col == 7:
            return left_item.get("mtime", 0) < right_item.get("mtime", 0)
            
        left_str = model.data(left, Qt.DisplayRole) or ""
        right_str = model.data(right, Qt.DisplayRole) or ""
        return left_str < right_str


class FileDataGridWidget(QWidget):
    """
    极速响应、低延迟数据表格组件
    采用 QTableView + QAbstractTableModel 模型，单次装填内存复用，杜绝海量 QWidget 对象导致的冻结卡死。
    """
    selection_changed_signal = Signal(object, object) # (选中数量, 选中字节总数)
    migrate_requested_signal = Signal(list)            # (选中的路径列表)

    def __init__(self, is_selectable: bool = True, parent=None):
        super().__init__(parent)
        
        self.is_selectable = is_selectable
        
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(20)
        self._debounce_timer.timeout.connect(self._emit_selection_stats)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
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
        
        # 替代原先的 QTableWidget，改用 QTableView
        self.table_view = QTableView()
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table_view.setSortingEnabled(True)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self.show_context_menu)
        
        self.source_model = FileTableModel([], self.is_selectable, self)
        self.proxy_model = FileSortFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.source_model)
        self.table_view.setModel(self.proxy_model)
        
        self.source_model.dataChanged.connect(self._schedule_selection_update)
        self.source_model.modelReset.connect(self._schedule_selection_update)
        self.proxy_model.layoutChanged.connect(self._update_stats_label)
        
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table_view.setColumnWidth(0, 50)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        self.table_view.setColumnWidth(1, 190)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Interactive)
        self.table_view.setColumnWidth(5, 130)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.Stretch)
        
        layout.addWidget(self.table_view)

    def populate_data(self, data_list: List[Dict[str, Any]], total_scan_bytes: int = 0):
        self.source_model.update_data(data_list)
        self._update_stats_label()

    def _schedule_selection_update(self, *args):
        self._debounce_timer.start()

    def _emit_selection_stats(self):
        self.selection_changed_signal.emit(len(self.source_model.checked_paths), self.source_model.checked_bytes)

    def _update_stats_label(self):
        total = self.source_model.rowCount()
        visible = self.proxy_model.rowCount()
        if total == visible:
            self.stats_label.setText(f"共 {total} 个项目")
        else:
            self.stats_label.setText(f"显示 {visible} / {total} 个项目")

    def select_all(self, checked: bool = True):
        self.source_model.select_all(checked)

    def invert_selection(self):
        self.source_model.invert_selection()

    def select_recommended_only(self):
        self.source_model.select_recommended_only()

    def select_ai_recommended_paths(self, ai_paths: List[str]):
        self.source_model.select_ai_recommended_paths(ai_paths)

    def get_checked_paths(self) -> List[str]:
        return list(self.source_model.checked_paths)

    def remove_paths(self, paths_to_remove: List[str]):
        remove_set = {os.path.normpath(p).lower() for p in paths_to_remove}
        self.source_model.remove_paths(remove_set)
        self._update_stats_label()

    def apply_filter(self, keyword: str):
        self.proxy_model.set_filter_keyword(keyword)
        self._update_stats_label()

    def show_context_menu(self, pos):
        index = self.table_view.indexAt(pos)
        if not index.isValid():
            return
            
        source_index = self.proxy_model.mapToSource(index)
        item = self.source_model._data[source_index.row()]
        file_path = item.get("path", "")
        if not file_path:
            return
        
        menu = QMenu(self)
        action_open_dir = QAction("📂 在文件资源管理器中定位", self)
        action_open_dir.triggered.connect(lambda: self._locate_in_explorer(file_path))
        
        action_open_file = QAction("📄 打开文件", self)
        action_open_file.triggered.connect(lambda: self._open_file(file_path))
        
        action_migrate = QAction("📦 智能迁移此项", self)
        action_migrate.triggered.connect(lambda: self.migrate_requested_signal.emit([file_path]))
        
        action_copy_path = QAction("📋 复制绝对路径", self)
        action_copy_path.triggered.connect(lambda: QApplication.clipboard().setText(file_path))
        
        menu.addAction(action_open_dir)
        menu.addAction(action_open_file)
        menu.addSeparator()
        menu.addAction(action_migrate)
        menu.addSeparator()
        menu.addAction(action_copy_path)
        
        menu.exec(self.table_view.viewport().mapToGlobal(pos))

    def _locate_in_explorer(self, file_path: str):
        norm = os.path.normpath(file_path)
        if os.path.exists(norm):
            subprocess.Popen(f'explorer.exe /select,"{norm}"')

    def _open_file(self, file_path: str):
        norm = os.path.normpath(file_path)
        if os.path.exists(norm):
            os.startfile(norm)
