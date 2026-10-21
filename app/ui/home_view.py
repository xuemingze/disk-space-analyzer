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
from app.ui.components.rollback_widget import RollbackWidget
from app.utils.file_helper import format_size
from app.utils.logger import app_logger


class AIWorker(QThread):
    phase_changed = Signal(str)
    recommend_done = Signal(list)
    report_done = Signal(object)
    classify_done = Signal(list)
    failed = Signal(str)

    def __init__(self, action: str, data: Any, parent=None, **kwargs):
        super().__init__(parent)
        self.action = action
        self.data = data
        self.kwargs = kwargs
        self._is_paused = False

    def pause(self):
        self._is_paused = True

    def resume(self):
        self._is_paused = False

    def cancel(self):
        self.terminate()
        self.wait()

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
                ai_response = AIService.generate_health_report_with_ai(
                    base_url, api_key, model, self.data, progress_callback=lambda p: self.phase_changed.emit(p)
                )
                self.report_done.emit(ai_response)
            elif self.action == "classify":
                dest_root = self.kwargs.get("destination_root", "D:/归档备份")
                options = self.kwargs.get("options")
                prefs = self.kwargs.get("prefs", {"work_ratio": 0.6, "personal_ratio": 0.4})
                classified = AIService.classify_files_with_ai(
                    base_url, api_key, model, self.data, dest_root,
                    weights=prefs,
                    options=options,
                    progress_callback=lambda p: self.phase_changed.emit(p)
                )
                self.classify_done.emit(classified)
            elif self.action == "process_report":
                dest_root = self.data.get("dest_root", "D:/归档备份")
                report_path = self.data.get("report_path", "")
                classified = AIService.process_report_with_ai(
                    base_url, api_key, model, report_path, dest_root
                )
                self.classify_done.emit(classified)
        except Exception as e:
            self.failed.emit(str(e))


class HomeView(QWidget):
    """
    主控扫描与分阶段全景呈现页面 (Home)
    """
    navigate_to_organizer = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_scan_result: Optional[Dict[str, Any]] = None
        self.scan_worker: Optional[ScanWorker] = None
        self.archive_worker: Optional[ArchiveWorker] = None
        self.scan_task_id: Optional[str] = None
        self.ai_worker: Optional[AIWorker] = None
        self._archived_files_backup = {}
        
        self.init_ui()
        
        from app.core.events import event_bus
        event_bus.files_state_changed.connect(self.on_global_files_changed, Qt.QueuedConnection)
        event_bus.report_updated.connect(self.on_global_report_updated, Qt.QueuedConnection)

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
        self.start_scan_btn.setStyleSheet("font-size: 13px; font-weight: bold;")
        self.start_scan_btn.clicked.connect(self.start_scan)
        
        self.pause_scan_btn = QPushButton("⏸️ 暂停")
        self.pause_scan_btn.setProperty("class", "SecondaryButton")
        self.pause_scan_btn.setEnabled(False)
        self.pause_scan_btn.clicked.connect(self.toggle_pause_scan)

        self.stop_scan_btn = QPushButton("⏹️ 取消")
        self.stop_scan_btn.setProperty("class", "DangerButton")
        self.stop_scan_btn.setEnabled(False)
        self.stop_scan_btn.clicked.connect(self.stop_scan)
        self.task_center_btn = QPushButton("⚡ 任务管理")
        self.task_center_btn.setStyleSheet("background-color: #4F46E5; border-color: #6366F1; font-weight: bold;")
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
        self.top_card = top_card
        main_layout.addWidget(top_card)

        # 2. 统计指标卡片栏
        self.stat_cards = StatCardsRow()
        main_layout.addWidget(self.stat_cards)

        # 3. 核心内容标签页
        self.tabs = QTabWidget()
        
        self.chart_widget = SpaceDistributionChartWidget()
        self.tabs.addTab(self.chart_widget, "📊 空间全景图与景深分布 (阶段一即显)")
        
        self.global_detail_table = FileDataGridWidget(is_selectable=True)
        self.global_detail_table.selection_changed_signal.connect(self.on_redundant_selection_changed)
        self.global_detail_table.migrate_requested_signal.connect(self.open_migration_dialog_for_paths)
        self.global_detail_table.promote_collective_requested.connect(self.on_promote_collective_requested)
        self.global_detail_table.path_edited_signal.connect(self.on_asset_path_edited)
        self.global_detail_table.category_changed_signal.connect(self.on_asset_category_changed)
        self.tabs.addTab(self.global_detail_table, "📑 全局扫描资产明细 (阶段一即显)")

        self.duplicate_table = FileDataGridWidget(is_selectable=True)
        self.duplicate_table.selection_changed_signal.connect(self.on_redundant_selection_changed)
        self.duplicate_table.migrate_requested_signal.connect(self.open_migration_dialog_for_paths)
        self.duplicate_table.promote_collective_requested.connect(self.on_promote_collective_requested)
        self.duplicate_table.path_edited_signal.connect(self.on_asset_path_edited)
        self.duplicate_table.category_changed_signal.connect(self.on_asset_category_changed)
        self.tabs.addTab(self.duplicate_table, "🔄 重复资产明细 (哈希确认)")
        
        self.releasable_table = FileDataGridWidget(is_selectable=True)
        self.releasable_table.selection_changed_signal.connect(self.on_redundant_selection_changed)
        self.releasable_table.migrate_requested_signal.connect(self.open_migration_dialog_for_paths)
        self.releasable_table.promote_collective_requested.connect(self.on_promote_collective_requested)
        self.releasable_table.path_edited_signal.connect(self.on_asset_path_edited)
        self.releasable_table.category_changed_signal.connect(self.on_asset_category_changed)
        self.tabs.addTab(self.releasable_table, "🗑️ 可释放资产明细 (规则识别)")
        
        self.top100_table = FileDataGridWidget(is_selectable=True)
        self.top100_table.selection_changed_signal.connect(self.on_redundant_selection_changed)
        self.top100_table.migrate_requested_signal.connect(self.open_migration_dialog_for_paths)
        self.top100_table.promote_collective_requested.connect(self.on_promote_collective_requested)
        self.top100_table.path_edited_signal.connect(self.on_asset_path_edited)
        self.top100_table.category_changed_signal.connect(self.on_asset_category_changed)
        self.tabs.addTab(self.top100_table, "🏆 全局 Top 100 超大资产 (>300MB) (阶段一即显)")
        
        self.rollback_tab = RollbackWidget()
        self.tabs.addTab(self.rollback_tab, "🔙 归档快照与安全回滚 (安全审计)")
        
        # AI 深度分析报告
        self.report_widget = QWidget()
        report_widget = self.report_widget
        report_layout = QVBoxLayout(report_widget)
        report_layout.setContentsMargins(10, 10, 10, 10)
        report_layout.setSpacing(8)
        
        report_top_bar = QHBoxLayout()
        self.gen_ai_report_btn = QPushButton("🤖 重新生成 AI 深度分析报告")
        self.gen_ai_report_btn.setProperty("class", "SecondaryButton")
        self.gen_ai_report_btn.clicked.connect(self.generate_ai_report)

        self.pause_ai_report_btn = QPushButton("⏸️ 暂停")
        self.pause_ai_report_btn.setProperty("class", "SecondaryButton")
        self.pause_ai_report_btn.setEnabled(False)
        self.pause_ai_report_btn.clicked.connect(self.toggle_pause_ai_report)

        self.stop_ai_report_btn = QPushButton("⏹️ 停止")
        self.stop_ai_report_btn.setProperty("class", "DangerButton")
        self.stop_ai_report_btn.setEnabled(False)
        self.stop_ai_report_btn.clicked.connect(self.stop_ai_report)
        
        self.export_report_btn = QPushButton("📑 导出 Markdown 报告 (.md)")
        self.export_report_btn.setProperty("class", "SuccessButton")
        self.export_report_btn.clicked.connect(self.export_markdown_report)
        
        report_top_bar.addWidget(self.gen_ai_report_btn)
        report_top_bar.addWidget(self.pause_ai_report_btn)
        report_top_bar.addWidget(self.stop_ai_report_btn)
        report_top_bar.addStretch()
        report_top_bar.addWidget(self.export_report_btn)
        
        from PySide6.QtWidgets import QSplitter
        report_splitter = QSplitter(Qt.Vertical)
        
        self.report_text_edit = QTextEdit()
        self.report_text_edit.setReadOnly(True)
        self.report_text_edit.setPlaceholderText("扫描完成后，此处将渲染基于 AI 大模型的磁盘全景深度分析与治理报告...")
        
        self.ai_log_edit = QTextEdit()
        self.ai_log_edit.setReadOnly(True)
        self.ai_log_edit.setPlaceholderText("AI 请求与执行日志将会显示在这里...")
        self.ai_log_edit.setStyleSheet("background-color: #0F172A; color: #38BDF8; font-family: Consolas, monospace; font-size: 11px;")
        
        report_splitter.addWidget(self.report_text_edit)
        report_splitter.addWidget(self.ai_log_edit)
        report_splitter.setStretchFactor(0, 3)
        report_splitter.setStretchFactor(1, 1)

        report_layout.addLayout(report_top_bar)
        # 决策卡片 (当独立资产 > 100 项时或 AI 异常时呈现，由用户决定，不因超时直接越权)
        self.ai_decision_banner = QFrame()
        self.ai_decision_banner.setObjectName("AIDecisionBanner")
        self.ai_decision_banner.setStyleSheet("""
            QFrame#AIDecisionBanner {
                background-color: #1E293B;
                border: 1px solid #F59E0B;
                border-radius: 8px;
            }
        """)
        decision_layout = QHBoxLayout(self.ai_decision_banner)
        decision_layout.setContentsMargins(12, 10, 12, 10)
        decision_layout.setSpacing(12)

        decision_icon_label = QLabel("⚠️")
        decision_icon_label.setStyleSheet("font-size: 24px;")
        decision_layout.addWidget(decision_icon_label)

        decision_text_layout = QVBoxLayout()
        decision_text_layout.setSpacing(3)
        self.decision_title_lbl = QLabel("扫描独立资产数量为 0 项 (80% 可能性为集合判断错误)")
        self.decision_title_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #FBBF24;")
        self.decision_sub_lbl = QLabel("检测到大量独立散落资产，建议前往文件整理进行应用/工程级收拢聚合；亦可由您自主决定强制执行 AI 全景总结。")
        self.decision_sub_lbl.setStyleSheet("font-size: 11px; color: #94A3B8;")
        decision_text_layout.addWidget(self.decision_title_lbl)
        decision_text_layout.addWidget(self.decision_sub_lbl)
        decision_layout.addLayout(decision_text_layout, 1)

        # 选项1: 运行文件整理 (跳转至文件整理页面)
        self.btn_decision_organize = QPushButton("📁 运行文件整理 (推荐)")
        self.btn_decision_organize.setProperty("class", "SuccessButton")
        self.btn_decision_organize.setStyleSheet("background-color: #10B981; color: white; font-weight: bold; padding: 6px 14px; border-radius: 6px;")
        self.btn_decision_organize.clicked.connect(self.navigate_to_organizer_page)
        decision_layout.addWidget(self.btn_decision_organize)

        # 选项2: 强制 AI 总结
        self.btn_decision_force_ai = QPushButton("⚡ 强制 AI 总结")
        self.btn_decision_force_ai.setProperty("class", "PrimaryButton")
        self.btn_decision_force_ai.setStyleSheet("background-color: #3B82F6; color: white; font-weight: bold; padding: 6px 14px; border-radius: 6px;")
        self.btn_decision_force_ai.clicked.connect(lambda: self.generate_ai_report(force=True))
        decision_layout.addWidget(self.btn_decision_force_ai)

        # 选项3: 重试 AI 总结 (异常时显示)
        self.btn_decision_retry_ai = QPushButton("🔄 重试 AI 总结")
        self.btn_decision_retry_ai.setStyleSheet("background-color: #3B82F6; color: white; font-weight: bold; padding: 6px 14px; border-radius: 6px;")
        self.btn_decision_retry_ai.clicked.connect(lambda: self.generate_ai_report(force=True))
        decision_layout.addWidget(self.btn_decision_retry_ai)
        self.btn_decision_retry_ai.hide()

        # 选项4: 载入本地专家应急报告 (异常时由用户决定是否载入，绝不自动越权)
        self.btn_decision_load_fallback = QPushButton("📑 载入本地专家应急报告")
        self.btn_decision_load_fallback.setStyleSheet("background-color: #64748B; color: white; font-weight: bold; padding: 6px 14px; border-radius: 6px;")
        self.btn_decision_load_fallback.clicked.connect(self.load_local_expert_fallback)
        decision_layout.addWidget(self.btn_decision_load_fallback)
        self.btn_decision_load_fallback.hide()

        self.ai_decision_banner.hide()
        report_layout.addWidget(self.ai_decision_banner)
        report_layout.addWidget(report_splitter)
        self.tabs.addTab(report_widget, "📑 AI 深度分析报告预览")
        
        self.tab_fullscreen_btn = QPushButton("⛶ 放大当前标签页")
        self.tab_fullscreen_btn.setStyleSheet("background-color: transparent; font-weight: bold; padding: 2px 8px; color: #38BDF8;")
        self.tab_fullscreen_btn.clicked.connect(self.toggle_tab_fullscreen)
        self.tabs.setCornerWidget(self.tab_fullscreen_btn, Qt.TopRightCorner)
        self.tab_states = {}
        self.tabs.currentChanged.connect(self.on_tab_changed)
        
        self._setup_gui_logger()

        main_layout.addWidget(self.tabs, 1)

        # 4. 底部批量交互操作栏
        self.bottom_bar = QFrame()
        bottom_bar = self.bottom_bar
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
    def toggle_tab_fullscreen(self):
        idx = self.tabs.currentIndex()
        is_fs = self.tab_states.get(idx, False)
        self.tab_states[idx] = not is_fs
        self.on_tab_changed(idx)
        
    def on_tab_changed(self, index: int):
        is_fs = self.tab_states.get(index, False)
        if is_fs:
            self.top_card.hide()
            self.stat_cards.hide()
            self.bottom_bar.hide()
            self.tab_fullscreen_btn.setText("🗗 还原标签页 (Esc)")
            self.tab_fullscreen_btn.setToolTip("按 Esc 键或点击此处还原")
        else:
            self.top_card.show()
            self.stat_cards.show()
            self.bottom_bar.show()
            self.tab_fullscreen_btn.setText("⛶ 放大当前标签页")
            self.tab_fullscreen_btn.setToolTip("将当前标签页放大至填满主区域")

        # 切换 Tab 时实时刷新底部选中统计栏，确保数值与当前活跃视图严格一致
        active_tbl = self.get_active_table()
        if active_tbl:
            self.on_redundant_selection_changed(
                len(active_tbl.source_model.checked_paths),
                active_tbl.source_model.checked_bytes
            )
            
    def is_tab_fullscreen(self) -> bool:
        idx = getattr(self, "tabs", None)
        if idx:
            return self.tab_states.get(self.tabs.currentIndex(), False)
        return False

    def _setup_gui_logger(self):
        import logging
        from PySide6.QtCore import QMetaObject, Qt, Q_ARG
        class GuiLogHandler(logging.Handler):
            def __init__(self, text_edit):
                super().__init__()
                self.text_edit = text_edit
                self.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%H:%M:%S"))

            def emit(self, record):
                msg = self.format(record)
                QMetaObject.invokeMethod(self.text_edit, "append", Qt.QueuedConnection, Q_ARG(str, msg))
                
        self.gui_log_handler = GuiLogHandler(self.ai_log_edit)
        app_logger.addHandler(self.gui_log_handler)

    def toggle_pause_ai_report(self):
        if not getattr(self, "ai_worker", None) or not self.ai_worker.isRunning():
            return
        if self.pause_ai_report_btn.text().startswith("⏸️"):
            self.ai_worker.pause()
            self.pause_ai_report_btn.setText("▶️ 恢复")
            self.report_text_edit.append("\n[已暂停]")
        else:
            self.ai_worker.resume()
            self.pause_ai_report_btn.setText("⏸️ 暂停")
            self.report_text_edit.append("\n[已恢复]")

    def stop_ai_report(self):
        if getattr(self, "ai_worker", None) and self.ai_worker.isRunning():
            self.ai_worker.cancel()
            self.report_text_edit.append("\n[已取消 AI 生成任务]")
            self.on_ai_failed("已手动停止任务")

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
            return self.global_detail_table
        elif idx == 2:
            return self.duplicate_table
        elif idx == 3:
            return self.releasable_table
        elif idx == 4:
            return self.top100_table
        return self.global_detail_table

    def on_asset_path_edited(self, item: Dict[str, Any], new_path: str):
        """
        建议归档规划路径就地手动修改后，同构同步四大表格并触发空间分布多级聚合重算
        """
        target_path = item.get("path")
        if not target_path:
            return
        norm_target = os.path.normcase(os.path.normpath(target_path))

        tables = [self.global_detail_table, self.duplicate_table, self.releasable_table, self.top100_table]
        for table in tables:
            for row, data_item in enumerate(table.source_model._data):
                p = data_item.get("path")
                if p and (p == target_path or os.path.normcase(os.path.normpath(p)) == norm_target):
                    data_item["suggested_archive_path"] = new_path
                    data_item["target_subpath"] = new_path
                    if item.get("category"):
                        data_item["category"] = item["category"]
                    if item.get("tag"):
                        data_item["tag"] = item["tag"]
                    if item.get("phase_status"):
                        data_item["phase_status"] = item["phase_status"]
                    idx1 = table.source_model.index(row, 0)
                    idx2 = table.source_model.index(row, table.source_model.columnCount() - 1)
                    table.source_model.dataChanged.emit(idx1, idx2)

        if self.current_scan_result:
            for key in ["all_scanned_files", "redundant_files", "top_100_files"]:
                if key in self.current_scan_result and isinstance(self.current_scan_result[key], list):
                    for f_item in self.current_scan_result[key]:
                        p = f_item.get("path")
                        if p and (p == target_path or os.path.normcase(os.path.normpath(p)) == norm_target):
                            f_item["suggested_archive_path"] = new_path
                            f_item["target_subpath"] = new_path
                            if item.get("category"):
                                f_item["category"] = item["category"]
                            if item.get("tag"):
                                f_item["tag"] = item["tag"]
                            if item.get("phase_status"):
                                f_item["phase_status"] = item["phase_status"]

        self.recalculate_space_distribution()

    def on_asset_category_changed(self, item: Dict[str, Any]):
        """
        分类树吸附或右键树状级联分类变更后，同构同步四大表格并触发空间分布多级聚合重算
        """
        target_path = item.get("path")
        if not target_path:
            return
        norm_target = os.path.normcase(os.path.normpath(target_path))

        tables = [self.global_detail_table, self.duplicate_table, self.releasable_table, self.top100_table]
        for table in tables:
            for row, data_item in enumerate(table.source_model._data):
                p = data_item.get("path")
                if p and (p == target_path or os.path.normcase(os.path.normpath(p)) == norm_target):
                    if item.get("category"):
                        data_item["category"] = item["category"]
                    if item.get("suggested_archive_path"):
                        data_item["suggested_archive_path"] = item["suggested_archive_path"]
                    if item.get("target_subpath"):
                        data_item["target_subpath"] = item["target_subpath"]
                    if item.get("tag"):
                        data_item["tag"] = item["tag"]
                    if item.get("phase_status"):
                        data_item["phase_status"] = item["phase_status"]
                    idx1 = table.source_model.index(row, 0)
                    idx2 = table.source_model.index(row, table.source_model.columnCount() - 1)
                    table.source_model.dataChanged.emit(idx1, idx2)

        if self.current_scan_result:
            for key in ["all_scanned_files", "redundant_files", "top_100_files"]:
                if key in self.current_scan_result and isinstance(self.current_scan_result[key], list):
                    for f_item in self.current_scan_result[key]:
                        p = f_item.get("path")
                        if p and (p == target_path or os.path.normcase(os.path.normpath(p)) == norm_target):
                            if item.get("category"):
                                f_item["category"] = item["category"]
                            if item.get("suggested_archive_path"):
                                f_item["suggested_archive_path"] = item["suggested_archive_path"]
                            if item.get("target_subpath"):
                                f_item["target_subpath"] = item["target_subpath"]
                            if item.get("tag"):
                                f_item["tag"] = item["tag"]
                            if item.get("phase_status"):
                                f_item["phase_status"] = item["phase_status"]

        self.recalculate_space_distribution()

    def recalculate_space_distribution(self):
        """
        多级聚合重算：全域同构联动，重新汇总分类占用并刷新空间分布饼图/柱状图
        """
        items = self.global_detail_table.source_model._data
        if not items and self.current_scan_result:
            items = self.current_scan_result.get("all_scanned_files", [])

        if not items:
            return

        category_bytes = {}
        category_counts = {}
        total_bytes = 0

        for it in items:
            cat = it.get("category") or "未分类"
            sz = it.get("size", 0)
            total_bytes += sz
            category_bytes[cat] = category_bytes.get(cat, 0) + sz
            category_counts[cat] = category_counts.get(cat, 0) + 1

        cat_stats = {
            cat: {
                "bytes": cb,
                "count": category_counts[cat],
                "percent": round((cb / total_bytes * 100), 2) if total_bytes > 0 else 0.0
            }
            for cat, cb in sorted(category_bytes.items(), key=lambda x: x[1], reverse=True)
        }

        if self.current_scan_result is None:
            self.current_scan_result = {}
        self.current_scan_result["category_stats"] = cat_stats

        self.chart_widget.update_chart(cat_stats)

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
        ignore_folders = app_config.get("ignore_folders", default=[])

        self.scan_worker = ScanWorker(
            target_paths=targets,
            enable_duplicate_detection=self.chk_dup_detect.isChecked(),
            hash_algorithm=hash_algo,
            skip_system_protected=self.chk_skip_system.isChecked(),
            concurrency=concurrency,
            ignore_folders=ignore_folders
        )
        
        task_item = global_task_manager.create_task(
            name=f"全景扫描 ({', '.join(targets)})",
            task_type=TaskType.SCAN,
            worker=self.scan_worker
        )
        self.scan_task_id = task_item.task_id
        self.scan_worker.task_id = self.scan_task_id

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
            if self.scan_task_id:
                global_task_manager.pause_task(self.scan_task_id)
        else:
            self.scan_worker.resume()
            self.pause_scan_btn.setText("⏸️ 暂停")
            if self.scan_task_id:
                global_task_manager.resume_task(self.scan_task_id)

    def stop_scan(self):
        if self.scan_worker and self.scan_worker.isRunning():
            self.phase_label.setText("正在中止扫描...")
            self.scan_worker.cancel()
            self.scan_worker.wait()
            if self.scan_task_id:
                global_task_manager.cancel_task(self.scan_task_id)
            self.on_scan_stopped()

    def on_scan_progress(self, current_dir: str, file_count: object, total_bytes: object):
        f_cnt = int(file_count)
        t_byt = int(total_bytes)
        self.current_path_label.setText(f"已扫: {f_cnt:,} 个碎片文件 ({format_size(t_byt)}) | {str(current_dir)[:50]}...")
        if self.scan_task_id:
            global_task_manager.update_task_progress(
                self.scan_task_id,
                processed_count=f_cnt,
                processed_bytes=t_byt
            )

    def on_scan_phase_changed(self, phase_name: str):
        self.phase_label.setText(phase_name)
        if self.scan_task_id:
            global_task_manager.update_task_progress(self.scan_task_id, phase=phase_name)

    def on_phase1_completed(self, p1_result: dict):
        self.phase_label.setText(f"✅ 阶段一完成 (耗时 {p1_result['elapsed_seconds']}s) - 正在进入阶段二哈希比对...")
        c_cnt = p1_result.get("collective_count", 0)
        s_cnt = p1_result.get("standalone_file_count", 0)
        tot_assets = c_cnt + s_cnt
        total_phys = p1_result.get("total_files", 0)
        if c_cnt > 0:
            files_str = f"{tot_assets:,} 项 ({c_cnt} 集体 / {s_cnt} 独立单项)"
        else:
            files_str = f"{total_phys:,} 个独立单项资产"

        self.stat_cards.update_stats(
            total_bytes_str=format_size(p1_result["total_bytes"]),
            reclaimable_str="比对中...",
            files_count_str=files_str,
            dup_waste_str="比对中...",
            dup_groups_count=p1_result.get("dup_candidate_groups_count", 0)
        )
        self.stat_cards.card_total_files.title_label.setText("扫描资产单元总数")
        if c_cnt > 0:
            self.stat_cards.card_total_files.subtext_label.setText(f"已聚合封包 {total_phys:,} 碎片文件")

        self.chart_widget.update_chart(p1_result.get("category_stats", {}))
        
        all_files = p1_result.get("all_scanned_files", [])
        self.global_detail_table.populate_data(all_files, p1_result["total_bytes"])
        self.tabs.setTabText(1, f"📑 全局扫描资产明细 [{len(all_files)}]")

        top_files = p1_result.get("top_100_files", [])
        self.top100_table.populate_data(top_files, p1_result["total_bytes"])
        self.tabs.setTabText(4, f"🏆 全局 Top 100 超大资产 (>300MB) [{len(top_files)}]")
        self.tabs.setCurrentIndex(0)

        # 阶段一完成即刻赋值当前扫描结果，解除收拢转集合的阻塞
        self.current_scan_result = dict(p1_result)

    def on_phase2_progress(self, proc_b: object, tot_b: object, speed: str, eta: int, cur_g: int, tot_g: int):
        proc_int = int(proc_b)
        tot_int = int(tot_b)
        pct = (proc_int / tot_int * 100.0) if tot_int > 0 else 0.0
        self.progress_bar.setValue(int(pct))
        self.speed_label.setText(f"⚡ 查重速度: {speed} | ETA: {eta}s (组: {cur_g}/{tot_g})")
        if self.scan_task_id:
            global_task_manager.update_task_progress(
                self.scan_task_id,
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

        c_cnt = result.get("collective_count", 0)
        s_cnt = result.get("standalone_file_count", 0)
        tot_assets = c_cnt + s_cnt
        total_phys = result.get("total_files", 0)
        if c_cnt > 0:
            files_str = f"{tot_assets:,} 项 ({c_cnt} 集体 / {s_cnt} 独立单项)"
        else:
            files_str = f"{total_phys:,} 个独立单项资产"

        self.stat_cards.update_stats(
            total_bytes_str=format_size(result["total_bytes"]),
            reclaimable_str=format_size(result["reclaimable_bytes"]),
            files_count_str=files_str,
            dup_waste_str=format_size(result["duplicate_wasted_bytes"]),
            dup_groups_count=result["duplicate_groups_count"]
        )
        self.stat_cards.card_total_files.title_label.setText("扫描资产单元总数")
        if c_cnt > 0:
            self.stat_cards.card_total_files.subtext_label.setText(f"已聚合封包 {total_phys:,} 碎片文件")

        all_redundant = result.get("redundant_files", [])
        duplicate_files = [f for f in all_redundant if f.get("is_duplicate")]
        releasable_files = [f for f in all_redundant if not f.get("is_duplicate")]
        
        self.duplicate_table.populate_data(duplicate_files, result["total_bytes"])
        self.releasable_table.populate_data(releasable_files, result["total_bytes"])
        self.tabs.setTabText(2, f"🔄 重复资产明细 (哈希确认) [{len(duplicate_files)}]")
        self.tabs.setTabText(3, f"🗑️ 可释放资产明细 (规则识别) [{len(releasable_files)}]")

        all_files = result.get("all_scanned_files", [])
        if all_files:
            self.global_detail_table.populate_data(all_files, result["total_bytes"])
            self.tabs.setTabText(1, f"📑 全局扫描资产明细 [{len(all_files)}]")

        if getattr(self, "scan_task_id", None):
            global_task_manager.set_task_status(self.scan_task_id, TaskStatus.COMPLETED)
            self.scan_task_id = None

        if duplicate_files:
            self.tabs.setCurrentIndex(2)
        elif releasable_files:
            self.tabs.setCurrentIndex(3)
        elif all_files:
            self.tabs.setCurrentIndex(1)

        # 准则一架构：AI 为核心编排器，本地的抛出必须要缩紧、精准
        # 扫描目录后独立资产如果超过 100，80% 可能性是集合判断错误，由用户决定运行文件整理或强制 AI 总结，绝不因超时直接越权
        standalone_count = s_cnt if (s_cnt > 0 or c_cnt > 0) else total_phys
        if standalone_count > 100:
            report_idx = self.tabs.indexOf(self.report_widget)
            if report_idx >= 0:
                self.tabs.setTabText(report_idx, f"📑 AI 深度分析报告 (待决策: {standalone_count} 独立资产)")
                self.tabs.setCurrentIndex(report_idx)

            self.decision_title_lbl.setText(f"扫描独立资产数量为 {standalone_count} 项 (80% 可能性为集合判断错误)")
            self.decision_sub_lbl.setText("当前目录下存在超过 100 项散落独立资产，极可能存在未聚合的目录集体或未整理工具链。请由您决定下一步治理路径：")
            self.btn_decision_organize.setVisible(True)
            self.btn_decision_force_ai.setVisible(True)
            self.btn_decision_retry_ai.setVisible(False)
            self.btn_decision_load_fallback.setVisible(False)
            self.ai_decision_banner.show()

            decision_md = (
                f"# ⚠️ 扫描独立资产数量为 {standalone_count} 项\n\n"
                f"> **架构诊断提示**：当前目录扫描识别出 `{standalone_count}` 项离散独立资产（阈值 > 100 项）。"
                f"根据存储治理规律，**有 80% 可能性是集合判断错误**（如应用工程、业务单据、虚拟机/模型角色或散落工具链未收拢为原子实体集体）。\n\n"
                f"### 🎯 请选择治理路径（严格遵从 AI 为核心，由您自主决定，绝不越权）：\n\n"
                f"1. **【📁 运行文件整理】（推荐）**：前往文件整理模块，按应用工具链、工程、前缀或业务类型进行目录级收拢聚合，从根源上消除文件散落；\n"
                f"2. **【⚡ 强制 AI 总结】**：跳过集合收拢建议，直接启动 AI 核心编排器对当前扫描样本进行全景深度分析与执行清单生成。\n\n"
                f"*请点击上方横幅按钮执行相应操作。*"
            )
            self.report_text_edit.setPlainText(decision_md)
        else:
            self.ai_decision_banner.hide()
            self.report_text_edit.setPlainText("⏳ 等待分析: 正在准备后台分析任务...")
            self.generate_ai_report(auto_triggered=True)

        msg = (
            f"空间全景深度扫描已全部完成！\n"
            f"共识别资产单元: {tot_assets:,} 项 (含 {c_cnt} 个原子实体集体, {s_cnt} 个独立单项资产)\n"
            f"底层碎片文件聚合: {total_phys:,} 个 (总存储占用: {format_size(result['total_bytes'])})\n"
        )
        skipped = result.get("skipped_ignored_count", 0)
        if skipped > 0:
            msg += f"跳过忽略目录: {skipped} 个\n"
            
        msg += (
            f"确认重复副本: {result['duplicate_groups_count']} 组 ({format_size(result['duplicate_wasted_bytes'])})\n"
            f"可释放空间预估: {format_size(result['reclaimable_bytes'] + result['duplicate_wasted_bytes'])}"
        )
        
        QMessageBox.information(self, "扫描全量完成", msg)


    def on_promote_collective_requested(self, target_dir: str, app_name: str):
        """响应任意表格触发的收拢转集合操作，执行全域同构收割与联动刷新"""
        from app.core.asset_promoter import AssetPromoterService

        # 1. 第一优先级执行规则沉淀落盘 (双保险落盘)
        AssetPromoterService.persist_collective(target_dir, app_name=app_name)

        # 2. 若当前 current_scan_result 为空，从全局表格中拉取已显示的数据作为数据源
        if not self.current_scan_result:
            grid_data = self.global_detail_table.source_model._data
            if grid_data:
                self.current_scan_result = {
                    "all_scanned_files": list(grid_data),
                    "total_bytes": sum(f.get("size", 0) for f in grid_data),
                    "redundant_files": []
                }
            else:
                return
        all_files = self.current_scan_result.get("all_scanned_files", [])
        updated_all_files, new_asset = AssetPromoterService.execute_promotion(
            target_dir=target_dir,
            app_name=app_name,
            current_assets=all_files,
            persist=True
        )
        self.current_scan_result["all_scanned_files"] = updated_all_files

        # 联动收割冗余与重复池中的碎片
        redundant = self.current_scan_result.get("redundant_files", [])
        norm_t = os.path.normcase(os.path.normpath(target_dir))
        prefix = norm_t + os.sep
        updated_redundant = [
            f for f in redundant
            if not (os.path.normcase(os.path.normpath(f.get("path", ""))) == norm_t or
                    os.path.normcase(os.path.normpath(f.get("path", ""))).startswith(prefix))
        ]
        self.current_scan_result["redundant_files"] = updated_redundant

        dup_files = [f for f in updated_redundant if f.get("is_duplicate")]
        rel_files = [f for f in updated_redundant if not f.get("is_duplicate")]

        tot_bytes = self.current_scan_result.get("total_bytes", 0)
        self.global_detail_table.populate_data(updated_all_files, tot_bytes)
        self.duplicate_table.populate_data(dup_files, tot_bytes)
        self.releasable_table.populate_data(rel_files, tot_bytes)

        self.tabs.setTabText(1, f"📑 全局扫描资产明细 [{len(updated_all_files)}]")
        self.tabs.setTabText(2, f"🔄 重复资产明细 (哈希确认) [{len(dup_files)}]")
        self.tabs.setTabText(3, f"🗑️ 可释放资产明细 (规则识别) [{len(rel_files)}]")

        # 联动刷新顶部指标卡片
        c_cnt = sum(1 for it in updated_all_files if it.get("is_directory_collective"))
        s_cnt = len(updated_all_files) - c_cnt
        files_str = f"{len(updated_all_files):,} 项 ({c_cnt} 集体 / {s_cnt} 独立单项)" if c_cnt > 0 else f"{len(updated_all_files):,} 个资产项"
        self.stat_cards.update_stats(
            total_bytes_str=format_size(tot_bytes),
            reclaimable_str=format_size(sum(f.get("size", 0) for f in rel_files)),
            files_count_str=files_str,
            dup_waste_str=format_size(sum(f.get("size", 0) for f in dup_files)),
            dup_groups_count=len(dup_files)
        )
        QMessageBox.information(
            self,
            "收拢与沉淀成功",
            f"✅ 已成功将目录 [{target_dir}] 下的内容就地收拢为新集合 [{app_name}]！\n全景资产明细已全量联动刷新，规则已永久沉淀。"
        )

    def on_scan_error(self, err_msg: str):
        self.on_scan_stopped()
        if self.scan_task_id:
            global_task_manager.set_task_status(self.scan_task_id, TaskStatus.FAILED, err_msg)
        QMessageBox.critical(self, "扫描异常", f"扫描过程中发生错误: {err_msg}")

    def on_scan_stopped(self):
        self.start_scan_btn.setEnabled(True)
        self.pause_scan_btn.setEnabled(False)
        self.pause_scan_btn.setText("⏸️ 暂停")
        self.stop_scan_btn.setEnabled(False)
        self.progress_bar.setVisible(False)

    def on_redundant_selection_changed(self, count: object, total_bytes: object):
        table = self.get_active_table()
        checked_paths = table.get_checked_paths()
        c_sel = 0
        for item in table.source_model._data:
            if item.get("path") in checked_paths and item.get("is_directory_collective"):
                c_sel += 1
        f_sel = len(checked_paths) - c_sel
        if c_sel > 0:
            self.selection_stat_label.setText(
                f"已选中: {len(checked_paths)} 个资产项 (含 {c_sel} 集体, {f_sel} 独立单项) | 容量: {format_size(int(total_bytes))}"
            )
        else:
            self.selection_stat_label.setText(
                f"已选中: {len(checked_paths)} 个独立单项资产 | 容量: {format_size(int(total_bytes))}"
            )

    def open_migration_dialog_for_paths(self, paths: List[str]):
        if not paths:
            return
        dlg = MigrationDialog(selected_paths=paths, parent=self)
        if dlg.exec():
            self.global_detail_table.remove_paths(paths)
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
        """
        📌 仅选推荐：
        遵循「AI 为核心编排器架构」原则：
        1. 优先以 AI 创作的结构化执行清单 (ai_execution_plan) 为最高准则，直接落地入轨；
        2. 若尚无 AI 执行清单，则以本地安全启发式打标为兜底，直接勾选推荐项；
        3. 作用于当前活跃表格，并即时联动更新底部统计栏与状态反馈，0 延迟、0 阻塞。
        """
        table = self.get_active_table()
        if not table or table.source_model.rowCount() == 0:
            if not self.current_scan_result or (
                not self.current_scan_result.get("all_scanned_files") and
                not self.current_scan_result.get("redundant_files")
            ):
                QMessageBox.warning(self, "提示", "请先完成一次有效扫描！")
                return
            QMessageBox.information(self, "提示", "当前查看的表格中暂无资产项！")
            return

        # 优先从 current_scan_result 中获取已生成的 AI 执行清单
        ai_plan = (self.current_scan_result or {}).get("ai_execution_plan", [])

        # 在当前活跃表格中执行安全推荐勾选 (支持 AI 执行清单 + 本地安全兜底)
        checked_count = table.select_recommended_only(ai_plan=ai_plan)

        # 联动刷新底部选中统计栏与全局标签
        self.on_redundant_selection_changed(
            len(table.source_model.checked_paths),
            table.source_model.checked_bytes
        )

        # 即时反馈
        if checked_count > 0:
            bytes_str = format_size(table.source_model.checked_bytes)
            self.phase_label.setText(f"📌 仅选推荐: 已勾选 {checked_count} 项安全资产 (共 {bytes_str})")
        else:
            self.phase_label.setText("📌 仅选推荐: 当前表格未发现符合安全推荐的资产项")
            QMessageBox.information(
                self, "智能推荐",
                "当前列表中未发现可安全释放的推荐项（或推荐项已被勾选）。\n可切换至「🔄 重复资产明细」或「🗑️ 可释放资产明细」查看推荐资产。"
            )

    def on_ai_recommend_done(self, recommended_items: List[Any]):
        self.btn_select_rec.setEnabled(True)
        self.phase_label.setText("AI 智能分析完成")
        if getattr(self, "ai_task_id", None):
            global_task_manager.set_task_status(self.ai_task_id, TaskStatus.COMPLETED)
            self.ai_task_id = None
        if recommended_items:
            # Normalize to list of dicts if they are strings (legacy fallback)
            if isinstance(recommended_items[0], str):
                recommended_items = [{"path": p, "risk_level": "未知", "confidence": 1.0, "reason": "遗留格式"} for p in recommended_items]
                
            # Filter strict rules
            safe_items = []
            unsafe_count = 0
            risk_stats = {"低风险": 0, "中风险": 0, "高风险": 0, "未知": 0}
            reasons = {}
            
            for item in recommended_items:
                risk = item.get("risk_level", "未知")
                if "低" in risk: risk_stats["低风险"] += 1
                elif "中" in risk: risk_stats["中风险"] += 1
                elif "高" in risk: risk_stats["高风险"] += 1
                else: risk_stats["未知"] += 1
                
                conf = float(item.get("confidence", 0.0))
                path = item.get("path", "").lower()
                
                is_system = any(sys_dir in path for sys_dir in ["windows", "program files", "programdata", "appdata", "system32"])
                
                reject_reason = []
                if "低风险" not in risk: reject_reason.append(f"非低风险({risk})")
                if conf < 0.75: reject_reason.append(f"置信度低({conf})")
                if is_system: reject_reason.append("涉及系统敏感目录")
                
                if not reject_reason:
                    safe_items.append(item)
                else:
                    unsafe_count += 1
                    r = " | ".join(reject_reason)
                    reasons[r] = reasons.get(r, 0) + 1
                    
            safe_paths = [i["path"] for i in safe_items]
            
            self.global_detail_table.select_ai_recommended_paths(safe_paths)
            self.duplicate_table.select_ai_recommended_paths(safe_paths)
            self.releasable_table.select_ai_recommended_paths(safe_paths)
            self.top100_table.select_ai_recommended_paths(safe_paths)
            
            msg = f"大模型智能甄别已完成！\\n\\n"
            msg += f"✅ 自动勾选 (安全/低风险): {len(safe_paths)} 项\\n"
            msg += f"⏸️ 拦截不选 (中高风险/系统): {unsafe_count} 项\\n"
            msg += f"📊 风险分布: 低 {risk_stats['低风险']} | 中 {risk_stats['中风险']} | 高 {risk_stats['高风险']} | 未知 {risk_stats['未知']}\\n"
            if reasons:
                msg += f"\\n未自动勾选的主要原因:\\n"
                for r, c in list(reasons.items())[:3]:
                    msg += f" - {r}: {c} 项\\n"
                    
            msg += "\\n(注: 未执行任何删除/归档，您可继续在列表中修改勾选)"
            QMessageBox.information(self, "AI 推荐就绪与拦截报告", msg)
        else:
            self.global_detail_table.select_recommended_only()
            self.duplicate_table.select_recommended_only()
            self.releasable_table.select_recommended_only()
            self.top100_table.select_recommended_only()
            QMessageBox.information(self, "智能推荐", "已根据本地安全启发式规则完成推荐勾选！")


    def trigger_ai_auto_process(self):
        """AI 自动处理：读取深度分析报告，让大模型根据报告建议生成执行清单"""
        if not self.current_scan_result:
            QMessageBox.warning(self, "提示", "请先完成一次有效扫描！")
            return

        report_content = self.report_text_edit.toPlainText().strip()
        if not report_content or not report_content.startswith("✅ 分析成功"):
            QMessageBox.warning(self, "提示", "当前没有有效的 AI 深度分析报告！请先在报告面板等待分析完成或重试。")
            return

        # Check task ID linkage
        scan_id = self.current_scan_result.get('task_id', 'Unknown')
        if f"扫描任务ID: {scan_id}" not in report_content:
            QMessageBox.warning(self, "提示", "当前显示的报告与最近一次扫描任务不匹配，请重新生成报告。")
            return

        # Export report to .md
        import uuid
        report_id = str(uuid.uuid4())[:8]
        report_filename = f"AI深度分析报告_{report_id}.md"
        export_dir = Path("D:/归档备份") if Path("D:/").exists() else Path.home() / "DiskAnalyzerArchive"
        export_path = export_dir / report_filename
        
        try:
            export_path.parent.mkdir(parents=True, exist_ok=True)
            with open(export_path, "w", encoding="utf-8") as f:
                f.write(report_content)
        except Exception as e:
            QMessageBox.critical(self, "报告导出失败", f"无法导出 Markdown 报告: {e}")
            return
            
        dest_root = self.archive_input.text().strip() or "D:/归档备份"

        # 核心直通优化：若当前已有 AI 执行清单，直接本地秒开预览对话框，杜绝二次大模型调用
        existing_plan = self.current_scan_result.get("ai_execution_plan")
        if existing_plan:
            from app.core.ai_service import AIService
            classified_results = AIService.convert_execution_plan_to_groups(existing_plan, dest_root)
            for g in classified_results:
                g["report_id"] = report_id
                g["task_id"] = scan_id

            dlg = OrganizePreviewDialog(
                classification_items=classified_results,
                destination_root=dest_root,
                parent=self
            )
            if dlg.exec():
                summary = getattr(dlg, 'last_summary', {})
                processed_paths = [
                    item["original_path"] 
                    for item in summary.get("items", []) 
                    if "original_path" in item
                ]
                if processed_paths:
                    self.global_detail_table.remove_paths(processed_paths)
                    self.duplicate_table.remove_paths(processed_paths)
                    self.releasable_table.remove_paths(processed_paths)
                    self.top100_table.remove_paths(processed_paths)
            return

        self.btn_ai_auto.setEnabled(False)
        self.phase_label.setText(f"🤖 正在提交报告 (ID: {report_id}) 给 AI 提取执行计划...")

        self.ai_worker = AIWorker("process_report", {"report_path": str(export_path), "report_id": report_id, "scan_id": scan_id, "dest_root": dest_root})
        self.ai_task_id = global_task_manager.create_task("AI 提取执行计划", TaskType.AI_ANALYSIS, self.ai_worker).task_id
        
        def on_process_report_done(classified_results):
            # 注入报告关联信息
            for g in classified_results:
                g["report_id"] = report_id
                g["task_id"] = scan_id
                
            self.btn_ai_auto.setEnabled(True)
            self.phase_label.setText("AI 智能规划已就绪")
            if getattr(self, "ai_task_id", None):
                global_task_manager.set_task_status(self.ai_task_id, TaskStatus.COMPLETED)
                self.ai_task_id = None
            dlg = OrganizePreviewDialog(
                classification_items=classified_results,
                destination_root=dest_root,
                parent=self
            )
            if dlg.exec():
                summary = getattr(dlg, 'last_summary', {})
                processed_paths = [
                    item["original_path"] 
                    for item in summary.get("items", []) 
                    if "original_path" in item
                ]
                if processed_paths:
                    self.global_detail_table.remove_paths(processed_paths)
                    self.duplicate_table.remove_paths(processed_paths)
                    self.releasable_table.remove_paths(processed_paths)
                    self.top100_table.remove_paths(processed_paths)

        def on_process_failed(err):
            self.btn_ai_auto.setEnabled(True)
            self.phase_label.setText("AI 提取执行计划失败")
            if getattr(self, "ai_task_id", None):
                global_task_manager.set_task_status(self.ai_task_id, TaskStatus.FAILED, str(err))
                self.ai_task_id = None
            QMessageBox.critical(self, "提取失败", f"AI 读取报告并生成执行清单失败:\n{err}")
                
        self.ai_worker.classify_done.connect(on_process_report_done)
        self.ai_worker.failed.connect(on_process_failed)
        self.ai_worker.start()

    def generate_ai_report(self, auto_triggered=False, force=False):
        if not self.current_scan_result:
            if not auto_triggered:
                QMessageBox.warning(self, "提示", "请先执行扫描！")
            return

        # 隐藏决策横幅并更新标签页状态
        self.ai_decision_banner.hide()
        report_idx = self.tabs.indexOf(self.report_widget)
        if report_idx >= 0:
            self.tabs.setTabText(report_idx, "📑 AI 深度分析报告预览 (分析中...)")
            self.tabs.setCurrentIndex(report_idx)

        # Check AI config
        llm_cfg = app_config.get("llm", default={})
        if not (llm_cfg.get("api_key") and llm_cfg.get("base_url") and llm_cfg.get("model")):
            self.report_text_edit.setPlainText("⚠️ AI 不可用\n\n大模型未正确配置，无法自动生成深度分析报告。\n请在设置中配置 API Key 后，点击上方“重新生成 AI 深度分析报告”进行重试。")
            return

        self.gen_ai_report_btn.setEnabled(False)
        self.pause_ai_report_btn.setEnabled(True)
        self.pause_ai_report_btn.setText("⏸️ 暂停")
        self.stop_ai_report_btn.setEnabled(True)

        self.report_text_edit.setPlainText("🤖 分析中: 正在调用 AI 核心编排器生成全景深度分析与治理报告，请稍候...")

        # 本地抛出缩紧精准：建立 5 类核心高价值资产前置过滤管道 (max 25 项，碎文件 0-Token 阻断)
        scan_copy = dict(self.current_scan_result)
        raw_redundant = scan_copy.get("redundant_files", [])
        if raw_redundant:
            scan_copy["redundant_files"] = AIService.filter_high_value_assets_for_ai(raw_redundant, max_items=25)
        self.ai_worker = AIWorker("report", scan_copy)
        self.ai_task_id = global_task_manager.create_task("生成深度分析报告", TaskType.AI_ANALYSIS, self.ai_worker).task_id
        self.ai_worker.report_done.connect(self.on_ai_report_done)
        self.ai_worker.failed.connect(self.on_ai_failed)
        self.ai_worker.phase_changed.connect(self.on_ai_phase_changed)
        self.ai_worker.start()

    def on_ai_phase_changed(self, phase_name: str):
        self.report_text_edit.setPlainText(f"🤖 分析中: {phase_name}")
        if getattr(self, "ai_task_id", None):
            global_task_manager.update_task_progress(self.ai_task_id, phase=phase_name)

    def on_ai_report_done(self, ai_response):
        self.gen_ai_report_btn.setEnabled(True)
        self.pause_ai_report_btn.setEnabled(False)
        self.stop_ai_report_btn.setEnabled(False)
        if getattr(self, "ai_task_id", None):
            global_task_manager.set_task_status(self.ai_task_id, TaskStatus.COMPLETED)
            self.ai_task_id = None
        # 添加任务关联信息
        scan_id = self.current_scan_result.get('task_id', 'Unknown')
        
        # 把 report_id 保存到 scan_result 里
        self.current_scan_result['report_id'] = ai_response.report_id
        
        report_text = f"✅ 分析成功\n扫描任务ID: {scan_id}\n生成时间: {self.current_scan_result.get('timestamp', 'N/A')}\n报告ID: {ai_response.report_id}\n分析模型: {ai_response.model}\n\n" + ai_response.final_text
        self.report_text_edit.setPlainText(report_text)
        
        # 更新图表
        if ai_response.structured_data and "chart_categories" in ai_response.structured_data:
            cat_list = ai_response.structured_data["chart_categories"]
            cat_stats = { item["category"]: {"bytes": item["bytes"], "percent": item.get("percent", 0.0)} for item in cat_list }
            self.chart_widget.update_chart(cat_stats)

        # 核心融合：直接接收 AI 创作的结构化执行清单，全量灌入全景表格
        exec_plan = (ai_response.structured_data or {}).get("execution_plan", [])
        if not exec_plan:
            from app.core.ai_service import AIService
            exec_plan = AIService.parse_markdown_table_to_execution_plan(ai_response.final_text or "")

        if exec_plan:
            self.current_scan_result["ai_execution_plan"] = exec_plan
            g_hits = self.global_detail_table.apply_ai_execution_plan(exec_plan)
            d_hits = self.duplicate_table.apply_ai_execution_plan(exec_plan)
            r_hits = self.releasable_table.apply_ai_execution_plan(exec_plan)
            t_hits = self.top100_table.apply_ai_execution_plan(exec_plan)
            app_logger.info(f"[HomeView] 成功将 AI 创作清单 ({len(exec_plan)} 项) 直灌全域表格 (全局命中 {g_hits}, 可释放命中 {r_hits})")
        
        from app.core.events import event_bus
        event_bus.publish_report_updated(ai_response.report_id, scan_id)
            
        # 准确定位并切换至 AI 深度分析报告选项卡 (同时带徽标提示)
        report_idx = self.tabs.indexOf(self.report_widget)
        if report_idx >= 0:
            self.tabs.setTabText(report_idx, "📑 AI 深度分析报告预览 (已生成)")
            self.tabs.setCurrentIndex(report_idx)
        else:
            self.tabs.setCurrentIndex(self.tabs.count() - 1)

    def on_ai_failed(self, err: str):
        self.btn_select_rec.setEnabled(True)
        self.gen_ai_report_btn.setEnabled(True)
        self.pause_ai_report_btn.setEnabled(False)
        self.stop_ai_report_btn.setEnabled(False)
        self.phase_label.setText("AI 请求异常")
        if getattr(self, "ai_task_id", None):
            global_task_manager.set_task_status(self.ai_task_id, TaskStatus.FAILED, str(err))
            self.ai_task_id = None

        if err == "已手动停止任务":
            self.report_text_edit.setPlainText("⏹️ 已手动停止 AI 生成任务。")
            self.ai_decision_banner.hide()
            return

        # 恪守 AI 核心编排架构：不因超时直接越权，向用户呈现决策选项由用户定夺
        self.decision_title_lbl.setText("AI 深度分析报告请求超时或异常")
        self.decision_sub_lbl.setText(f"原因: {err}。系统恪守 AI 为核心编排架构，绝不自作主张以本地离线兜底越权替代 AI 输出。")
        self.btn_decision_organize.setVisible(True)
        self.btn_decision_force_ai.setVisible(False)
        self.btn_decision_retry_ai.setVisible(True)
        self.btn_decision_load_fallback.setVisible(True)
        self.ai_decision_banner.show()

        report_idx = self.tabs.indexOf(self.report_widget)
        if report_idx >= 0:
            self.tabs.setTabText(report_idx, "📑 AI 深度分析报告 (调用未完成)")
            self.tabs.setCurrentIndex(report_idx)

        err_md = (
            f"# ⚠️ AI 大模型深度分析调用未完成\n\n"
            f"> **异常详情**：`{err}`\n\n"
            f"**架构契约保障**：本系统严格恪守 **「AI 为核心编排器架构」** 原则，**严禁在超时或异常时直接越权**使用离线规则静默覆盖。\n\n"
            f"### 🛠️ 请由您决定后续治理路径：\n\n"
            f"1. **【🔄 重试 AI 总结】**：网络抖动或大模型排队可能导致偶发超时，点击可重新向大模型发起深度分析；\n"
            f"2. **【📑 载入本地专家应急报告】**：若当前无可用网络或模型服务暂不可用，可由您明确授权临时载入本地专家引擎分析；\n"
            f"3. **【📁 运行文件整理】**：若散落资产过多，可先前往整理页面收拢聚合后再行分析。\n\n"
            f"*请点击上方横幅按钮执行相应操作。*"
        )
        self.report_text_edit.setPlainText(err_md)

    def load_local_expert_fallback(self):
        """由用户明确授权载入本地专家应急报告，绝不自作主张越权替代"""
        if not self.current_scan_result:
            return
        try:
            fallback_md = AIService._generate_fallback_report(self.current_scan_result)
            notice = (
                "> 💡 **用户授权提示**：已根据您的选择，载入**本地智能专家离线分析引擎**生成的数据全景报告与推荐清单。\n"
                "> （注：本报告由本地专家引擎根据启发式规则生成，AI 核心模型未参与本次推演）。\n\n"
            )
            full_md = notice + fallback_md
            self.report_text_edit.setPlainText(full_md)
            exec_plan = AIService.parse_markdown_table_to_execution_plan(fallback_md) or AIService._generate_fallback_execution_plan(self.current_scan_result)
            if exec_plan:
                self.current_scan_result["ai_execution_plan"] = exec_plan
                self.global_detail_table.apply_ai_execution_plan(exec_plan)
                self.duplicate_table.apply_ai_execution_plan(exec_plan)
                self.releasable_table.apply_ai_execution_plan(exec_plan)
                self.top100_table.apply_ai_execution_plan(exec_plan)
            self.ai_decision_banner.hide()
            report_idx = self.tabs.indexOf(self.report_widget)
            if report_idx >= 0:
                self.tabs.setTabText(report_idx, "📑 AI 深度分析报告预览 (本地专家已载入)")
                self.tabs.setCurrentIndex(report_idx)
        except Exception as ex:
            app_logger.error(f"载入本地专家应急报告失败: {ex}")
            QMessageBox.warning(self, "错误", f"载入本地应急报告失败: {ex}")

    def navigate_to_organizer_page(self):
        """跳转至文件整理页面，复用现有 OrganizerView，切忌重写脚本"""
        target_dir = ""
        if self.current_scan_result and self.current_scan_result.get("target_paths"):
            paths = self.current_scan_result.get("target_paths", [])
            if paths:
                target_dir = paths[0]
        if not target_dir:
            targets = self.get_selected_targets()
            if targets:
                target_dir = targets[0]

        self.navigate_to_organizer.emit(target_dir)

        # 遍历父级寻找 switch_view 兜底
        p = self.parent()
        while p:
            if hasattr(p, "switch_view"):
                if hasattr(p, "organizer_view") and target_dir and os.path.exists(target_dir):
                    p.organizer_view.dir_input.setText(target_dir)
                p.switch_view(1)
                break
            p = p.parent()

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
            f"即将把 {len(checked_paths)} 个勾选资产单元移入后台归档队列至:\n{archive_dir}\n\n"
            "归档将在后台多线程执行，界面将保持流畅无卡顿。是否立即启动？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        # 从当前活动表格中获取勾选项的完整元数据（包含 AI 赋权的 category 与 target_subpath）
        model_data_map = {item.get("path"): item for item in table.source_model._data if item.get("path")}
        file_items = []
        for p in checked_paths:
            m_item = model_data_map.get(p, {})
            cat = m_item.get("category")
            sub = m_item.get("target_subpath")
            f_entry = {"path": p}
            if cat:
                f_entry["target_category"] = f"{cat}/{sub}" if sub else cat
            file_items.append(f_entry)

        report_id = self.current_scan_result.get('report_id', '') if self.current_scan_result else ''
        scan_id = self.current_scan_result.get('task_id', '') if self.current_scan_result else ''
        self.archive_worker = ArchiveWorker(
            file_items=file_items,
            destination_root=archive_dir,
            conflict_policy="auto_rename",
            preserve_structure=True,
            report_id=report_id,
            scan_task_id=scan_id
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
        
        # 从四张表格中同步安全移除
        migrated = [item["original_path"] for item in summary.get("items", []) if "original_path" in item]
        if migrated:
            self.global_detail_table.remove_paths(migrated)
            self.duplicate_table.remove_paths(migrated)
            self.releasable_table.remove_paths(migrated)
            self.top100_table.remove_paths(migrated)

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
            QMessageBox.warning(self, "提示", "您尚未勾选任何需要清理的文件或实体！")
            return

        reply = QMessageBox.question(
            self, "确认清理",
            f"您已选择清理 {len(checked_paths)} 个资产项。\n\n"
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
            self.global_detail_table.remove_paths(checked_paths)
            self.duplicate_table.remove_paths(checked_paths)
            self.releasable_table.remove_paths(checked_paths)
            self.top100_table.remove_paths(checked_paths)
            QMessageBox.information(self, "清理完成", f"已成功清理 {summary['success_count']} 个资产项！")
            
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

    def on_global_files_changed(self, event_type: str, processed_paths: list, task_id: str, payload: dict):
        if not self.current_scan_result:
            return
            
        processed_set = set(processed_paths)
        redundant_files = self.current_scan_result.get("redundant_files", [])
        top100_files = self.current_scan_result.get("top_100_files", [])
        
        if "history_removed_files" not in self.current_scan_result:
            self.current_scan_result["history_removed_files"] = {}
        if "history_removed_top100" not in self.current_scan_result:
            self.current_scan_result["history_removed_top100"] = {}
            
        history_map = self.current_scan_result["history_removed_files"]
        history_top100_map = self.current_scan_result["history_removed_top100"]
        
        changed_count = 0
        changed_bytes = 0
        changed_dup_bytes = 0
        
        if event_type == "rollbacked":
            restored_files = []
            restored_top100 = []
            for path in processed_paths:
                if path in history_map:
                    f = history_map.pop(path)
                    redundant_files.append(f)
                    restored_files.append(f)
                    
                    changed_count += 1
                    changed_bytes += f.get("size", 0)
                    if f.get("is_duplicate"):
                        changed_dup_bytes += f.get("size", 0)
                
                if path in history_top100_map:
                    f_top = history_top100_map.pop(path)
                    top100_files.append(f_top)
                    restored_top100.append(f_top)
                        
            if changed_count == 0 and not restored_top100:
                return
                
            self.current_scan_result["total_files"] = self.current_scan_result.get("total_files", 0) + changed_count
            self.current_scan_result["total_bytes"] = self.current_scan_result.get("total_bytes", 0) + changed_bytes
            
            reclaimable_diff = changed_bytes - changed_dup_bytes
            self.current_scan_result["reclaimable_bytes"] = self.current_scan_result.get("reclaimable_bytes", 0) + reclaimable_diff
            self.current_scan_result["duplicate_wasted_bytes"] = self.current_scan_result.get("duplicate_wasted_bytes", 0) + changed_dup_bytes
            
            dup_to_add = [f for f in restored_files if f.get("is_duplicate")]
            rel_to_add = [f for f in restored_files if not f.get("is_duplicate")]
            
            if dup_to_add:
                self.duplicate_table.add_data(dup_to_add)
            if rel_to_add:
                self.releasable_table.add_data(rel_to_add)
            if restored_top100:
                # 重新排序并恢复
                top100_files.sort(key=lambda x: x.get("size", 0), reverse=True)
                self.current_scan_result["top_100_files"] = top100_files[:100]
                self.top100_table.populate_data(self.current_scan_result["top_100_files"], self.current_scan_result["total_bytes"])
                
            action_name = "回滚并恢复显示"
        else:
            new_redundant = []
            for f in redundant_files:
                if f.get("path") in processed_set:
                    history_map[f.get("path")] = f
                    changed_count += 1
                    changed_bytes += f.get("size", 0)
                    if f.get("is_duplicate"):
                        changed_dup_bytes += f.get("size", 0)
                else:
                    new_redundant.append(f)
                    
            new_top100 = []
            for f in top100_files:
                if f.get("path") in processed_set:
                    history_top100_map[f.get("path")] = f
                else:
                    new_top100.append(f)
                    
            if changed_count == 0 and len(new_top100) == len(top100_files):
                return
                
            self.current_scan_result["redundant_files"] = new_redundant
            self.current_scan_result["top_100_files"] = new_top100
            
            self.current_scan_result["total_files"] = max(0, self.current_scan_result.get("total_files", 0) - changed_count)
            self.current_scan_result["total_bytes"] = max(0, self.current_scan_result.get("total_bytes", 0) - changed_bytes)
            
            reclaimable_diff = changed_bytes - changed_dup_bytes
            self.current_scan_result["reclaimable_bytes"] = max(0, self.current_scan_result.get("reclaimable_bytes", 0) - reclaimable_diff)
            self.current_scan_result["duplicate_wasted_bytes"] = max(0, self.current_scan_result.get("duplicate_wasted_bytes", 0) - changed_dup_bytes)
            
            self.duplicate_table.remove_paths(processed_paths)
            self.releasable_table.remove_paths(processed_paths)
            self.top100_table.remove_paths(processed_paths)
            
            action_name = {"archived": "归档", "deleted": "清理", "migrated": "迁移"}.get(event_type, event_type)
            
        self.stat_cards.update_stats(
            total_bytes_str=format_size(self.current_scan_result["total_bytes"]),
            reclaimable_str=format_size(self.current_scan_result["reclaimable_bytes"]),
            files_count_str=f"{self.current_scan_result['total_files']:,} 个",
            dup_waste_str=format_size(self.current_scan_result["duplicate_wasted_bytes"]),
            dup_groups_count=self.current_scan_result.get("duplicate_groups_count", 0)
        )
        self.selection_stat_label.setText(f"增量刷新: {changed_count} 个文件已{action_name}")

    def on_global_report_updated(self, report_id: str, scan_task_id: str):
        pass
