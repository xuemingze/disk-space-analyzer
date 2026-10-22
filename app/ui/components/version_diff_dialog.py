"""
app/ui/components/version_diff_dialog.py
AI 语义多版本文档差异比对与智能保留决策对话框

遵循系统最高宪法与核心准则：
- 准则一 (AI 为核心编排器): AI 统揽语义比对与版本演进裁决；
- 准则二 (GUI 永久一致性法则): 行高锁死 44px、禁用斑马纹、深底纯白高对比度、操作栏 28px 居中容器；
- 方针三 (本地不抢功冒进): AI 离线或异常时不越权编造裁决，呈现物理事实由用户自主定夺。
"""

import os
import subprocess
import time
from typing import Optional, Dict, Any

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QRadioButton, QButtonGroup, QFrame, QProgressBar, QApplication
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QBrush

from app.config import app_config
from app.core.ai_service import AIService
from app.core.domain_models import VersionClusterGroup, VersionClusterItem, SemanticDiffDecision
from app.utils.file_helper import format_size


class VersionDiffWorker(QThread):
    """后台异步请求 AI 语义比对工作线程"""
    finished_signal = Signal(object, object)  # (SemanticDiffDecision, VersionClusterGroup)
    failed_signal = Signal(str)

    def __init__(self, cluster: VersionClusterGroup, parent=None):
        super().__init__(parent)
        self.cluster = cluster

    def run(self):
        try:
            llm_cfg = app_config.get("llm", default={})
            base_url = llm_cfg.get("base_url", "")
            api_key = llm_cfg.get("api_key", "")
            model = llm_cfg.get("model", "gpt-4o-mini")

            decision = AIService.audit_similar_versions_with_ai(
                cluster=self.cluster,
                base_url=base_url,
                api_key=api_key,
                model=model,
                timeout=12.0
            )
            self.finished_signal.emit(decision, self.cluster)
        except Exception as e:
            self.failed_signal.emit(str(e))


class VersionDiffDialog(QDialog):
    """多版本文档语义差异比对与智能保留决策对话框"""
    decision_applied = Signal(object, str)  # (VersionClusterGroup, selected_keep_path)

    def __init__(self, cluster: VersionClusterGroup, auto_start_ai: bool = True, parent=None):
        super().__init__(parent)
        self.cluster = cluster
        self.selected_keep_path: str = cluster.recommended_keep_path or (cluster.items[0].path if cluster.items else "")
        self.worker: Optional[VersionDiffWorker] = None

        self.setWindowTitle("🔍 AI 多版本文档语义比对与智能保留决策")
        self.resize(1100, 680)
        self.setMinimumSize(960, 560)
        self.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
                color: #F8FAFC;
            }
            QLabel {
                color: #F8FAFC;
                font-size: 12px;
            }
        """)

        self._init_ui()
        self._populate_table()

        if auto_start_ai and not self.cluster.ai_evaluated:
            self._start_ai_evaluation()
        else:
            self._update_ai_banner()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        # 1. 顶部标题栏
        top_bar = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        lbl_title = QLabel("🔍 AI 多版本文档语义差异比对与智能保留决策")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #38BDF8;")
        lbl_sub = QLabel(
            f"同族基准词干: <b style='color:#FBBF24;'>{self.cluster.normalized_stem}</b> | "
            f"聚类版本数: <b>{len(self.cluster.items)}</b> 份 | "
            f"所在目录: <span style='color:#94A3B8;'>{self.cluster.directory}</span>"
        )
        lbl_sub.setStyleSheet("font-size: 12px; color: #94A3B8;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        top_bar.addLayout(title_box, 1)

        # 重新研判按钮
        self.btn_re_eval = QPushButton("🤖 重新进行 AI 语义研判")
        self.btn_re_eval.setFixedHeight(34)
        self.btn_re_eval.setStyleSheet("""
            QPushButton {
                background-color: #2563EB;
                color: #FFFFFF;
                font-weight: bold;
                border-radius: 6px;
                padding: 0 16px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #1D4ED8; }
            QPushButton:disabled { background-color: #475569; color: #94A3B8; }
        """)
        self.btn_re_eval.clicked.connect(self._start_ai_evaluation)
        top_bar.addWidget(self.btn_re_eval)
        layout.addLayout(top_bar)

        # 2. AI 诊断报告卡片
        self.banner_frame = QFrame()
        self.banner_frame.setStyleSheet("""
            QFrame {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 8px;
            }
        """)
        banner_layout = QVBoxLayout(self.banner_frame)
        banner_layout.setContentsMargins(14, 10, 14, 10)
        banner_layout.setSpacing(6)

        banner_top = QHBoxLayout()
        self.lbl_status_badge = QLabel("🤖 正在连接 AI 编排器分析语义演化差异...")
        self.lbl_status_badge.setStyleSheet("""
            background-color: #0369A1;
            color: #FFFFFF;
            font-weight: bold;
            font-size: 12px;
            border-radius: 4px;
            padding: 3px 8px;
        """)
        banner_top.addWidget(self.lbl_status_badge)
        banner_top.addStretch()

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: #334155;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background-color: #38BDF8;
                border-radius: 3px;
            }
        """)
        self.progress_bar.hide()
        banner_top.addWidget(self.progress_bar)
        banner_layout.addLayout(banner_top)

        self.lbl_summary_text = QLabel("正在抽取各版本文本摘要与演变特征，交由 AI 核心编排器统揽分析...")
        self.lbl_summary_text.setWordWrap(True)
        self.lbl_summary_text.setStyleSheet("color: #E2E8F0; font-size: 12px; line-height: 1.4;")
        banner_layout.addWidget(self.lbl_summary_text)

        layout.addWidget(self.banner_frame)

        # 3. 多版本对比表格 (准则二：行高锁死 44px、深底纯白字、操作栏 28px 居中容器)
        self.table = QTableWidget()
        self._setup_table()
        layout.addWidget(self.table, 1)

        # 4. 底部操作按钮栏
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(12)

        lbl_tip = QLabel("💡 提示: 选中的版本将作为唯一正本保留；未选版本可安全归档至历史隔离目录，绝不强制物理硬删。")
        lbl_tip.setStyleSheet("color: #94A3B8; font-size: 11px;")
        bottom_bar.addWidget(lbl_tip, 1)

        self.btn_cancel = QPushButton("仅查看 / 取消")
        self.btn_cancel.setFixedHeight(36)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #F8FAFC;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 0 16px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        self.btn_cancel.clicked.connect(self.reject)
        bottom_bar.addWidget(self.btn_cancel)

        self.btn_apply = QPushButton("📦 应用推荐决策 (保留选定正本)")
        self.btn_apply.setFixedHeight(36)
        self.btn_apply.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: #FFFFFF;
                font-weight: bold;
                border-radius: 6px;
                padding: 0 22px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #059669; }
        """)
        self.btn_apply.clicked.connect(self._on_apply_clicked)
        bottom_bar.addWidget(self.btn_apply)

        layout.addLayout(bottom_bar)

    def _setup_table(self):
        """表格初始化，严格锁定 44px 垂直行高"""
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "保留正本", "版本标识", "文件名与路径", "大小", "修改时间", "推荐处置动作", "差异与决策依据", "快捷操作"
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(False)

        # 表格现代高对比暗黑风 (准则二：纯白字 #F8FAFC, 禁斑马纹)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #1E293B;
                color: #F8FAFC;
                gridline-color: #334155;
                border: 1px solid #334155;
                border-radius: 6px;
            }
            QTableWidget::item {
                padding-left: 8px;
                padding-right: 8px;
                color: #F8FAFC;
            }
            QTableWidget::item:selected {
                background-color: #334155;
                color: #FFFFFF;
            }
            QHeaderView::section {
                background-color: #0F172A;
                color: #F8FAFC;
                font-weight: bold;
                border: 1px solid #334155;
                height: 38px;
                font-size: 12px;
            }
        """)

        # 准则二 铁律 1: 锁死行高 44px
        vh = self.table.verticalHeader()
        vh.setDefaultSectionSize(44)
        vh.setSectionResizeMode(QHeaderView.Fixed)
        vh.setVisible(False)

        # 铁律 2: 列宽分层
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 95)   # 保留单选
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 100)  # 版本标识
        hh.setSectionResizeMode(2, QHeaderView.Stretch) # 路径
        hh.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(3, 90)   # 大小
        hh.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(4, 130)  # 修改时间
        hh.setSectionResizeMode(5, QHeaderView.Fixed)
        self.table.setColumnWidth(5, 120)  # 推荐动作
        hh.setSectionResizeMode(6, QHeaderView.Fixed)
        self.table.setColumnWidth(6, 210)  # 差异研判
        hh.setSectionResizeMode(7, QHeaderView.Fixed)
        self.table.setColumnWidth(7, 100)  # 快捷操作

    def _populate_table(self):
        """填充表格数据"""
        items = self.cluster.items
        self.table.setRowCount(len(items))
        self.radio_group = QButtonGroup(self)

        for row, it in enumerate(items):
            # 0: 单选按钮 (准则二 铁律 3: 28px 居中容器包裹)
            container = QWidget()
            c_layout = QHBoxLayout(container)
            c_layout.setContentsMargins(0, 0, 0, 0)
            c_layout.setAlignment(Qt.AlignCenter)
            radio = QRadioButton("保留")
            radio.setFixedHeight(28)
            radio.setStyleSheet("QRadioButton { color: #F8FAFC; font-weight: bold; }")
            is_checked = (it.path == self.selected_keep_path)
            radio.setChecked(is_checked)
            radio.toggled.connect(lambda checked, p=it.path: self._on_keep_toggled(p, checked))
            self.radio_group.addButton(radio)
            c_layout.addWidget(radio)
            self.table.setCellWidget(row, 0, container)

            # 1: 版本标识
            tag_text = it.version_suffix if it.version_suffix else "基准版本"
            item_tag = QTableWidgetItem(tag_text)
            item_tag.setTextAlignment(Qt.AlignCenter)
            item_tag.setForeground(QBrush(QColor("#38BDF8")))
            self.table.setItem(row, 1, item_tag)

            # 2: 文件名与路径
            item_path = QTableWidgetItem(f"{it.name}\n({it.path})")
            item_path.setToolTip(f"完整路径: {it.path}\n文本摘要: {it.content_snippet or '无'}")
            item_path.setForeground(QBrush(QColor("#F8FAFC")))
            self.table.setItem(row, 2, item_path)

            # 3: 大小
            item_size = QTableWidgetItem(format_size(it.size))
            item_size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            item_size.setForeground(QBrush(QColor("#F8FAFC")))
            self.table.setItem(row, 3, item_size)

            # 4: 修改时间
            m_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(it.mtime)) if it.mtime > 0 else "-"
            item_time = QTableWidgetItem(m_str)
            item_time.setTextAlignment(Qt.AlignCenter)
            item_time.setForeground(QBrush(QColor("#94A3B8")))
            self.table.setItem(row, 4, item_time)

            # 5: 推荐处置动作
            action_text = it.retention_action or "建议归档"
            item_action = QTableWidgetItem(action_text)
            item_action.setTextAlignment(Qt.AlignCenter)
            if "保留" in action_text:
                item_action.setForeground(QBrush(QColor("#10B981"))) # 绿色
            elif "归档" in action_text:
                item_action.setForeground(QBrush(QColor("#FBBF24"))) # 琥珀金
            else:
                item_action.setForeground(QBrush(QColor("#94A3B8")))
            self.table.setItem(row, 5, item_action)

            # 6: 差异与决策依据
            reason_text = it.decision_reason or "-"
            item_reason = QTableWidgetItem(reason_text)
            item_reason.setToolTip(reason_text)
            item_reason.setForeground(QBrush(QColor("#CBD5E1")))
            self.table.setItem(row, 6, item_reason)

            # 7: 快捷操作 (定位/打开 28px 居中容器)
            op_container = QWidget()
            op_layout = QHBoxLayout(op_container)
            op_layout.setContentsMargins(0, 0, 0, 0)
            op_layout.setAlignment(Qt.AlignCenter)
            op_layout.setSpacing(4)

            btn_open = QPushButton("📂")
            btn_open.setToolTip("在文件管理器中定位")
            btn_open.setFixedSize(28, 28)
            btn_open.setStyleSheet("QPushButton { background-color: #334155; border-radius: 4px; } QPushButton:hover { background-color: #475569; }")
            btn_open.clicked.connect(lambda _, p=it.path: self._locate_in_explorer(p))
            op_layout.addWidget(btn_open)

            self.table.setCellWidget(row, 7, op_container)

    def _update_ai_banner(self):
        """刷新 AI 状态卡片"""
        if self.cluster.ai_evaluated:
            self.lbl_status_badge.setText("🤖 AI 核心编排器已完成多版本研判")
            self.lbl_status_badge.setStyleSheet("""
                background-color: #065F46;
                color: #34D399;
                font-weight: bold;
                font-size: 12px;
                border-radius: 4px;
                padding: 3px 8px;
            """)
            self.lbl_summary_text.setText(self.cluster.ai_summary or "各版本演变分析完毕，推荐保留最新/最全正本。")
        else:
            self.lbl_status_badge.setText("⚠️ AI 编排器离线/本地事实模式 (不越权)")
            self.lbl_status_badge.setStyleSheet("""
                background-color: #78350F;
                color: #FBBF24;
                font-weight: bold;
                font-size: 12px;
                border-radius: 4px;
                padding: 3px 8px;
            """)
            self.lbl_summary_text.setText(
                self.cluster.ai_summary or
                "AI 未连接，系统恪守不越权原则，仅为您呈现物理时间与大小对比事实。请自主选择保留项。"
            )

    def _start_ai_evaluation(self):
        """启动后台线程请求 AI 语义比对"""
        self.btn_re_eval.setEnabled(False)
        self.progress_bar.show()
        self.lbl_status_badge.setText("🤖 正在请求 AI 核心编排器研判各版本演进语义...")
        self.lbl_status_badge.setStyleSheet("""
            background-color: #0369A1;
            color: #FFFFFF;
            font-weight: bold;
            font-size: 12px;
            border-radius: 4px;
            padding: 3px 8px;
        """)
        self.lbl_summary_text.setText("正在通过单例 Keep-Alive 连接池上送脱敏特征与文本样本，请稍候...")

        self.worker = VersionDiffWorker(self.cluster, parent=self)
        self.worker.finished_signal.connect(self._on_ai_finished)
        self.worker.failed_signal.connect(self._on_ai_failed)
        self.worker.start()

    def _on_ai_finished(self, decision: SemanticDiffDecision, updated_cluster: VersionClusterGroup):
        self.progress_bar.hide()
        self.btn_re_eval.setEnabled(True)
        self.cluster = updated_cluster
        if updated_cluster.recommended_keep_path:
            self.selected_keep_path = updated_cluster.recommended_keep_path
        self._update_ai_banner()
        self._populate_table()

    def _on_ai_failed(self, err_msg: str):
        self.progress_bar.hide()
        self.btn_re_eval.setEnabled(True)
        self.cluster.ai_evaluated = False
        self.cluster.ai_summary = f"AI 服务异常: {err_msg}。系统恪守不越权原则，已保留本地物理比对事实供您定夺。"
        self._update_ai_banner()
        self._populate_table()

    def _on_keep_toggled(self, path: str, checked: bool):
        if checked:
            self.selected_keep_path = path

    def _locate_in_explorer(self, file_path: str):
        if not file_path or not os.path.exists(file_path):
            return
        try:
            norm_p = os.path.normpath(file_path)
            subprocess.Popen(f'explorer /select,"{norm_p}"')
        except Exception:
            pass

    def _on_apply_clicked(self):
        self.decision_applied.emit(self.cluster, self.selected_keep_path)
        self.accept()
