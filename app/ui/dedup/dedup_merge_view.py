"""
app/ui/dedup/dedup_merge_view.py
文件查重与跨盘融合主视图看板 (Wizard 流式多步控制器)
"""
from typing import Set, Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QStackedWidget, QFrame
)
from PySide6.QtCore import Qt

from app.dedup.models import DedupScanConfig, DedupScanResult
from app.ui.dedup.directory_select_step import DirectorySelectStep
from app.ui.dedup.scan_progress_step import ScanProgressStep
from app.ui.dedup.review_table_step import ReviewTableStep
from app.ui.dedup.merge_execute_step import MergeExecuteStep


class DedupMergeView(QWidget):
    """文件查重与跨盘融合主看板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_config: Optional[DedupScanConfig] = None
        self.current_scan_result: Optional[DedupScanResult] = None
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 顶部步骤导航指示条
        self.step_bar = QFrame()
        self.step_bar.setFixedHeight(50)
        self.step_bar.setStyleSheet("background-color: #f8fafc; border-bottom: 1px solid #e2e8f0;")
        bar_layout = QHBoxLayout(self.step_bar)
        bar_layout.setContentsMargins(20, 0, 20, 0)
        bar_layout.setSpacing(12)

        self.step_labels = [
            QLabel("① 选择源与目标"),
            QLabel("➔"),
            QLabel("② 建立索引与查重"),
            QLabel("➔"),
            QLabel("③ 重复与冲突审核"),
            QLabel("➔"),
            QLabel("④ 策略预检与原子融合")
        ]

        for lbl in self.step_labels:
            if lbl.text() == "➔":
                lbl.setStyleSheet("color: #94a3b8; font-weight: bold;")
            else:
                lbl.setStyleSheet("color: #64748b; font-size: 12px; font-weight: 500;")
            bar_layout.addWidget(lbl)

        bar_layout.addStretch()
        main_layout.addWidget(self.step_bar)

        # 多步内容栈
        self.stacked = QStackedWidget()

        # Step 1
        self.step1 = DirectorySelectStep()
        self.step1.config_ready.connect(self._on_step1_ready)
        self.stacked.addWidget(self.step1)

        # Step 2
        self.step2 = ScanProgressStep()
        self.step2.scan_completed.connect(self._on_step2_completed)
        self.step2.cancel_requested.connect(self._on_step2_cancelled)
        self.stacked.addWidget(self.step2)

        # Step 3
        self.step3 = ReviewTableStep()
        self.step3.proceed_to_plan.connect(self._on_step3_proceed)
        self.step3.back_to_select.connect(lambda: self._go_step(0))
        self.stacked.addWidget(self.step3)

        # Step 4 & 5
        self.step4 = MergeExecuteStep()
        self.step4.back_to_review.connect(lambda: self._go_step(2))
        self.step4.reset_to_start.connect(lambda: self._go_step(0))
        self.stacked.addWidget(self.step4)

        main_layout.addWidget(self.stacked)
        self._go_step(0)

    def _go_step(self, step_idx: int):
        self.stacked.setCurrentIndex(step_idx)
        step_map = {0: 0, 1: 2, 2: 4, 3: 6}
        active_lbl_idx = step_map.get(step_idx, 0)

        for i, lbl in enumerate(self.step_labels):
            if lbl.text() == "➔":
                continue
            if i == active_lbl_idx:
                lbl.setStyleSheet("color: #2563eb; font-size: 13px; font-weight: bold;")
            elif i < active_lbl_idx:
                lbl.setStyleSheet("color: #16a34a; font-size: 12px; font-weight: bold;")
            else:
                lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")

    def _on_step1_ready(self, config: DedupScanConfig):
        self.current_config = config
        self._go_step(1)
        self.step2.start_scan(config)

    def _on_step2_completed(self, result: DedupScanResult):
        self.current_scan_result = result
        self.step3.load_scan_result(result)
        self._go_step(2)

    def _on_step2_cancelled(self):
        self._go_step(0)

    def _on_step3_proceed(self, result: DedupScanResult, keep_paths: Set[str]):
        if self.current_config:
            self.step4.load_plan(
                scan_result=result,
                keep_paths=keep_paths,
                target_dir=self.current_config.target_dir or "",
                isolation_dir=self.current_config.isolation_dir
            )
            self._go_step(3)
