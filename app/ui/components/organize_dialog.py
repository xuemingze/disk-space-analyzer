import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QProgressDialog,
    QApplication,
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QProgressBar, QMessageBox, QFrame, QAbstractItemView,
    QMenu, QComboBox, QStyledItemDelegate, QCompleter
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QBrush, QFont, QIcon

from app.core.category_manager import global_category_manager
from app.core.cleaner import ArchiveWorker
from app.utils.file_helper import format_size
from app.core.organize_models import sanitize_subpath
from app.core.domain_models import (
    ArchiveDestinationPath, HistorySuggestionProvider, ArchivePlanningUnit,
    TopologyRoutingTable, MorphologyType
)


class TreeInplaceItemDelegate(QStyledItemDelegate):
    """
    目录树归档计划预览就地编辑委托：
    1. 支持建议归档分类 (第 2 列) 与目标规划路径 (第 3 列) 就地编辑微调；
    2. 严格践行「防清空重写原则 (Zero-clearing Rule)」：初始化时保留并全选原文本，光标就绪，严禁先清空；
    3. 集成「历史候选与建议联想 (QCompleter)」：
       - 第 2 列提供标准业务领域与自沉淀分类候选联想；
       - 第 3 列提供智能生成路径、现有物理目录与历史归档路径候选联想。
    """
    def __init__(self, dialog: "OrganizePreviewDialog", parent=None):
        super().__init__(parent or dialog)
        self.dialog = dialog

    def createEditor(self, parent, option, index):
        col = index.column()
        if col not in (2, 3):
            return None

        editor = QLineEdit(parent)
        editor.setStyleSheet("""
            QLineEdit {
                background-color: #0F172A;
                color: #F8FAFC;
                font-weight: bold;
                font-size: 12px;
                padding: 2px 6px;
                border: 2px solid #38BDF8;
                border-radius: 4px;
                selection-background-color: #2563EB;
                selection-color: #FFFFFF;
            }
        """)

        # 候选联想与历史建议 (QCompleter)
        if col == 2:
            candidates = HistorySuggestionProvider.get_category_suggestions()
        else:
            item = self.dialog.tree.itemFromIndex(index)
            u_data = item.data(0, Qt.UserRole) if item else {}
            gdata = u_data.get("data", {}) if isinstance(u_data, dict) else {}
            app_name = gdata.get("app_name", "")
            cat = gdata.get("effective_category", gdata.get("suggested_category", ""))
            candidates = HistorySuggestionProvider.get_path_suggestions(
                dest_root=self.dialog.destination_root,
                current_cat=cat,
                app_name=app_name
            )

        if candidates:
            completer = QCompleter(candidates, editor)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains)
            completer.setCompletionMode(QCompleter.PopupCompletion)

            popup = completer.popup()
            if popup:
                popup.setStyleSheet("""
                    QListView {
                        background-color: #1E293B;
                        color: #F8FAFC;
                        border: 1px solid #475569;
                        selection-background-color: #3B82F6;
                        selection-color: #FFFFFF;
                        font-size: 12px;
                        padding: 4px;
                    }
                """)
            editor.setCompleter(completer)

        return editor

    def setEditorData(self, editor, index):
        # 核心防清空契约：严格在原路径/分类基础上修改，绝不先清空
        val = index.data(Qt.EditRole) or index.data(Qt.DisplayRole) or ""
        val_str = str(val).strip()
        if val_str == "-":
            val_str = ""
        editor.setText(val_str)
        # 文本全选保留，光标就绪，方便用户就地在原路径上增删微调或方向键单字调整
        editor.selectAll()

    def setModelData(self, editor, model, index):
        new_text = editor.text().strip()
        if not new_text:
            return
        col = index.column()
        item = self.dialog.tree.itemFromIndex(index)
        if not item:
            return

        if col == 2:
            self.dialog._on_category_edited(item, new_text)
        elif col == 3:
            self.dialog._on_path_edited(item, new_text)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class OrganizePreviewDialog(QDialog):
    """
    AI 归档计划预览、目录树层级审核与安全确认执行向导 (QTreeWidget 目录视图)
    """
    def __init__(
        self,
        classification_items: List[Dict[str, Any]], # 传入目录聚合单元列表 (由 AppDetector.group_files_by_parent_or_tool 或 AIService 生成)
        destination_root: str,
        conflict_policy: str = "auto_rename",
        allow_execute: bool = True,
        parent=None
    ):
        super().__init__(parent)
        self.classification_items = classification_items
        self.destination_root = os.path.normpath(destination_root)
        self.conflict_policy = conflict_policy
        self.allow_execute = allow_execute
        self.archive_worker: Optional[ArchiveWorker] = None
        self.last_manifest_path: str = ""
        self._is_updating_checks = False

        self.setWindowTitle("🤖 AI 目录树归档计划预览与安全确认")
        self.resize(1100, 680)
        self.setModal(True)

        self.init_ui()

        # 核心保证：分析完成进入弹窗预览即刻提炼沉淀入主路由表 (0 Token 本地秒级命中保证)
        try:
            TopologyRoutingTable.instance().precipitate_ai_decisions(self.classification_items)
        except Exception:
            pass

        self.populate_tree()


    def closeEvent(self, event):
        if hasattr(self, 'archive_worker') and self.archive_worker and self.archive_worker.isRunning():
            try:
                self.archive_worker.progress_signal.disconnect(self.on_archive_progress)
                self.archive_worker.finished_signal.disconnect(self.on_archive_finished)
            except RuntimeError:
                pass
        super().closeEvent(event)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        # 1. 顶部标题栏
        top_bar = QHBoxLayout()
        title_lbl = QLabel("🌳 AI 智能归档规划目录树 (按 App / 工具链整体分组)")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #38BDF8;")
        top_bar.addWidget(title_lbl)
        top_bar.addStretch()

        dest_desc = QLabel(f"目标归档根路径: <code style='color: #A7F3D0;'>{self.destination_root}</code>")
        dest_desc.setStyleSheet("font-size: 12px; color: #94A3B8;")
        top_bar.addWidget(dest_desc)
        layout.addLayout(top_bar)

        # 2. 统计摘要与详细勾选拦截报告
        self.lbl_auto_checked = QLabel("自动勾选: 0项")
        self.lbl_auto_checked.setStyleSheet("color: #10B981; font-weight: bold;")
        self.lbl_unselected = QLabel("未勾选: 0项")
        self.lbl_unselected.setStyleSheet("color: #F59E0B; font-weight: bold;")
        self.lbl_risk_stats = QLabel("风险统计: 低 0 | 中 0 | 高 0")
        self.lbl_risk_stats.setStyleSheet("color: #94A3B8;")

        # 2. 统计摘要与快捷操作栏
        stats_frame = QFrame()
        stats_frame.setProperty("class", "CardFrame")
        stats_layout = QHBoxLayout(stats_frame)
        stats_layout.setContentsMargins(12, 8, 12, 8)
        stats_layout.setSpacing(10)

        total_groups = len(self.classification_items)
        total_files = sum(g.get("file_count", len(g.get("sub_items", []))) for g in self.classification_items)
        total_bytes = sum(g.get("total_size", sum(s.get("size", 0) for s in g.get("sub_items", []))) for g in self.classification_items)
        need_conf_groups = sum(1 for g in self.classification_items if g.get("require_confirmation", False))

        self.stats_label = QLabel(
            f"待归档单元: <b>{total_groups}</b> 个目录/组 (共 <b>{total_files}</b> 个文件，<b>{format_size(total_bytes)}</b>) | "
            f"需人工确认: <span style='color: {'#F59E0B' if need_conf_groups > 0 else '#10B981'}; font-weight: bold;'>{need_conf_groups} 组</span>"
        )
        self.stats_label.setStyleSheet("font-size: 12px; color: #E2E8F0;")
        stats_layout.addWidget(self.stats_label)
        stats_layout.addStretch()

        # 展开/折叠与知识库按钮
        self.btn_routing_table = QPushButton("🌐 拓扑路由知识库")
        self.btn_routing_table.setProperty("class", "SecondaryButton")
        self.btn_routing_table.setToolTip("查看、编辑、导入/导出拓扑路由规则与配置 AI 审查策略")
        self.btn_routing_table.clicked.connect(self._open_routing_table_viewer)
        stats_layout.addWidget(self.btn_routing_table)

        self.btn_expand_all = QPushButton("📂 全部展开")
        self.btn_expand_all.setProperty("class", "SecondaryButton")
        self.btn_expand_all.clicked.connect(self._expand_all_with_progress)
        stats_layout.addWidget(self.btn_expand_all)

        self.btn_collapse_all = QPushButton("📁 全部折叠")
        self.btn_collapse_all.setProperty("class", "SecondaryButton")
        self.btn_collapse_all.clicked.connect(lambda: self.tree.collapseAll())
        stats_layout.addWidget(self.btn_collapse_all)

        layout.addWidget(stats_frame)

        # 3. 核心目录树表格 (QTreeWidget)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(10)
        self.tree.setHeaderLabels([
            "目录 / 文件单元", "所属 App / 工具", "建议归档分类", "目标规划路径",
            "识别依据 / 特征", "数量 / 大小", "置信度", "安全等级", "操作", "任务与报告关联"
        ])
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemChanged.connect(self._schedule_update_stats)
        self.tree.itemExpanded.connect(self._on_item_expanded)
        
        # 绑定专用就地微调编辑委托 (防清空重写、历史候选预览、F2/双击激活)
        self.tree_delegate = TreeInplaceItemDelegate(self, self.tree)
        self.tree.setItemDelegateForColumn(2, self.tree_delegate)
        self.tree.setItemDelegateForColumn(3, self.tree_delegate)
        self.tree.setEditTriggers(
            QAbstractItemView.DoubleClicked |
            QAbstractItemView.EditKeyPressed |
            QAbstractItemView.SelectedClicked
        )
        
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        self.tree.setColumnWidth(0, 240)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        self.tree.setColumnWidth(1, 140)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        self.tree.setColumnWidth(2, 120)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        self.tree.setColumnWidth(3, 160)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Interactive)
        self.tree.setColumnWidth(5, 80)
        header.setSectionResizeMode(6, QHeaderView.Interactive)
        self.tree.setColumnWidth(6, 60)
        header.setSectionResizeMode(7, QHeaderView.Interactive)
        self.tree.setColumnWidth(7, 80)
        header.setSectionResizeMode(8, QHeaderView.Interactive)
        self.tree.setColumnWidth(8, 80)
        header.setSectionResizeMode(9, QHeaderView.Interactive)
        self.tree.setColumnWidth(9, 120)

        layout.addWidget(self.tree, 1)

        # 4. 实时执行进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("提示：勾选父目录将作为整体原子单元整体迁移，保留内部完整相对层级。")
        self.status_label.setStyleSheet("color: #94A3B8; font-size: 11px;")
        layout.addWidget(self.status_label)

        # 5. 底部操作栏
        btn_bar = QHBoxLayout()
        self.btn_select_all = QPushButton("☑️ 全选")
        self.btn_select_all.setProperty("class", "SecondaryButton")
        self.btn_select_all.clicked.connect(lambda: self._set_all_checked_state(Qt.Checked))
        btn_bar.addWidget(self.btn_select_all)

        self.btn_select_safe = QPushButton("🛡️ 仅勾选安全推荐项 (免确认)")
        self.btn_select_safe.setProperty("class", "SecondaryButton")
        self.btn_select_safe.clicked.connect(self._select_safe_only)
        btn_bar.addWidget(self.btn_select_safe)

        self.btn_clear_sel = QPushButton("🚫 全部取消")
        self.btn_clear_sel.setProperty("class", "SecondaryButton")
        self.btn_clear_sel.clicked.connect(lambda: self._set_all_checked_state(Qt.Unchecked))
        btn_bar.addWidget(self.btn_clear_sel)

        btn_bar.addStretch()

        self.btn_execute = QPushButton("🚀 确认并开始后台归档")
        self.btn_execute.setStyleSheet(
            "font-size: 13px; font-weight: bold; background-color: #059669; border-color: #10B981; padding: 8px 22px;"
        )
        self.btn_execute.clicked.connect(self.execute_archive)
        btn_bar.addWidget(self.btn_execute)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setProperty("class", "SecondaryButton")
        self.btn_cancel.clicked.connect(self.reject)
        btn_bar.addWidget(self.btn_cancel)

        layout.addLayout(btn_bar)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F2:
            curr_item = self.tree.currentItem()
            if curr_item:
                curr_col = self.tree.currentColumn()
                target_col = curr_col if curr_col in (2, 3) else 3
                self.tree.editItem(curr_item, target_col)
                return
        super().keyPressEvent(event)

    def _open_routing_table_viewer(self):
        """打开全局拓扑路由知识库与自省管理对话框"""
        from app.ui.components.routing_table_viewer import RoutingTableViewerDialog
        dlg = RoutingTableViewerDialog(self)
        dlg.exec()

    def populate_tree(self):
        self._is_updating_checks = True
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        
        # 全局设计铁律：顶级蓝底白字，子级绿底白字，纯色深底统一使用清晰纯白字
        folder_bg = QBrush(QColor("#1E3A8A"))
        folder_fg = QBrush(QColor("#FFFFFF"))
        
        auto_checked_count = 0
        unselected_count = 0
        risk_low = 0
        risk_mid = 0
        risk_high = 0

        for group in self.classification_items:
            if not os.environ.get("QT_QPA_PLATFORM"):
                QApplication.processEvents()
            orig_root = group.get("original_root", "")
            sub_items = group.get("sub_items", [])
            
            risk = group.get("risk_level", "未知风险")
            
            if "低风险" in risk:
                risk_color = QColor("#10B981")
                risk_low += 1
            elif "中风险" in risk:
                risk_color = QColor("#F59E0B")
                risk_mid += 1
            else:
                risk_color = QColor("#EF4444")
                risk_high += 1
                if risk == "未知风险":
                    risk = "高风险 (无法确认系统影响)"
            
            conf = float(group.get("confidence", 0.0))
            require_conf = group.get("require_confirmation", True)
            
            app_name = group.get("app_name", "").lower()
            unrecognized = not app_name or "未识别" in app_name or "未知" in app_name
            
            is_system_path = False
            if orig_root:
                from app.utils.file_helper import is_system_critical_path
                is_system_path = is_system_critical_path(orig_root)
            
            default_checked = False
            if (not require_conf) and conf >= 0.7 and (not unrecognized) and (not is_system_path):
                default_checked = True
                auto_checked_count += 1
            else:
                unselected_count += 1
                
            group_item = QTreeWidgetItem(self.tree)
            group_item.setFlags(
                group_item.flags() |
                Qt.ItemIsUserCheckable |
                Qt.ItemIsAutoTristate |
                Qt.ItemIsEditable |
                Qt.ItemIsEnabled |
                Qt.ItemIsSelectable
            )
            init_check_state = Qt.Checked if default_checked else Qt.Unchecked
            group_item.setCheckState(0, init_check_state)
            group_item.setData(0, Qt.UserRole, {"type": "group", "data": group})
            
            from pathlib import Path
            pt = Path(orig_root)
            display_name = pt.name if pt.name else str(pt)
            group_item.setText(0, f"📦 {display_name}")
            group_item.setToolTip(0, orig_root)
            
            for col in range(10):
                group_item.setBackground(col, folder_bg)
                group_item.setForeground(col, folder_fg)
                
            source = group.get("source", "离线规则")
            correction_rec = group.get("correction_record")
            is_corrected = bool(correction_rec or group.get("action") == "已纠偏")
            corr_badge = " [AI已纠偏]" if is_corrected else ""
            group_item.setText(1, f"{group.get('app_name', '')} [{source}]{corr_badge}")
            font = group_item.font(1)
            font.setBold(True)
            if is_corrected:
                group_item.setForeground(1, QBrush(QColor("#C084FC")))  # 高亮淡紫强调 AI 绝对纠偏
                diag_msg = ""
                if isinstance(correction_rec, dict):
                    diag_msg = f"{correction_rec.get('diagnostic_tag', '[AI已纠偏]')}: {correction_rec.get('reason', '')}"
                elif hasattr(correction_rec, "diagnostic_tag"):
                    diag_msg = f"{correction_rec.diagnostic_tag}: {correction_rec.reason}"
                elif correction_rec:
                    diag_msg = str(correction_rec)
                else:
                    diag_msg = "已由 AI 核心审查引擎执行绝对纠偏并剔除中转污染目录"
                group_item.setToolTip(1, f"【AI 绝对纠偏诊断】\n{diag_msg}")
            elif source == "AI":
                group_item.setForeground(1, QBrush(QColor("#38BDF8")))  # 高亮天蓝白字
            elif "涉敏" in source or "降级" in source:
                group_item.setForeground(1, QBrush(QColor("#FBBF24")))  # 高亮琥珀橙字
                group_item.setToolTip(1, "触发大模型内容安全审查 (422 Sensitive)，已安全保留本地离线启发式规则")
            else:
                group_item.setForeground(1, QBrush(QColor("#FFFFFF")))
            group_item.setFont(1, font)
            
            # 第 2 列：建议归档分类 (采用 TreeInplaceItemDelegate 就地编辑，防清空 + 历史联想)
            curr_cat = group.get("effective_category") or group.get("suggested_category", "未分类/待人工确认")
            group_item.setText(2, curr_cat)
            group_item.setTextAlignment(2, Qt.AlignCenter)
            group_item.setForeground(2, QBrush(QColor("#38BDF8")))
            group_item.setToolTip(2, f"建议归档分类: {curr_cat}\n[双击或按 F2 就地微调修改，输入时有历史候选联想]")
            
            # 第 3 列：建议目标规划路径 (采用 TreeInplaceItemDelegate 就地编辑，防清空 + 历史联想)
            rec_subpath = group.get("recommended_subpath", "")
            target_path_str = group.get("target_root", "")
            group_item.setText(3, target_path_str)
            group_item.setForeground(3, QBrush(QColor("#FBBF24")))
            tip_parts = [f"建议目标规划路径: {target_path_str}"]
            if rec_subpath:
                tip_parts.append(f"推荐细分子层级: {rec_subpath}")
            tip_parts.append("[双击或按 F2 就地微调修改，输入时有历史候选联想]")
            group_item.setToolTip(3, "\n".join(tip_parts))
            
            # 第 4 列：研判依据
            corr_prefix = ""
            if is_corrected:
                c_tag = correction_rec.get("diagnostic_tag") if isinstance(correction_rec, dict) else (getattr(correction_rec, "diagnostic_tag", "[AI已纠偏]") if correction_rec else "[AI已纠偏]")
                corr_prefix = f"{c_tag} "

            if rec_subpath:
                rationale_text = group.get("rationale", "")
                if rec_subpath not in rationale_text:
                    group_item.setText(4, f"{corr_prefix}[{rec_subpath}] {rationale_text}")
                else:
                    group_item.setText(4, f"{corr_prefix}{rationale_text}")
                group_item.setToolTip(4, f"推荐细分子层级: {rec_subpath}\n识别依据: {rationale_text}")
            else:
                group_item.setText(4, f"{corr_prefix}{group.get('rationale', '')}")
            
            total_size = sum(s.get("size", 0) for s in sub_items)
            size_str = f"{len(sub_items)} 项 ({format_size(total_size)})"
            group_item.setText(5, size_str)
            group_item.setTextAlignment(5, Qt.AlignRight | Qt.AlignVCenter)
            
            group_item.setText(6, f"{conf * 100:.0f}%")
            group_item.setTextAlignment(6, Qt.AlignCenter)
            
            group_item.setText(7, risk)
            group_item.setTextAlignment(7, Qt.AlignCenter)
            group_item.setForeground(7, QBrush(risk_color))
            
            action_text = group.get("action", "")
            group_item.setText(8, action_text)
            group_item.setTextAlignment(8, Qt.AlignCenter)
            if is_corrected or action_text == "已纠偏":
                group_item.setForeground(8, QBrush(QColor("#C084FC")))
            
            task_info = f"R:{group.get('report_id','-')} | T:{group.get('task_id','-')}"
            group_item.setText(9, task_info)
            
            if sub_items:
                dummy = QTreeWidgetItem(group_item)
                dummy.setText(0, "加载中...")
                dummy.setFlags(dummy.flags() | Qt.ItemIsUserCheckable)
                dummy.setCheckState(0, init_check_state)
            
            # 关键：在添加 dummy 子项后重新强制设定顶级项的 CheckState，防止 Qt ItemIsAutoTristate 计算丢失复选框
            group_item.setCheckState(0, init_check_state)

        self._is_updating_checks = False
        self.tree.setUpdatesEnabled(True)
        # self.tree.expandToDepth(0)
        self.update_stats()


    def _is_unexpanded(self, item: QTreeWidgetItem) -> bool:
        """判断顶级节点是否尚处于分批延迟加载状态（未展开真实子节点）"""
        return item is not None and item.childCount() == 1 and item.child(0).text(0) == "加载中..."

    def get_selected_file_items(self) -> List[Dict[str, Any]]:
        """
        获取当前所有勾选的文件项。
        支持：
        1. 未展开的顶级分组节点（以顶级节点勾选状态为准，提取其 group['sub_items']）；
        2. 已展开的节点（以各个子项的逐项独立勾选状态为准，支持局部勾选/反选）。
        """
        selected_file_items = []

        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            u_data = item.data(0, Qt.UserRole) or {}
            if u_data.get("type") != "group":
                continue
            group = u_data.get("data", {})
            eff_cat = group.get("effective_category", group.get("suggested_category", ""))
            sub_items = group.get("sub_items", [])

            if self._is_unexpanded(item):
                if item.checkState(0) == Qt.Checked:
                    if sub_items:
                        for sub in sub_items:
                            selected_file_items.append({
                                "path": sub.get("original_path", ""),
                                "target_category": eff_cat,
                                "custom_target": sub.get("target_path", ""),
                                "size": sub.get("size", 0)
                            })
                    elif group.get("original_root"):
                        selected_file_items.append({
                            "path": group.get("original_root", ""),
                            "target_category": eff_cat,
                            "custom_target": group.get("target_root", ""),
                            "size": group.get("total_size", 0)
                        })
            else:
                for j in range(item.childCount()):
                    child = item.child(j)
                    c_data = child.data(0, Qt.UserRole) or {}
                    if c_data.get("type") == "file" and child.checkState(0) == Qt.Checked:
                        sub = c_data.get("data", {})
                        selected_file_items.append({
                            "path": sub.get("original_path", ""),
                            "target_category": eff_cat,
                            "custom_target": sub.get("target_path", ""),
                            "size": sub.get("size", 0)
                        })

        return selected_file_items
    def _set_all_checked_state(self, state: Any):
        if isinstance(state, bool):
            check_state = Qt.Checked if state else Qt.Unchecked
        elif isinstance(state, Qt.CheckState):
            check_state = state
        else:
            check_state = Qt.Checked if bool(state) else Qt.Unchecked

        self._is_updating_checks = True
        
        def recurse_check(item):
            item.setCheckState(0, check_state)
            for j in range(item.childCount()):
                recurse_check(item.child(j))
                
        for i in range(self.tree.topLevelItemCount()):
            recurse_check(self.tree.topLevelItem(i))
            
        self._is_updating_checks = False
        self.update_stats()


    def _on_category_edited(self, item: QTreeWidgetItem, new_cat_name: str):
        """处理建议归档分类就地微调修改，基于 ArchiveDestinationPath 防重去冗余并全域同构级联更新"""
        u_data = item.data(0, Qt.UserRole)
        if not u_data or not new_cat_name:
            return

        item_type = u_data.get("type")
        if item_type == "group":
            group = u_data["data"]
            old_cat = group.get("effective_category", group.get("suggested_category", ""))
            if new_cat_name == old_cat:
                return

            group["effective_category"] = new_cat_name
            group["suggested_category"] = new_cat_name
            group["source"] = "User"
            group["require_confirmation"] = True

            # 通过 ArchiveDestinationPath 构建新的目标根目录 (彻底去除重复段)
            orig_root_p = Path(group.get("original_root", ""))
            clean_sub = sanitize_subpath(group.get("recommended_subpath", ""))
            dest_obj = ArchiveDestinationPath.build(
                dest_root=self.destination_root,
                category=new_cat_name,
                subpath=clean_sub,
                entity_name=orig_root_p.name,
                is_dir=group.get("is_directory_group", True)
            )
            group["target_root"] = str(dest_obj)
            item.setData(0, Qt.UserRole, u_data)

            # 同步更新 self.classification_items 原始数据引用
            for orig_g in self.classification_items:
                if orig_g.get("group_id") == group.get("group_id") or orig_g.get("original_root") == group.get("original_root"):
                    orig_g["target_root"] = str(dest_obj)
                    orig_g["effective_category"] = new_cat_name
                    orig_g["suggested_category"] = new_cat_name
                    orig_g["source"] = "User"
                    orig_g["require_confirmation"] = True
                    for sub in orig_g.get("sub_items", []):
                        rel = sub.get("relative_path", "")
                        if rel and orig_g.get("is_directory_group", True):
                            sub["target_path"] = dest_obj.relative_join(rel)
                        else:
                            sub["target_path"] = dest_obj.relative_join(sub.get("name", Path(rel).name if rel else "unnamed"))

            item.setText(2, new_cat_name)
            item.setText(3, str(dest_obj))
            app_name = group.get("app_name", orig_root_p.name)
            item.setText(1, f"{app_name} [User]")
            item.setForeground(1, QBrush(QColor("#F59E0B")))  # Warn amber

            # 记录历史路径
            HistorySuggestionProvider.record_path(str(dest_obj))

            # 手动修改顶格覆盖主路由表 (USER_CONFIRMED 强制覆盖且永不被 AI 冲刷)
            orig_root = group.get("original_root", "")
            pattern_name = group.get("name", Path(orig_root).name if orig_root else "")
            morph = MorphologyType.SEALED_COLLECTIVE if group.get("is_directory_group") else MorphologyType.INDEPENDENT_ASSET
            TopologyRoutingTable.instance().record_user_override(
                pattern_or_name=pattern_name,
                new_cat=new_cat_name,
                new_target=str(dest_obj),
                morphology=morph
            )

            # 级联更新已展开的子项
            for i in range(item.childCount()):
                child = item.child(i)
                c_data = child.data(0, Qt.UserRole)
                if c_data and c_data.get("type") == "file":
                    sub = c_data["data"]
                    rel = sub.get("relative_path", "")
                    if rel and group.get("is_directory_group", True):
                        new_sub_target = dest_obj.relative_join(rel)
                    else:
                        new_sub_target = dest_obj.relative_join(sub.get("name", Path(rel).name if rel else "unnamed"))
                    sub["target_path"] = new_sub_target
                    child.setData(0, Qt.UserRole, c_data)
                    child.setText(2, new_cat_name)
                    child.setText(3, new_sub_target)

            # 确保原始数据模型中的 sub_items 也同步更新 (针对尚未展开的节点)
            for sub in group.get("sub_items", []):
                rel = sub.get("relative_path", "")
                if rel and group.get("is_directory_group", True):
                    sub["target_path"] = dest_obj.relative_join(rel)
                else:
                    sub["target_path"] = dest_obj.relative_join(sub.get("name", Path(rel).name if rel else "unnamed"))

            self.tree.viewport().update()

        elif item_type == "file":
            sub = u_data["data"]
            sub["category"] = new_cat_name
            item.setText(2, new_cat_name)
            sub_name = sub.get("name", "")
            if sub_name:
                TopologyRoutingTable.instance().record_user_override(
                    pattern_or_name=sub_name,
                    new_cat=new_cat_name,
                    new_target=sub.get("target_path", ""),
                    morphology=MorphologyType.INDEPENDENT_ASSET
                )
            self.tree.viewport().update()

    def _on_path_edited(self, item: QTreeWidgetItem, new_path_str: str):
        """处理目标规划路径就地微调修改，执行安全检验并全域同构级联更新"""
        u_data = item.data(0, Qt.UserRole)
        if not u_data or not new_path_str:
            return

        dest_obj = ArchiveDestinationPath(new_path_str)
        is_safe, reason = dest_obj.is_safe()
        if not is_safe:
            QMessageBox.warning(self, "规划路径不合法", f"所填写的归档规划路径存在安全风险: {reason}")
            return

        HistorySuggestionProvider.record_path(new_path_str)

        item_type = u_data.get("type")
        if item_type == "group":
            group = u_data["data"]
            old_path = group.get("target_root", "")
            if new_path_str == old_path:
                return

            group["target_root"] = new_path_str
            item.setData(0, Qt.UserRole, u_data)

            # 同步更新 self.classification_items 原始数据引用
            for orig_g in self.classification_items:
                if orig_g.get("group_id") == group.get("group_id") or orig_g.get("original_root") == group.get("original_root"):
                    orig_g["target_root"] = new_path_str
                    orig_g["source"] = "User"
                    orig_g["require_confirmation"] = True
                    for sub in orig_g.get("sub_items", []):
                        rel = sub.get("relative_path", "")
                        if rel and orig_g.get("is_directory_group", True):
                            sub["target_path"] = dest_obj.relative_join(rel)
                        else:
                            sub["target_path"] = dest_obj.relative_join(sub.get("name", Path(rel).name if rel else "unnamed"))

            item.setText(3, new_path_str)
            orig_root_p = Path(group.get("original_root", ""))
            app_name = group.get("app_name", orig_root_p.name)
            item.setText(1, f"{app_name} [User]")
            item.setForeground(1, QBrush(QColor("#F59E0B")))

            # 级联更新已展开的子项
            for i in range(item.childCount()):
                child = item.child(i)
                c_data = child.data(0, Qt.UserRole)
                if c_data and c_data.get("type") == "file":
                    sub = c_data["data"]
                    rel = sub.get("relative_path", "")
                    if rel and group.get("is_directory_group", True):
                        new_sub_target = dest_obj.relative_join(rel)
                    else:
                        new_sub_target = dest_obj.relative_join(sub.get("name", Path(rel).name if rel else "unnamed"))
                    sub["target_path"] = new_sub_target
                    child.setData(0, Qt.UserRole, c_data)
                    child.setText(3, new_sub_target)

            # 确保原始数据模型中的 sub_items 也同步更新
            for sub in group.get("sub_items", []):
                rel = sub.get("relative_path", "")
                if rel and group.get("is_directory_group", True):
                    sub["target_path"] = dest_obj.relative_join(rel)
                else:
                    sub["target_path"] = dest_obj.relative_join(sub.get("name", Path(rel).name if rel else "unnamed"))

            # 手动修改顶格覆盖主路由表 (USER_CONFIRMED 强制覆盖且永不被 AI 冲刷)
            orig_root = group.get("original_root", "")
            pattern_name = group.get("name", Path(orig_root).name if orig_root else "")
            morph = MorphologyType.SEALED_COLLECTIVE if group.get("is_directory_group") else MorphologyType.INDEPENDENT_ASSET
            TopologyRoutingTable.instance().record_user_override(
                pattern_or_name=pattern_name,
                new_cat=group.get("effective_category", group.get("suggested_category", "未分类/待人工确认")),
                new_target=new_path_str,
                morphology=morph
            )

            self.tree.viewport().update()

        elif item_type == "file":
            sub = u_data["data"]
            sub["target_path"] = new_path_str
            item.setData(0, Qt.UserRole, u_data)
            item.setText(3, new_path_str)
            sub_name = sub.get("name", "")
            if sub_name:
                TopologyRoutingTable.instance().record_user_override(
                    pattern_or_name=sub_name,
                    new_cat=sub.get("category", "未分类/待人工确认"),
                    new_target=new_path_str,
                    morphology=MorphologyType.INDEPENDENT_ASSET
                )
            self.tree.viewport().update()

    def _on_category_changed(self, group_item, new_cat_name):
        """向下兼容历史调用"""
        self._on_category_edited(group_item, new_cat_name)


    def _on_item_expanded(self, item):
        if item.childCount() == 1 and item.child(0).text(0) == "加载中...":
            u_data = item.data(0, Qt.UserRole)
            if not u_data or u_data.get("type") != "group": return
            
            parent_check_state = item.checkState(0)
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
                    child_item.setFlags(
                        child_item.flags() |
                        Qt.ItemIsUserCheckable |
                        Qt.ItemIsAutoTristate |
                        Qt.ItemIsEditable |
                        Qt.ItemIsEnabled |
                        Qt.ItemIsSelectable
                    )
                    child_item.setCheckState(0, parent_check_state)
                    
                    child_item.setData(0, Qt.UserRole, {"type": "file", "data": sub, "parent_group": group})
                    child_item.setText(0, sub.get("relative_path", ""))
                    child_item.setText(1, "-")
                    child_cat = group.get("effective_category", group.get("suggested_category", ""))
                    child_item.setText(2, child_cat)
                    child_item.setTextAlignment(2, Qt.AlignCenter)
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
                    # 子项统一绿底白字，第2列天蓝，第3列琥珀金
                    child_bg = QBrush(QColor("#065F46"))
                    child_fg = QBrush(QColor("#FFFFFF"))
                    for c_col in range(10):
                        child_item.setBackground(c_col, child_bg)
                        child_item.setForeground(c_col, child_fg)
                    child_item.setForeground(2, QBrush(QColor("#38BDF8")))
                    child_item.setForeground(3, QBrush(QColor("#FBBF24")))
                    new_children.append(child_item)
                    
                    if len(new_children) >= batch_size:
                        item.addChildren(new_children)
                        new_children = []
                        files_processed += batch_size
                        if use_progress and progress:
                            progress.setValue(files_processed)
                            if not os.environ.get("QT_QPA_PLATFORM"):
                                QApplication.processEvents()
                            
                if new_children:
                    item.addChildren(new_children)
                    files_processed += len(new_children)
                    if use_progress and progress:
                        progress.setValue(files_processed)
            finally:
                self.tree.setUpdatesEnabled(True)
                if use_progress and progress:
                    progress.setValue(total_files)

    def _expand_all_with_progress(self):
        try:
            self.tree.itemExpanded.disconnect(self._on_item_expanded)
        except RuntimeError:
            pass
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

        use_progress = total_files > 500 and not os.environ.get("QT_QPA_PLATFORM")
        if use_progress:
            progress = QProgressDialog("正在分批展开目录树...", "取消", 0, total_files, self)
            progress.setWindowTitle("批量展开")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
        else:
            progress = None
        
        from app.utils.file_helper import format_size
        files_processed = 0
        batch_size = 500
        self.tree.setUpdatesEnabled(False)
        
        try:
            for item in groups_to_expand:
                if progress and progress.wasCanceled():
                    break
                u_data = item.data(0, Qt.UserRole)
                if not u_data or u_data.get("type") != "group":
                    continue
                
                if item.childCount() == 1 and item.child(0).text(0) == "加载中...":
                    parent_check_state = item.checkState(0)
                    item.removeChild(item.child(0))
                    group = u_data["data"]
                    risk = group.get("risk_level", "未知风险")
                    if "低风险" in risk: risk_color = QColor("#10B981")
                    elif "中风险" in risk: risk_color = QColor("#F59E0B")
                    else: risk_color = QColor("#EF4444")
                    
                    sub_items = group.get("sub_items", [])
                    new_children = []
                    for i, sub in enumerate(sub_items):
                        if progress and progress.wasCanceled():
                            break
                        child_item = QTreeWidgetItem()
                        child_item.setFlags(
                            child_item.flags() |
                            Qt.ItemIsUserCheckable |
                            Qt.ItemIsAutoTristate |
                            Qt.ItemIsEditable |
                            Qt.ItemIsEnabled |
                            Qt.ItemIsSelectable
                        )
                        child_item.setCheckState(0, parent_check_state)
                        
                        child_item.setData(0, Qt.UserRole, {"type": "file", "data": sub, "parent_group": group})
                        child_item.setText(0, sub.get("relative_path", ""))
                        child_item.setText(1, "-")
                        child_cat = group.get("effective_category", group.get("suggested_category", ""))
                        child_item.setText(2, child_cat)
                        child_item.setTextAlignment(2, Qt.AlignCenter)
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
                        # 子项统一绿底白字，第2列天蓝，第3列琥珀金
                        child_bg = QBrush(QColor("#065F46"))
                        child_fg = QBrush(QColor("#FFFFFF"))
                        for c_col in range(10):
                            child_item.setBackground(c_col, child_bg)
                            child_item.setForeground(c_col, child_fg)
                        child_item.setForeground(2, QBrush(QColor("#38BDF8")))
                        child_item.setForeground(3, QBrush(QColor("#FBBF24")))
                        new_children.append(child_item)
                        
                        if len(new_children) >= batch_size:
                            item.addChildren(new_children)
                            new_children = []
                            files_processed += batch_size
                            if progress:
                                progress.setValue(files_processed)
                            if not os.environ.get("QT_QPA_PLATFORM"):
                                QApplication.processEvents()
                            
                    if new_children:
                        item.addChildren(new_children)
                        files_processed += len(new_children)
                        if progress:
                            progress.setValue(files_processed)
                        if not os.environ.get("QT_QPA_PLATFORM"):

                            QApplication.processEvents()
                item.setExpanded(True)
        finally:
            self.tree.setUpdatesEnabled(True)
            self.tree.itemExpanded.connect(self._on_item_expanded)
            if progress:
                progress.setValue(total_files)

    def _select_safe_only(self):
        self._is_updating_checks = True
        
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            u_data = item.data(0, Qt.UserRole) or {}
            if u_data.get("type") != "group":
                continue
            g_info = u_data.get("data", {})
            is_safe = (not g_info.get("require_confirmation", False)) and (g_info.get("confidence", 0) >= 0.7) and ("低风险" in g_info.get("risk_level", ""))
            target_state = Qt.Checked if is_safe else Qt.Unchecked
            
            item.setCheckState(0, target_state)
            for j in range(item.childCount()):
                item.child(j).setCheckState(0, target_state)
                
        self._is_updating_checks = False
        self.update_stats()


    def _schedule_update_stats(self, item, column):
        if column != 0: return
        if not hasattr(self, '_stats_timer'):
            from PySide6.QtCore import QTimer
            self._stats_timer = QTimer(self)
            self._stats_timer.setSingleShot(True)
            self._stats_timer.timeout.connect(self.update_stats)
        self._stats_timer.start(50) # 50ms debounce

    def update_stats(self):
        selected_items = self.get_selected_file_items()
        selected_count = len(selected_items)
        total_bytes = sum(it.get("size", 0) for it in selected_items)
        
        from app.utils.file_helper import format_size
        self.lbl_auto_checked.setText(f"已勾选: {selected_count}项 ({format_size(total_bytes)})")
        
        total_groups = len(self.classification_items)
        total_files = sum(g.get("file_count", len(g.get("sub_items", []))) for g in self.classification_items)
        need_conf_groups = sum(1 for g in self.classification_items if g.get("require_confirmation", False))
        if hasattr(self, "stats_label") and self.stats_label:
            self.stats_label.setText(
                f"待归档单元: <b>{total_groups}</b> 个目录/组 (共 <b>{total_files}</b> 个文件) | "
                f"需人工确认: <span style='color: {'#F59E0B' if need_conf_groups > 0 else '#10B981'}; font-weight: bold;'>{need_conf_groups} 组</span> | "
                f"已勾选: <span style='color: #10B981; font-weight: bold;'>{selected_count} 个文件 ({format_size(total_bytes)})</span>"
            )

    def export_script(self):
        """仅导出执行批处理脚本"""
        selected_file_items = self.get_selected_file_items()

        if not selected_file_items:
            QMessageBox.warning(self, "提示", "未勾选任何文件！")
            return

        from pathlib import Path
        import os
        
        script_path, _ = QFileDialog.getSaveFileName(self, "保存批处理脚本", "DiskAnalyzer_Migration.bat", "Batch Files (*.bat)")
        if not script_path:
            return

        try:
            with open(script_path, "w", encoding="utf-8") as f:
                f.write("@echo off\n")
                f.write("chcp 65001 > nul\n")
                f.write("echo === 空间全景深度分析与冗余文件扫描 - 文件迁移脚本 ===\n\n")
                for item in selected_file_items:
                    src = os.path.normpath(item["path"])
                    custom_target = item.get("custom_target")
                    if custom_target:
                        dest = os.path.normpath(custom_target)
                    else:
                        dest = os.path.normpath(str(Path(self.destination_root) / item.get("target_category", "") / Path(src).name))
                    
                    dest_dir = os.path.dirname(dest)
                    f.write(f'if not exist "{dest_dir}" mkdir "{dest_dir}"\n')
                    f.write(f'move /Y "{src}" "{dest}"\n')
                
                f.write("\necho.\necho 迁移完成！\npause\n")
            
            QMessageBox.information(self, "导出成功", f"脚本已成功导出至：\n{script_path}")
            # Do not close dialog, let user decide if they want to exit
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"无法写入文件: {e}")

    def execute_archive(self):
        """收集勾选的项目并启动后台流式归档"""
        selected_file_items = self.get_selected_file_items()

        if not selected_file_items:
            QMessageBox.warning(self, "提示", "您尚未勾选任何需要归档的目录或文件！")
            return

        selected_groups_count = 0
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.checkState(0) in (Qt.Checked, Qt.PartiallyChecked):
                selected_groups_count += 1

        total_bytes = sum(it.get("size", 0) for it in selected_file_items)
        reply = QMessageBox.question(
            self, "确认启动后台归档",
            f"已勾选 <b>{len(selected_file_items)}</b> 个文件 (共 {format_size(total_bytes)})\n"
            f"包含 <b>{selected_groups_count}</b> 个完整工具/目录处理单元。\n\n"
            f"目标根目录: <code>{self.destination_root}</code>\n"
            f"是否立即启动后台流式安全归档？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        self.btn_execute.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("正在执行后台目录级安全归档...")

        report_id = ""
        scan_id = ""
        if hasattr(self, "classification_items") and self.classification_items and len(self.classification_items) > 0:
            report_id = self.classification_items[0].get("report_id", "")
            scan_id = self.classification_items[0].get("task_id", "")
        self.archive_worker = ArchiveWorker(
            file_items=selected_file_items,
            destination_root=self.destination_root,
            conflict_policy=self.conflict_policy,
            preserve_structure=True,
            report_id=report_id,
            scan_task_id=scan_id
        )
        from app.core.task_manager import global_task_manager, TaskType
        self.archive_task = global_task_manager.create_task(
            name=f"批量归档 ({len(selected_file_items)} 项)",
            task_type=TaskType.MIGRATION,
            worker=self.archive_worker
        )
        self.archive_worker.progress_signal.connect(self.on_archive_progress)
        self.archive_worker.finished_signal.connect(self.on_archive_finished)
        self.archive_worker.start()

    def on_archive_progress(self, cur, tot, speed, eta, proc_b, tot_b):
        pct = (cur / tot * 100.0) if tot > 0 else 0.0
        self.progress_bar.setValue(int(pct))
        self.status_label.setText(
            f"⚡ 正在归档: {cur}/{tot} ({format_size(proc_b)} / {format_size(tot_b)}) | 速度: {speed} | 预计剩余: {eta}s"
        )

    def on_archive_finished(self, all_success: bool, summary: dict):
        self.btn_execute.setEnabled(True)
        self.btn_cancel.setEnabled(True)
        self.last_manifest_path = summary.get("manifest_path", "")
        self.last_summary = summary

        msg = (
            f"🎉 智能目录归档已全部完成！\n"
            f"成功迁移: {summary['success_count']} 个文件\n"
            f"失败项: {summary['failed_count']} 个 | 跳过项: {summary['skipped_count']} 个\n"
            f"释放/迁移容量: {format_size(summary['archived_bytes'])}\n"
            f"回滚凭证: {Path(summary.get('manifest_path', '')).name}\n\n"
            f"是否立即在文件资源管理器中打开目标归档目录？"
        )
        reply = QMessageBox.question(self, "归档任务完成", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply == QMessageBox.Yes:
            if os.path.exists(self.destination_root):
                subprocess.Popen(f'explorer.exe "{os.path.normpath(self.destination_root)}"')

        self.accept()
