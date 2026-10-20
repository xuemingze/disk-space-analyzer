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
from typing import List, Set, Optional, Dict
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
    QRadioButton, QButtonGroup, QFrame
)
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
