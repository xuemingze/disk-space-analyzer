"""
app/ui/dedup/merge_execute_step.py
步骤 4 & 5: 融合策略确认、原子执行与回滚凭证看板
"""
import os
from typing import List, Dict, Optional, Set, Any
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QGroupBox, QMessageBox, QFrame
)
from PySide6.QtCore import Qt, Signal, QThread
from app.dedup.models import DedupScanResult, MergeAction
from app.dedup.executor import MergeExecutor
from app.utils.file_helper import format_size


class MergeExecutionWorker(QThread):
    """跨盘原子融合后台执行线程"""
    progress_signal = Signal(int, int, str, int, int)
    finished_signal = Signal(dict)

    def __init__(self, actions: List[MergeAction], target_dir: str, parent=None):
        super().__init__(parent)
        self.actions = actions
        self.target_dir = target_dir
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        def _prog_cb(cur, total, cur_name, succ, fail):
            self.progress_signal.emit(cur, total, cur_name, succ, fail)

        def _cancel_check():
            return self._is_running

        res = MergeExecutor.execute_plan(
            actions=self.actions,
            target_dir=self.target_dir,
            progress_cb=_prog_cb,
            cancel_check=_cancel_check
        )
        self.finished_signal.emit(res)


class MergeExecuteStep(QWidget):
    """步骤 4 & 5: 策略预检与执行看板"""
    back_to_review = Signal()
    reset_to_start = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.actions: List[MergeAction] = []
        self.target_dir: str = ""
        self.worker: Optional[MergeExecutionWorker] = None
        self.last_manifest_file: str = ""
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # 头部说明
        self.title = QLabel("🛡️ 步骤 4: 融合策略确认与跨盘预检")
        self.title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1e293b;")
        self.desc = QLabel("系统已为您规划出安全的原子转移指令。融合过程支持断点保护，未修改正本全部留存，所有移动均生成回滚凭据。")
        self.desc.setStyleSheet("font-size: 12px; color: #64748b;")
        layout.addWidget(self.title)
        layout.addWidget(self.desc)

        # 计划汇总统计卡片
        self.plan_box = QGroupBox("📋 融合执行清单概览")
        self.plan_box.setStyleSheet("QGroupBox { font-weight: bold; color: #334155; }")
        p_layout = QVBoxLayout(self.plan_box)
        p_layout.setSpacing(8)

        self.lbl_plan_keep = QLabel("• 留存正本: 0 项")
        self.lbl_plan_isolate = QLabel("• 冗余副本 (安全移入隔离区): 0 项 (释放 0 B)")
        self.lbl_plan_rename = QLabel("• 同名冲突 (自动重命名融入): 0 项")
        self.lbl_plan_unique = QLabel("• 唯一资产 (相对结构融入): 0 项")
        self.lbl_plan_locked = QLabel("• 被外部占用锁定 (安全自动跳过): 0 项")

        self.lbl_plan_keep.setStyleSheet("color: #15803d; font-size: 12px;")
        self.lbl_plan_isolate.setStyleSheet("color: #b45309; font-size: 12px;")
        self.lbl_plan_rename.setStyleSheet("color: #2563eb; font-size: 12px;")
        self.lbl_plan_unique.setStyleSheet("color: #475569; font-size: 12px;")
        self.lbl_plan_locked.setStyleSheet("color: #dc2626; font-size: 12px;")

        p_layout.addWidget(self.lbl_plan_keep)
        p_layout.addWidget(self.lbl_plan_isolate)
        p_layout.addWidget(self.lbl_plan_rename)
        p_layout.addWidget(self.lbl_plan_unique)
        p_layout.addWidget(self.lbl_plan_locked)
        layout.addWidget(self.plan_box)

        # 执行进度卡片 (执行时显示)
        self.exec_card = QFrame()
        self.exec_card.setStyleSheet("QFrame { background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; }")
        self.exec_card.setVisible(False)
        e_layout = QVBoxLayout(self.exec_card)
        e_layout.setSpacing(10)

        self.lbl_exec_status = QLabel("正在执行跨盘原子转移与校验...")
        self.lbl_exec_status.setStyleSheet("font-size: 13px; font-weight: bold; color: #2563eb;")
        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(0)
        self.prog_bar.setFixedHeight(18)
        self.lbl_exec_detail = QLabel("正在处理...")
        self.lbl_exec_detail.setStyleSheet("font-size: 11px; color: #64748b;")

        e_layout.addWidget(self.lbl_exec_status)
        e_layout.addWidget(self.prog_bar)
        e_layout.addWidget(self.lbl_exec_detail)
        layout.addWidget(self.exec_card)

        # 完成报告卡片
        self.report_card = QFrame()
        self.report_card.setStyleSheet("QFrame { background-color: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 14px; }")
        self.report_card.setVisible(False)
        r_layout = QVBoxLayout(self.report_card)
        r_layout.setSpacing(8)

        self.lbl_report_title = QLabel("🎉 融合治理圆满完成！")
        self.lbl_report_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #166534;")
        self.lbl_report_detail = QLabel("全部操作清单已安全记录至 Manifest 凭据，可随时一键回滚。")
        self.lbl_report_detail.setStyleSheet("font-size: 12px; color: #15803d;")

        btn_row = QHBoxLayout()
        self.btn_open_target = QPushButton("📂 打开目标目录")
        self.btn_open_target.setFixedHeight(30)
        self.btn_open_target.clicked.connect(self._open_target_folder)
        self.btn_finish_reset = QPushButton("✨ 完成并返回初始")
        self.btn_finish_reset.setFixedHeight(30)
        self.btn_finish_reset.setStyleSheet("background-color: #16a34a; color: white; font-weight: bold; border-radius: 4px; padding: 0 14px;")
        self.btn_finish_reset.clicked.connect(self.reset_to_start.emit)

        btn_row.addWidget(self.btn_open_target)
        btn_row.addWidget(self.btn_finish_reset)
        btn_row.addStretch()

        r_layout.addWidget(self.lbl_report_title)
        r_layout.addWidget(self.lbl_report_detail)
        r_layout.addLayout(btn_row)
        layout.addWidget(self.report_card)

        layout.addStretch()

        # 底部操作栏
        self.bottom_bar = QHBoxLayout()
        self.btn_back = QPushButton("⬅️ 返回审核修改")
        self.btn_back.setFixedHeight(36)
        self.btn_back.setStyleSheet("border: 1px solid #cbd5e1; border-radius: 6px; padding: 0 14px;")
        self.btn_back.clicked.connect(self.back_to_review.emit)

        self.btn_start_merge = QPushButton("🚀 立即执行跨盘原子融合")
        self.btn_start_merge.setFixedHeight(36)
        self.btn_start_merge.setStyleSheet(
            "background-color: #16a34a; color: white; font-weight: bold; border-radius: 6px; padding: 0 24px; font-size: 13px;"
        )
        self.btn_start_merge.clicked.connect(self._start_execution)

        self.bottom_bar.addWidget(self.btn_back)
        self.bottom_bar.addStretch()
        self.bottom_bar.addWidget(self.btn_start_merge)
        layout.addLayout(self.bottom_bar)

    def load_plan(self, scan_result: DedupScanResult, keep_paths: Set[str], target_dir: str, isolation_dir: Optional[str]):
        self.target_dir = target_dir
        self.exec_card.setVisible(False)
        self.report_card.setVisible(False)
        self.plan_box.setVisible(True)
        self.bottom_bar.setVisible(True)

        self.actions = MergeExecutor.build_merge_plan(
            scan_result=scan_result,
            target_dir=target_dir,
            isolation_dir=isolation_dir,
            keep_paths_override=keep_paths
        )

        # 统计数量
        c_keep = sum(1 for a in self.actions if a.action_type == "keep")
        c_iso = [a for a in self.actions if a.action_type == "isolate_archive"]
        c_rename = sum(1 for a in self.actions if a.action_type == "rename_merge")
        c_unique = sum(1 for a in self.actions if a.action_type == "move_merge")
        c_locked = sum(1 for a in self.actions if a.is_locked)

        iso_bytes = sum(a.size for a in c_iso)

        self.lbl_plan_keep.setText(f"• 留存正本: {c_keep} 项 (原位安全保留)")
        self.lbl_plan_isolate.setText(f"• 冗余副本 (安全移入隔离区): {len(c_iso)} 项 (释放 {format_size(iso_bytes)} 磁盘空间)")
        self.lbl_plan_rename.setText(f"• 同名冲突 (自动重命名融入): {c_rename} 项")
        self.lbl_plan_unique.setText(f"• 唯一资产 (相对结构融入): {c_unique} 项")
        self.lbl_plan_locked.setText(f"• 被外部占用锁定 (安全自动跳过): {c_locked} 项")

    def _start_execution(self):
        reply = QMessageBox.question(
            self,
            "确认执行",
            "是否确认启动跨盘原子融合？\n系统将自动生成可回滚 Manifest 凭据，遇到程序占用的文件将自动安全跳过。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        self.plan_box.setVisible(False)
        self.bottom_bar.setVisible(False)
        self.exec_card.setVisible(True)

        self.worker = MergeExecutionWorker(self.actions, self.target_dir, self)
        self.worker.progress_signal.connect(self._on_exec_progress)
        self.worker.finished_signal.connect(self._on_exec_finished)
        self.worker.start()

    def _on_exec_progress(self, cur: int, total: int, cur_name: str, succ: int, fail: int):
        pct = int(cur / total * 100) if total > 0 else 0
        self.prog_bar.setValue(pct)
        self.lbl_exec_detail.setText(f"正在处理 [{cur}/{total}]: {cur_name} (成功: {succ}, 失败: {fail})")

    def _on_exec_finished(self, res: dict):
        self.exec_card.setVisible(False)
        self.report_card.setVisible(True)
        self.last_manifest_file = res.get("manifest_file", "")

        self.lbl_report_title.setText(f"🎉 融合治理完成！(成功: {res['success']}, 失败: {res['failed']}, 跳过: {res['skipped']})")
        self.lbl_report_detail.setText(
            f"备份批次号: {res['backup_id']}\n"
            f"可回滚凭据: {self.last_manifest_file}\n"
            f"所有转移项均已妥善归置，您可在历史记录或使用主控回滚功能随时还原。"
        )

    def _open_target_folder(self):
        if self.target_dir and os.path.exists(self.target_dir):
            os.startfile(self.target_dir)
