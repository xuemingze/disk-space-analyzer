"""
自动化中心主视图容器 (Automation Center View)
承载 4 大自动化子模块：
1. 规则监控 (Rule Monitor)
2. 计划任务 (Scheduled Tasks)
3. 快速整理 (Quick Organize)
4. 命令行与脚本 (CLI & Scripts)
支持顶部子导航与主窗口侧边栏双向无缝联动。
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QButtonGroup, QFrame
)
from PySide6.QtCore import Qt

from app.ui.automation.rule_monitor_page import RuleMonitorPage
from app.ui.automation.schedule_task_page import ScheduleTaskPage
from app.ui.automation.quick_organize_page import QuickOrganizePage
from app.ui.automation.cli_script_page import CliScriptPage
from app.automation.manager import AutomationManager


class AutomationCenterView(QWidget):
    """自动化中心多标签路由主视图"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = AutomationManager.get_instance()
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 顶部导航卡片条
        top_nav_frame = QFrame()
        top_nav_frame.setStyleSheet("""
            QFrame {
                background-color: #0F172A;
                border: 1px solid #1E293B;
                border-radius: 8px;
                padding: 4px;
            }
        """)
        top_nav_layout = QHBoxLayout(top_nav_frame)
        top_nav_layout.setContentsMargins(6, 4, 6, 4)
        top_nav_layout.setSpacing(8)

        # 子模块切换按钮组
        self.sub_btn_group = QButtonGroup(self)
        self.sub_btn_group.setExclusive(True)

        self.btn_sub_monitor = QPushButton("👁️ 规则监控")
        self.btn_sub_schedule = QPushButton("⏰ 计划任务")
        self.btn_sub_quick = QPushButton("⚡ 快速整理")
        self.btn_sub_cli = QPushButton("💻 命令行与脚本")

        sub_btns = [
            (self.btn_sub_monitor, 0),
            (self.btn_sub_schedule, 1),
            (self.btn_sub_quick, 2),
            (self.btn_sub_cli, 3)
        ]

        btn_qss = """
            QPushButton {
                background-color: transparent;
                color: #94A3B8;
                font-weight: 500;
                font-size: 13px;
                padding: 8px 18px;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #1E293B;
                color: #F8FAFC;
            }
            QPushButton:checked {
                background-color: #2563EB;
                color: #FFFFFF;
                font-weight: bold;
            }
        """

        for btn, idx in sub_btns:
            btn.setCheckable(True)
            btn.setStyleSheet(btn_qss)
            btn.clicked.connect(lambda _, i=idx: self.switch_subpage(i))
            self.sub_btn_group.addButton(btn)
            top_nav_layout.addWidget(btn)

        self.btn_sub_monitor.setChecked(True)
        top_nav_layout.addStretch()

        # 右侧服务状态小标
        self.lbl_service_status = QLabel("🟢 自动化引擎运行中")
        self.lbl_service_status.setStyleSheet("color: #10B981; font-size: 12px; font-weight: bold; padding-right: 8px;")
        top_nav_layout.addWidget(self.lbl_service_status)

        main_layout.addWidget(top_nav_frame)

        # 4 大子页面栈
        self.sub_stack = QStackedWidget()
        self.page_monitor = RuleMonitorPage()
        self.page_schedule = ScheduleTaskPage()
        self.page_quick = QuickOrganizePage()
        self.page_cli = CliScriptPage()

        self.sub_stack.addWidget(self.page_monitor)
        self.sub_stack.addWidget(self.page_schedule)
        self.sub_stack.addWidget(self.page_quick)
        self.sub_stack.addWidget(self.page_cli)

        main_layout.addWidget(self.sub_stack, 1)

    def switch_subpage(self, index: int):
        """切换自动化中心子页面"""
        self.sub_stack.setCurrentIndex(index)
        if index == 0:
            self.btn_sub_monitor.setChecked(True)
        elif index == 1:
            self.btn_sub_schedule.setChecked(True)
        elif index == 2:
            self.btn_sub_quick.setChecked(True)
        elif index == 3:
            self.btn_sub_cli.setChecked(True)

    def showEvent(self, event):
        super().showEvent(event)
        self.manager.start_services()
