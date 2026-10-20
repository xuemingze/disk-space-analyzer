"""
app/ui/components/ai_insight_dialog.py
AI 智能资产研判与治理建议对话框
遵循《列表与表格模块 UI 设计铁律》与系统现代化深浅色设计，
为应用管理看板与全量扫描表格提供统一同构的深度 AI 决策辅助。
"""
import os
from typing import Dict, Any, Optional

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QTextEdit, QApplication, QMessageBox,
    QProgressBar
)
from PySide6.QtCore import Qt, QThread, Signal

from app.config import app_config
from app.core.ai_service import AIService
from app.core.asset_promoter import AssetPromoterService
from app.utils.file_helper import format_size


class AIInsightWorker(QThread):
    finished_signal = Signal(dict)
    failed_signal = Signal(str)

    def __init__(self, target_path: str, context_files=None, parent=None):
        super().__init__(parent)
        self.target_path = target_path
        self.context_files = context_files or []

    def run(self):
        try:
            llm_cfg = app_config.get("llm", default={})
            base_url = llm_cfg.get("base_url", "")
            api_key = llm_cfg.get("api_key", "")
            model = llm_cfg.get("model", "gpt-4o-mini")

            result = AIService.analyze_directory_or_app_with_ai(
                base_url=base_url,
                api_key=api_key,
                model=model,
                target_path=self.target_path,
                context_files=self.context_files
            )
            self.finished_signal.emit(result)
        except Exception as e:
            self.failed_signal.emit(str(e))


class AIAssetInsightDialog(QDialog):
    """AI 智能资产研判与治理建议对话框"""

    def __init__(self, asset_item: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.asset_item = dict(asset_item)
        self.worker: Optional[AIInsightWorker] = None
        self.insight_data: Dict[str, Any] = {}

        self.setWindowTitle("🤖 AI 智能资产研判与治理建议")
        self.setMinimumWidth(620)
        self.setStyleSheet("""
            QDialog { background-color: #ffffff; color: #1e293b; }
            QLabel { font-size: 12px; }
        """)
        self._init_ui()
        self._start_analysis()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # 1. 顶部标题栏
        top_bar = QHBoxLayout()
        title_box = QVBoxLayout()
        lbl_title = QLabel("🤖 AI 智能资产研判与治理建议")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1e293b;")
        lbl_sub = QLabel("基于大模型认知与物理事实特征，为您研判应用归属、用途说明与治理方案。")
        lbl_sub.setStyleSheet("color: #64748b; font-size: 12px;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        top_bar.addLayout(title_box)
        top_bar.addStretch()

        self.badge_status = QLabel("⏳ 正在研判")
        self.badge_status.setStyleSheet(
            "background-color: #eff6ff; color: #2563eb; border: 1px solid #bfdbfe; "
            "border-radius: 12px; padding: 4px 12px; font-weight: bold; font-size: 11px;"
        )
        top_bar.addWidget(self.badge_status)
        layout.addLayout(top_bar)

        # 2. 资产基本信息卡片
        info_card = QFrame()
        info_card.setStyleSheet("background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px;")
        ic_layout = QVBoxLayout(info_card)
        ic_layout.setSpacing(6)

        name = self.asset_item.get("name") or self.asset_item.get("software_name") or "未知资产"
        path = self.asset_item.get("path") or self.asset_item.get("install_root") or ""
        size_str = format_size(self.asset_item.get("size", 0))
        cat = self.asset_item.get("category") or self.asset_item.get("suggested_category") or "通用资产"
        fc = self.asset_item.get("file_count", 1)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel(f"<b>📦 资产名称:</b> {name}"))
        row1.addStretch()
        row1.addWidget(QLabel(f"<b>📊 大小:</b> {size_str} ({fc:,} 个文件)"))
        ic_layout.addLayout(row1)

        row2 = QHBoxLayout()
        lbl_p = QLabel(f"<b>📂 路径:</b> <span style='font-family: Consolas;'>{path}</span>")
        lbl_p.setWordWrap(True)
        row2.addWidget(lbl_p, 1)
        btn_copy = QPushButton("复制")
        btn_copy.setFixedSize(48, 22)
        btn_copy.setStyleSheet("font-size: 10px; border: 1px solid #cbd5e1; border-radius: 3px;")
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(path))
        row2.addWidget(btn_copy)
        ic_layout.addLayout(row2)

        layout.addWidget(info_card)

        # 3. 研判进度指示条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #4f46e5; }")
        layout.addWidget(self.progress_bar)

        # 4. AI 研判详情卡片
        self.ai_card = QFrame()
        self.ai_card.setStyleSheet("background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px; padding: 12px;")
        ac_layout = QVBoxLayout(self.ai_card)
        ac_layout.setSpacing(8)

        self.lbl_ai_name = QLabel("🏷️ <b>官方标准名称:</b> 识别中...")
        self.lbl_ai_pub = QLabel("🏢 <b>开发商/发布主体:</b> 识别中...")
        self.lbl_ai_cat = QLabel("📑 <b>推荐所属分类:</b> 识别中...")
        self.lbl_ai_risk = QLabel("🛡️ <b>安全风险等级:</b> 评估中...")
        self.lbl_ai_action = QLabel("💡 <b>治理建议动作:</b> 研判中...")

        ac_layout.addWidget(self.lbl_ai_name)
        ac_layout.addWidget(self.lbl_ai_pub)
        ac_layout.addWidget(self.lbl_ai_cat)
        ac_layout.addWidget(self.lbl_ai_risk)
        ac_layout.addWidget(self.lbl_ai_action)

        lbl_desc_title = QLabel("📝 <b>核心应用功能与用途说明:</b>")
        self.txt_desc = QTextEdit()
        self.txt_desc.setReadOnly(True)
        self.txt_desc.setFixedHeight(75)
        self.txt_desc.setPlaceholderText("正在调用大模型生成用途与功能研判...")
        self.txt_desc.setStyleSheet("background-color: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 4px; padding: 6px; font-size: 11px;")

        ac_layout.addWidget(lbl_desc_title)
        ac_layout.addWidget(self.txt_desc)
        layout.addWidget(self.ai_card)

        # 5. 底部动作条
        bottom_bar = QHBoxLayout()
        self.btn_promote = QPushButton("✨ 沉淀为独立应用规则")
        self.btn_promote.setFixedHeight(32)
        self.btn_promote.setStyleSheet(
            "background-color: #16a34a; color: white; font-weight: bold; border-radius: 4px; padding: 0 14px;"
        )
        self.btn_promote.clicked.connect(self._on_promote_clicked)

        bottom_bar.addWidget(self.btn_promote)
        bottom_bar.addStretch()

        btn_close = QPushButton("关闭")
        btn_close.setFixedHeight(32)
        btn_close.setFixedWidth(70)
        btn_close.setStyleSheet("border: 1px solid #cbd5e1; border-radius: 4px;")
        btn_close.clicked.connect(self.accept)
        bottom_bar.addWidget(btn_close)

        layout.addLayout(bottom_bar)

    def _start_analysis(self):
        target_path = self.asset_item.get("path") or self.asset_item.get("install_root") or ""
        self.worker = AIInsightWorker(target_path, parent=self)
        self.worker.finished_signal.connect(self._on_analysis_finished)
        self.worker.failed_signal.connect(self._on_analysis_failed)
        self.worker.start()

    def _on_analysis_finished(self, result: Dict[str, Any]):
        self.insight_data = result
        self.progress_bar.setVisible(False)

        is_ai = result.get("ai_generated", False)
        status_text = "✅ AI 研判完成" if is_ai else "⚡ 本地先验推断"
        self.badge_status.setText(status_text)
        self.badge_status.setStyleSheet(
            "background-color: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; "
            "border-radius: 12px; padding: 4px 12px; font-weight: bold; font-size: 11px;"
        )

        self.lbl_ai_name.setText(f"🏷️ <b>官方标准名称:</b> {result.get('official_name', '未知')}")
        self.lbl_ai_pub.setText(f"🏢 <b>开发商/发布主体:</b> {result.get('publisher', '未知')}")
        self.lbl_ai_cat.setText(f"📑 <b>推荐所属分类:</b> {result.get('suggested_category', '通用分类')}")

        risk = result.get("risk_level", "低风险")
        risk_color = "#16a34a" if "低" in risk else ("#ea580c" if "确认" in risk else "#dc2626")
        self.lbl_ai_risk.setText(f"🛡️ <b>安全风险等级:</b> <span style='color: {risk_color}; font-weight: bold;'>{risk}</span>")

        action = result.get("action_recommendation", "保留")
        self.lbl_ai_action.setText(f"💡 <b>治理建议动作:</b> <span style='font-weight: bold;'>{action}</span> (建议归档: {result.get('recommended_subpath', '-')})")

        self.txt_desc.setText(result.get("purpose_description", "无特定描述"))

    def _on_analysis_failed(self, err_msg: str):
        self.progress_bar.setVisible(False)
        self.badge_status.setText("⚠️ 研判异常")
        self.badge_status.setStyleSheet("background-color: #fee2e2; color: #dc2626; border-radius: 12px; padding: 4px 12px;")
        self.txt_desc.setText(f"获取 AI 研判失败: {err_msg}")

    def _on_promote_clicked(self):
        target_path = self.asset_item.get("path") or self.asset_item.get("install_root") or ""
        if not target_path or not os.path.exists(target_path):
            QMessageBox.warning(self, "提示", "物理目录不存在，无法沉淀！")
            return
        app_name = self.insight_data.get("official_name") or self.asset_item.get("name") or os.path.basename(target_path)
        AssetPromoterService.persist_collective(target_path)
        QMessageBox.information(self, "沉淀成功", f"✅ 已成功将 [{app_name}] 沉淀为独立应用规则！")
        self.accept()
