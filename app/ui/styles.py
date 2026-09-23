MODERN_DARK_STYLE = """
/* 全局基础设置 */
QWidget {
    background-color: #121820;
    color: #E2E8F0;
    font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
    font-size: 13px;
    selection-background-color: #3B82F6;
    selection-color: #FFFFFF;
}

/* 侧边栏导航 */
#SidebarWidget {
    background-color: #0F172A;
    border-right: 1px solid #1E293B;
    min-width: 220px;
    max-width: 220px;
}

#AppTitleLabel {
    font-size: 16px;
    font-weight: bold;
    color: #38BDF8;
    padding: 18px 12px;
}

#AppSubtitleLabel {
    font-size: 11px;
    color: #64748B;
    padding-left: 12px;
    margin-top: -12px;
    margin-bottom: 20px;
}

/* 导航按钮 */
QPushButton.NavButton {
    background-color: transparent;
    color: #94A3B8;
    text-align: left;
    padding: 12px 20px;
    font-size: 14px;
    font-weight: 500;
    border: none;
    border-left: 4px solid transparent;
    border-radius: 0px;
}

QPushButton.NavButton:hover {
    background-color: #1E293B;
    color: #F8FAFC;
}

QPushButton.NavButton:checked {
    background-color: #1E293B;
    color: #38BDF8;
    border-left: 4px solid #38BDF8;
    font-weight: bold;
}

/* 主容器背景 */
#MainContentArea {
    background-color: #0B0F17;
}

/* 卡片容器 */
QFrame.CardFrame {
    background-color: #161F2E;
    border: 1px solid #233247;
    border-radius: 8px;
    padding: 14px;
}

/* 按钮通用 */
QPushButton {
    background-color: #2563EB;
    color: #FFFFFF;
    border: 1px solid #3B82F6;
    border-radius: 6px;
    padding: 7px 16px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #1D4ED8;
    border-color: #60A5FA;
}

QPushButton:pressed {
    background-color: #1E40AF;
}

QPushButton:disabled {
    background-color: #1E293B;
    color: #64748B;
    border-color: #334155;
}

QPushButton.SuccessButton {
    background-color: #059669;
    border-color: #10B981;
}

QPushButton.SuccessButton:hover {
    background-color: #047857;
    border-color: #34D399;
}

QPushButton.DangerButton {
    background-color: #DC2626;
    border-color: #EF4444;
}

QPushButton.DangerButton:hover {
    background-color: #B91C1C;
    border-color: #F87171;
}

QPushButton.SecondaryButton {
    background-color: #1E293B;
    color: #CBD5E1;
    border-color: #334155;
}

QPushButton.SecondaryButton:hover {
    background-color: #334155;
    color: #FFFFFF;
    border-color: #475569;
}

/* 输入框与下拉框 */
QLineEdit, QComboBox, QSpinBox, QTextEdit {
    background-color: #0F172A;
    color: #F8FAFC;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 10px;
}

QLineEdit:focus, QComboBox:focus, QTextEdit:focus {
    border: 1px solid #38BDF8;
    background-color: #111C33;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
    padding-right: 6px;
}

/* 下拉菜单列表视图确保明亮对比与可见性 */
QComboBox QAbstractItemView, QListView {
    background-color: #0F172A;
    color: #F8FAFC;
    border: 1px solid #38BDF8;
    border-radius: 4px;
    padding: 4px;
    selection-background-color: #2563EB;
    selection-color: #FFFFFF;
    outline: none;
}

QComboBox QAbstractItemView::item {
    min-height: 28px;
    padding-left: 8px;
    color: #F8FAFC;
}

QComboBox QAbstractItemView::item:hover {
    background-color: #1E293B;
    color: #38BDF8;
}

QComboBox QAbstractItemView::item:selected {
    background-color: #2563EB;
    color: #FFFFFF;
}

/* 表格 Data Grid */
QTableWidget, QTableView {
    background-color: #121A27;
    alternate-background-color: #162234;
    gridline-color: #223249;
    border: 1px solid #233247;
    border-radius: 6px;
    color: #E2E8F0;
}

QHeaderView::section {
    background-color: #1A2638;
    color: #94A3B8;
    padding: 8px;
    border: none;
    border-bottom: 2px solid #2E405B;
    font-weight: bold;
}

QTableWidget::item {
    padding: 5px;
    border-bottom: 1px solid #1A2638;
}

QTableWidget::item:selected {
    background-color: #1E3A8A;
    color: #FFFFFF;
}

/* 标签页 QTabWidget */
QTabWidget::pane {
    border: 1px solid #233247;
    border-radius: 6px;
    background-color: #161F2E;
    top: -1px;
}

QTabBar::tab {
    background-color: #0F172A;
    color: #94A3B8;
    padding: 9px 18px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    border: 1px solid #233247;
    border-bottom: none;
}

QTabBar::tab:selected {
    background-color: #161F2E;
    color: #38BDF8;
    font-weight: bold;
    border-top: 2px solid #38BDF8;
}

QTabBar::tab:hover:!selected {
    background-color: #1E293B;
    color: #E2E8F0;
}

/* 进度条 */
QProgressBar {
    background-color: #0F172A;
    border: 1px solid #233247;
    border-radius: 6px;
    text-align: center;
    color: #FFFFFF;
    font-weight: bold;
    height: 18px;
}

QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563EB, stop:1 #38BDF8);
    border-radius: 5px;
}

/* 滚动条 */
QScrollBar:vertical {
    background: #0F172A;
    width: 10px;
    margin: 0px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #334155;
    min-height: 20px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #475569;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background: #0F172A;
    height: 10px;
    margin: 0px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background: #334155;
    min-width: 20px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal:hover {
    background: #475569;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* 复选框与单选框 */
QCheckBox, QRadioButton {
    spacing: 6px;
    color: #E2E8F0;
}

QCheckBox::indicator, QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #475569;
    border-radius: 3px;
    background-color: #0F172A;
}

QCheckBox::indicator:checked {
    background-color: #2563EB;
    border-color: #38BDF8;
}

QGroupBox {
    border: 1px solid #233247;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: bold;
    color: #38BDF8;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
}
"""
