"""
app/ui/dedup/review_table_step.py
步骤 3: 重复组与冲突项审核看板
严格遵循《列表与表格模块 UI 设计铁律》:
- 垂直表头锁死 44px 行高 (setDefaultSectionSize(44) + QHeaderView.Fixed)
- 列宽清晰分层 (固定宽与 Stretch 结合)
- 操作按钮独立 QWidget 居中包装，高度固定 28px 保底
"""
import os
import time
from typing import List, Set, Optional, Dict, Any
from PySide6.QtWidgets import (
    QMenu, QMessageBox,
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
    QRadioButton, QButtonGroup, QFrame
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt, Signal
from app.dedup.models import DedupScanResult, DedupGroup, CollisionItem, DedupFileItem
from app.utils.file_helper import format_size


class ReviewTableStep(QWidget):
    """步骤 3: 查重与冲突项审核看板"""
    proceed_to_plan = Signal(object, set)  # (DedupScanResult, keep_paths_set)
    back_to_select = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scan_result: Optional[DedupScanResult] = None
        self.keep_paths: Set[str] = set()
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 头部说明与摘要栏
        top_bar = QHBoxLayout()
        header_box = QVBoxLayout()
        title = QLabel("🔍 步骤 3: 重复文件与冲突项审核")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1e293b;")
        desc = QLabel("严格遵循内容无损核对，默认自动推选最佳单份正本保留。冗余副本将安全移至隔离归档区，杜绝误删。")
        desc.setStyleSheet("font-size: 12px; color: #64748b;")
        header_box.addWidget(title)
        header_box.addWidget(desc)
        top_bar.addLayout(header_box)
        top_bar.addStretch()

        # 统计指标小卡片
        self.lbl_stats_badge = QLabel("重复组: 0 | 可释放: 0 B | 冲突: 0")
        self.lbl_stats_badge.setStyleSheet(
            "background-color: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; "
            "border-radius: 6px; padding: 6px 14px; font-weight: bold; font-size: 12px;"
        )
        top_bar.addWidget(self.lbl_stats_badge)
        layout.addLayout(top_bar)

        # 分页 TabWidget (重复组 / 冲突项 / 唯一项)
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabBar::tab { height: 32px; padding: 0 16px; font-weight: bold; }")

        # Tab 1: 完全重复组表格
        self.table_dups = QTableWidget()
        self._setup_dup_table()
        self.tabs.addTab(self.table_dups, "完全重复文件组 (Duplicates)")

        # Tab 2: 同名异内容冲突表格
        self.table_collisions = QTableWidget()
        self._setup_collision_table()
        self.tabs.addTab(self.table_collisions, "同名异内容冲突项 (Collisions)")

        layout.addWidget(self.tabs)

        # 底部快捷规则与导航栏
        bottom_bar = QHBoxLayout()
        self.btn_back = QPushButton("⬅️ 重新选择")
        self.btn_back.setFixedHeight(34)
        self.btn_back.setStyleSheet("background-color: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; border-radius: 6px; padding: 0 14px;")
        self.btn_back.clicked.connect(self.back_to_select.emit)
        bottom_bar.addWidget(self.btn_back)

        bottom_bar.addSpacing(16)
        lbl_batch = QLabel("快速推荐:")
        lbl_batch.setStyleSheet("color: #64748b; font-size: 12px;")
        bottom_bar.addWidget(lbl_batch)

        btn_batch_primary = QPushButton("保留主源正本")
        btn_batch_primary.setFixedHeight(28)
        btn_batch_primary.setStyleSheet("border: 1px solid #cbd5e1; border-radius: 4px; padding: 0 8px; font-size: 11px;")
        btn_batch_primary.clicked.connect(lambda: self._apply_quick_preset("primary"))
        bottom_bar.addWidget(btn_batch_primary)

        btn_batch_newest = QPushButton("保留最新文件")
        btn_batch_newest.setFixedHeight(28)
        btn_batch_newest.setStyleSheet("border: 1px solid #cbd5e1; border-radius: 4px; padding: 0 8px; font-size: 11px;")
        btn_batch_newest.clicked.connect(lambda: self._apply_quick_preset("newest"))
        bottom_bar.addWidget(btn_batch_newest)

        btn_batch_oldest = QPushButton("保留最早文件")
        btn_batch_oldest.setFixedHeight(28)
        btn_batch_oldest.setStyleSheet("border: 1px solid #cbd5e1; border-radius: 4px; padding: 0 8px; font-size: 11px;")
        btn_batch_oldest.clicked.connect(lambda: self._apply_quick_preset("oldest"))
        bottom_bar.addWidget(btn_batch_oldest)

        bottom_bar.addSpacing(10)
        self.btn_ai_diff = QPushButton("🤖 AI 多版本语义比对与保留建议...")
        self.btn_ai_diff.setFixedHeight(28)
        self.btn_ai_diff.setStyleSheet("background-color: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; border-radius: 4px; padding: 0 10px; font-size: 11px; font-weight: bold;")
        self.btn_ai_diff.clicked.connect(self._open_ai_version_diff)
        bottom_bar.addWidget(self.btn_ai_diff)

        bottom_bar.addStretch()

        self.btn_next = QPushButton("下一步: 制定融合策略与预检 ➔")
        self.btn_next.setFixedHeight(36)
        self.btn_next.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold; border-radius: 6px; padding: 0 20px; font-size: 13px;")
        self.btn_next.clicked.connect(self._on_next_clicked)
        bottom_bar.addWidget(self.btn_next)

        layout.addLayout(bottom_bar)

    def _setup_dup_table(self):
        """完全重复表格遵循 UI 铁律"""
        self.table_dups.setColumnCount(7)
        self.table_dups.setHorizontalHeaderLabels([
            "组ID", "保留决策", "文件路径", "所属源目录", "大小", "修改时间", "锁定防护"
        ])
        self.table_dups.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_dups.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_dups.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_dups.customContextMenuRequested.connect(self._show_dup_context_menu)

        # 铁律 1: 锁死行高 44px
        vh = self.table_dups.verticalHeader()
        vh.setDefaultSectionSize(44)
        vh.setSectionResizeMode(QHeaderView.Fixed)
        vh.setVisible(False)

        # 铁律 2: 列宽明确分层
        hh = self.table_dups.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table_dups.setColumnWidth(0, 95)  # 组ID
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        self.table_dups.setColumnWidth(1, 110)  # 保留单选
        hh.setSectionResizeMode(2, QHeaderView.Stretch)  # 路径弹性
        hh.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table_dups.setColumnWidth(3, 110)  # 所属源
        hh.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table_dups.setColumnWidth(4, 90)  # 大小
        hh.setSectionResizeMode(5, QHeaderView.Fixed)
        self.table_dups.setColumnWidth(5, 125)  # 修改时间
        hh.setSectionResizeMode(6, QHeaderView.Fixed)
        self.table_dups.setColumnWidth(6, 95)  # 锁

    def _setup_collision_table(self):
        """同名冲突表格遵循 UI 铁律"""
        self.table_collisions.setColumnCount(5)
        self.table_collisions.setHorizontalHeaderLabels([
            "冲突相对路径", "文件路径", "所属源目录", "修改时间", "建议安全融合动作"
        ])
        self.table_collisions.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_collisions.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_collisions.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_collisions.customContextMenuRequested.connect(self._show_collision_context_menu)

        vh = self.table_collisions.verticalHeader()
        vh.setDefaultSectionSize(44)
        vh.setSectionResizeMode(QHeaderView.Fixed)
        vh.setVisible(False)

        hh = self.table_collisions.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table_collisions.setColumnWidth(0, 160)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table_collisions.setColumnWidth(2, 110)
        hh.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table_collisions.setColumnWidth(3, 125)
        hh.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table_collisions.setColumnWidth(4, 150)

    def load_scan_result(self, result: DedupScanResult):
        self.scan_result = result
        self.keep_paths.clear()

        # 默认将推荐保留项加入 keep_paths
        for group in result.duplicate_groups:
            rec = group.recommended_keep_path or (group.items[0].path if group.items else "")
            if rec:
                self.keep_paths.add(rec)

        self._refresh_tables()

    def _refresh_tables(self):
        if not self.scan_result:
            return

        res = self.scan_result
        self.lbl_stats_badge.setText(
            f"完全重复: {len(res.duplicate_groups)} 组 (共 {res.total_duplicates_count} 个副本, 冗余 {format_size(res.total_wasted_bytes)}) | "
            f"同名冲突: {len(res.collisions)} 项 | 唯一: {len(res.unique_files)} 个"
        )

        # 1. 填充重复表格
        total_dup_rows = sum(len(g.items) for g in res.duplicate_groups)
        self.table_dups.setRowCount(total_dup_rows)

        cur_row = 0
        for group in res.duplicate_groups:
            btn_group = QButtonGroup(self)
            for item in group.items:
                # 0: 组ID
                it_gid = QTableWidgetItem(group.group_id)
                it_gid.setTextAlignment(Qt.AlignCenter)
                self.table_dups.setItem(cur_row, 0, it_gid)

                # 1: 保留决策 (铁律 3: 独立 QWidget 居中包装，固定 28px 高度)
                radio_container = QWidget()
                radio_layout = QHBoxLayout(radio_container)
                radio_layout.setContentsMargins(0, 0, 0, 0)
                radio_layout.setAlignment(Qt.AlignCenter)
                radio_btn = QRadioButton("保留正本")
                radio_btn.setFixedHeight(28)
                is_kept = item.path in self.keep_paths
                radio_btn.setChecked(is_kept)
                radio_btn.toggled.connect(lambda checked, p=item.path, grp=group: self._on_keep_toggled(p, grp, checked))
                btn_group.addButton(radio_btn)
                radio_layout.addWidget(radio_btn)
                self.table_dups.setCellWidget(cur_row, 1, radio_container)

                # 2: 文件路径
                it_path = QTableWidgetItem(item.path)
                it_path.setToolTip(item.path)
                self.table_dups.setItem(cur_row, 2, it_path)

                # 3: 所属源目录
                it_src = QTableWidgetItem(os.path.basename(item.source_dir))
                it_src.setTextAlignment(Qt.AlignCenter)
                self.table_dups.setItem(cur_row, 3, it_src)

                # 4: 大小
                it_size = QTableWidgetItem(format_size(item.size))
                it_size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table_dups.setItem(cur_row, 4, it_size)

                # 5: 修改时间
                m_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(item.mtime))
                it_time = QTableWidgetItem(m_str)
                it_time.setTextAlignment(Qt.AlignCenter)
                self.table_dups.setItem(cur_row, 5, it_time)

                # 6: 锁定防护
                it_lock = QTableWidgetItem("⚠️ 占用中" if item.is_locked else "正常")
                it_lock.setTextAlignment(Qt.AlignCenter)
                if item.is_locked:
                    it_lock.setForeground(Qt.red)
                    it_lock.setToolTip(item.lock_reason)
                else:
                    it_lock.setForeground(Qt.darkGreen)
                self.table_dups.setItem(cur_row, 6, it_lock)

                cur_row += 1

        # 2. 填充冲突表格
        total_col_rows = sum(len(c.files) for c in res.collisions)
        self.table_collisions.setRowCount(total_col_rows)
        c_row = 0
        for col in res.collisions:
            for item in col.files:
                it_rel = QTableWidgetItem(col.rel_path)
                self.table_collisions.setItem(c_row, 0, it_rel)

                it_p = QTableWidgetItem(item.path)
                it_p.setToolTip(item.path)
                self.table_collisions.setItem(c_row, 1, it_p)

                it_src = QTableWidgetItem(os.path.basename(item.source_dir))
                it_src.setTextAlignment(Qt.AlignCenter)
                self.table_collisions.setItem(c_row, 2, it_src)

                m_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(item.mtime))
                it_time = QTableWidgetItem(m_str)
                it_time.setTextAlignment(Qt.AlignCenter)
                self.table_collisions.setItem(c_row, 3, it_time)

                it_action = QTableWidgetItem(f"重命名融入 (_from_{os.path.basename(item.source_dir)})")
                it_action.setForeground(Qt.darkBlue)
                self.table_collisions.setItem(c_row, 4, it_action)

                c_row += 1

    def _on_keep_toggled(self, path: str, group: DedupGroup, checked: bool):
        if checked:
            for it in group.items:
                if it.path in self.keep_paths:
                    self.keep_paths.remove(it.path)
            self.keep_paths.add(path)

    def _open_ai_version_diff(self):
        """为当前选中的重复组或冲突项打开 AI 多版本语义比对对话框"""
        if not self.scan_result:
            return

        current_tab_idx = self.tabs.currentIndex()
        if current_tab_idx == 0:
            # 重复组 Tab
            row = self.table_dups.currentRow()
            target_group = self._get_dup_group_by_row(row) if row >= 0 else (self.scan_result.duplicate_groups[0] if self.scan_result.duplicate_groups else None)
            if not target_group or not target_group.items:
                QMessageBox.information(self, "提示", "当前没有可比对的重复文件组。")
                return
            self._launch_version_diff_for_group(target_group)
        else:
            # 冲突项 Tab
            row = self.table_collisions.currentRow()
            target_col = self._get_collision_by_row(row) if row >= 0 else (self.scan_result.collisions[0] if self.scan_result.collisions else None)
            if not target_col or not target_col.files:
                QMessageBox.information(self, "提示", "当前没有可比对的冲突项。")
                return
            self._launch_version_diff_for_collision(target_col)

    def _show_dup_context_menu(self, pos):
        row = self.table_dups.rowAt(pos.y())
        if row < 0 or not self.scan_result:
            return
        group = self._get_dup_group_by_row(row)
        if not group:
            return

        menu = QMenu(self)
        action_diff = QAction(f"🔍 对此重复组 ({group.group_id}) 进行 AI 语义比对与保留建议...", self)
        action_diff.triggered.connect(lambda: self._launch_version_diff_for_group(group))
        menu.addAction(action_diff)
        menu.exec(self.table_dups.viewport().mapToGlobal(pos))

    def _show_collision_context_menu(self, pos):
        row = self.table_collisions.rowAt(pos.y())
        if row < 0 or not self.scan_result:
            return
        col = self._get_collision_by_row(row)
        if not col:
            return

        menu = QMenu(self)
        action_diff = QAction(f"🔍 对此同名冲突项 ({col.rel_path}) 进行 AI 语义比对与保留建议...", self)
        action_diff.triggered.connect(lambda: self._launch_version_diff_for_collision(col))
        menu.addAction(action_diff)
        menu.exec(self.table_collisions.viewport().mapToGlobal(pos))

    def _get_dup_group_by_row(self, target_row: int) -> Optional[DedupGroup]:
        if not self.scan_result or target_row < 0:
            return None
        cur = 0
        for grp in self.scan_result.duplicate_groups:
            end = cur + len(grp.items)
            if cur <= target_row < end:
                return grp
            cur = end
        return None

    def _get_collision_by_row(self, target_row: int) -> Optional[CollisionItem]:
        if not self.scan_result or target_row < 0:
            return None
        cur = 0
        for c in self.scan_result.collisions:
            end = cur + len(c.files)
            if cur <= target_row < end:
                return c
            cur = end
        return None

    def _launch_version_diff_for_group(self, group: DedupGroup):
        from app.core.version_cluster import VersionClusterDetector
        from app.core.domain_models import VersionClusterGroup
        from app.ui.components.version_diff_dialog import VersionDiffDialog

        items = [VersionClusterDetector.build_cluster_item(it.path) for it in group.items]
        cluster = VersionClusterGroup(
            group_id=group.group_id,
            normalized_stem=items[0].stem,
            directory=os.path.dirname(items[0].path),
            items=items,
            ai_evaluated=False
        )
        dlg = VersionDiffDialog(cluster, parent=self)
        dlg.decision_applied.connect(self._on_version_diff_decision_applied)
        dlg.exec()

    def _launch_version_diff_for_collision(self, collision: CollisionItem):
        from app.core.version_cluster import VersionClusterDetector
        from app.core.domain_models import VersionClusterGroup
        from app.ui.components.version_diff_dialog import VersionDiffDialog

        items = [VersionClusterDetector.build_cluster_item(it.path) for it in collision.files]
        cluster = VersionClusterGroup(
            group_id=f"col_{os.path.basename(collision.rel_path)}",
            normalized_stem=items[0].stem,
            directory=os.path.dirname(items[0].path),
            items=items,
            ai_evaluated=False
        )
        dlg = VersionDiffDialog(cluster, parent=self)
        dlg.decision_applied.connect(self._on_version_diff_decision_applied)
        dlg.exec()

    def _on_version_diff_decision_applied(self, cluster: Any, selected_keep_path: str):
        """将 AI 研判选定的正本应用到当前保留集合中"""
        cluster_paths = {it.path for it in cluster.items}
        for p in list(self.keep_paths):
            if p in cluster_paths:
                self.keep_paths.remove(p)
        self.keep_paths.add(selected_keep_path)
        self._refresh_tables()
        QMessageBox.information(
            self,
            "保留决策已同步",
            f"已成功将正本 [{os.path.basename(selected_keep_path)}] 设为优先保留项。"
        )

    def _apply_quick_preset(self, preset: str):
        if not self.scan_result:
            return
        self.keep_paths.clear()
        sources = self.scan_result.scanned_sources
        primary = sources[0] if sources else ""

        for group in self.scan_result.duplicate_groups:
            if not group.items:
                continue
            if preset == "primary":
                best = next((it for it in group.items if it.source_dir == primary), group.items[0])
            elif preset == "newest":
                best = max(group.items, key=lambda it: it.mtime)
            elif preset == "oldest":
                best = min(group.items, key=lambda it: it.mtime)
            else:
                best = group.items[0]
            self.keep_paths.add(best.path)

        self._refresh_tables()

    def _on_next_clicked(self):
        if self.scan_result:
            self.proceed_to_plan.emit(self.scan_result, self.keep_paths)
