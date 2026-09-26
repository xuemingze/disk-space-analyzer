import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QApplication,
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QProgressBar, QMessageBox, QFrame, QAbstractItemView,
    QMenu
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QBrush, QFont, QIcon

from PySide6.QtWidgets import QComboBox
from app.core.category_manager import global_category_manager
from pathlib import Path
from app.core.cleaner import ArchiveWorker
from app.utils.file_helper import format_size


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
        self.populate_tree()

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

        # 展开/折叠按钮
        self.btn_expand_all = QPushButton("📂 全部展开")
        self.btn_expand_all.setProperty("class", "SecondaryButton")
        self.btn_expand_all.clicked.connect(lambda: self.tree.expandAll())
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
        self.tree.itemChanged.connect(self.on_tree_item_changed)
        self.tree.itemExpanded.connect(self._on_item_expanded)
        
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
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.ResizeToContents)
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


    def populate_tree(self):
        self._is_updating_checks = True
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        
        folder_bg = QBrush(QColor("#E3F2FD"))
        folder_fg = QBrush(QColor("#000000"))
        
        auto_checked_count = 0
        unselected_count = 0
        risk_low = 0
        risk_mid = 0
        risk_high = 0

        for group in self.classification_items:
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
            group_item.setFlags(group_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            group_item.setCheckState(0, Qt.Checked if default_checked else Qt.Unchecked)
            group_item.setData(0, Qt.UserRole, {"type": "group", "data": group})
            
            from pathlib import Path
            pt = Path(orig_root)
            display_name = pt.name if pt.name else str(pt)
            group_item.setText(0, f"📦 {display_name}")
            group_item.setToolTip(0, orig_root)
            
            for col in range(8):
                group_item.setBackground(col, folder_bg)
                group_item.setForeground(col, folder_fg)
                
            source = group.get("source", "离线规则")
            group_item.setText(1, f"{group.get('app_name', '')} [{source}]")
            font = group_item.font(1)
            font.setBold(True)
            if source == "AI":
                group_item.setForeground(1, QBrush(QColor("#38BDF8")))
            else:
                group_item.setForeground(1, QBrush(QColor("#94A3B8")))
            group_item.setFont(1, font)
            
            combo = QComboBox()
            cats = ["未分类/待人工确认"] + [c["name"] for c in global_category_manager.get_active()]
            combo.addItems(cats)
            
            curr_cat = group.get("suggested_category", "")
            if curr_cat in cats:
                combo.setCurrentText(curr_cat)
            else:
                combo.addItem(curr_cat)
                combo.setCurrentText(curr_cat)
                
            combo.currentTextChanged.connect(lambda txt, it=group_item: self._on_category_changed(it, txt))
            self.tree.setItemWidget(group_item, 2, combo)
            
            group_item.setText(3, group.get("target_root", ""))
            group_item.setText(4, group.get("rationale", ""))
            
            total_size = sum(s.get("size", 0) for s in sub_items)
            size_str = f"{len(sub_items)} 项 ({format_size(total_size)})"
            group_item.setText(5, size_str)
            group_item.setTextAlignment(5, Qt.AlignRight | Qt.AlignVCenter)
            
            group_item.setText(6, f"{conf * 100:.0f}%")
            group_item.setTextAlignment(6, Qt.AlignCenter)
            
            group_item.setText(7, risk)
            group_item.setTextAlignment(7, Qt.AlignCenter)
            group_item.setForeground(7, QBrush(risk_color))
            
            group_item.setText(8, group.get("action", ""))
            group_item.setTextAlignment(8, Qt.AlignCenter)
            
            task_info = f"R:{group.get('report_id','-')} | T:{group.get('task_id','-')}"
            group_item.setText(9, task_info)
            
            if sub_items:
                dummy = QTreeWidgetItem(group_item)
                dummy.setText(0, "加载中...")

        self._is_updating_checks = False
        self.tree.setUpdatesEnabled(True)
        # self.tree.expandToDepth(0)


    def on_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        """父子节点联动勾选事件响应"""
        if self._is_updating_checks or column != 0:
            return

        self._is_updating_checks = True
        state = item.checkState(0)

        # 1. 若改变的是父节点，递归更新所有子节点
        if item.childCount() > 0:
            for i in range(item.childCount()):
                child = item.child(i)
                child.setCheckState(0, state)

        # 2. 若改变的是子节点，更新父节点状态 (Checked / PartiallyChecked / Unchecked)
        parent = item.parent()
        if parent:
            checked_count = 0
            partial_count = 0
            for i in range(parent.childCount()):
                ch_state = parent.child(i).checkState(0)
                if ch_state == Qt.Checked:
                    checked_count += 1
                elif ch_state == Qt.PartiallyChecked:
                    partial_count += 1

            if checked_count == parent.childCount():
                parent.setCheckState(0, Qt.Checked)
            elif checked_count > 0 or partial_count > 0:
                parent.setCheckState(0, Qt.PartiallyChecked)
            else:
                parent.setCheckState(0, Qt.Unchecked)

        self._is_updating_checks = False

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


    def _on_category_changed(self, group_item, new_cat_name):
        u_data = group_item.data(0, Qt.UserRole)
        if not u_data or u_data.get("type") != "group":
            return
            
        group = u_data["data"]
        group["effective_category"] = new_cat_name
        group["source"] = "User"
        
        # Recalculate target root
        dest_root_p = Path(self.destination_root)
        orig_root_p = Path(group.get("original_root", ""))
        
        # Calculate new target base
        active_cats = global_category_manager.get_active()
        template = "{archive_root}/{category_name}/{app_name}"
        for cat in active_cats:
            if cat["name"] == new_cat_name:
                template = cat.get("target_path_template", template)
                break
                
        app_name = group.get("app_name", orig_root_p.name)
        res = template.replace("{archive_root}", str(dest_root_p))
        res = res.replace("{category_name}", new_cat_name)
        res = res.replace("{app_name}", app_name)
        
        new_target_base = Path(res)
        if not group.get("is_directory_group", True):
            # For loose files, the group root might just be the dest folder
            if "{app_name}" not in template:
                new_target_base = dest_root_p / new_cat_name
                
        group["target_root"] = str(new_target_base)
        group_item.setText(3, str(new_target_base))
        group_item.setText(1, f"{app_name} [User]")
        group_item.setForeground(1, QBrush(QColor("#F59E0B"))) # Warn color for manual
        
        # If manual, set requires confirmation to true
        group["require_confirmation"] = True
        
        # Update children
        for i in range(group_item.childCount()):
            child = group_item.child(i)
            c_data = child.data(0, Qt.UserRole)
            if c_data and c_data.get("type") == "file":
                sub = c_data["data"]
                rel = sub.get("relative_path", "")
                if rel:
                    new_sub_target = new_target_base / Path(rel)
                    sub["target_path"] = str(new_target_base / Path(rel))
                    child.setText(3, str(new_sub_target))
                child.setText(2, new_cat_name)
                
        self.tree.viewport().update()


    def _on_item_expanded(self, item):
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
                child_item.setText(7, risk)
                child_item.setTextAlignment(7, Qt.AlignCenter)
                child_item.setForeground(7, QBrush(risk_color))
                child_item.setText(8, group.get("action", ""))
                child_item.setTextAlignment(8, Qt.AlignCenter)
                child_item.setText(9, f"R:{group.get('report_id','-')} | T:{group.get('task_id','-')}")
                new_children.append(child_item)
            item.addChildren(new_children)
            self.tree.setUpdatesEnabled(True)

    def _select_safe_only(self):
        self._is_updating_checks = True
        
        def recurse_safe(item, parent_safe=False):
            u_data = item.data(0, Qt.UserRole) or {}
            g_info = u_data.get("data", {}) if u_data.get("type") == "group" else u_data.get("group", {})
            
            is_safe = parent_safe
            if u_data.get("type") == "group" and g_info:
                is_safe = (not g_info.get("require_confirmation", False)) and (g_info.get("confidence", 0) >= 0.7) and ("低风险" in g_info.get("risk_level", ""))
            
            if u_data.get("type") == "file":
                item.setCheckState(0, Qt.Checked if is_safe else Qt.Unchecked)
                
            for j in range(item.childCount()):
                recurse_safe(item.child(j), is_safe)
                
        for i in range(self.tree.topLevelItemCount()):
            recurse_safe(self.tree.topLevelItem(i))
            
        self._is_updating_checks = False


    def export_script(self):
        """仅导出执行批处理脚本"""
        selected_file_items = []
        
        def recurse_collect(item):
            state = item.checkState(0)
            u_data = item.data(0, Qt.UserRole) or {}
            if u_data.get("type") == "file" and state == Qt.Checked:
                sub_info = u_data.get("data", {})
                group_data = u_data.get("group", {})
                if sub_info:
                    eff_cat = group_data.get("effective_category", group_data.get("suggested_category", ""))
                    selected_file_items.append({
                        "path": sub_info.get("original_path", ""),
                        "target_category": eff_cat,
                        "custom_target": sub_info.get("target_path", "")
                    })
            for j in range(item.childCount()):
                recurse_collect(item.child(j))

        for i in range(self.tree.topLevelItemCount()):
            recurse_collect(self.tree.topLevelItem(i))

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
        selected_file_items = []
        selected_groups_count = 0

        def recurse_collect(item):
            state = item.checkState(0)
            u_data = item.data(0, Qt.UserRole) or {}
            
            if u_data.get("type") == "file" and state == Qt.Checked:
                sub_info = u_data.get("data", {})
                group_data = u_data.get("group", {})
                if sub_info:
                    eff_cat = group_data.get("effective_category", group_data.get("suggested_category", ""))
                    selected_file_items.append({
                        "path": sub_info.get("original_path", ""),
                        "target_category": eff_cat,
                        "custom_target": sub_info.get("target_path", "")
                    })
            
            for j in range(item.childCount()):
                recurse_collect(item.child(j))

        for i in range(self.tree.topLevelItemCount()):
            recurse_collect(self.tree.topLevelItem(i))

        if not selected_file_items:
            QMessageBox.warning(self, "提示", "您尚未勾选任何需要归档的目录或文件！")
            return

        total_bytes = sum(os.path.getsize(it["path"]) for it in selected_file_items if os.path.exists(it["path"]))
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
