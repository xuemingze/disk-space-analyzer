import os
import string
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTabWidget, QFileDialog, QMessageBox,
    QCheckBox, QListWidget, QListWidgetItem, QLineEdit,
    QGroupBox, QFrame, QTextEdit, QRadioButton, QButtonGroup,
    QInputDialog
)
from PySide6.QtCore import Qt, QThread, Signal

from app.config import app_config
from app.core.scanner import ScanWorker
from app.core.cleaner import ArchiveWorker, DeleteWorker
from app.core.ai_service import AIService
from app.core.reporter import ReportExporter
from app.core.task_manager import global_task_manager, TaskType, TaskStatus
from app.ui.components.stat_cards import StatCardsRow
from app.ui.components.chart_widget import SpaceDistributionChartWidget
from app.ui.components.data_table import FileDataGridWidget
from app.ui.components.migration_dialog import MigrationDialog
from app.ui.components.task_manager_widget import TaskManagerDialog
from app.ui.components.organize_dialog import OrganizePreviewDialog
from app.utils.file_helper import format_size
from app.utils.logger import app_logger


class AIWorker(QThread):
    recommend_done = Signal(list)
    report_done = Signal(str)
    classify_done = Signal(list)
    failed = Signal(str)

    def __init__(self, action: str, data: Any, parent=None, **kwargs):
        super().__init__(parent)
        self.action = action
        self.data = data
        self.kwargs = kwargs

    def run(self):
        try:
            llm_cfg = app_config.get("llm", default={})
            base_url = llm_cfg.get("base_url", "")
            api_key = llm_cfg.get("api_key", "")
            model = llm_cfg.get("model", "gpt-4o-mini")

            if self.action == "recommend":
                paths = AIService.analyze_redundant_files_with_ai(
                    base_url, api_key, model, self.data
                )
                self.recommend_done.emit(paths)
            elif self.action == "report":
                report_md = AIService.generate_health_report_with_ai(
                    base_url, api_key, model, self.data
                )
                self.report_done.emit(report_md)
            elif self.action == "classify":
                dest_root = self.kwargs.get("destination_root", "D:/归档备份")
                classified = AIService.classify_files_with_ai(
                    base_url, api_key, model, self.data, dest_root,
                    weights={"work_ratio": 0.6, "personal_ratio": 0.4}
                )
                self.classify_done.emit(classified)
        except Exception as e:
            self.failed.emit(str(e))


class HomeView(QWidget):
    """
    主控扫描与分阶段全景呈现页面 (Home)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_scan_result: Optional[Dict[str, Any]] = None
        self.scan_worker: Optional[ScanWorker] = None
        self.archive_worker: Optional[ArchiveWorker] = None
        self.current_task_id: Optional[str] = None
        self.ai_worker: Optional[AIWorker] = None
        
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 15, 20, 15)
        main_layout.setSpacing(12)

        # 1. 顶部控制与配置面板
        top_card = QFrame()
        top_card.setProperty("class", "CardFrame")
        top_card_layout = QVBoxLayout(top_card)
        top_card_layout.setContentsMargins(14, 12, 14, 12)
        top_card_layout.setSpacing(10)

        # 第一行: 目标盘符与自定义路径
        target_row = QHBoxLayout()
        target_row.setSpacing(12)

        # 盘符多选
        drive_box = QGroupBox("📍 扫描目标盘符")
        drive_layout = QHBoxLayout(drive_box)
        drive_layout.setContentsMargins(8, 8, 8, 8)
        self.drive_checkboxes: List[QCheckBox] = []
        
        available_drives = self.get_available_drives()
        for d in available_drives:
            chk = QCheckBox(f"{d} 盘")
            if d.upper() == "C":
                chk.setChecked(True)
            self.drive_checkboxes.append(chk)
            drive_layout.addWidget(chk)
            
        target_row.addWidget(drive_box, 1)

        # 归档目录配置
        archive_box = QGroupBox("📦 默认归档/迁移基准目录")
        archive_layout = QHBoxLayout(archive_box)
        archive_layout.setContentsMargins(8, 8, 8, 8)
        
        self.archive_input = QLineEdit()
        self.archive_input.setText(app_config.get("archive_dir", default="D:/归档备份"))
        self.archive_input.setPlaceholderText("选择用于存放归档文件的目录...")
        self.archive_btn = QPushButton("📁 浏览...")
        self.archive_btn.setProperty("class", "SecondaryButton")
        self.archive_btn.clicked.connect(self.browse_archive_dir)
        
        archive_layout.addWidget(self.archive_input, 1)
        archive_layout.addWidget(self.archive_btn)
        target_row.addWidget(archive_box, 1)

        top_card_layout.addLayout(target_row)

        # 第二行: 自定义文件夹列表与扫描选项
        options_row = QHBoxLayout()
        options_row.setSpacing(12)

        # 自定义追加扫描
        custom_folder_box = QGroupBox("📂 自定义追加扫描路径")
        custom_folder_layout = QHBoxLayout(custom_folder_box)
        custom_folder_layout.setContentsMargins(8, 8, 8, 8)
        
        self.custom_paths_list = QListWidget()
        self.custom_paths_list.setMaximumHeight(45)
        self.add_folder_btn = QPushButton("➕ 添加目录")
        self.add_folder_btn.setProperty("class", "SecondaryButton")
        self.add_folder_btn.clicked.connect(self.add_custom_folder)
        self.del_folder_btn = QPushButton("➖ 移除")
        self.del_folder_btn.setProperty("class", "SecondaryButton")
        self.del_folder_btn.clicked.connect(self.remove_custom_folder)
        
        custom_folder_layout.addWidget(self.custom_paths_list, 1)
        custom_folder_layout.addWidget(self.add_folder_btn)
        custom_folder_layout.addWidget(self.del_folder_btn)
        options_row.addWidget(custom_folder_box, 2)

        # 引擎选项
        scan_opt_box = QGroupBox("⚙️ 引擎选项")
        scan_opt_layout = QHBoxLayout(scan_opt_box)
        scan_opt_layout.setContentsMargins(8, 8, 8, 8)
        
        self.chk_dup_detect = QCheckBox("分块哈希查重")
        self.chk_dup_detect.setChecked(True)
        self.chk_skip_system = QCheckBox("保护系统核心目录")
        self.chk_skip_system.setChecked(True)
        
        scan_opt_layout.addWidget(self.chk_dup_detect)
        scan_opt_layout.addWidget(self.chk_skip_system)
        options_row.addWidget(scan_opt_box, 1)

        # 操作控制按钮
        action_btn_box = QHBoxLayout()
        self.start_scan_btn = QPushButton("🚀 启动分阶段扫描")
        self.start_scan_btn.setMinimumHeight(40)
        self.start_scan_btn.setStyleSheet("font-size: 13px; font-weight: bold;")
        self.start_scan_btn.clicked.connect(self.start_scan)
        
        self.pause_scan_btn = QPushButton("⏸️ 暂停")
        self.pause_scan_btn.setProperty("class", "SecondaryButton")
        self.pause_scan_btn.setMinimumHeight(40)
        self.pause_scan_btn.setEnabled(False)
        self.pause_scan_btn.clicked.connect(self.toggle_pause_scan)

        self.stop_scan_btn = QPushButton("⏹️ 取消")
        self.stop_scan_btn.setProperty("class", "DangerButton")
        self.stop_scan_btn.setMinimumHeight(40)
        self.stop_scan_btn.setEnabled(False)
        self.stop_scan_btn.clicked.connect(self.stop_scan)

        self.task_center_btn = QPushButton("⚡ 任务管理")
        self.task_center_btn.setStyleSheet("background-color: #4F46E5; border-color: #6366F1; font-weight: bold;")
        self.task_center_btn.setMinimumHeight(40)
        self.task_center_btn.clicked.connect(self.open_task_manager)
        
        action_btn_box.addWidget(self.start_scan_btn, 2)
        action_btn_box.addWidget(self.pause_scan_btn, 1)
        action_btn_box.addWidget(self.stop_scan_btn, 1)
        action_btn_box.addWidget(self.task_center_btn, 1)
        options_row.addLayout(action_btn_box, 2)

        top_card_layout.addLayout(options_row)

        # 扫描状态与进度条
        progress_layout = QVBoxLayout()
        progress_layout.setSpacing(4)
        
        status_info_layout = QHBoxLayout()
        self.phase_label = QLabel("就绪 - 点击启动分阶段全景深度扫描")
        self.phase_label.setStyleSheet("color: #38BDF8; font-weight: bold;")
        self.speed_label = QLabel("")
        self.speed_label.setStyleSheet("color: #10B981; font-size: 11px; font-weight: bold;")
        self.current_path_label = QLabel("")
        self.current_path_label.setStyleSheet("color: #64748B; font-size: 11px;")
        
        status_info_layout.addWidget(self.phase_label)
        status_info_layout.addWidget(self.speed_label)
        status_info_layout.addStretch()
        status_info_layout.addWidget(self.current_path_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        
        progress_layout.addLayout(status_info_layout)
        progress_layout.addWidget(self.progress_bar)
        
        top_card_layout.addLayout(progress_layout)
        main_layout.addWidget(top_card)

        # 2. 统计指标卡片栏
        self.stat_cards = StatCardsRow()
        main_layout.addWidget(self.stat_cards)

        # 3. 核心内容标签页
        self.tabs = QTabWidget()
        
        self.chart_widget = SpaceDistributionChartWidget()
        self.tabs.addTab(self.chart_widget, "📊 空间全景图与类型分布 (阶段一即显)")
        
        self.duplicate_table = FileDataGridWidget(is_selectable=True)
        self.duplicate_table.selection_changed_signal.connect(self.on_redundant_selection_changed)
        self.duplicate_table.migrate_requested_signal.connect(self.open_migration_dialog_for_paths)
        self.tabs.addTab(self.duplicate_table, "📋 重复文件明细 (哈希确认)")
        
        self.releasable_table = FileDataGridWidget(is_selectable=True)
        self.releasable_table.selection_changed_signal.connect(self.on_redundant_selection_changed)
        self.releasable_table.migrate_requested_signal.connect(self.open_migration_dialog_for_paths)
        self.tabs.addTab(self.releasable_table, "🗑️ 可释放文件明细 (规则识别)")
        
        self.top100_table = FileDataGridWidget(is_selectable=True)
        self.top100_table.selection_changed_signal.connect(self.on_redundant_selection_changed)
        self.top100_table.migrate_requested_signal.connect(self.open_migration_dialog_for_paths)
        self.tabs.addTab(self.top100_table, "🏆 全局 Top 100 超大文件 (阶段一即显)")
        
        # AI 深度分析报告
        report_widget = QWidget()
        report_layout = QVBoxLayout(report_widget)
        report_layout.setContentsMargins(10, 10, 10, 10)
        report_layout.setSpacing(8)
        
        report_top_bar = QHBoxLayout()
        self.gen_ai_report_btn = QPushButton("🤖 重新生成 AI 深度分析报告")
        self.gen_ai_report_btn.setProperty("class", "SecondaryButton")
        self.gen_ai_report_btn.clicked.connect(self.generate_ai_report)
        
        self.export_report_btn = QPushButton("📑 导出 Markdown 报告 (.md)")
        self.export_report_btn.setProperty("class", "SuccessButton")
        self.export_report_btn.clicked.connect(self.export_markdown_report)
        
        report_top_bar.addWidget(self.gen_ai_report_btn)
        report_top_bar.addStretch()
        report_top_bar.addWidget(self.export_report_btn)
        
        self.report_text_edit = QTextEdit()
        self.report_text_edit.setReadOnly(True)
        self.report_text_edit.setPlaceholderText("扫描完成后，此处将渲染基于 AI 大模型的磁盘全景深度分析与治理报告...")
        
        report_layout.addLayout(report_top_bar)
        report_layout.addWidget(self.report_text_edit)
        self.tabs.addTab(report_widget, "📑 AI 深度分析报告预览")

        main_layout.addWidget(self.tabs, 1)

        # 4. 底部批量交互操作栏
        bottom_bar = QFrame()
        bottom_bar.setProperty("class", "CardFrame")
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(12, 8, 12, 8)
        bottom_layout.setSpacing(10)

        # 选择控制按钮
        self.btn_select_all = QPushButton("全选")
        self.btn_select_all.setProperty("class", "SecondaryButton")
        self.btn_select_all.clicked.connect(lambda: self.get_active_table().select_all(True))
        
        self.btn_invert_sel = QPushButton("反选")
        self.btn_invert_sel.setProperty("class", "SecondaryButton")
        self.btn_invert_sel.clicked.connect(lambda: self.get_active_table().invert_selection())
        
        self.btn_select_rec = QPushButton("📌 仅选推荐")
        self.btn_select_rec.setProperty("class", "SecondaryButton")
        self.btn_select_rec.clicked.connect(self.trigger_ai_recommendation_only)

        self.btn_clear_sel = QPushButton("清空")
        self.btn_clear_sel.setProperty("class", "SecondaryButton")
        self.btn_clear_sel.clicked.connect(lambda: self.get_active_table().select_all(False))

        bottom_layout.addWidget(self.btn_select_all)
        bottom_layout.addWidget(self.btn_invert_sel)
        bottom_layout.addWidget(self.btn_select_rec)
        bottom_layout.addWidget(self.btn_clear_sel)

        # 选中统计
        self.selection_stat_label = QLabel("已选中: 0 个文件 (0 B)")
        self.selection_stat_label.setStyleSheet("color: #38BDF8; font-weight: bold; margin-left: 10px;")
        bottom_layout.addWidget(self.selection_stat_label)
        bottom_layout.addStretch()

        # AI 自动处理按钮 (明确区分于仅选推荐)
        self.btn_ai_auto = QPushButton("🤖 AI 自动处理 (分类并归档)")
        self.btn_ai_auto.setStyleSheet("background-color: #7C3AED; border-color: #8B5CF6; font-weight: bold;")
        self.btn_ai_auto.clicked.connect(self.trigger_ai_auto_process)
        bottom_layout.addWidget(self.btn_ai_auto)

        # 智能迁移
        self.btn_migrate = QPushButton("📦 智能迁移所选项")
        self.btn_migrate.setStyleSheet("background-color: #0284C7; border-color: #38BDF8; font-weight: bold;")
        self.btn_migrate.clicked.connect(self.execute_migration_selected)
        bottom_layout.addWidget(self.btn_migrate)

        # 一键快速归档 (后台非阻塞)
        self.btn_archive = QPushButton("📁 一键快速归档")
        self.btn_archive.setProperty("class", "SuccessButton")
        self.btn_archive.clicked.connect(self.execute_archive_selected_async)
        bottom_layout.addWidget(self.btn_archive)

        # 一键清理
        self.btn_cleanup = QPushButton("🗑️ 一键清理所选项")
        self.btn_cleanup.setProperty("class", "DangerButton")
        self.btn_cleanup.clicked.connect(self.execute_cleanup_selected)
        bottom_layout.addWidget(self.btn_cleanup)

        main_layout.addWidget(bottom_bar)

    def get_available_drives(self) -> List[str]:
        drives = []
        for letter in string.ascii_uppercase:
            drive_path = f"{letter}:\\"
            if os.path.exists(drive_path):
                drives.append(f"{letter}:")
        return drives

    def get_selected_targets(self) -> List[str]:
        targets = []
        for chk in self.drive_checkboxes:
            if chk.isChecked():
                drive_name = chk.text().split()[0] + "\\"
                targets.append(drive_name)
                
        for i in range(self.custom_paths_list.count()):
            targets.append(self.custom_paths_list.item(i).text())
            
        return list(set(targets))

    def browse_archive_dir(self):
        curr = self.archive_input.text().strip() or "D:/"
        selected = QFileDialog.getExistingDirectory(self, "选择归档迁移目标目录", curr)
        if selected:
            self.archive_input.setText(selected)
            app_config.set("archive_dir", selected)

    def add_custom_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择要加入扫描的文件夹")
        if folder:
            for i in range(self.custom_paths_list.count()):
                if self.custom_paths_list.item(i).text().lower() == folder.lower():
                    return
            self.custom_paths_list.addItem(folder)

    def remove_custom_folder(self):
        curr_item = self.custom_paths_list.currentItem()
        if curr_item:
            self.custom_paths_list.takeItem(self.custom_paths_list.row(curr_item))

    def get_active_table(self) -> FileDataGridWidget:
        idx = self.tabs.currentIndex()
        if idx == 1:
            return self.duplicate_table
        elif idx == 2:
            return self.releasable_table
        elif idx == 3:
            return self.top100_table
        return self.duplicate_table

    def open_task_manager(self):
        dlg = TaskManagerDialog(self)
        dlg.exec()

    def start_scan(self):
        targets = self.get_selected_targets()
        if not targets:
            QMessageBox.warning(self, "提示", "请至少勾选一个盘符或添加一个自定义扫描目录！")
            return

        self.start_scan_btn.setEnabled(False)
        self.pause_scan_btn.setEnabled(True)
        self.pause_scan_btn.setText("⏸️ 暂停")
        self.stop_scan_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.phase_label.setText("正在准备启动扫描...")
        self.speed_label.setText("")

        concurrency = app_config.get("perf_options", "concurrency", default=4)
        hash_algo = app_config.get("hash_algorithm", default="md5")

        self.scan_worker = ScanWorker(
            target_paths=targets,
            enable_duplicate_detection=self.chk_dup_detect.isChecked(),
            hash_algorithm=hash_algo,
            skip_system_protected=self.chk_skip_system.isChecked(),
            concurrency=concurrency
        )
        
        task_item = global_task_manager.create_task(
            name=f"全景扫描 ({', '.join(targets)})",
            task_type=TaskType.SCAN,
            worker=self.scan_worker
        )
        self.current_task_id = task_item.task_id

        self.scan_worker.progress_updated.connect(self.on_scan_progress)
        self.scan_worker.phase_changed.connect(self.on_scan_phase_changed)
        self.scan_worker.phase1_completed.connect(self.on_phase1_completed)
        self.scan_worker.phase2_progress.connect(self.on_phase2_progress)
        self.scan_worker.phase2_completed.connect(self.on_phase2_completed)
        self.scan_worker.phase3_completed.connect(self.on_phase3_completed)
        self.scan_worker.scan_error.connect(self.on_scan_error)
        
        self.scan_worker.start()

    def toggle_pause_scan(self):
        if not self.scan_worker or not self.scan_worker.isRunning():
            return
        if self.pause_scan_btn.text().startswith("⏸️"):
            self.scan_worker.pause()
            self.pause_scan_btn.setText("▶️ 恢复")
            self.phase_label.setText("⏸️ 扫描已暂停")
            if self.current_task_id:
                global_task_manager.pause_task(self.current_task_id)
        else:
            self.scan_worker.resume()
            self.pause_scan_btn.setText("⏸️ 暂停")
            if self.current_task_id:
                global_task_manager.resume_task(self.current_task_id)

    def stop_scan(self):
        if self.scan_worker and self.scan_worker.isRunning():
            self.phase_label.setText("正在中止扫描...")
            self.scan_worker.cancel()
            self.scan_worker.wait()
            if self.current_task_id:
                global_task_manager.cancel_task(self.current_task_id)
            self.on_scan_stopped()

    def on_scan_progress(self, current_dir: str, file_count: object, total_bytes: object):
        f_cnt = int(file_count)
        t_byt = int(total_bytes)
        self.current_path_label.setText(f"已扫: {f_cnt:,} 文件 ({format_size(t_byt)}) | {str(current_dir)[:50]}...")
        if self.current_task_id:
            global_task_manager.update_task_progress(
                self.current_task_id,
                processed_count=f_cnt,
                processed_bytes=t_byt
            )

    def on_scan_phase_changed(self, phase_name: str):
        self.phase_label.setText(phase_name)
        if self.current_task_id:
            global_task_manager.update_task_progress(self.current_task_id, phase=phase_name)

    def on_phase1_completed(self, p1_result: dict):
        self.phase_label.setText(f"✅ 阶段一完成 (耗时 {p1_result['elapsed_seconds']}s) - 正在进入阶段二哈希比对...")
        self.stat_cards.update_stats(
            total_bytes_str=format_size(p1_result["total_bytes"]),
            reclaimable_str="比对中...",
            files_count_str=f"{p1_result['total_files']:,} 个",
            dup_waste_str="比对中...",
            dup_groups_count=p1_result.get("dup_candidate_groups_count", 0)
        )
        self.chart_widget.update_chart(p1_result.get("category_stats", {}))
        self.top100_table.populate_data(p1_result.get("top_100_files", []), p1_result["total_bytes"])
        self.tabs.setCurrentIndex(0)

    def on_phase2_progress(self, proc_b: object, tot_b: object, speed: str, eta: int, cur_g: int, tot_g: int):
        proc_int = int(proc_b)
        tot_int = int(tot_b)
        pct = (proc_int / tot_int * 100.0) if tot_int > 0 else 0.0
        self.progress_bar.setValue(int(pct))
        self.speed_label.setText(f"⚡ 查重速度: {speed} | ETA: {eta}s (组: {cur_g}/{tot_g})")
        if self.current_task_id:
            global_task_manager.update_task_progress(
                self.current_task_id,
                progress_pct=pct,
                processed_bytes=proc_int,
                total_bytes=tot_int,
                speed=speed,
                eta=eta
            )

    def on_phase2_completed(self, p2_result: dict):
        self.speed_label.setText(f"✅ 哈希比对完成 (耗时 {p2_result['elapsed_seconds']}s | 命中缓存 {p2_result['cache_hits']} 次)")

    def on_phase3_completed(self, result: Dict[str, Any]):
        self.on_scan_stopped()
        self.current_scan_result = result
        self.phase_label.setText(f"🎉 全流程扫描完成 (总耗时 {result['total_elapsed_seconds']}s)")
        self.speed_label.setText("")

        self.stat_cards.update_stats(
            total_bytes_str=format_size(result["total_bytes"]),
            reclaimable_str=format_size(result["reclaimable_bytes"]),
            files_count_str=f"{result['total_files']:,} 个",
            dup_waste_str=format_size(result["duplicate_wasted_bytes"]),
            dup_groups_count=result["duplicate_groups_count"]
        )
        all_redundant = result.get("redundant_files", [])
        duplicate_files = [f for f in all_redundant if f.get("is_duplicate")]
        releasable_files = [f for f in all_redundant if not f.get("is_duplicate")]
        
        self.duplicate_table.populate_data(duplicate_files, result["total_bytes"])
        self.releasable_table.populate_data(releasable_files, result["total_bytes"])

        report_preview = AIService._generate_fallback_report(result)
        self.report_text_edit.setPlainText(report_preview)

        if duplicate_files:
            self.tabs.setCurrentIndex(1)
        elif releasable_files:
            self.tabs.setCurrentIndex(2)

        if self.current_task_id:
            global_task_manager.set_task_status(self.current_task_id, TaskStatus.COMPLETED)

        QMessageBox.information(
            self, "扫描全量完成",
            f"空间全景深度扫描已全部完成！\n"
            f"索引文件: {result['total_files']:,} 个 ({format_size(result['total_bytes'])})\n"
            f"确认重复副本: {result['duplicate_groups_count']} 组 ({format_size(result['duplicate_wasted_bytes'])})\n"
            f"可释放空间预估: {format_size(result['reclaimable_bytes'] + result['duplicate_wasted_bytes'])}"
        )

    def on_scan_error(self, err_msg: str):
        self.on_scan_stopped()
        if self.current_task_id:
            global_task_manager.set_task_status(self.current_task_id, TaskStatus.FAILED, err_msg)
        QMessageBox.critical(self, "扫描异常", f"扫描过程中发生错误: {err_msg}")

    def on_scan_stopped(self):
        self.start_scan_btn.setEnabled(True)
        self.pause_scan_btn.setEnabled(False)
        self.pause_scan_btn.setText("⏸️ 暂停")
        self.stop_scan_btn.setEnabled(False)
        self.progress_bar.setVisible(False)

    def on_redundant_selection_changed(self, count: object, total_bytes: object):
        self.selection_stat_label.setText(f"已选中: {int(count)} 个文件 ({format_size(int(total_bytes))})")

    def open_migration_dialog_for_paths(self, paths: List[str]):
        if not paths:
            return
        dlg = MigrationDialog(selected_paths=paths, parent=self)
        if dlg.exec():
            self.duplicate_table.remove_paths(paths)
            self.releasable_table.remove_paths(paths)
            self.top100_table.remove_paths(paths)

    def execute_migration_selected(self):
        table = self.get_active_table()
        checked_paths = table.get_checked_paths()
        if not checked_paths:
            QMessageBox.warning(self, "提示", "请先在列表中勾选需要迁移的文件或文件夹！")
            return
        self.open_migration_dialog_for_paths(checked_paths)

    def trigger_ai_recommendation_only(self):
        """仅选推荐：由 AI 智能打标并勾选，绝不执行任何移动或删除"""
        if not self.current_scan_result or not self.current_scan_result.get("redundant_files"):
            QMessageBox.warning(self, "提示", "请先完成一次有效扫描！")
            return

        llm_cfg = app_config.get("llm", default={})
        if not llm_cfg.get("api_key") or not llm_cfg.get("base_url"):
            self.duplicate_table.select_recommended_only()
            self.releasable_table.select_recommended_only()
            QMessageBox.information(self, "智能推荐", "已根据本地安全启发式规则完成推荐勾选！")
            return

        self.btn_select_rec.setEnabled(False)
        self.phase_label.setText("🤖 正在向大模型提交文件特征进行智能甄别...")
        
        self.ai_worker = AIWorker("recommend", self.current_scan_result["redundant_files"])
        self.ai_worker.recommend_done.connect(self.on_ai_recommend_done)
        self.ai_worker.failed.connect(self.on_ai_failed)
        self.ai_worker.start()

    def on_ai_recommend_done(self, recommended_paths: List[str]):
        self.btn_select_rec.setEnabled(True)
        self.phase_label.setText("AI 智能分析完成")
        if recommended_paths:
            self.duplicate_table.select_ai_recommended_paths(recommended_paths)
            self.releasable_table.select_ai_recommended_paths(recommended_paths)
            QMessageBox.information(self, "仅选推荐就绪", f"大模型已甄别并勾选了 {len(recommended_paths)} 个推荐清理项！\n未执行任何删除/归档，您可继续修改勾选。")
        else:
            self.duplicate_table.select_recommended_only()
            self.releasable_table.select_recommended_only()
            QMessageBox.information(self, "智能推荐", "已根据本地安全启发式规则完成推荐勾选！")

    def trigger_ai_auto_process(self):
        """AI 自动处理：智能生成分类规划并在确认后安全后台归档"""
        if not self.current_scan_result or not self.current_scan_result.get("redundant_files"):
            QMessageBox.warning(self, "提示", "请先勾选盘符并完成一次有效扫描！")
            return

        table = self.get_active_table()
        checked_paths = table.get_checked_paths()
        
        redundant_files = self.current_scan_result.get("redundant_files", [])
        target_files = []
        if checked_paths:
            target_files = [f for f in redundant_files if f["path"] in checked_paths]
        else:
            target_files = [f for f in redundant_files if f.get("is_recommended", False)]
            if not target_files:
                target_files = redundant_files[:80]

        if not target_files:
            QMessageBox.warning(self, "提示", "未发现可供自动归档处理的冗余文件！")
            return

        dest_root = self.archive_input.text().strip() or "D:/归档备份"
        
        self.btn_ai_auto.setEnabled(False)
        self.phase_label.setText("AI 正在深度分析文件特征并生成归档规划...")

        self.ai_worker = AIWorker("classify", target_files, destination_root=dest_root)
        
        def on_classify_done(classified_results):
            self.btn_ai_auto.setEnabled(True)
            self.phase_label.setText("AI 智能规划已就绪")
            dlg = OrganizePreviewDialog(
                classification_items=classified_results,
                destination_root=dest_root,
                parent=self
            )
            if dlg.exec():
                processed_paths = [
                    sub["original_path"]
                    for g in classified_results
                    for sub in g.get("sub_items", [])
                ]
                self.duplicate_table.remove_paths(processed_paths)
                self.releasable_table.remove_paths(processed_paths)
                self.top100_table.remove_paths(processed_paths)
                
        self.ai_worker.classify_done.connect(on_classify_done)
        self.ai_worker.failed.connect(self.on_ai_failed)
        self.ai_worker.start()

    def generate_ai_report(self):
        if not self.current_scan_result:
            QMessageBox.warning(self, "提示", "请先执行扫描！")
            return

        self.gen_ai_report_btn.setEnabled(False)
        self.report_text_edit.setPlainText("🤖 正在调用大模型生成全景深度分析与治理报告，请稍候...")
        
        self.ai_worker = AIWorker("report", self.current_scan_result)
        self.ai_worker.report_done.connect(self.on_ai_report_done)
        self.ai_worker.failed.connect(self.on_ai_failed)
        self.ai_worker.start()

    def on_ai_report_done(self, report_md: str):
        self.gen_ai_report_btn.setEnabled(True)
        self.report_text_edit.setPlainText(report_md)
        self.tabs.setCurrentIndex(3)

    def on_ai_failed(self, err: str):
        self.btn_select_rec.setEnabled(True)
        self.gen_ai_report_btn.setEnabled(True)
        self.phase_label.setText("AI 请求异常")
        QMessageBox.warning(self, "AI 接口请求异常", f"调用大模型失败: {err}\n已自动切换为本地分析模式。")

    def execute_archive_selected_async(self):
        """一键快速归档 (完全在后台 Worker 中执行，杜绝主线程卡死)"""
        table = self.get_active_table()
        checked_paths = table.get_checked_paths()
        if not checked_paths:
            QMessageBox.warning(self, "提示", "您尚未勾选任何需要归档的文件！")
            return

        archive_dir = self.archive_input.text().strip()
        if not archive_dir:
            QMessageBox.warning(self, "提示", "请先在上方设置归档目标目录！")
            return

        reply = QMessageBox.question(
            self, "确认后台归档",
            f"即将把 {len(checked_paths)} 个勾选文件移入后台归档队列至:\n{archive_dir}\n\n"
            "归档将在后台多线程执行，界面将保持流畅无卡顿。是否立即启动？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        file_items = [{"path": p} for p in checked_paths]

        self.archive_worker = ArchiveWorker(
            file_items=file_items,
            destination_root=archive_dir,
            conflict_policy="auto_rename",
            preserve_structure=True
        )

        task_item = global_task_manager.create_task(
            name=f"批量归档 ({len(file_items)} 项)",
            task_type=TaskType.CLEANUP,
            worker=self.archive_worker
        )

        self.btn_archive.setEnabled(False)
        self.phase_label.setText("📦 正在后台流式归档文件...")

        self.archive_worker.progress_signal.connect(
            lambda cur, tot, spd, eta, pb, tb: self.speed_label.setText(f"⚡ 归档速度: {spd} | 进度: {cur}/{tot} | ETA: {eta}s")
        )
        self.archive_worker.finished_signal.connect(self.on_home_archive_finished)
        self.archive_worker.start()

    def on_home_archive_finished(self, all_success: bool, summary: dict):
        self.btn_archive.setEnabled(True)
        self.speed_label.setText("")
        self.phase_label.setText("✅ 归档任务已完成")
        
        table = self.get_active_table()
        # 从表格中安全移除
        migrated = [item["original_path"] for item in summary.get("items", []) if "original_path" in item]
        if migrated:
            table.remove_paths(migrated)

        msg = (
            f"后台归档执行完成！\n"
            f"成功迁移: {summary['success_count']} 个\n"
            f"失败项: {summary['failed_count']} 个 | 跳过项: {summary['skipped_count']} 个\n"
            f"累计归档容量: {format_size(summary['archived_bytes'])}\n\n"
            f"是否立即在文件资源管理器中打开目标归档目录？"
        )
        reply = QMessageBox.question(self, "归档完成", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply == QMessageBox.Yes:
            dest = self.archive_input.text().strip()
            if os.path.exists(dest):
                subprocess.Popen(f'explorer.exe "{os.path.normpath(dest)}"')

    def execute_cleanup_selected(self):
        table = self.get_active_table()
        checked_paths = table.get_checked_paths()
        if not checked_paths:
            QMessageBox.warning(self, "提示", "您尚未勾选任何需要清理的文件！")
            return

        reply = QMessageBox.question(
            self, "确认清理",
            f"您已选择清理 {len(checked_paths)} 个文件。\n\n"
            f"点击「Yes」移入回收站（可撤销恢复）\n"
            f"点击「No」执行永久彻底删除（不可撤销）\n"
            f"点击「Cancel」取消本次操作",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes
        )
        if reply == QMessageBox.Cancel:
            return
            
        to_recycle = (reply == QMessageBox.Yes)
        
        self.del_worker = DeleteWorker(checked_paths, to_recycle_bin=to_recycle)
        
        self.btn_cleanup.setEnabled(False)
        self.phase_label.setText("🗑️ 正在后台清理文件...")
        
        def on_del_finished(ok, summary):
            self.btn_cleanup.setEnabled(True)
            self.phase_label.setText("✅ 清理任务已完成")
            table.remove_paths(checked_paths)
            QMessageBox.information(self, "清理完成", f"已成功清理 {summary['success_count']} 个文件！")
            
        self.del_worker.finished_signal.connect(on_del_finished)
        self.del_worker.start()

    def export_markdown_report(self):
        if not self.current_scan_result:
            QMessageBox.warning(self, "提示", "请先执行扫描后再导出报告！")
            return

        default_name = f"磁盘全景深度分析报告_{os.path.basename(os.getcwd())}.md"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "导出 Markdown 深度分析报告", default_name, "Markdown 文件 (*.md)"
        )
        if not save_path:
            return

        content = self.report_text_edit.toPlainText().strip()
        if content:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(content)
            QMessageBox.information(self, "导出成功", f"分析报告已成功保存至:\n{save_path}")
        else:
            ok = ReportExporter.generate_and_export_report(self.current_scan_result, save_path)
            if ok:
                QMessageBox.information(self, "导出成功", f"分析报告已成功生成并保存至:\n{save_path}")
            else:
                QMessageBox.critical(self, "导出失败", "生成或保存报告时发生错误！")
