import os
import subprocess
from datetime import datetime
from typing import List, Dict, Any, Optional, Set

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView,
    QHeaderView, QMenu, QLineEdit, QLabel, QPushButton, QAbstractItemView,
    QApplication, QStyledItemDelegate, QMessageBox
)
from PySide6.QtCore import Qt, QObject, Signal, QTimer, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QEvent
from PySide6.QtGui import QAction, QColor, QBrush

from app.utils.file_helper import format_size


class FileTableModel(QAbstractTableModel):
    def __init__(self, data_list: List[Dict[str, Any]], is_selectable: bool, parent=None):
        super().__init__(parent)
        self._data = data_list
        self._is_selectable = is_selectable
        self._headers = ["勾选", "资产项 / 实体名称", "高阶全景分类", "建议归档规划路径", "占用大小", "治理形态与阶段", "治理标记 / 建议", "查重分组", "修改时间", "完整绝对路径"]
        self.checked_paths: Set[str] = set()
        self.checked_bytes: int = 0
        self._on_path_edited_handler = None

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(self._headers)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._data)):
            return None
            
        item = self._data[index.row()]
        col = index.column()

        if role in (Qt.DisplayRole, Qt.EditRole):
            if col == 1:
                name = item.get("name", "")
                if item.get("is_directory_collective"):
                    c_info = item.get("collective_info") or {}
                    c_type = c_info.get("type", "") or c_info.get("collective_type", "")
                    app_name = c_info.get("app_name") or c_info.get("project_name") or c_info.get("software_name")
                    f_count = item.get("file_count", 1)
                    if "缓存" in c_type or c_info.get("is_cache") is True:
                        prefix = f"🗑️ [缓存集体: {app_name}] " if app_name else "🗑️ [缓存集体] "
                    elif "软件" in c_type or c_type == "standalone_app":
                        prefix = f"📦 [独立软件: {app_name}] " if app_name else "📦 [独立软件] "
                    elif "工程" in c_type or c_type == "dev_project":
                        prefix = f"💻 [工程代码: {app_name}] " if app_name else "💻 [工程代码] "
                    elif "Live2D" in c_type or "模型" in c_type:
                        prefix = f"🎨 [Live2D模型: {name}] "
                    elif "账套" in c_type or "发票" in c_type:
                        prefix = f"📂 [业务账套: {name}] "
                    elif "业务实体" in c_type or c_type == "business_entity":
                        prefix = f"📂 [业务实体: {name}] "
                    else:
                        prefix = "📁 [实体集体] "
                    return f"{prefix}{name} ({f_count:,} 个子文件)"
                # 语义化外显标识：根据资产类型与治理标记动态展示专属前缀
                tag = item.get("tag", "")
                cat = item.get("category", "")
                if "安装" in tag or "安装" in cat or "程序" in tag:
                    prefix = "📦 [安装程序] "
                elif "归档" in tag or "压缩" in cat:
                    prefix = "🗜️ [归档包] "
                elif "账套" in tag or "单据" in tag or "文档" in cat or "发票" in tag:
                    prefix = "📑 [业务单据] "
                elif "代码" in tag or "代码" in cat or "工程" in cat:
                    prefix = "💻 [代码文件] "
                elif "设计" in tag or "图像" in cat or "模型" in tag:
                    prefix = "🎨 [设计素材] "
                elif "视频" in cat or "音频" in cat or "媒体" in cat:
                    prefix = "🎬 [多媒体] "
                elif "副本" in tag or "冲突" in tag:
                    prefix = "⚠️ [副本冲突] "
                elif "临时" in tag or "日志" in tag or "缓存" in tag:
                    prefix = "🗑️ [临时日志] "
                else:
                    prefix = "📄 [独立资产] "
                return f"{prefix}{name}"
            elif col == 2:
                cat = item.get("category", "其他")
                prefix = "🏷️ "
                if item.get("is_directory_collective"):
                    f_count = item.get("file_count", 1)
                    return f"{prefix}{cat} [{f_count:,} 子文件]"
                return f"{prefix}{cat}"
            elif col == 3:
                subpath = item.get("target_subpath") or item.get("suggested_archive_path") or item.get("planning_path") or item.get("recommended_subpath") or ""
                if not subpath:
                    cat = item.get("category", "")
                    name = item.get("name", "")
                    subpath = f"{cat}/{name}" if cat and name else (name or "-")
                return subpath
            elif col == 4: return format_size(item.get("size", 0))
            elif col == 5:
                if item.get("is_directory_collective"):
                    return item.get("phase_status", "阶段一已归类 (原子保全)")
                return item.get("phase_status", "阶段一已归类 (独立单项)")
            elif col == 6:
                tag = item.get("tag", "")
                if not tag or tag == "-":
                    if item.get("is_directory_collective"):
                        return "原子保全 (防撕裂整体)"
                    return "标准资产 (保留)"
                return tag
            elif col == 7: 
                gid = item.get("duplicate_group_id", "")
                return gid if gid else "-"
            elif col == 8:
                mtime = item.get("mtime", 0)
                return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M") if mtime > 0 else "-"
            elif col == 9: return item.get("path", "")
            
        elif role == Qt.UserRole:
            return item
            
        elif role == Qt.CheckStateRole and col == 0 and self._is_selectable:
            return Qt.Checked if item.get("path") in self.checked_paths else Qt.Unchecked
            
        elif role == Qt.TextAlignmentRole:
            if col in (2, 5, 7, 8): return int(Qt.AlignCenter)
            if col == 4: return int(Qt.AlignRight | Qt.AlignVCenter)
            
        elif role == Qt.ForegroundRole:
            if col == 1 and item.get("is_directory_collective"):
                return QBrush(QColor("#A78BFA"))
            elif col == 2:
                return QBrush(QColor("#38BDF8")) # 天蓝多级分类树标签
            elif col == 3:
                return QBrush(QColor("#FBBF24")) # 琥珀金建议归档规划路径
            elif col == 5:
                status = item.get("phase_status", "")
                if "哈希已确认" in status: return QBrush(QColor("#10B981"))
                elif "AI" in status or "原子保全" in status or "规则" in status: return QBrush(QColor("#38BDF8"))
                else: return QBrush(QColor("#94A3B8"))
            elif col == 6:
                tag = item.get("tag", "")
                if "重复副本" in tag: return QBrush(QColor("#F59E0B"))
                elif "安全可清理" in tag or "临时" in tag: return QBrush(QColor("#10B981"))
                elif "防撕裂" in tag or "保全" in tag: return QBrush(QColor("#818CF8"))
                elif "归档" in tag or "自沉淀" in tag: return QBrush(QColor("#38BDF8"))
                
        elif role == Qt.ToolTipRole:
            if col == 1 or col == 9:
                p = item.get("path", "")
                if item.get("is_directory_collective"):
                    c_info = item.get("collective_info") or {}
                    return f"{p}\n[原子实体集体] 文件数: {item.get('file_count', 1):,} | 类型: {c_info.get('type', 'collective')} | 推荐泛归类: {item.get('category', '')}"
                return p
            elif col == 2:
                cat = item.get("category", "")
                sub = item.get("target_subpath") or item.get("suggested_archive_path") or ""
                return f"全局分类树节点: {cat}\n建议规划路径: {sub}"
            elif col == 3:
                sub = item.get("target_subpath") or item.get("suggested_archive_path") or ""
                return f"建议归档规划路径: {sub}\n[双击或快捷键 F2 激活就地编辑，回车提交 AI 审核自沉淀]"
            elif col == 6: return item.get("reason", "")
            
        elif role == Qt.SizeHintRole:
            from PySide6.QtCore import QSize
            return QSize(0, 44)

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self._headers[section]
        return None

    def flags(self, index):
        default_flags = super().flags(index)
        col = index.column()
        if col == 0 and self._is_selectable:
            return default_flags | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
        if col == 3:
            return default_flags | Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return default_flags

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid():
            return False
        col = index.column()
        row = index.row()
        item = self._data[row]

        if role == Qt.CheckStateRole and col == 0 and self._is_selectable:
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
        elif role == Qt.EditRole and col == 3:
            new_val = str(value).strip()
            if not new_val:
                return False
            old_val = item.get("target_subpath") or item.get("suggested_archive_path") or ""
            if new_val == old_val:
                return True

            old_state = {
                "target_subpath": item.get("target_subpath", ""),
                "suggested_archive_path": item.get("suggested_archive_path", ""),
                "category": item.get("category", ""),
                "phase_status": item.get("phase_status", ""),
                "tag": item.get("tag", "")
            }
            # 乐观即时更新当前项
            item["target_subpath"] = new_val
            item["suggested_archive_path"] = new_val
            start_idx = self.index(row, 0)
            end_idx = self.index(row, self.columnCount() - 1)
            self.dataChanged.emit(start_idx, end_idx, [Qt.DisplayRole, Qt.EditRole, Qt.ToolTipRole, Qt.ForegroundRole])
            # 回调通知外部组件进行 AI 编排审核与自沉淀
            if hasattr(self, "_on_path_edited_handler") and self._on_path_edited_handler:
                self._on_path_edited_handler(item, new_val, index, old_state)
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

    def add_data(self, new_items: List[Dict[str, Any]]):
        if not new_items:
            return
        self.beginResetModel()
        self._data.extend(new_items)
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

    def select_recommended_only(self, ai_plan: Optional[List[Dict[str, Any]]] = None) -> int:
        """
        根据 AI 执行清单及本地启发式标记勾选推荐资产：
        1. 优先以 AI 创作清单 (ai_plan) 为核心凭据，匹配 safe actions (归档/清理/迁移) 且非高风险项；
        2. 结合底层已有 is_recommended == True, is_duplicate_copy == True 等安全项；
        返回选中的资产数量。
        """
        ai_safe_paths = set()
        if ai_plan:
            for it in ai_plan:
                p = it.get("original_path") or it.get("path") or it.get("source_path")
                if not p:
                    continue
                risk = str(it.get("risk_level", "低风险"))
                act = str(it.get("action", ""))
                is_safe_action = any(k in act.lower() for k in ["归档", "清理", "迁移", "archive", "clean", "delete", "move", "reclaim"])
                if "高" not in risk and (is_safe_action or not act):
                    ai_safe_paths.add(os.path.normcase(os.path.normpath(str(p).strip())))

        self.beginResetModel()
        self.checked_paths.clear()
        self.checked_bytes = 0
        for item in self._data:
            p = item.get("path", "")
            if not p:
                continue
            norm_p = os.path.normcase(os.path.normpath(str(p).strip()))

            is_rec = False
            if norm_p in ai_safe_paths:
                is_rec = True
            elif item.get("is_recommended", False):
                is_rec = True
            elif item.get("is_duplicate_copy", False):
                is_rec = True
            elif str(item.get("phase_status", "")).startswith("AI智脑已决策") and "高" not in str(item.get("risk_level", "")):
                is_rec = True

            if is_rec:
                item["is_recommended"] = True
                self.checked_paths.add(p)
                self.checked_bytes += int(item.get("size", 0))

        self.endResetModel()
        return len(self.checked_paths)

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

    def apply_ai_execution_plan(self, execution_items: List[Dict[str, Any]]) -> int:
        """
        接收 AI 创作的结构化执行清单，直接导入并就地升级模型内部资产属性：
        - 覆盖 category 为 AI 研判的高阶分类（如经控、业务单据）
        - 覆盖 target_subpath 为 AI 推荐的多级归档路径
        - 覆盖 tag 与 reason 为 AI 研判理由
        - 根据 AI 研判将安全/建议操作项纳入选中
        返回命中的资产数量。
        """
        if not execution_items:
            return 0

        # 构建规范化路径字典索引
        plan_map = {}
        for it in execution_items:
            p = it.get("original_path") or it.get("path") or it.get("source_path")
            if p:
                norm_p = os.path.normcase(os.path.normpath(p.strip()))
                plan_map[norm_p] = it

        updated_count = 0
        self.beginResetModel()
        for item in self._data:
            p = item.get("path", "")
            if not p:
                continue
            norm_p = os.path.normcase(os.path.normpath(p.strip()))
            plan = plan_map.get(norm_p)
            if plan:
                updated_count += 1
                # 升级高阶分类 (AI 自主提炼，不受限于传统死板后缀)
                if plan.get("suggested_category"):
                    item["category"] = plan["suggested_category"]

                # 记录推荐归档子目录
                if plan.get("target_subpath") or plan.get("recommended_subpath"):
                    item["target_subpath"] = plan.get("target_subpath") or plan.get("recommended_subpath")

                # 治理标记与建议
                if plan.get("action"):
                    item["action"] = plan["action"]
                if plan.get("rationale") or plan.get("reason"):
                    item["reason"] = plan.get("rationale") or plan.get("reason")
                    item["tag"] = f"AI推荐 ({item.get('category', '归档')})"
                if plan.get("risk_level"):
                    item["risk_level"] = plan["risk_level"]

                item["phase_status"] = f"AI智脑已决策 ({plan.get('action', '归档')})"

                # 若属于安全低风险且操作为归档/清理，自动加入推荐与勾选
                action_str = str(plan.get("action", ""))
                risk_str = str(plan.get("risk_level", "低风险"))
                if "低" in risk_str and ("归档" in action_str or "清理" in action_str or "迁移" in action_str):
                    item["is_recommended"] = True
                    if p not in self.checked_paths:
                        self.checked_paths.add(p)
                        self.checked_bytes += int(item.get("size", 0))

        self.endResetModel()
        return updated_count


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
        subpath = str(item.get("target_subpath") or item.get("suggested_archive_path") or "").lower()
        phase = item.get("phase_status", "").lower()
        tag = item.get("tag", "").lower()
        path = item.get("path", "").lower()
        
        if kw in name or kw in cat or kw in subpath or kw in phase or kw in tag or kw in path:
            return True
        return False

    def lessThan(self, left, right):
        col = left.column()
        model = self.sourceModel()
        left_item = model._data[left.row()]
        right_item = model._data[right.row()]
        
        if col == 4:
            return left_item.get("size", 0) < right_item.get("size", 0)
        elif col == 8:
            return left_item.get("mtime", 0) < right_item.get("mtime", 0)
            
        left_str = model.data(left, Qt.DisplayRole) or ""
        right_str = model.data(right, Qt.DisplayRole) or ""
        return left_str < right_str


class PlanningPathItemDelegate(QStyledItemDelegate):
    """
    建议归档规划路径专用就地编辑委托：
    严格在原路径基础上就地微调修改，初始化时保留原规划路径文本，严禁先清空。
    """
    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setStyleSheet("""
            QLineEdit {
                background-color: #0F172A;
                color: #FBBF24;
                font-weight: bold;
                font-size: 12px;
                padding: 2px 6px;
                border: 2px solid #38BDF8;
                border-radius: 4px;
            }
        """)
        return editor

    def setEditorData(self, editor, index):
        # 核心契约：必须在原路径基础上修改，绝不先清空
        val = index.data(Qt.EditRole) or index.data(Qt.DisplayRole) or ""
        val_str = str(val).strip()
        if val_str == "-":
            val_str = ""
        editor.setText(val_str)
        # 文本全选保留，光标就绪，方便用户就地在原路径上增删微调
        editor.selectAll()

    def setModelData(self, editor, model, index):
        new_text = editor.text().strip()
        model.setData(index, new_text, Qt.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class FileDataGridWidget(QWidget):
    """
    极速响应、低延迟数据表格组件
    采用 QTableView + QAbstractTableModel 模型，单次装填内存复用，杜绝海量 QWidget 对象导致的冻结卡死。
    """
    selection_changed_signal = Signal(object, object) # (选中数量, 选中字节总数)
    migrate_requested_signal = Signal(list)            # (选中的路径列表)
    promote_collective_requested = Signal(str, str)    # (target_dir, app_name) 统一收拢转集合信号
    ai_insight_requested = Signal(dict)                # AI 资产深度研判信号 (资产条目字典)
    path_edited_signal = Signal(dict, str)             # (资产项, 新规划路径) 就地修改完成信号
    category_changed_signal = Signal(dict)             # (资产项) 分类树吸附或变更信号

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
        # 全局设计铁律：坚决禁用白黑交叉混杂，保持统一清晰底色
        self.table_view.setAlternatingRowColors(False)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table_view.setSortingEnabled(True)
        self.table_view.verticalHeader().setVisible(False)
        # UI 铁律: 锁死 44px 行高
        self.table_view.verticalHeader().setDefaultSectionSize(44)
        self.table_view.verticalHeader().setMinimumSectionSize(44)
        self.table_view.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self.show_context_menu)
        self.table_view.doubleClicked.connect(self._on_table_double_clicked)
        self.table_view.installEventFilter(self)
        
        self.source_model = FileTableModel([], self.is_selectable, self)
        self.source_model._on_path_edited_handler = self._handle_archive_path_edited
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
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        self.table_view.setColumnWidth(2, 170)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        self.table_view.setColumnWidth(3, 230)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Interactive)
        self.table_view.setColumnWidth(6, 130)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(9, QHeaderView.Stretch)
        # 规划路径列就地编辑专用委托 (原路径基础上修改，绝不先清空)
        self.table_view.setItemDelegateForColumn(3, PlanningPathItemDelegate(self.table_view))
        
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
        if total == 0:
            self.stats_label.setText("暂无资产项 (若为 Top 100 选项卡，则说明当前无超过 300MB 的大文件/集体资产)")
        else:
            c_cnt = sum(1 for it in self.source_model._data if it.get("is_directory_collective"))
            c_files = sum(it.get("file_count", 1) for it in self.source_model._data if it.get("is_directory_collective"))
            f_cnt = total - c_cnt
            c_info_str = f" (含 {c_cnt} 个原子实体集体 [底层封包聚合 {c_files:,} 个碎片文件], {f_cnt} 个独立单项资产)" if c_cnt > 0 else f" (共 {total} 个独立单项资产)"
            if total == visible:
                self.stats_label.setText(f"共 {total} 个资产单元{c_info_str}")
            else:
                self.stats_label.setText(f"显示 {visible} / {total} 个资产单元{c_info_str}")

    def select_all(self, checked: bool = True):
        self.source_model.select_all(checked)
        self._update_stats_label()
        self._emit_selection_stats()

    def invert_selection(self):
        self.source_model.invert_selection()
        self._update_stats_label()
        self._emit_selection_stats()

    def select_recommended_only(self, ai_plan: Optional[List[Dict[str, Any]]] = None) -> int:
        count = self.source_model.select_recommended_only(ai_plan=ai_plan)
        self._update_stats_label()
        self._emit_selection_stats()
        return count

    def select_ai_recommended_paths(self, ai_paths: List[str]) -> int:
        count = self.source_model.select_ai_recommended_paths(ai_paths)
        self._update_stats_label()
        self._emit_selection_stats()
        return count

    def apply_ai_execution_plan(self, execution_items: List[Dict[str, Any]]) -> int:
        count = self.source_model.apply_ai_execution_plan(execution_items)
        self._update_stats_label()
        return count

    def get_checked_paths(self) -> List[str]:
        return list(self.source_model.checked_paths)

    def remove_paths(self, paths_to_remove: List[str]):
        remove_set = {os.path.normpath(p).lower() for p in paths_to_remove}
        self.source_model.remove_paths(remove_set)
        self._update_stats_label()

    def add_data(self, new_items: List[Dict[str, Any]]):
        self.source_model.add_data(new_items)
        self._update_stats_label()

    def apply_filter(self, keyword: str):
        self.proxy_model.set_filter_keyword(keyword)
        self._update_stats_label()

    def eventFilter(self, obj, event):
        if obj == self.table_view and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_F2:
                cur = self.table_view.currentIndex()
                row = cur.row() if cur.isValid() else 0
                if self.proxy_model.rowCount() > 0:
                    target_idx = self.proxy_model.index(row, 3)
                    self.table_view.setCurrentIndex(target_idx)
                    self.table_view.edit(target_idx)
                return True
        return super().eventFilter(obj, event)

    def show_context_menu(self, pos):
        index = self.table_view.indexAt(pos)
        if not index.isValid():
            return
            
        source_index = self.proxy_model.mapToSource(index)
        item = self.source_model._data[source_index.row()]
        file_path = item.get("path", "")
        if not file_path:
            return

        # 检查是否同时多选了多行
        selected_proxy_rows = self.table_view.selectionModel().selectedRows()
        selected_source_rows = []
        for p_idx in selected_proxy_rows:
            s_idx = self.proxy_model.mapToSource(p_idx)
            if s_idx.isValid() and 0 <= s_idx.row() < len(self.source_model._data):
                selected_source_rows.append(s_idx.row())

        if source_index.row() in selected_source_rows and len(selected_source_rows) > 1:
            target_items = [self.source_model._data[r] for r in selected_source_rows]
        else:
            target_items = [item]

        is_multi = len(target_items) > 1
        target_paths = [it.get("path") for it in target_items if it.get("path")]
        
        menu = QMenu(self)
        if not is_multi:
            action_open_dir = QAction("📂 在文件资源管理器中定位", self)
            action_open_dir.triggered.connect(lambda: self._locate_in_explorer(file_path))
            
            action_open_file = QAction("📄 打开文件", self)
            action_open_file.triggered.connect(lambda: self._open_file(file_path))
            
            action_ai = QAction("🤖 AI 智能研判与治理建议...", self)
            action_ai.triggered.connect(lambda: self._on_ai_insight_action(item))

            action_promote = QAction("📦 向上收拢并转为集合...", self)
            action_promote.triggered.connect(lambda: self._on_promote_collective_action(file_path))

            menu.addAction(action_open_dir)
            menu.addAction(action_open_file)
            menu.addSeparator()
            menu.addAction(action_ai)
            menu.addAction(action_promote)

        action_migrate = QAction(f"📦 智能迁移所选项 ({len(target_items)} 项)", self) if is_multi else QAction("📦 智能迁移此项", self)
        action_migrate.triggered.connect(lambda: self.migrate_requested_signal.emit(target_paths))
        
        action_copy_path = QAction(f"📋 复制所选绝对路径 ({len(target_items)} 项)", self) if is_multi else QAction("📋 复制绝对路径", self)
        action_copy_path.triggered.connect(lambda: QApplication.clipboard().setText("\n".join(target_paths) if is_multi else file_path))
        
        # 树状级联归类子菜单 (支持多选批量)
        cascade_title = f"🏷️ 树状级联归档分类与规划 (批量 {len(target_items)} 项)" if is_multi else "🏷️ 树状级联归档分类与规划"
        cascade_menu = menu.addMenu(cascade_title)
        self._populate_category_cascade_menu(cascade_menu, target_items)

        menu.addAction(action_migrate)
        menu.addSeparator()
        menu.addAction(action_copy_path)
        
        menu.exec(self.table_view.viewport().mapToGlobal(pos))

    def _populate_category_cascade_menu(self, parent_menu: QMenu, target_items: Any):
        """根据 2~3 级分类树动态构建级联右键归类菜单 (支持单项与多选批量，自动过滤未启用分类)"""
        from app.core.category_manager import global_category_manager
        tree = global_category_manager.get_tree()

        def _add_nodes(menu, nodes, prefix=""):
            for node in nodes:
                if not node.get("enabled", True):
                    continue
                n_name = node.get("name", "")
                full_path = f"{prefix} / {n_name}" if prefix else n_name
                active_children = [c for c in node.get("children", []) if c.get("enabled", True)]
                if active_children:
                    sub_m = menu.addMenu(f"📁 {n_name}")
                    act_self = sub_m.addAction(f"🎯 直接归为此大类 ({n_name})")
                    act_self.triggered.connect(lambda _, c=node, p=full_path: self._apply_category_change(target_items, c, p))
                    sub_m.addSeparator()
                    _add_nodes(sub_m, active_children, full_path)
                else:
                    act = menu.addAction(f"📄 {n_name}")
                    act.triggered.connect(lambda _, c=node, p=full_path: self._apply_category_change(target_items, c, p))

        _add_nodes(parent_menu, tree)

    def _apply_category_change(self, target_items: Any, cat_node: Dict[str, Any], full_path: str):
        """应用右键树状级联分类变更并触发 AI 极速自沉淀 (支持单项与多选批量原子回滚)"""
        from app.core.ai_service import AIService
        if isinstance(target_items, dict):
            items_list = [target_items]
        elif isinstance(target_items, list):
            items_list = list(target_items)
        else:
            items_list = [target_items]

        if not items_list:
            return

        success_count = 0
        fail_reasons = []

        template = cat_node.get("target_path_template", "")
        clean_tmpl = ""
        if template:
            clean_tmpl = template.replace("{archive_root}/", "").replace("{archive_root}\\", "").replace("{archive_root}", "").lstrip("/\\")

        for item in items_list:
            old_cat = item.get("category", "")
            old_subpath = item.get("target_subpath") or item.get("suggested_archive_path") or ""
            old_status = item.get("phase_status", "")
            old_tag = item.get("tag", "")

            name = item.get("name", "")
            if clean_tmpl:
                new_path = clean_tmpl.replace("{app_name}", name).replace("{asset_name}", name).replace("{category_name}", cat_node.get("name", ""))
            else:
                new_path = f"{full_path.replace(' / ', '/')}/{name}"

            item["category"] = full_path
            item["target_subpath"] = new_path
            item["suggested_archive_path"] = new_path

            # 触发 AI 审核与自沉淀
            res = AIService.audit_manual_path_and_precipitate(item, new_path)
            if res.get("valid"):
                item["phase_status"] = "AI已审核 (自沉淀)"
                item["tag"] = f"AI沉淀 ({cat_node.get('name')})"
                success_count += 1
                self.path_edited_signal.emit(item, new_path)
                self.category_changed_signal.emit(item)
            else:
                # 单项失败回滚
                item["category"] = old_cat
                item["target_subpath"] = old_subpath
                item["suggested_archive_path"] = old_subpath
                item["phase_status"] = old_status
                item["tag"] = old_tag
                fail_reasons.append(f"{name}: {res.get('error', '未知原因')}")

        self.source_model.layoutChanged.emit()

        if fail_reasons:
            if len(items_list) == 1:
                QMessageBox.warning(self, "分类变更失败", f"AI审核未通过:\n{fail_reasons[0]}")
            else:
                msg = f"批量分类完成：成功 {success_count} 项，失败 {len(fail_reasons)} 项。\n" + "\n".join(fail_reasons[:5])
                if len(fail_reasons) > 5:
                    msg += f"\n... 等共 {len(fail_reasons)} 项失败"
                QMessageBox.warning(self, "批量分类部分未通过", msg)

    def _handle_archive_path_edited(
        self,
        item: Dict[str, Any],
        new_path: str,
        model_index: QModelIndex,
        old_state: Optional[Dict[str, Any]] = None
    ):
        """就地编辑提交后，由 AI 核心编排器在 1 秒以内进行合法性检验、分类树吸附与规则抽象审核，审核通过后自动增量自沉淀并在当前视图乐观更新"""
        from app.core.ai_service import AIService
        res = AIService.audit_manual_path_and_precipitate(item, new_path)
        row = model_index.row()
        start_idx = self.source_model.index(row, 0)
        end_idx = self.source_model.index(row, self.source_model.columnCount() - 1)

        if res.get("valid"):
            if res.get("category"):
                item["category"] = res["category"]
            item["phase_status"] = "AI已审核 (自沉淀)"
            item["tag"] = f"AI沉淀 ({item.get('category', '已归类')})"
            self.source_model.dataChanged.emit(start_idx, end_idx, [Qt.DisplayRole, Qt.ToolTipRole, Qt.ForegroundRole])
            self.path_edited_signal.emit(item, new_path)
            self.category_changed_signal.emit(item)
        else:
            # 回滚乐观更新，还原为修改前状态
            if old_state:
                item["target_subpath"] = old_state.get("target_subpath", "")
                item["suggested_archive_path"] = old_state.get("suggested_archive_path", "")
                item["category"] = old_state.get("category", "")
                item["phase_status"] = old_state.get("phase_status", "")
                item["tag"] = old_state.get("tag", "")
            self.source_model.dataChanged.emit(start_idx, end_idx, [Qt.DisplayRole, Qt.ToolTipRole, Qt.ForegroundRole])
            err = res.get("error", "规划路径未通过合法性检验")
            QMessageBox.warning(self, "AI 规划审核未通过", f"建议归档规划路径审核未通过:\n{err}")

    def _on_table_double_clicked(self, index: QModelIndex):
        """双击表格行: 若双击建议归档规划路径列(col 3)，激活就地编辑；其余列打开目录或在资源管理器中定位"""
        if not index.isValid():
            return
        if index.column() == 3:
            self.table_view.edit(index)
            return
        source_index = self.proxy_model.mapToSource(index)
        if 0 <= source_index.row() < len(self.source_model._data):
            item = self.source_model._data[source_index.row()]
            file_path = item.get("path", "")
            if file_path:
                self._locate_or_open(file_path)

    def _locate_or_open(self, file_path: str):
        norm = os.path.normpath(file_path)
        if os.path.exists(norm):
            if os.path.isdir(norm):
                os.startfile(norm)
            else:
                subprocess.Popen(f'explorer.exe /select,"{norm}"')

    def _on_ai_insight_action(self, item: Dict[str, Any]):
        """弹出 AI 资产研判弹窗并通知上层"""
        self.ai_insight_requested.emit(item)
        try:
            from app.ui.components.ai_insight_dialog import AIAssetInsightDialog
            dlg = AIAssetInsightDialog(item, self)
            dlg.exec()
        except Exception as e:
            QMessageBox.warning(self, "AI 研判错误", f"无法打开 AI 研判对话框: {e}")

    def _on_promote_collective_action(self, file_path: str):
        """触发向上收拢转为集合弹窗"""
        from app.ui.components.promote_collective_dialog import PromoteCollectiveDialog
        dlg = PromoteCollectiveDialog(file_path, self)
        if dlg.exec() == PromoteCollectiveDialog.Accepted:
            target_dir = dlg.selected_target_dir
            app_name = dlg.app_name
            if target_dir:
                self.promote_collective_requested.emit(target_dir, app_name)

    def _locate_in_explorer(self, file_path: str):
        norm = os.path.normpath(file_path)
        if os.path.exists(norm):
            subprocess.Popen(f'explorer.exe /select,"{norm}"')

    def _open_file(self, file_path: str):
        norm = os.path.normpath(file_path)
        if os.path.exists(norm):
            os.startfile(norm)
