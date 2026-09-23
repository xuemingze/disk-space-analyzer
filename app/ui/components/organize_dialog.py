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
        self.tree.setColumnCount(8)
        self.tree.setHeaderLabels([
            "目录 / 文件单元", "所属 App / 工具", "建议归档分类", "目标规划路径",
            "识别依据 / 特征", "数量 / 大小", "置信度", "安全等级"
        ])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemChanged.connect(self.on_tree_item_changed)
        
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        self.tree.setColumnWidth(0, 260)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        self.tree.setColumnWidth(1, 150)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        self.tree.setColumnWidth(2, 140)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        self.tree.setColumnWidth(3, 180)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)

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
        """装填目录树结构"""
        self._is_updating_checks = True
        self.tree.clear()

        for group in self.classification_items:
            # 判断是否为整体目录单元
            is_dir = group.get("is_directory_group", True)
            group_name = group.get("name", "")
            orig_root = group.get("original_root", "")
            target_root = group.get("target_root", "")
            app_name = group.get("app_name", "未识别工具/待分类")
            category = group.get("suggested_category", "未识别工具/待分类")
            rationale = group.get("rationale", "-")
            conf = float(group.get("confidence", 0.8))
            risk = group.get("risk_level", "低风险")
            require_conf = group.get("require_confirmation", False)
            sub_items = group.get("sub_items", [])
            total_size = group.get("total_size", 0)
            file_count = group.get("file_count", len(sub_items))

            # 创建父节点 (Top Level Tree Item)
            parent_item = QTreeWidgetItem(self.tree)
            parent_item.setFlags(parent_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            
            # 默认勾选策略：若不需要人工确认且置信度>=0.7，则默认勾选
            default_checked = (not require_conf) and (conf >= 0.7) and ("低风险" in risk)
            parent_item.setCheckState(0, Qt.Checked if default_checked else Qt.Unchecked)

            # 0. 目录名称 (带图标与提示)
            icon_prefix = "📁 " if is_dir else "📄 "
            parent_item.setText(0, f"{icon_prefix}{group_name}")
            parent_item.setToolTip(0, f"原根路径: {orig_root}")
            parent_item.setData(0, Qt.UserRole, {"type": "group", "data": group})

            # 1. 所属 App / 工具
            parent_item.setText(1, app_name)
            parent_item.setForeground(1, QBrush(QColor("#38BDF8")))
            font = parent_item.font(1)
            font.setBold(True)
            parent_item.setFont(1, font)

            # 2. 建议归档分类
            parent_item.setText(2, category)
            parent_item.setForeground(2, QBrush(QColor("#A7F3D0")))

            # 3. 目标规划路径
            parent_item.setText(3, target_root)
            parent_item.setToolTip(3, f"目标路径: {target_root}")

            # 4. 依据 / 特征
            parent_item.setText(4, rationale)
            parent_item.setToolTip(4, rationale)

            # 5. 数量 / 大小
            size_str = f"{file_count} 项 ({format_size(total_size)})" if is_dir else format_size(total_size)
            parent_item.setText(5, size_str)
            parent_item.setTextAlignment(5, Qt.AlignRight | Qt.AlignVCenter)

            # 6. 置信度
            parent_item.setText(6, f"{conf * 100:.0f}%")
            parent_item.setTextAlignment(6, Qt.AlignCenter)

            # 7. 安全等级
            parent_item.setText(7, risk)
            parent_item.setTextAlignment(7, Qt.AlignCenter)
            if "低风险" in risk:
                parent_item.setForeground(7, QBrush(QColor("#10B981")))
            elif "中风险" in risk:
                parent_item.setForeground(7, QBrush(QColor("#F59E0B")))
            else:
                parent_item.setForeground(7, QBrush(QColor("#EF4444")))

            # 添加子节点（展开可查每个具体文件的相对层级与目标路径）
            for sub in sub_items:
                child_item = QTreeWidgetItem(parent_item)
                child_item.setFlags(child_item.flags() | Qt.ItemIsUserCheckable)
                child_item.setCheckState(0, Qt.Checked if default_checked else Qt.Unchecked)

                rel_p = sub.get("relative_path", sub.get("name", ""))
                child_item.setText(0, f"  └ {rel_p}")
                child_item.setToolTip(0, f"原绝对路径: {sub.get('original_path')}")
                child_item.setData(0, Qt.UserRole, {"type": "file", "data": sub, "group": group})

                child_item.setText(1, "-")
                child_item.setText(2, category)
                child_item.setText(3, sub.get("target_path", ""))
                child_item.setToolTip(3, f"目标文件: {sub.get('target_path')}")
                child_item.setText(4, "包含在目录单元中")
                child_item.setText(5, format_size(sub.get("size", 0)))
                child_item.setTextAlignment(5, Qt.AlignRight | Qt.AlignVCenter)
                child_item.setText(6, "-")
                child_item.setText(7, risk)
                child_item.setForeground(7, parent_item.foreground(7))

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
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            top.setCheckState(0, check_state)
            for j in range(top.childCount()):
                top.child(j).setCheckState(0, check_state)
        self._is_updating_checks = False

    def _select_safe_only(self):
        self._is_updating_checks = True
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            u_data = top.data(0, Qt.UserRole) or {}
            g_info = u_data.get("data", {})
            
            is_safe = (not g_info.get("require_confirmation", False)) and (g_info.get("confidence", 0) >= 0.7) and ("低风险" in g_info.get("risk_level", ""))
            target_state = Qt.Checked if is_safe else Qt.Unchecked
            top.setCheckState(0, target_state)
            for j in range(top.childCount()):
                top.child(j).setCheckState(0, target_state)
        self._is_updating_checks = False

    def execute_archive(self):
        """收集勾选的项目并启动后台流式归档"""
        selected_file_items = []
        selected_groups_count = 0

        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            top_state = top.checkState(0)
            u_data = top.data(0, Qt.UserRole) or {}
            group_data = u_data.get("data", {})

            if top_state == Qt.Checked:
                # 整个目录单元完全勾选 -> 整体归档其所有子项并保持相对路径
                selected_groups_count += 1
                for sub in group_data.get("sub_items", []):
                    selected_file_items.append({
                        "path": sub["original_path"],
                        "target_category": group_data.get("suggested_category"),
                        "custom_target": sub.get("target_path")
                    })
            elif top_state == Qt.PartiallyChecked:
                # 部分勾选 -> 仅归档被勾选的子项
                for j in range(top.childCount()):
                    child = top.child(j)
                    if child.checkState(0) == Qt.Checked:
                        c_data = child.data(0, Qt.UserRole) or {}
                        sub_info = c_data.get("data", {})
                        selected_file_items.append({
                            "path": sub_info["original_path"],
                            "target_category": group_data.get("suggested_category"),
                            "custom_target": sub_info.get("target_path")
                        })

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

        self.archive_worker = ArchiveWorker(
            file_items=selected_file_items,
            destination_root=self.destination_root,
            conflict_policy=self.conflict_policy,
            preserve_structure=True
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
