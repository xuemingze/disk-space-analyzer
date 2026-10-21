from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton
)
from PySide6.QtCore import Qt, Signal


class AIDecisionBannerWidget(QFrame):
    """
    AI 诊断决策卡片 (统一面向对象组件)
    
    用于主控扫描 (HomeView) 与文件整理 (OrganizerView)：
    1. 当扫描独立资产 > 100 项时：给出“80% 可能性为集合判断错误”诊断，提供【查看全局扫描资产明细 (推荐并最大化)】与【强制 AI 总结/整理】；
    2. 当 AI 请求超时或异常时：恪守准则一不越权静默替代，提供【重试】、【载入本地专家应急报告】与【查看明细】供用户定夺。
    """
    inspect_details_requested = Signal()     # 查看并最大化资产明细
    force_ai_requested = Signal()            # 强制 AI 处理
    retry_ai_requested = Signal()            # 重试 AI 处理
    load_fallback_requested = Signal()       # 用户授权载入本地应急报告

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AIDecisionBanner")
        self.setStyleSheet("""
            QFrame#AIDecisionBanner {
                background-color: #1E293B;
                border: 1px solid #F59E0B;
                border-radius: 8px;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        self.icon_label = QLabel("⚠️")
        self.icon_label.setStyleSheet("font-size: 24px;")
        layout.addWidget(self.icon_label)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)
        self.title_lbl = QLabel("扫描独立资产数量为 0 项 (80% 可能性为集合判断错误)")
        self.title_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #FBBF24;")
        self.sub_lbl = QLabel("检测到大量散落独立资产，极可能存在未聚合的目录集体或未整理工具链。请由您决定下一步治理路径：")
        self.sub_lbl.setStyleSheet("font-size: 11px; color: #94A3B8;")
        text_layout.addWidget(self.title_lbl)
        text_layout.addWidget(self.sub_lbl)
        layout.addLayout(text_layout, 1)

        # 选项1: 查看全局扫描资产明细 (推荐并最大化)
        self.btn_inspect = QPushButton("🔍 查看资产明细 (推荐并最大化)")
        self.btn_inspect.setStyleSheet("background-color: #10B981; color: white; font-weight: bold; padding: 6px 14px; border-radius: 6px;")
        self.btn_inspect.clicked.connect(self.inspect_details_requested.emit)
        layout.addWidget(self.btn_inspect)

        # 选项2: 强制 AI 总结 / 强制 AI 整理
        self.btn_force_ai = QPushButton("⚡ 强制 AI 总结")
        self.btn_force_ai.setStyleSheet("background-color: #3B82F6; color: white; font-weight: bold; padding: 6px 14px; border-radius: 6px;")
        self.btn_force_ai.clicked.connect(self.force_ai_requested.emit)
        layout.addWidget(self.btn_force_ai)

        # 选项3: 重试 AI
        self.btn_retry_ai = QPushButton("🔄 重试 AI 总结")
        self.btn_retry_ai.setStyleSheet("background-color: #3B82F6; color: white; font-weight: bold; padding: 6px 14px; border-radius: 6px;")
        self.btn_retry_ai.clicked.connect(self.retry_ai_requested.emit)
        layout.addWidget(self.btn_retry_ai)
        self.btn_retry_ai.hide()

        # 选项4: 载入本地专家应急报告
        self.btn_load_fallback = QPushButton("📑 载入本地专家应急报告")
        self.btn_load_fallback.setStyleSheet("background-color: #64748B; color: white; font-weight: bold; padding: 6px 14px; border-radius: 6px;")
        self.btn_load_fallback.clicked.connect(self.load_fallback_requested.emit)
        layout.addWidget(self.btn_load_fallback)
        self.btn_load_fallback.hide()

        self.hide()

    def show_over_threshold_diagnosis(self, standalone_count: int, action_type: str = "AI 总结"):
        """显示独立资产超 100 项诊断 (80% 可能性为集合判断错误)"""
        self.icon_label.setText("⚠️")
        self.title_lbl.setText(f"扫描独立资产数量为 {standalone_count} 项 (80% 可能性为集合判断错误)")
        self.sub_lbl.setText(f"检测到大量散落独立资产，极可能存在未聚合的目录集体或未整理工具链。建议前往全屏明细进行「收拢转集合」；亦可由您自主决定强制执行 {action_type}：")
        
        self.btn_inspect.setText("🔍 查看全局扫描资产明细 (推荐并最大化)")
        self.btn_inspect.setVisible(True)
        self.btn_force_ai.setText(f"⚡ 强制 {action_type}")
        self.btn_force_ai.setVisible(True)
        self.btn_retry_ai.setVisible(False)
        self.btn_load_fallback.setVisible(False)
        self.show()

    def show_ai_error_diagnosis(self, err_msg: str, action_type: str = "AI 总结"):
        """显示 AI 调用超时或异常决策卡片 (不因超时直接越权，由用户定夺)"""
        self.icon_label.setText("⚠️")
        self.title_lbl.setText(f"{action_type}请求超时或异常")
        self.sub_lbl.setText(f"原因: {err_msg}。系统恪守 AI 为核心编排架构，绝不在未授权情况下以本地离线兜底越权替代 AI 输出。")

        self.btn_inspect.setText("🔍 查看全局扫描资产明细 (最大化)")
        self.btn_inspect.setVisible(True)
        self.btn_force_ai.setVisible(False)
        self.btn_retry_ai.setText(f"🔄 重试 {action_type}")
        self.btn_retry_ai.setVisible(True)
        self.btn_load_fallback.setVisible(True)
        self.show()

    def hide_diagnosis(self):
        self.hide()
