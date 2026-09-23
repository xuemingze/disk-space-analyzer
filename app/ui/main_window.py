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

        self.btn_nav_home = QPushButton("  🏠  主控扫描 (Home)")
        self.btn_nav_home.setProperty("class", "NavButton")
        self.btn_nav_home.setCheckable(True)
        self.btn_nav_home.setChecked(True)
        self.btn_nav_home.clicked.connect(lambda: self.switch_view(0))
        self.nav_btn_group.addButton(self.btn_nav_home)
        sidebar_layout.addWidget(self.btn_nav_home)

        self.btn_nav_organizer = QPushButton("  📁  文件整理 (Organizer)")
        self.btn_nav_organizer.setProperty("class", "NavButton")
        self.btn_nav_organizer.setCheckable(True)
        self.btn_nav_organizer.clicked.connect(lambda: self.switch_view(1))
        self.nav_btn_group.addButton(self.btn_nav_organizer)
        sidebar_layout.addWidget(self.btn_nav_organizer)

        self.btn_nav_settings = QPushButton("  ⚙️  配置与模型 (Settings)")
        self.btn_nav_settings.setProperty("class", "NavButton")
        self.btn_nav_settings.setCheckable(True)
        self.btn_nav_settings.clicked.connect(lambda: self.switch_view(2))
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
        bottom_info = QLabel("v1.3.0 | Pro Edition\n全后台异步架构\nAI辅助文件归档引擎")
        bottom_info.setStyleSheet("color: #475569; font-size: 11px; padding-left: 20px; line-height: 140%;")
        sidebar_layout.addWidget(bottom_info)

        main_layout.addWidget(sidebar)

        # 2. 右侧多视图路由栈
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setObjectName("MainContentArea")

        self.home_view = HomeView()
        self.organizer_view = OrganizerView()
        self.settings_view = SettingsView()

        self.stacked_widget.addWidget(self.home_view)
        self.stacked_widget.addWidget(self.organizer_view)
        self.stacked_widget.addWidget(self.settings_view)

        main_layout.addWidget(self.stacked_widget, 1)

    def switch_view(self, index: int):
        self.stacked_widget.setCurrentIndex(index)
        if index == 0:
            self.btn_nav_home.setChecked(True)
        elif index == 1:
            self.btn_nav_organizer.setChecked(True)
        elif index == 2:
            self.btn_nav_settings.setChecked(True)

    def open_task_manager(self):
        dlg = TaskManagerDialog(self)
        dlg.exec()

    def closeEvent(self, event: QCloseEvent):
        """主窗口关闭时安全拦截活跃后台任务"""
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
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
