from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame, QButtonGroup,
    QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent

from app.ui.home_view import HomeView
from app.ui.organizer_view import OrganizerView
from app.ui.settings_view import SettingsView
from app.ui.automation import AutomationCenterView
from app.ui.dedup import DedupMergeView
from app.ui.app_manager_view import AppManagerView
from app.automation.manager import AutomationManager
from app.ui.components.task_manager_widget import TaskManagerDialog
from app.ui.styles import MODERN_DARK_STYLE
from app.core.task_manager import global_task_manager
from app.config import app_config


class MainWindow(QMainWindow):
    """
    应用程序主窗口：侧边栏导航 + StackedWidget 现代化路由 + 任务安全退出拦截
    包含：
    - 主控扫描 (Home)
    - 文件整理 (Organizer)
    - 自动化中心 (Automation Center: 规则监控 / 计划任务 / 快速整理 / 命令行与脚本)
    - 系统配置 (Settings)
    - 任务管理器 (Tasks)
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("空间全景深度分析与冗余文件扫描 - AI 智能桌面客户端")
        
        w = app_config.get("ui", "window_width", default=1360)
        h = app_config.get("ui", "window_height", default=900)
        self.resize(w, h)
        self.setMinimumSize(1150, 750)
        
        self.setStyleSheet(MODERN_DARK_STYLE)
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. 左侧现代化导航侧边栏
        sidebar = QFrame()
        sidebar.setObjectName("SidebarWidget")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 16)
        sidebar_layout.setSpacing(4)

        # 标题与副标
        title_label = QLabel("🚀 空间全景分析")
        title_label.setObjectName("AppTitleLabel")
        
        subtitle_label = QLabel("分阶段扫描与 AI 智能治理")
        subtitle_label.setObjectName("AppSubtitleLabel")
        
        sidebar_layout.addWidget(title_label)
        sidebar_layout.addWidget(subtitle_label)

        # 导航按钮组
        self.nav_btn_group = QButtonGroup(self)
        self.nav_btn_group.setExclusive(True)

        # 1.1 主控扫描
        self.btn_nav_home = QPushButton("  🏠  主控扫描 (Home)")
        self.btn_nav_home.setProperty("class", "NavButton")
        self.btn_nav_home.setCheckable(True)
        self.btn_nav_home.setChecked(True)
        self.btn_nav_home.clicked.connect(lambda: self.switch_view(0))
        self.nav_btn_group.addButton(self.btn_nav_home)
        sidebar_layout.addWidget(self.btn_nav_home)

        # 1.2 文件整理
        self.btn_nav_organizer = QPushButton("  📁  文件整理 (Organizer)")
        self.btn_nav_organizer.setProperty("class", "NavButton")
        self.btn_nav_organizer.setCheckable(True)
        self.btn_nav_organizer.clicked.connect(lambda: self.switch_view(1))
        self.nav_btn_group.addButton(self.btn_nav_organizer)
        sidebar_layout.addWidget(self.btn_nav_organizer)

        # 1.3 可展开的「自动化中心」主导航
        self.btn_nav_automation = QPushButton("  🤖  自动化中心 ▾")
        self.btn_nav_automation.setProperty("class", "NavButton")
        self.btn_nav_automation.setCheckable(True)
        self.btn_nav_automation.clicked.connect(self._on_automation_clicked)
        self.nav_btn_group.addButton(self.btn_nav_automation)
        sidebar_layout.addWidget(self.btn_nav_automation)

        # 1.3.1 自动化中心可展开子菜单容器
        self.sub_nav_container = QWidget()
        sub_layout = QVBoxLayout(self.sub_nav_container)
        sub_layout.setContentsMargins(0, 0, 0, 0)
        sub_layout.setSpacing(2)

        self.sub_btn_group = QButtonGroup(self)
        self.sub_btn_group.setExclusive(True)

        self.btn_sub_monitor = QPushButton("  👁️ 规则监控")
        self.btn_sub_schedule = QPushButton("  ⏰ 计划任务")
        self.btn_sub_quick = QPushButton("  ⚡ 快速整理")
        self.btn_sub_cli = QPushButton("  💻 命令行与脚本")

        self.sub_nav_btns = [
            (self.btn_sub_monitor, 0),
            (self.btn_sub_schedule, 1),
            (self.btn_sub_quick, 2),
            (self.btn_sub_cli, 3)
        ]

        for btn, sub_idx in self.sub_nav_btns:
            btn.setProperty("class", "SubNavButton")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, s_idx=sub_idx: self.switch_view(2, sub_index=s_idx))
            self.sub_btn_group.addButton(btn)
            sub_layout.addWidget(btn)

        self.btn_sub_monitor.setChecked(True)
        sidebar_layout.addWidget(self.sub_nav_container)

        # 1.4 文件查重与融合
        self.btn_nav_dedup = QPushButton("  🔍  查重与融合 (Dedup)")
        self.btn_nav_dedup.setProperty("class", "NavButton")
        self.btn_nav_dedup.setCheckable(True)
        self.btn_nav_dedup.clicked.connect(lambda: self.switch_view(3))
        self.nav_btn_group.addButton(self.btn_nav_dedup)
        sidebar_layout.addWidget(self.btn_nav_dedup)

        # 1.5 软件与应用管理
        self.btn_nav_app_mgr = QPushButton("  🎯  应用管理 (App Manager)")
        self.btn_nav_app_mgr.setProperty("class", "NavButton")
        self.btn_nav_app_mgr.setCheckable(True)
        self.btn_nav_app_mgr.clicked.connect(lambda: self.switch_view(4))
        self.nav_btn_group.addButton(self.btn_nav_app_mgr)
        sidebar_layout.addWidget(self.btn_nav_app_mgr)

        # 1.6 配置与模型
        self.btn_nav_settings = QPushButton("  ⚙️  配置与模型 (Settings)")
        self.btn_nav_settings.setProperty("class", "NavButton")
        self.btn_nav_settings.setCheckable(True)
        self.btn_nav_settings.clicked.connect(lambda: self.switch_view(5))
        self.nav_btn_group.addButton(self.btn_nav_settings)
        sidebar_layout.addWidget(self.btn_nav_settings)

        sidebar_layout.addSpacing(10)

        # 任务管理器快速入口
        self.btn_task_mgr = QPushButton("  ⚡  任务管理器 (Tasks)")
        self.btn_task_mgr.setProperty("class", "NavButton")
        self.btn_task_mgr.clicked.connect(self.open_task_manager)
        sidebar_layout.addWidget(self.btn_task_mgr)

        sidebar_layout.addStretch()

        # 底部状态信息
        bottom_info = QLabel("v1.8.0 | Pro Edition\n全后台异步架构\nAI辅助文件归档引擎")
        bottom_info.setStyleSheet("color: #475569; font-size: 11px; padding-left: 20px; line-height: 140%;")
        sidebar_layout.addWidget(bottom_info)

        main_layout.addWidget(sidebar)

        # 2. 右侧多视图路由栈
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setObjectName("MainContentArea")

        self.home_view = HomeView()
        self.organizer_view = OrganizerView()
        self.automation_view = AutomationCenterView()
        self.dedup_view = DedupMergeView()
        self.app_manager_view = AppManagerView()
        self.settings_view = SettingsView()

        self.stacked_widget.addWidget(self.home_view)        # 0
        self.stacked_widget.addWidget(self.organizer_view)   # 1
        self.stacked_widget.addWidget(self.automation_view)  # 2
        self.stacked_widget.addWidget(self.dedup_view)       # 3
        self.stacked_widget.addWidget(self.app_manager_view) # 4
        self.stacked_widget.addWidget(self.settings_view)    # 5

        # 连接 HomeView 的导航跳转请求 (切忌重写脚本，无缝路由至既有 OrganizerView)
        self.home_view.navigate_to_organizer.connect(self.navigate_to_organizer_with_path)

        main_layout.addWidget(self.stacked_widget, 1)

    def navigate_to_organizer_with_path(self, target_path: str = ""):
        """从主控扫描直接无缝路由跳转至文件整理页，并同步目标路径"""
        import os
        if target_path and os.path.exists(target_path):
            self.organizer_view.dir_input.setText(target_path)
        self.switch_view(1)

    def _on_automation_clicked(self):
        """点击自动化中心主按钮：切换视图并折叠/展开子菜单"""
        if self.stacked_widget.currentIndex() == 2:
            # 已经在自动化中心：切换折叠状态
            is_visible = self.sub_nav_container.isVisible()
            self.sub_nav_container.setVisible(not is_visible)
            self.btn_nav_automation.setText("  🤖  自动化中心 ▾" if not is_visible else "  🤖  自动化中心 ▸")
        else:
            # 从其他视图切过来：展开并切到自动化中心
            self.sub_nav_container.setVisible(True)
            self.btn_nav_automation.setText("  🤖  自动化中心 ▾")
            self.switch_view(2)

    def switch_view(self, index: int, sub_index: int = None):
        """路由切换主视图，支持联动自动化中心子页面"""
        self.stacked_widget.setCurrentIndex(index)
        if index == 0:
            self.btn_nav_home.setChecked(True)
        elif index == 1:
            self.btn_nav_organizer.setChecked(True)
        elif index == 2:
            self.btn_nav_automation.setChecked(True)
            self.sub_nav_container.setVisible(True)
            self.btn_nav_automation.setText("  🤖  自动化中心 ▾")
            if sub_index is not None:
                self.automation_view.switch_subpage(sub_index)
                if 0 <= sub_index < len(self.sub_nav_btns):
                    self.sub_nav_btns[sub_index][0].setChecked(True)
            else:
                curr_sub = self.automation_view.sub_stack.currentIndex()
                if 0 <= curr_sub < len(self.sub_nav_btns):
                    self.sub_nav_btns[curr_sub][0].setChecked(True)
        elif index == 3:
            self.btn_nav_dedup.setChecked(True)
        elif index == 4:
            self.btn_nav_app_mgr.setChecked(True)
        elif index == 5:
            self.btn_nav_settings.setChecked(True)

    def open_task_manager(self):
        dlg = TaskManagerDialog(self)
        dlg.exec()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            handled = False
            # 1. 优先退出标签页内全屏
            if hasattr(self, "page_home") and hasattr(self.page_home, "is_tab_fullscreen"):
                if self.page_home.is_tab_fullscreen():
                    self.page_home.toggle_tab_fullscreen()
                    handled = True
            
            # 2. 其次退出主窗口全屏 (如果存在)
            if not handled and self.isFullScreen():
                self.showNormal()
                handled = True
                
            if not handled:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent):
        """主窗口关闭时安全拦截活跃后台任务并停止自动化监控"""
        if global_task_manager.has_active_tasks():
            reply = QMessageBox.question(
                self, "任务运行中",
                "当前仍有正在执行的后台扫描、哈希或归档任务！\n\n"
                "确定要立即中止所有后台任务并退出程序吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                for t in global_task_manager.list_tasks():
                    if t.worker and hasattr(t.worker, "cancel"):
                        t.worker.cancel()
                AutomationManager.get_instance().stop_services()
                event.accept()
            else:
                event.ignore()
        else:
            AutomationManager.get_instance().stop_services()
            event.accept()
