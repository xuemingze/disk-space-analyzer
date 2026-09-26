import os
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QScrollArea, QFrame, QGroupBox,
    QSlider, QComboBox, QMessageBox, QCheckBox, QSpinBox, QFormLayout
)
from PySide6.QtCore import Qt

from app.config import app_config
from app.core.ai_service import AIService
from app.core.task_manager import global_task_manager, TaskType, TaskStatus
from app.ui.components.organize_dialog import OrganizePreviewDialog
from app.ui.home_view import AIWorker
from app.core.scanner import DirectoryScanTask


class OrganizerView(QWidget):
    """
    智能文件整理与归档管理页 (支持以 App / 工具链为原子单元的树状目录整理规划)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_dir = str(Path.home() / "Downloads")
        self.scan_task: Optional[DirectoryScanTask] = None
        self.ai_worker: Optional[AIWorker] = None
        self.scan_task_id: Optional[str] = None
        self.ai_task_id: Optional[str] = None

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        title_lbl = QLabel("🤖 目录级 AI 分类与整理规划中心")
        title_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #38BDF8;")
        main_layout.addWidget(title_lbl)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(16)

        # 1. 路径设置
        path_group = QGroupBox("📁 路径设置")
        path_layout = QFormLayout(path_group)
        
        self.dir_input = QLineEdit(self.current_dir)
        btn_browse_src = QPushButton("浏览...")
        btn_browse_src.clicked.connect(self.browse_source)
        src_row = QHBoxLayout()
        src_row.addWidget(self.dir_input)
        src_row.addWidget(btn_browse_src)
        path_layout.addRow("整理根目录:", src_row)

        self.dest_input = QLineEdit(app_config.get("archive_dir", default="D:/归档备份"))
        btn_browse_dest = QPushButton("浏览...")
        btn_browse_dest.clicked.connect(self.browse_dest)
        dest_row = QHBoxLayout()
        dest_row.addWidget(self.dest_input)
        dest_row.addWidget(btn_browse_dest)
        path_layout.addRow("归档目标根目录:", dest_row)
        
        content_layout.addWidget(path_group)

        # 2. 偏好设置
        pref_group = QGroupBox("⚙️ 分类与偏好设置")
        pref_layout = QFormLayout(pref_group)
        
        from app.ui.components.category_dialog import CategoryManagerDialog
        self.btn_manage_categories = QPushButton("📂 管理全局自定义分类...")
        self.btn_manage_categories.clicked.connect(lambda: CategoryManagerDialog(self).exec())
        pref_layout.addRow("", self.btn_manage_categories)
        
        # 场景偏好
        self.work_personal_slider = QSlider(Qt.Horizontal)
        self.work_personal_slider.setRange(0, 100)
        self.work_personal_slider.setValue(app_config.get("org_work_weight", default=60))
        self.lbl_work_slider = QLabel(f"工作类 {self.work_personal_slider.value()}% / 私人类 {100 - self.work_personal_slider.value()}%")
        self.work_personal_slider.valueChanged.connect(lambda v: self.lbl_work_slider.setText(f"工作类 {v}% / 私人类 {100 - v}%"))
        slider_row = QHBoxLayout()
        slider_row.addWidget(self.work_personal_slider)
        slider_row.addWidget(self.lbl_work_slider)
        pref_layout.addRow("场景分类比重:", slider_row)

        # 未知目录处理方式
        self.unknown_combo = QComboBox()
        self.unknown_combo.addItems(["转入人工确认 (安全)", "放入归档杂项", "忽略并跳过"])
        self.unknown_combo.setCurrentIndex(app_config.get("org_unknown_policy", default=0))
        pref_layout.addRow("未知目录处理:", self.unknown_combo)

        # 冲突处理
        self.conflict_combo = QComboBox()
        self.conflict_combo.addItems(["自动重命名 (推荐)", "跳过", "覆盖"])
        self.conflict_combo.setCurrentIndex(app_config.get("org_conflict_policy", default=0))
        pref_layout.addRow("文件冲突策略:", self.conflict_combo)
        
        # 跨磁盘移动
        self.chk_execute = QCheckBox("允许直接执行文件移动 (不勾选则仅生成离线批处理脚本)")
        self.chk_execute.setChecked(app_config.get("org_allow_execute", default=False))
        pref_layout.addRow("执行安全策略:", self.chk_execute)

        self.chk_cross_disk = QCheckBox("允许跨磁盘移动 (物理剪切)")
        self.chk_cross_disk.setChecked(app_config.get("org_cross_disk", default=True))
        pref_layout.addRow("磁盘策略:", self.chk_cross_disk)
        
        # 最低置信度
        self.spin_conf = QSpinBox()
        self.spin_conf.setRange(50, 100)
        self.spin_conf.setValue(app_config.get("org_min_conf", default=75))
        self.spin_conf.setSuffix("%")
        pref_layout.addRow("自动勾选最低置信度:", self.spin_conf)

        # 高风险处理
        self.high_risk_combo = QComboBox()
        self.high_risk_combo.addItems(["强制拦截屏蔽 (最安全)", "允许人工强行解锁"])
        self.high_risk_combo.setCurrentIndex(app_config.get("org_high_risk_policy", default=0))
        pref_layout.addRow("高风险目录策略:", self.high_risk_combo)

        content_layout.addWidget(pref_group)
        content_layout.addStretch()
        
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)

        # 3. 底部执行栏
        bottom_bar = QFrame()
        bottom_bar.setProperty("class", "CardFrame")
        bottom_layout = QHBoxLayout(bottom_bar)
        
        self.lbl_status = QLabel("就绪")
        self.lbl_status.setStyleSheet("color: #94A3B8;")
        bottom_layout.addWidget(self.lbl_status)
        bottom_layout.addStretch()

        self.btn_run = QPushButton("🚀 启动全景目录扫描与 AI 规划")
        self.btn_run.setStyleSheet("background-color: #059669; border-color: #10B981; font-weight: bold; padding: 10px 20px; font-size: 14px;")
        self.btn_run.clicked.connect(self.start_ai_planning)
        bottom_layout.addWidget(self.btn_run)

        main_layout.addWidget(bottom_bar)

    def browse_source(self):
        d = QFileDialog.getExistingDirectory(self, "选择整理根目录", self.dir_input.text())
        if d: self.dir_input.setText(d)

    def browse_dest(self):
        d = QFileDialog.getExistingDirectory(self, "选择归档目标", self.dest_input.text())
        if d: self.dest_input.setText(d)

    def save_prefs(self):
        app_config.set("archive_dir", self.dest_input.text().strip())
        app_config.set("org_work_weight", self.work_personal_slider.value())
        app_config.set("org_unknown_policy", self.unknown_combo.currentIndex())
        app_config.set("org_conflict_policy", self.conflict_combo.currentIndex())
        app_config.set("org_cross_disk", self.chk_cross_disk.isChecked())
        app_config.set("org_allow_execute", self.chk_execute.isChecked())
        app_config.set("org_min_conf", self.spin_conf.value())
        app_config.set("org_high_risk_policy", self.high_risk_combo.currentIndex())

    def start_ai_planning(self):
        src = self.dir_input.text().strip()
        dest = self.dest_input.text().strip()
        if not os.path.isdir(src):
            QMessageBox.warning(self, "错误", "整理根目录无效！")
            return
        if not dest:
            QMessageBox.warning(self, "错误", "目标归档目录不能为空！")
            return

        self.save_prefs()
        self.btn_run.setEnabled(False)
        self.lbl_status.setText("🔍 阶段 1: 正在递归扫描目录结构...")

        # 1. Start Directory Scan
        self.scan_task = DirectoryScanTask([src], True, False, [])
        self.scan_task_id = global_task_manager.create_task("目录层级扫描", TaskType.SCAN, self.scan_task).task_id
        
        # We need to map signals from QRunnable, but DirectoryScanTask is QRunnable, it communicates via EventBus or we wrap it in a QObject.
        # Actually in scanner.py, BaseScanTask inherits QObject and QRunnable! So it has signals.
        self.scan_task.finished_ok.connect(self.on_scan_completed)
        self.scan_task.error.connect(self.on_scan_error)
        
        # DirectoryScanTask inherits from QThread (via BaseScanTask)
        self.scan_task.start()

    def on_scan_error(self, err: str):
        self.btn_run.setEnabled(True)
        self.lbl_status.setText(f"❌ 扫描失败: {err}")
        if getattr(self, "scan_task_id", None):
            global_task_manager.set_task_status(self.scan_task_id, TaskStatus.FAILED, err)
            self.last_scan_task_id = self.scan_task_id
            self.scan_task_id = None

    def on_scan_completed(self, result: dict):
        if getattr(self, "scan_task_id", None):
            global_task_manager.set_task_status(self.scan_task_id, TaskStatus.COMPLETED)
            self.last_scan_task_id = self.scan_task_id
            self.scan_task_id = None

        all_scanned_files = result.get("all_scanned_files", [])
        if not all_scanned_files:
            self.btn_run.setEnabled(True)
            self.lbl_status.setText("就绪")
            QMessageBox.information(self, "提示", "未扫描到任何文件。")
            return

        self.lbl_status.setText("🤖 阶段 2: 正在提交目录级报告至 AI 进行规划...")
        
        # Pass preferences to AI via kwargs
        prefs = {
            "work_ratio": self.work_personal_slider.value() / 100.0,
            "personal_ratio": (100 - self.work_personal_slider.value()) / 100.0,
            "min_conf": self.spin_conf.value() / 100.0,
            "conflict_policy": "auto_rename" if self.conflict_combo.currentIndex() == 0 else ("skip" if self.conflict_combo.currentIndex() == 1 else "overwrite")
        }

        self.ai_worker = AIWorker("classify", all_scanned_files, destination_root=self.dest_input.text().strip(), prefs=prefs)
        self.ai_task_id = global_task_manager.create_task("AI 目录级归档规划", TaskType.AI_ANALYSIS, self.ai_worker).task_id
        self.ai_worker.classify_done.connect(self.on_ai_classify_done)
        self.ai_worker.failed.connect(self.on_ai_error)
        
        # Optional progress updates
        if hasattr(self.ai_worker, "phase_changed"):
            self.ai_worker.phase_changed.connect(lambda p: self.lbl_status.setText(f"🤖 阶段 2: {p}"))
            
        self.ai_worker.start()

    def on_ai_error(self, err: str):
        self.btn_run.setEnabled(True)
        self.lbl_status.setText(f"❌ AI 规划失败: {err}")
        if getattr(self, "ai_task_id", None):
            global_task_manager.set_task_status(self.ai_task_id, TaskStatus.FAILED, err)
            self.ai_task_id = None

    def on_ai_classify_done(self, classified_groups: List[Dict[str, Any]]):
        self.btn_run.setEnabled(True)
        self.lbl_status.setText("✅ AI 规划已就绪等待确认")
        if getattr(self, "ai_task_id", None):
            global_task_manager.set_task_status(self.ai_task_id, TaskStatus.COMPLETED)
            self.last_ai_task_id = self.ai_task_id
            self.ai_task_id = None
            
        for g in classified_groups:
            g["task_id"] = getattr(self, "last_scan_task_id", "")
            g["report_id"] = getattr(self, "last_ai_task_id", "")


        dest_root = self.dest_input.text().strip()
        conflict = "auto_rename" if self.conflict_combo.currentIndex() == 0 else ("skip" if self.conflict_combo.currentIndex() == 1 else "overwrite")

        dlg = OrganizePreviewDialog(
            classification_items=classified_groups,
            destination_root=dest_root,
            conflict_policy=conflict,
            allow_execute=self.chk_execute.isChecked(),
            parent=self
        )
        dlg.exec()
