import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QProgressBar, QMessageBox, QFrame, QAbstractItemView,
    QMenu
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QBrush, QFont, QIcon

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
        parent=None
    ):
        super().__init__(parent)
        self.classification_items = classification_items
        self.destination_root = os.path.normpath(destination_root)
        self.conflict_policy = conflict_policy
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
        """装填目录树结构 (按原根路径完整层级)"""
        self._is_updating_checks = True
        self.tree.clear()

        node_map = {}
        dir_stats = {}

        folder_bg = QBrush(QColor("#E3F2FD"))
        folder_fg = QBrush(QColor("#000000"))
        file_bg = QBrush(QColor("#FFFFFF"))
        file_fg = QBrush(QColor("#000000"))
        
        auto_checked_count = 0
        unselected_count = 0
        risk_low = 0
        risk_mid = 0
        risk_high = 0

        for group in self.classification_items:
            orig_root = group.get("original_root", "")
            scan_root = group.get("scan_root", "")
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
            for sys_dir in ["windows", "program files", "programdata", "appdata", "system32"]:
                if sys_dir in orig_root.lower():
                    is_system_path = True
                    break
            
            # 严格拦截规则
            reject_reasons = []
            if "高风险" in risk or risk_color == QColor("#EF4444"):
                reject_reasons.append(risk)
            if "中风险" in risk:
                reject_reasons.append("中风险需复核")
            if conf < 0.75:
                reject_reasons.append(f"置信度偏低({conf})")
            if require_conf:
                reject_reasons.append("要求人工确认")
            if unrecognized:
                reject_reasons.append("未识别所属应用")
            if is_system_path:
                reject_reasons.append("涉及系统敏感目录")
                
            default_checked = len(reject_reasons) == 0
            if default_checked:
                auto_checked_count += 1
                group["reject_reason"] = ""
            else:
                unselected_count += 1
                group["reject_reason"] = " | ".join(reject_reasons)
                
            # Update root node text if rejected
            from pathlib import Path
            if not scan_root:
                scan_root = str(Path(orig_root).anchor) if orig_root else "C:\\"

            for sub in sub_items:
                orig_path = sub.get("original_path", "")
                if not orig_path: continue
                
                p = Path(orig_path)
                parts = []
                curr = p
                
                while str(curr) != str(curr.anchor) and str(curr) != scan_root and str(curr) != curr.parent.name:
                    parts.append(curr)
                    if str(curr) == scan_root or str(curr) == str(curr.parent):
                        break
                    curr = curr.parent
                if str(curr) not in [str(pt) for pt in parts]:
                    parts.append(curr)
                
                parts.reverse()

                parent_item = self.tree.invisibleRootItem()
                
                for idx, pt in enumerate(parts):
                    pt_str = str(pt)

                    is_file = (idx == len(parts) - 1 and p.is_file() if p.exists() else idx == len(parts) - 1)
                    
                    if pt_str not in node_map:
                        item = QTreeWidgetItem(parent_item)
                        item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                        item.setCheckState(0, Qt.Checked if default_checked else Qt.Unchecked)
                        
                        icon_prefix = "📄 " if is_file else "📁 "
                        display_name = pt.name if pt.name else str(pt)
                        if display_name.endswith("\\") or display_name.endswith("/"):
                            display_name = display_name[:-1]
                        if not display_name:
                            display_name = str(pt)
                            
                        item.setText(0, f"{icon_prefix}{display_name}")
                        item.setToolTip(0, pt_str)
                        
                        for col in range(8):
                            item.setBackground(col, file_bg if is_file else folder_bg)
                            item.setForeground(col, file_fg if is_file else folder_fg)
                        
                        node_map[pt_str] = item
                        if not is_file:
                            dir_stats[pt_str] = {"size": 0, "count": 0, "group_data": None}
                    
                    parent_item = node_map[pt_str]
                    
                    if not is_file:
                        dir_stats[pt_str]["size"] += sub.get("size", 0)
                        dir_stats[pt_str]["count"] += 1
                        
                        if pt_str == orig_root:
                            dir_stats[pt_str]["group_data"] = group
                            parent_item.setData(0, Qt.UserRole, {"type": "group", "data": group})
                            
                            app_name = group.get("app_name", "")
                            source = group.get("source", "离线规则")
                            parent_item.setText(1, f"{app_name} [{source}]")
                            font = parent_item.font(1)
                            font.setBold(True)
                            if source == "AI":
                                parent_item.setForeground(1, QBrush(QColor("#38BDF8")))
                            else:
                                parent_item.setForeground(1, QBrush(QColor("#94A3B8")))
                            parent_item.setFont(1, font)
                            
                            parent_item.setText(2, group.get("suggested_category", ""))
                            parent_item.setText(3, group.get("target_root", ""))
                            parent_item.setText(4, group.get("rationale", ""))
                            parent_item.setText(6, f"{conf * 100:.0f}%")
                            parent_item.setTextAlignment(6, Qt.AlignCenter)
                            
                            parent_item.setText(7, risk)
                            parent_item.setTextAlignment(7, Qt.AlignCenter)
                            parent_item.setForeground(7, QBrush(risk_color))
                            
                            action = group.get("action", "")
                            parent_item.setText(8, action)
                            parent_item.setTextAlignment(8, Qt.AlignCenter)
                            
                            task_info = f"R:{group.get('report_id','-')} | T:{group.get('task_id','-')}"
                            parent_item.setText(9, task_info)

                    if is_file:
                        parent_item.setData(0, Qt.UserRole, {"type": "file", "data": sub, "group": group})
                        parent_item.setText(1, "-")
                        parent_item.setText(2, group.get("suggested_category", ""))
                        parent_item.setText(3, sub.get("target_path", ""))
                        parent_item.setText(4, "包含在目录单元中")
                        parent_item.setText(5, format_size(sub.get("size", 0)))
                        parent_item.setTextAlignment(5, Qt.AlignRight | Qt.AlignVCenter)
                        parent_item.setText(6, "-")
                        parent_item.setTextAlignment(6, Qt.AlignCenter)
                        parent_item.setText(7, risk)
                        parent_item.setTextAlignment(7, Qt.AlignCenter)
                        parent_item.setForeground(7, QBrush(risk_color))
                        
                        action = group.get("action", "")
                        parent_item.setText(8, action)
                        parent_item.setTextAlignment(8, Qt.AlignCenter)
                        
                        task_info = f"R:{group.get('report_id','-')} | T:{group.get('task_id','-')}"
                        parent_item.setText(9, task_info)

        for pt_str, stats in dir_stats.items():
            item = node_map.get(pt_str)
            if item:
                size_str = f"{stats['count']} 项 ({format_size(stats['size'])})"
                item.setText(5, size_str)
                item.setTextAlignment(5, Qt.AlignRight | Qt.AlignVCenter)
                
        self._is_updating_checks = False
        self.tree.expandToDepth(0) # 默认展开第一层顶级目录

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
                    selected_file_items.append({
                        "path": sub_info.get("original_path", ""),
                        "target_category": group_data.get("suggested_category", ""),
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
        if self.groups and len(self.groups) > 0:
            report_id = self.groups[0].get("report_id", "")
            scan_id = self.groups[0].get("task_id", "")
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
