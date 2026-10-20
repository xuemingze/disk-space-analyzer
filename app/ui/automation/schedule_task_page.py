"""
计划任务子页面 (Scheduled Tasks Page)
功能：
1. 定时任务配置与周期设定；
2. 调度状态、上次执行结果与下次触发时间追踪；
3. 支持手动立即触发生成提案；
4. 严格执行安全规约：初期只生成整理计划/预览，不在用户不知情时移动文件。
"""

import os
import time
from pathlib import Path
from typing import Optional, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
    QFormLayout, QLineEdit, QComboBox, QSpinBox, QMessageBox,
    QFileDialog, QGroupBox, QTextEdit
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from app.automation.models import ScheduledTask
from app.automation.manager import AutomationManager
from app.utils.lock_detector import is_destination_valid


class TaskEditDialog(QDialog):
    """新建/编辑计划任务对话框"""
    def __init__(self, task: Optional[ScheduledTask] = None, parent=None):
        super().__init__(parent)
        self.task = task or ScheduledTask()
        self.setWindowTitle("编辑计划任务" if task else "新建计划任务")
        self.resize(500, 320)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        form = QFormLayout()
        form.setSpacing(12)

        self.name_input = QLineEdit(self.task.name)
        form.addRow("任务名称:", self.name_input)

        path_row = QHBoxLayout()
        self.path_input = QLineEdit(self.task.target_path)
        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self._browse_dir)
        path_row.addWidget(self.path_input)
        path_row.addWidget(btn_browse)
        form.addRow("目标整理路径:", path_row)

        self.interval_combo = QComboBox()
        self.interval_combo.addItem("每 1 小时 (60 分钟)", 60)
        self.interval_combo.addItem("每 6 小时 (360 分钟)", 360)
        self.interval_combo.addItem("每 12 小时 (720 分钟)", 720)
        self.interval_combo.addItem("每日一次 (1440 分钟)", 1440)
        self.interval_combo.addItem("每周一次 (10080 分钟)", 10080)
        
        idx = self.interval_combo.findData(self.task.interval_minutes)
        if idx >= 0:
            self.interval_combo.setCurrentIndex(idx)
        else:
            self.interval_combo.addItem(f"自定义: {self.task.interval_minutes} 分钟", self.task.interval_minutes)
            self.interval_combo.setCurrentIndex(self.interval_combo.count() - 1)
        form.addRow("执行周期:", self.interval_combo)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("综合智能规划 (comprehensive)", "comprehensive")
        self.mode_combo.addItem("按格式类型 (by_type)", "by_type")
        self.mode_combo.addItem("按前缀聚类 (by_prefix)", "by_prefix")
        self.mode_combo.addItem("按修改日期 (by_date)", "by_date")
        self.mode_combo.addItem("按应用工具链 (by_app)", "by_app")
        idx_m = self.mode_combo.findData(self.task.organize_mode)
        if idx_m >= 0:
            self.mode_combo.setCurrentIndex(idx_m)
        form.addRow("整理模式:", self.mode_combo)

        # 归档目标目录
        target_row = QHBoxLayout()
        self.target_dir_input = QLineEdit(self.task.target_dir)
        self.target_dir_input.setPlaceholderText("留空则采用系统默认归档根目录 (D:/归档备份)")
        btn_browse_target = QPushButton("浏览...")
        btn_browse_target.clicked.connect(self._browse_target_dir)
        target_row.addWidget(self.target_dir_input)
        target_row.addWidget(btn_browse_target)
        form.addRow("归档目标目录:", target_row)

        # 执行模式切换
        self.exec_mode_combo = QComboBox()
        self.exec_mode_combo.addItem("💡 仅生成整理提案 (默认安全，生成待审核卡片)", True)
        self.exec_mode_combo.addItem("⚡ 定时自动归档平移 (无人值守，安全避让运行/编辑锁)", False)
        if not self.task.propose_only:
            self.exec_mode_combo.setCurrentIndex(1)
        else:
            self.exec_mode_combo.setCurrentIndex(0)
        form.addRow("执行模式:", self.exec_mode_combo)

        layout.addLayout(form)

        tip = QLabel("🛡️ 安全保底：若选自动归档，内置独占锁与 Office/WPS 伴生锁探针将自动避让正在编辑或占用的文件。")
        tip.setStyleSheet("color: #38BDF8; font-size: 12px; background: #0F172A; padding: 8px; border-radius: 4px;")
        layout.addWidget(tip)

        btns = QHBoxLayout()
        btns.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("保存任务")
        btn_ok.setStyleSheet("background-color: #2563EB; color: white; font-weight: bold; padding: 6px 16px;")
        btn_ok.clicked.connect(self._save)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        layout.addLayout(btns)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择整理路径", self.path_input.text() or str(Path.home()))
        if d:
            self.path_input.setText(d)

    def _browse_target_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择专属归档目标目录", self.target_dir_input.text() or "D:/归档备份")
        if d:
            self.target_dir_input.setText(d)

    def _save(self):
        name = self.name_input.text().strip()
        path = self.path_input.text().strip()
        target_dir = self.target_dir_input.text().strip()
        propose_only = self.exec_mode_combo.currentData()

        if not name or not path:
            QMessageBox.warning(self, "提示", "任务名称与目标路径不能为空。")
            return
        if not os.path.exists(path):
            QMessageBox.warning(self, "提示", f"路径不存在: {path}")
            return

        # 校验归档目标防死循环
        if target_dir:
            valid, err = is_destination_valid(path, target_dir)
            if not valid:
                QMessageBox.critical(self, "防回环安全拦截", f"归档目标目录无效:\n{err}")
                return
        elif not propose_only:
            target_dir = "D:/归档备份"

        self.task.name = name
        self.task.target_path = path
        self.task.target_dir = target_dir
        self.task.propose_only = propose_only
        self.task.interval_minutes = self.interval_combo.currentData()
        self.task.organize_mode = self.mode_combo.currentData()
        self.accept()


class ScheduleTaskPage(QWidget):
    """计划任务视图"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = AutomationManager.get_instance()
        self.init_ui()
        self._bind_events()
        self.refresh_tasks()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)

        # 头部操作栏
        top_bar = QHBoxLayout()
        title_box = QVBoxLayout()
        lbl_title = QLabel("⏰ 计划任务 (Scheduled Tasks)")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #38BDF8;")
        lbl_desc = QLabel("定时扫描关键目录并生成整理提案；初期只做规划，确保数据安全可控")
        lbl_desc.setStyleSheet("color: #94A3B8; font-size: 12px;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_desc)
        top_bar.addLayout(title_box)

        top_bar.addStretch()

        self.btn_add_task = QPushButton("➕ 新建计划任务")
        self.btn_add_task.setStyleSheet("background-color: #0284C7; color: white; font-weight: bold; padding: 8px 16px; border-radius: 4px;")
        self.btn_add_task.clicked.connect(self._add_task)
        top_bar.addWidget(self.btn_add_task)

        main_layout.addLayout(top_bar)

        # 任务表格
        self.task_table = QTableWidget()
        self.task_table.setColumnCount(8)
        self.task_table.setHorizontalHeaderLabels(["状态", "任务名称", "目标路径", "归档目录", "执行周期", "模式", "下次执行", "操作"])

        # 严格执行设计铁律：统一行高 44px
        self.task_table.verticalHeader().setVisible(False)
        self.task_table.verticalHeader().setDefaultSectionSize(44)
        self.task_table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)

        # 严格执行设计铁律：列宽分层策略 (控件列锁定宽度，纯文本列弹性伸缩)
        h_header = self.task_table.horizontalHeader()
        h_header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.task_table.setColumnWidth(0, 90)   # 状态开关
        h_header.setSectionResizeMode(1, QHeaderView.Interactive)
        self.task_table.setColumnWidth(1, 130)  # 任务名称
        h_header.setSectionResizeMode(2, QHeaderView.Stretch)  # 目标路径
        h_header.setSectionResizeMode(3, QHeaderView.Stretch)  # 归档目录
        h_header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.task_table.setColumnWidth(4, 100)  # 执行周期
        h_header.setSectionResizeMode(5, QHeaderView.Fixed)
        self.task_table.setColumnWidth(5, 100)  # 模式
        h_header.setSectionResizeMode(6, QHeaderView.Fixed)
        self.task_table.setColumnWidth(6, 135)  # 下次执行
        h_header.setSectionResizeMode(7, QHeaderView.Fixed)
        self.task_table.setColumnWidth(7, 220)  # 操作列 (3按钮)

        self.task_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.task_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.task_table.setStyleSheet("""
            QTableWidget {
                background: #1E293B;
                border: 1px solid #334155;
                border-radius: 6px;
                gridline-color: #334155;
            }
            QTableWidget::item {
                padding: 4px 6px;
                color: #F8FAFC;
            }
            QHeaderView::section {
                background: #0F172A;
                color: #94A3B8;
                font-weight: bold;
                padding: 6px;
                border: none;
                border-bottom: 1px solid #334155;
            }
        """)
        main_layout.addWidget(self.task_table, 3)

        # 执行日志输出框
        log_group = QGroupBox("📋 调度与执行历史日志")
        log_group.setStyleSheet("QGroupBox { font-weight: bold; color: #38BDF8; }")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("background: #0F172A; color: #E2E8F0; font-family: monospace; font-size: 12px; border: 1px solid #1E293B;")
        log_layout.addWidget(self.log_text)
        main_layout.addWidget(log_group, 2)

    def _bind_events(self):
        self.manager.tasks_changed.connect(self.refresh_tasks)
        self.manager.log_emitted.connect(self._append_log)

    def _append_log(self, msg: str, level: str):
        t_str = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{t_str}] {msg}")

    def refresh_tasks(self):
        """刷新任务表格 (严格遵循行高、固定尺寸与居中包裹铁律)"""
        tasks = self.manager.tasks
        self.task_table.setRowCount(len(tasks))
        for row, task in enumerate(tasks):
            # 1. 状态开关按钮 (使用独立居中容器，固定 70x28 尺寸)
            toggle_container = QWidget()
            toggle_layout = QHBoxLayout(toggle_container)
            toggle_layout.setContentsMargins(0, 0, 0, 0)
            toggle_layout.setAlignment(Qt.AlignCenter)

            btn_toggle = QPushButton("已启用" if task.enabled else "已停用")
            btn_toggle.setCheckable(True)
            btn_toggle.setChecked(task.enabled)
            btn_toggle.setFixedSize(70, 28)
            btn_toggle.setStyleSheet(
                """
                QPushButton {
                    background: #10B981;
                    color: white;
                    font-size: 12px;
                    font-weight: bold;
                    border: none;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background: #059669;
                }
                QPushButton:pressed {
                    background: #047857;
                }
                """ if task.enabled else """
                QPushButton {
                    background: #475569;
                    color: #CBD5E1;
                    font-size: 12px;
                    border: none;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background: #64748B;
                }
                QPushButton:pressed {
                    background: #334155;
                }
                """
            )
            btn_toggle.clicked.connect(lambda checked, t_id=task.id: self._toggle_task(t_id, checked))
            toggle_layout.addWidget(btn_toggle)
            self.task_table.setCellWidget(row, 0, toggle_container)

            # 2. 文本单元格
            item_name = QTableWidgetItem(task.name)
            item_name.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            self.task_table.setItem(row, 1, item_name)

            item_path = QTableWidgetItem(task.target_path)
            item_path.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            item_path.setToolTip(task.target_path)
            self.task_table.setItem(row, 2, item_path)

            item_dest = QTableWidgetItem(task.target_dir or "默认(D:/归档备份)")
            item_dest.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            item_dest.setToolTip(task.target_dir or "D:/归档备份")
            self.task_table.setItem(row, 3, item_dest)

            hours = task.interval_minutes / 60.0
            cycle_str = f"{task.interval_minutes} 分钟" if task.interval_minutes < 60 else f"{hours:.1f} 小时"
            item_cycle = QTableWidgetItem(cycle_str)
            item_cycle.setTextAlignment(Qt.AlignCenter)
            self.task_table.setItem(row, 4, item_cycle)

            mode_item = QTableWidgetItem("💡 仅提议" if task.propose_only else "⚡ 自动归档")
            mode_item.setForeground(QColor("#38BDF8" if task.propose_only else "#10B981"))
            mode_item.setTextAlignment(Qt.AlignCenter)
            self.task_table.setItem(row, 5, mode_item)

            next_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(task.next_run_time)) if task.next_run_time else "未排定"
            item_next = QTableWidgetItem(next_str)
            item_next.setTextAlignment(Qt.AlignCenter)
            self.task_table.setItem(row, 6, item_next)

            # 3. 操作按钮栏 (严格遵循独立容器居中 + 28px 高度保底，3按钮固定尺寸)
            ops_widget = QWidget()
            ops_layout = QHBoxLayout(ops_widget)
            ops_layout.setContentsMargins(4, 0, 4, 0)
            ops_layout.setSpacing(6)
            ops_layout.setAlignment(Qt.AlignCenter)

            btn_run_now = QPushButton("立即运行")
            btn_run_now.setFixedSize(68, 28)
            btn_run_now.setStyleSheet("""
                QPushButton {
                    background: #0284C7;
                    color: white;
                    font-size: 12px;
                    border: none;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background: #0369A1;
                }
                QPushButton:pressed {
                    background: #075985;
                }
            """)
            btn_run_now.clicked.connect(lambda _, t_id=task.id: self._run_now(t_id))
            ops_layout.addWidget(btn_run_now)

            btn_edit = QPushButton("编辑")
            btn_edit.setFixedSize(54, 28)
            btn_edit.setStyleSheet("""
                QPushButton {
                    background: #2563EB;
                    color: white;
                    font-size: 12px;
                    border: none;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background: #1D4ED8;
                }
                QPushButton:pressed {
                    background: #1E40AF;
                }
            """)
            btn_edit.clicked.connect(lambda _, t=task: self._edit_task(t))
            ops_layout.addWidget(btn_edit)

            btn_del = QPushButton("删除")
            btn_del.setFixedSize(54, 28)
            btn_del.setStyleSheet("""
                QPushButton {
                    background: #DC2626;
                    color: white;
                    font-size: 12px;
                    border: none;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background: #B91C1C;
                }
                QPushButton:pressed {
                    background: #991B1B;
                }
            """)
            btn_del.clicked.connect(lambda _, t_id=task.id: self._delete_task(t_id))
            ops_layout.addWidget(btn_del)

            self.task_table.setCellWidget(row, 7, ops_widget)

    def _add_task(self):
        dlg = TaskEditDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.manager.add_task(dlg.task)

    def _edit_task(self, task: ScheduledTask):
        dlg = TaskEditDialog(task=task, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.manager.update_task(dlg.task)

    def _delete_task(self, task_id: str):
        if QMessageBox.question(self, "确认删除", "确定要删除该计划任务吗？") == QMessageBox.Yes:
            self.manager.delete_task(task_id)

    def _toggle_task(self, task_id: str, checked: bool):
        self.manager.toggle_task(task_id, checked)

    def _run_now(self, task_id: str):
        self.manager.run_task_now(task_id)
