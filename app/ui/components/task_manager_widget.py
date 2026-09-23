import time
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QPushButton, QLabel,
    QProgressBar, QMessageBox, QTextEdit, QAbstractItemView
)
from PySide6.QtCore import Qt, QTimer

from app.core.task_manager import global_task_manager, TaskItem, TaskStatus, TaskType
from app.utils.file_helper import format_size


class TaskLogDialog(QDialog):
    """任务运行日志详情窗口"""
    def __init__(self, task_item: TaskItem, parent=None):
        super().__init__(parent)
        self.task_item = task_item
        self.setWindowTitle(f"📜 任务运行日志 - {task_item.name} ({task_item.task_id})")
        self.resize(680, 460)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("background-color: #0F172A; font-family: Consolas, monospace; font-size: 11px;")
        layout.addWidget(self.log_text, 1)
        
        btn_close = QPushButton("关闭")
        btn_close.setProperty("class", "SecondaryButton")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, 0, Qt.AlignRight)
        
        self.refresh_logs()

    def refresh_logs(self):
        self.log_text.clear()
        for log in self.task_item.logs:
            color = "#10B981" if log["level"] == "success" else ("#F59E0B" if log["level"] == "warn" else ("#EF4444" if log["level"] == "error" else "#CBD5E1"))
            self.log_text.append(f'<span style="color: #64748B;">[{log["time"]}]</span> <span style="color: {color};">{log["message"]}</span>')


class TaskManagerDialog(QDialog):
    """
    统一后台任务管理控制中心对话框
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚡ 后台任务管理器 (Task Center)")
        self.resize(920, 520)
        
        self.init_ui()
        
        # 定时器定时刷新任务列表 (每 300ms)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_task_table)
        self.timer.start(300)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # 顶部标题栏
        top_row = QHBoxLayout()
        title_lbl = QLabel("⚡ 全局后台任务管理中心")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #38BDF8;")
        top_row.addWidget(title_lbl)
        top_row.addStretch()
        
        self.clear_btn = QPushButton("🧹 清理已完成/已取消历史")
        self.clear_btn.setProperty("class", "SecondaryButton")
        self.clear_btn.clicked.connect(self.on_clear_history)
        top_row.addWidget(self.clear_btn)
        
        layout.addLayout(top_row)

        # 任务表格
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "任务ID", "任务名称", "类型", "状态", "当前阶段", "进度", "速度 / ETA", "操作"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.setColumnWidth(1, 160)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        self.table.setColumnWidth(5, 120)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.Fixed)
        self.table.setColumnWidth(7, 180)
        
        layout.addWidget(self.table, 1)

        # 底部关闭按钮
        bottom_row = QHBoxLayout()
        self.status_info_label = QLabel("正在监控后台并发与扫描任务...")
        self.status_info_label.setStyleSheet("color: #64748B; font-size: 11px;")
        bottom_row.addWidget(self.status_info_label)
        bottom_row.addStretch()
        
        close_btn = QPushButton("关闭窗口 (任务在后台持续运行)")
        close_btn.setProperty("class", "SecondaryButton")
        close_btn.clicked.connect(self.accept)
        bottom_row.addWidget(close_btn)
        
        layout.addLayout(bottom_row)

    def refresh_task_table(self):
        tasks = global_task_manager.list_tasks()
        
        if self.table.rowCount() != len(tasks):
            self.table.setRowCount(len(tasks))

        for row, task in enumerate(reversed(tasks)):
            # 0. 任务ID
            self._set_item(row, 0, task.task_id)
            
            # 1. 任务名称
            self._set_item(row, 1, task.name)
            
            # 2. 类型
            self._set_item(row, 2, task.task_type.value)
            
            # 3. 状态
            status_item = QTableWidgetItem(task.status.value)
            status_item.setTextAlignment(Qt.AlignCenter)
            if task.status == TaskStatus.RUNNING:
                status_item.setForeground(Qt.green)
            elif task.status == TaskStatus.PAUSED:
                status_item.setForeground(Qt.yellow)
            elif task.status == TaskStatus.FAILED:
                status_item.setForeground(Qt.red)
            elif task.status == TaskStatus.COMPLETED:
                status_item.setForeground(Qt.cyan)
            self.table.setItem(row, 3, status_item)
            
            # 4. 当前阶段
            self._set_item(row, 4, task.current_phase)
            
            # 5. 进度条组件
            p_widget = QWidget()
            p_layout = QVBoxLayout(p_widget)
            p_layout.setContentsMargins(4, 4, 4, 4)
            p_bar = QProgressBar()
            p_bar.setRange(0, 100)
            p_bar.setValue(int(task.progress_percent))
            p_bar.setTextVisible(True)
            p_layout.addWidget(p_bar)
            self.table.setCellWidget(row, 5, p_widget)
            
            # 6. 速度 / ETA
            eta_str = f"{task.eta_seconds}s" if task.eta_seconds > 0 else "-"
            self._set_item(row, 6, f"{task.current_speed} (ETA: {eta_str})")
            
            # 7. 控制操作按钮组
            act_widget = QWidget()
            act_layout = QHBoxLayout(act_widget)
            act_layout.setContentsMargins(2, 2, 2, 2)
            act_layout.setSpacing(4)
            
            if task.status == TaskStatus.RUNNING:
                btn_pause = QPushButton("⏸️")
                btn_pause.setToolTip("暂停任务")
                btn_pause.setFixedWidth(32)
                btn_pause.clicked.connect(lambda _, tid=task.task_id: global_task_manager.pause_task(tid))
                act_layout.addWidget(btn_pause)
            elif task.status == TaskStatus.PAUSED:
                btn_resume = QPushButton("▶️")
                btn_resume.setToolTip("恢复任务")
                btn_resume.setFixedWidth(32)
                btn_resume.clicked.connect(lambda _, tid=task.task_id: global_task_manager.resume_task(tid))
                act_layout.addWidget(btn_resume)
                
            if task.status in (TaskStatus.RUNNING, TaskStatus.PAUSED):
                btn_cancel = QPushButton("⏹️")
                btn_cancel.setToolTip("取消任务")
                btn_cancel.setProperty("class", "DangerButton")
                btn_cancel.setFixedWidth(32)
                btn_cancel.clicked.connect(lambda _, tid=task.task_id: global_task_manager.cancel_task(tid))
                act_layout.addWidget(btn_cancel)
                
            btn_log = QPushButton("📜")
            btn_log.setToolTip("查看运行日志")
            btn_log.setFixedWidth(32)
            btn_log.clicked.connect(lambda _, t=task: TaskLogDialog(t, self).exec())
            act_layout.addWidget(btn_log)
            
            self.table.setCellWidget(row, 7, act_widget)

    def _set_item(self, row: int, col: int, text: str):
        item = self.table.item(row, col)
        if not item:
            item = QTableWidgetItem(text)
            self.table.setItem(row, col, item)
        else:
            item.setText(text)

    def on_clear_history(self):
        global_task_manager.clear_history()
        self.table.setRowCount(0)
        self.refresh_task_table()
