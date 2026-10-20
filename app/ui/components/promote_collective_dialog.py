"""
app/ui/components/promote_collective_dialog.py
智能父级路径推断单选弹窗
支持一键将零散资产向上收拢为原子集合，并就地沉淀为长期规则
"""
import os
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton,
    QButtonGroup, QLineEdit, QPushButton, QGroupBox, QFileDialog,
    QMessageBox, QFrame
)
from PySide6.QtCore import Qt

from app.core.asset_promoter import AssetPromoterService


class PromoteCollectiveDialog(QDialog):
    """智能父级推断与转为集合弹窗"""

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = os.path.normpath(file_path)
        self.selected_target_dir: str = ""
        self.app_name: str = ""

        self.setWindowTitle("📦 向上收拢并转为资产集合")
        self.setMinimumWidth(600)
        self.setStyleSheet("""
            QDialog { background-color: #ffffff; color: #1e293b; }
            QGroupBox { font-weight: bold; color: #334155; margin-top: 12px; }
            QRadioButton { font-size: 13px; color: #334155; padding: 4px; }
            QRadioButton::indicator:checked { background-color: #2563eb; border: 2px solid #2563eb; }
        """)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # 头部说明
        title = QLabel("📦 调整目录层级并转为原子实体集合")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1e293b;")
        desc = QLabel(
            "当前项属于散碎独立资产，系统已自动解析其各级父目录拓扑。\n"
            "选择合适的软件根目录后，该目录下所有碎片将秒级打包为单一应用集合并沉淀为系统规则。"
        )
        desc.setStyleSheet("font-size: 12px; color: #64748b; line-height: 140%;")
        layout.addWidget(title)
        layout.addWidget(desc)

        # 当前文件路径提示卡片
        path_box = QFrame()
        path_box.setStyleSheet("background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 8px;")
        pb_layout = QVBoxLayout(path_box)
        pb_layout.setContentsMargins(6, 6, 6, 6)
        lbl_curr = QLabel(f"当前选定条目:\n{self.file_path}")
        lbl_curr.setStyleSheet("font-size: 11px; color: #475569; font-family: Consolas, monospace;")
        lbl_curr.setWordWrap(True)
        pb_layout.addWidget(lbl_curr)
        layout.addWidget(path_box)

        # 智能父级候选组
        group_box = QGroupBox("智能推断父级候选目录 (单选推荐根)")
        g_layout = QVBoxLayout(group_box)
        g_layout.setSpacing(10)

        self.btn_group = QButtonGroup(self)
        candidates = AssetPromoterService.infer_parent_candidates(self.file_path)

        self.radio_widgets = []
        if candidates:
            for idx, cand in enumerate(candidates):
                p_str = cand["path"]
                name = cand["name"]
                is_rec = cand["is_recommended"]
                reason = cand["reason"]

                r_container = QWidget()
                r_box = QVBoxLayout(r_container)
                r_box.setContentsMargins(0, 0, 0, 0)
                r_box.setSpacing(2)

                radio = QRadioButton(f"{p_str}")
                radio.setProperty("target_dir", p_str)
                radio.setProperty("app_name", name)

                lbl_reason = QLabel(f"   ↳ {reason}")
                if is_rec:
                    lbl_reason.setStyleSheet("color: #16a34a; font-weight: bold; font-size: 11px;")
                    radio.setStyleSheet("font-weight: bold; color: #1d4ed8;")
                else:
                    lbl_reason.setStyleSheet("color: #94a3b8; font-size: 11px;")

                r_box.addWidget(radio)
                r_box.addWidget(lbl_reason)
                g_layout.addWidget(r_container)
                self.btn_group.addButton(radio, idx)
                self.radio_widgets.append(radio)

                radio.toggled.connect(lambda checked, r=radio: self._on_radio_toggled(r, checked))

            # 默认选中第一个候选 (推荐项排在最前)
            self.radio_widgets[0].setChecked(True)
        else:
            lbl_none = QLabel("未找到适宜的父目录候选，请在下方手动指定")
            lbl_none.setStyleSheet("color: #ef4444;")
            g_layout.addWidget(lbl_none)

        layout.addWidget(group_box)

        # 自定义路径与名称编辑栏
        edit_group = QGroupBox("集合属性确认")
        e_layout = QVBoxLayout(edit_group)
        e_layout.setSpacing(8)

        # 集合名称
        name_row = QHBoxLayout()
        name_lbl = QLabel("🏷️ 集合外显名称:")
        name_lbl.setFixedWidth(110)
        self.txt_name = QLineEdit()
        self.txt_name.setFixedHeight(30)
        self.btn_ai_suggest = QPushButton("🤖 AI 智能研判推荐")
        self.btn_ai_suggest.setFixedHeight(30)
        self.btn_ai_suggest.setStyleSheet(
            "QPushButton { background-color: #4f46e5; color: white; border-radius: 4px; font-weight: bold; padding: 0 10px; font-size: 11px; }"
            "QPushButton:hover { background-color: #4338ca; }"
        )
        self.btn_ai_suggest.clicked.connect(self._on_ai_suggest_clicked)

        name_row.addWidget(name_lbl)
        name_row.addWidget(self.txt_name, 1)
        name_row.addWidget(self.btn_ai_suggest)
        e_layout.addLayout(name_row)

        self.lbl_ai_hint = QLabel("")
        self.lbl_ai_hint.setStyleSheet("color: #16a34a; font-size: 11px; padding-left: 110px;")
        e_layout.addWidget(self.lbl_ai_hint)

        # 集合物理目录
        dir_row = QHBoxLayout()
        dir_lbl = QLabel("📂 集合根目录:")
        dir_lbl.setFixedWidth(110)
        self.txt_dir = QLineEdit()
        self.txt_dir.setFixedHeight(30)
        btn_browse = QPushButton("浏览...")
        btn_browse.setFixedHeight(30)
        btn_browse.clicked.connect(self._on_browse_clicked)
        dir_row.addWidget(dir_lbl)
        dir_row.addWidget(self.txt_dir)
        dir_row.addWidget(btn_browse)
        e_layout.addLayout(dir_row)

        layout.addWidget(edit_group)

        # 底部操作按钮
        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch()

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setFixedHeight(32)
        self.btn_cancel.setFixedWidth(80)
        self.btn_cancel.setStyleSheet("border: 1px solid #cbd5e1; border-radius: 4px;")
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_confirm = QPushButton("✨ 确认收拢并沉淀")
        self.btn_confirm.setFixedHeight(32)
        self.btn_confirm.setStyleSheet(
            "background-color: #2563eb; color: white; font-weight: bold; border-radius: 4px; padding: 0 16px;"
        )
        self.btn_confirm.clicked.connect(self._on_confirm_clicked)

        bottom_bar.addWidget(self.btn_cancel)
        bottom_bar.addWidget(self.btn_confirm)
        layout.addLayout(bottom_bar)

        if candidates:
            self._on_radio_toggled(self.radio_widgets[0], True)

    def _on_radio_toggled(self, radio: QRadioButton, checked: bool):
        if checked:
            target_p = radio.property("target_dir")
            name = radio.property("app_name")
            self.txt_dir.setText(target_p)
            self.txt_name.setText(name)

    def _on_browse_clicked(self):
        d = QFileDialog.getExistingDirectory(self, "选择集合根目录", self.txt_dir.text() or self.file_path)
        if d:
            norm_d = os.path.normpath(d)
            self.txt_dir.setText(norm_d)
            self.txt_name.setText(os.path.basename(norm_d))
            # 取消单选框高亮
            for r in self.radio_widgets:
                r.setAutoExclusive(False)
                r.setChecked(False)
                r.setAutoExclusive(True)

    def _on_ai_suggest_clicked(self):
        target_dir = self.txt_dir.text().strip()
        if not target_dir or not os.path.exists(target_dir):
            QMessageBox.warning(self, "提示", "请先选择有效的集合物理根目录！")
            return

        self.btn_ai_suggest.setEnabled(False)
        self.btn_ai_suggest.setText("⏳ AI 研判中...")
        self.lbl_ai_hint.setText("正在调用大模型分析应用名称与所属分类...")

        try:
            from app.config import app_config
            from app.core.ai_service import AIService
            llm_cfg = app_config.get("llm", default={})
            res = AIService.analyze_directory_or_app_with_ai(
                base_url=llm_cfg.get("base_url", ""),
                api_key=llm_cfg.get("api_key", ""),
                model=llm_cfg.get("model", "gpt-4o-mini"),
                target_path=target_dir
            )
            rec_name = res.get("official_name") or os.path.basename(target_dir)
            self.txt_name.setText(rec_name)
            desc = res.get("purpose_description", "")
            cat = res.get("suggested_category", "")
            self.lbl_ai_hint.setText(f"💡 AI 研判: [{rec_name}] | {cat} | {desc[:40]}...")
        except Exception as e:
            self.lbl_ai_hint.setText(f"AI 研判失败: {e}")
        finally:
            self.btn_ai_suggest.setEnabled(True)
            self.btn_ai_suggest.setText("🤖 AI 智能研判推荐")

    def _on_confirm_clicked(self):
        d = self.txt_dir.text().strip()
        n = self.txt_name.text().strip()

        if not d or not os.path.exists(d):
            QMessageBox.warning(self, "提示", "请选择有效的集合物理根目录！")
            return
        if not n:
            QMessageBox.warning(self, "提示", "请输入集合外显名称！")
            return

        self.selected_target_dir = os.path.normpath(d)
        self.app_name = n
        self.accept()
