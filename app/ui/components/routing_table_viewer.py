"""
全局拓扑路由知识库与自省管理视图 (Topology Routing Table Viewer & AI Auditor)
遵循面向对象设计原则与全域 UI 铁律（44px 固定行高、深色沉浸主题、防清空重写、导入/导出）。

包含：
1. AIAuditPolicyDialog: 人为操控的 AI 审查机制与自定义 Prompt 策略配置
2. RoutingRuleEditDialog: 强类型主路由规则新增/编辑对话框
3. RoutingTableViewerDialog: 全局拓扑路由规则可视化自省与管理对话框
"""

import os
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QFileDialog, QFrame, QComboBox, QTextEdit, QDoubleSpinBox,
    QCheckBox, QWidget, QSplitter
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush, QFont

from app.core.domain_models import (
    TopologyRoutingTable, MasterRoutingRule, MorphologyType, KnowledgeProvenance,
    TopologyRole, AIAuditPolicyConfig
)


class AIAuditPolicyDialog(QDialog):
    """
    AI 审查机制与自定义 Prompt 策略配置对话框
    支持人为操控 AI 审查规则、调整置信度阈值、启用/禁用中转剥离与注入专属 Prompt
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ AI 审查机制与自省策略配置")
        self.resize(580, 480)
        self.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
                color: #F8FAFC;
            }
            QLabel {
                color: #E2E8F0;
                font-size: 12px;
            }
            QLineEdit, QTextEdit, QDoubleSpinBox {
                background-color: #1E293B;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 6px;
            }
            QLineEdit:focus, QTextEdit:focus, QDoubleSpinBox:focus {
                border-color: #38BDF8;
            }
            QCheckBox {
                color: #E2E8F0;
                font-size: 13px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 1px solid #475569;
                border-radius: 3px;
                background-color: #1E293B;
            }
            QCheckBox::indicator:checked {
                background-color: #0284C7;
                border-color: #38BDF8;
            }
            QPushButton {
                background-color: #1E293B;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #334155;
                border-color: #38BDF8;
            }
            QPushButton#btn_save {
                background-color: #0284C7;
                color: #FFFFFF;
                font-weight: bold;
                border-color: #0369A1;
            }
            QPushButton#btn_save:hover {
                background-color: #0369A1;
            }
        """)
        self.config = AIAuditPolicyConfig.get_instance()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        title_lbl = QLabel("AI 核心编排审核与自省控制台")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #38BDF8;")
        layout.addWidget(title_lbl)

        desc_lbl = QLabel("配置 AI 自动审查算法。AI 负责对扫描路径进行深度语义研判与纠偏，并反哺主路由表。")
        desc_lbl.setStyleSheet("color: #94A3B8; font-size: 12px;")
        desc_lbl.setWordWrap(True)
        layout.addWidget(desc_lbl)

        # 选项 1: 启用审查
        self.chk_enabled = QCheckBox("启用 AI 智能审查机制 (AI Audit Engine Enabled)")
        self.chk_enabled.setChecked(self.config.enabled)
        layout.addWidget(self.chk_enabled)

        # 选项 2: 严格剥离中转名
        self.chk_strip = QCheckBox("严格剥离原材料与中转容器名 (如 '共用文件', 'Downloads', '待分类')")
        self.chk_strip.setChecked(self.config.strict_strip_staging_containers)
        layout.addWidget(self.chk_strip)

        # 选项 3: 置信度阈值
        conf_row = QHBoxLayout()
        conf_lbl = QLabel("AI 审查与自沉淀置信度阈值 (Confidence Threshold):")
        self.spin_conf = QDoubleSpinBox()
        self.spin_conf.setRange(0.10, 1.00)
        self.spin_conf.setSingleStep(0.05)
        self.spin_conf.setValue(self.config.confidence_threshold)
        self.spin_conf.setFixedWidth(100)
        conf_row.addWidget(conf_lbl)
        conf_row.addStretch()
        conf_row.addWidget(self.spin_conf)
        layout.addLayout(conf_row)

        # 选项 4: 自定义 AI 审查 Prompt
        prompt_lbl = QLabel("自定义 AI 审查与自省提示词 (Prompt):")
        layout.addWidget(prompt_lbl)

        self.txt_prompt = QTextEdit()
        self.txt_prompt.setPlaceholderText("可填入企业专属或个人自定义归档审计准则（例如：禁止在路径中保留临时批次编号，统一使用年-月归类等）")
        self.txt_prompt.setText(self.config.custom_instruction_prompt)
        self.txt_prompt.setMinimumHeight(120)
        layout.addWidget(self.txt_prompt)

        # 底部按钮栏
        btn_bar = QHBoxLayout()
        btn_reset = QPushButton("恢复默认")
        btn_reset.clicked.connect(self._reset_defaults)
        btn_bar.addWidget(btn_reset)

        btn_bar.addStretch()

        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_bar.addWidget(btn_cancel)

        btn_save = QPushButton("保存并立即生效")
        btn_save.setObjectName("btn_save")
        btn_save.clicked.connect(self._save)
        btn_bar.addWidget(btn_save)

        layout.addLayout(btn_bar)

    def _reset_defaults(self):
        self.chk_enabled.setChecked(True)
        self.chk_strip.setChecked(True)
        self.spin_conf.setValue(0.80)
        self.txt_prompt.setPlainText("")

    def _save(self):
        self.config.enabled = self.chk_enabled.isChecked()
        self.config.strict_strip_staging_containers = self.chk_strip.isChecked()
        self.config.confidence_threshold = round(self.spin_conf.value(), 2)
        self.config.custom_instruction_prompt = self.txt_prompt.toPlainText().strip()
        self.config.save()
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            QMessageBox.information(self, "配置已保存", "AI 审查与自省策略配置已保存并立即生效。")
        self.accept()


class RoutingRuleEditDialog(QDialog):
    """
    强类型主路由规则添加/编辑对话框
    """
    def __init__(self, rule: Optional[MasterRoutingRule] = None, parent=None):
        super().__init__(parent)
        self.rule = rule
        self.is_edit = rule is not None
        self.setWindowTitle("✏️ 编辑拓扑主路由规则" if self.is_edit else "➕ 新增拓扑主路由规则")
        self.resize(540, 420)
        self.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
                color: #F8FAFC;
            }
            QLabel {
                color: #E2E8F0;
                font-size: 12px;
                min-width: 90px;
            }
            QLineEdit, QComboBox {
                background-color: #1E293B;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 6px;
                font-size: 12px;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #38BDF8;
            }
            QPushButton {
                background-color: #1E293B;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 8px 18px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #334155;
                border-color: #38BDF8;
            }
            QPushButton#btn_ok {
                background-color: #0284C7;
                color: #FFFFFF;
                font-weight: bold;
                border-color: #0369A1;
            }
        """)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        title = "编辑主路由规则" if self.is_edit else "新增主路由规则"
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #38BDF8;")
        layout.addWidget(title_lbl)

        # 1. 特征匹配模式
        row_pat = QHBoxLayout()
        lbl_pat = QLabel("特征匹配模式:")
        self.edt_pattern = QLineEdit(self.rule.pattern if self.rule else "")
        self.edt_pattern.setPlaceholderText("例如: MotrixNext_*.exe, node_modules, WeChat.exe")
        row_pat.addWidget(lbl_pat)
        row_pat.addWidget(self.edt_pattern)
        layout.addLayout(row_pat)

        # 2. 资产形态
        row_morph = QHBoxLayout()
        lbl_morph = QLabel("资产形态:")
        self.cbo_morph = QComboBox()
        self.cbo_morph.addItem("独立资产 (INDEPENDENT_ASSET)", MorphologyType.INDEPENDENT_ASSET)
        self.cbo_morph.addItem("密封集合 (SEALED_COLLECTIVE)", MorphologyType.SEALED_COLLECTIVE)
        self.cbo_morph.addItem("离散媒体 (LOOSE_MEDIA)", MorphologyType.LOOSE_MEDIA)
        if self.rule:
            for idx in range(self.cbo_morph.count()):
                if self.cbo_morph.itemData(idx) == self.rule.morphology:
                    self.cbo_morph.setCurrentIndex(idx)
                    break
        row_morph.addWidget(lbl_morph)
        row_morph.addWidget(self.cbo_morph)
        layout.addLayout(row_morph)

        # 3. 拓扑角色
        row_role = QHBoxLayout()
        lbl_role = QLabel("拓扑角色:")
        self.cbo_role = QComboBox()
        self.cbo_role.addItem("独立软件集体 (APP_COLLECTIVE)", TopologyRole.APP_COLLECTIVE)
        self.cbo_role.addItem("中转容器 (STAGING_BUCKET)", TopologyRole.STAGING_BUCKET)
        if self.rule:
            for idx in range(self.cbo_role.count()):
                if self.cbo_role.itemData(idx) == self.rule.topology_role:
                    self.cbo_role.setCurrentIndex(idx)
                    break
        row_role.addWidget(lbl_role)
        row_role.addWidget(self.cbo_role)
        layout.addLayout(row_role)

        # 4. PE签名 / 发布者
        row_pe = QHBoxLayout()
        lbl_pe = QLabel("PE特征/发布者:")
        self.edt_pe = QLineEdit(self.rule.pe_signature if self.rule and self.rule.pe_signature else "")
        self.edt_pe.setPlaceholderText("可选，如 Tencent, Microsoft Corporation, Adobe")
        row_pe.addWidget(lbl_pe)
        row_pe.addWidget(self.edt_pe)
        layout.addLayout(row_pe)

        # 5. 建议归档分类
        row_cat = QHBoxLayout()
        lbl_cat = QLabel("建议归档分类:")
        self.edt_cat = QLineEdit(self.rule.target_category if self.rule else "")
        self.edt_cat.setPlaceholderText("例如: 软件安装与程序 (Apps & Installers)")
        row_cat.addWidget(lbl_cat)
        row_cat.addWidget(self.edt_cat)
        layout.addLayout(row_cat)

        # 6. 规划路径模板
        row_tpl = QHBoxLayout()
        lbl_tpl = QLabel("规划路径模板:")
        self.edt_tpl = QLineEdit(self.rule.target_subpath_template if self.rule else "")
        self.edt_tpl.setPlaceholderText("可选细分子路径，如: 工具/网络传输")
        row_tpl.addWidget(lbl_tpl)
        row_tpl.addWidget(self.edt_tpl)
        layout.addLayout(row_tpl)

        # 7. 知识来源
        row_prov = QHBoxLayout()
        lbl_prov = QLabel("知识来源:")
        self.cbo_prov = QComboBox()
        self.cbo_prov.addItem("用户确认 (USER_CONFIRMED - P1顶格锁定)", KnowledgeProvenance.USER_CONFIRMED)
        self.cbo_prov.addItem("AI自学 (AI_LEARNED - P2)", KnowledgeProvenance.AI_LEARNED)
        self.cbo_prov.addItem("系统内置 (SYSTEM_BUILTIN - P3)", KnowledgeProvenance.SYSTEM_BUILTIN)
        if self.rule:
            for idx in range(self.cbo_prov.count()):
                if self.cbo_prov.itemData(idx) == self.rule.provenance:
                    self.cbo_prov.setCurrentIndex(idx)
                    break
        else:
            self.cbo_prov.setCurrentIndex(0)  # 手动添加默认 USER_CONFIRMED
        row_prov.addWidget(lbl_prov)
        row_prov.addWidget(self.cbo_prov)
        layout.addLayout(row_prov)

        layout.addStretch()

        # 底部按钮
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_bar.addWidget(btn_cancel)

        btn_ok = QPushButton("确定保存")
        btn_ok.setObjectName("btn_ok")
        btn_ok.clicked.connect(self._on_confirm)
        btn_bar.addWidget(btn_ok)

        layout.addLayout(btn_bar)

    def _on_confirm(self):
        pat = self.edt_pattern.text().strip()
        cat = self.edt_cat.text().strip()
        if not pat:
            QMessageBox.warning(self, "校验失败", "特征匹配模式不能为空。")
            return
        if not cat:
            QMessageBox.warning(self, "校验失败", "建议归档分类不能为空。")
            return

        import uuid
        rule_id = self.rule.rule_id if self.rule else str(uuid.uuid4())[:8]
        hit_count = self.rule.hit_count if self.rule else 1

        raw_morph = self.cbo_morph.currentData()
        raw_role = self.cbo_role.currentData()
        raw_prov = self.cbo_prov.currentData()

        self.result_rule = MasterRoutingRule(
            rule_id=rule_id,
            pattern=pat,
            pe_signature=self.edt_pe.text().strip(),
            morphology=MorphologyType(raw_morph) if not isinstance(raw_morph, MorphologyType) else raw_morph,
            topology_role=TopologyRole(raw_role) if not isinstance(raw_role, TopologyRole) else raw_role,
            target_category=cat,
            target_subpath_template=self.edt_tpl.text().strip(),
            provenance=KnowledgeProvenance(raw_prov) if not isinstance(raw_prov, KnowledgeProvenance) else raw_prov,
            hit_count=hit_count,
            updated_at=time.time()
        )
        self.accept()


class RoutingTableViewerDialog(QDialog):
    """
    全局拓扑路由知识库与自省管理对话框 (QDialog)
    遵循 GUI 铁律：
    1. verticalHeader().setDefaultSectionSize(44) + Fixed
    2. 深色沉浸质感主题
    3. 支持导入 (Import)、导出 (Export)、新增、编辑、删除主路由规则
    4. 支持配置 AI 审查策略与自定义 Prompt
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🌐 全局拓扑路由知识库与自省管理")
        self.resize(1060, 640)
        self.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
                color: #F8FAFC;
            }
            QLabel {
                color: #E2E8F0;
                font-size: 12px;
            }
            QLineEdit, QComboBox {
                background-color: #1E293B;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 12px;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #38BDF8;
            }
            QPushButton {
                background-color: #1E293B;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #334155;
                border-color: #38BDF8;
            }
            QPushButton#btn_add {
                background-color: #0284C7;
                color: #FFFFFF;
                font-weight: bold;
                border-color: #0369A1;
            }
            QPushButton#btn_add:hover {
                background-color: #0369A1;
            }
            QTableWidget {
                background-color: #0B1120;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 4px;
                gridline-color: #1E293B;
                selection-background-color: #1E3A8A;
                selection-color: #FFFFFF;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #1E293B;
                color: #94A3B8;
                font-weight: bold;
                font-size: 12px;
                padding: 6px;
                border: none;
                border-right: 1px solid #334155;
                border-bottom: 1px solid #334155;
            }
        """)
        self.routing_table = TopologyRoutingTable.instance()
        self.init_ui()
        self.refresh_table()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(12)

        # 1. 顶部标题栏与全局统计
        top_bar = QHBoxLayout()
        title_box = QVBoxLayout()
        lbl_title = QLabel("🌐 全局拓扑路由知识库与自省管理")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #38BDF8;")
        self.lbl_stats = QLabel("当前主规则: 0 条")
        self.lbl_stats.setStyleSheet("color: #94A3B8; font-size: 12px;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(self.lbl_stats)
        top_bar.addLayout(title_box)

        top_bar.addStretch()

        self.btn_ai_audit = QPushButton("⚙️ AI 审查配置")
        self.btn_ai_audit.setToolTip("配置 AI 审查策略、置信度阈值与自定义 Prompt")
        self.btn_ai_audit.clicked.connect(self._open_ai_audit_policy)
        top_bar.addWidget(self.btn_ai_audit)

        self.btn_import = QPushButton("📥 导入规则")
        self.btn_import.setToolTip("从 JSON 文件导入主路由表 (支持增量合并或完全覆盖)")
        self.btn_import.clicked.connect(self._import_rules)
        top_bar.addWidget(self.btn_import)

        self.btn_export = QPushButton("📤 导出规则")
        self.btn_export.setToolTip("将全量主路由表与拓扑规则导出为标准 JSON 备份")
        self.btn_export.clicked.connect(self._export_rules)
        top_bar.addWidget(self.btn_export)

        self.btn_refresh = QPushButton("🔄 刷新")
        self.btn_refresh.clicked.connect(self.refresh_table)
        top_bar.addWidget(self.btn_refresh)

        main_layout.addLayout(top_bar)

        # 2. 过滤与操作工具栏
        filter_bar = QHBoxLayout()
        self.edt_search = QLineEdit()
        self.edt_search.setPlaceholderText("🔍 搜索特征模式、分类、角色或发布者...")
        self.edt_search.textChanged.connect(self.refresh_table)
        filter_bar.addWidget(self.edt_search, 2)

        self.cbo_prov_filter = QComboBox()
        self.cbo_prov_filter.addItem("全部来源", "")
        self.cbo_prov_filter.addItem("用户确认 (USER_CONFIRMED)", KnowledgeProvenance.USER_CONFIRMED.value)
        self.cbo_prov_filter.addItem("AI自学 (AI_LEARNED)", KnowledgeProvenance.AI_LEARNED.value)
        self.cbo_prov_filter.addItem("系统内置 (SYSTEM_BUILTIN)", KnowledgeProvenance.SYSTEM_BUILTIN.value)
        self.cbo_prov_filter.currentIndexChanged.connect(self.refresh_table)
        filter_bar.addWidget(self.cbo_prov_filter, 1)

        self.cbo_morph_filter = QComboBox()
        self.cbo_morph_filter.addItem("全部形态", "")
        self.cbo_morph_filter.addItem("独立资产", MorphologyType.INDEPENDENT_ASSET.value)
        self.cbo_morph_filter.addItem("密封集合", MorphologyType.SEALED_COLLECTIVE.value)
        self.cbo_morph_filter.addItem("离散媒体", MorphologyType.LOOSE_MEDIA.value)
        self.cbo_morph_filter.currentIndexChanged.connect(self.refresh_table)
        filter_bar.addWidget(self.cbo_morph_filter, 1)

        filter_bar.addSpacing(10)

        self.btn_add = QPushButton("➕ 新增规则")
        self.btn_add.setObjectName("btn_add")
        self.btn_add.clicked.connect(self._add_rule)
        filter_bar.addWidget(self.btn_add)

        self.btn_edit = QPushButton("✏️ 编辑选中")
        self.btn_edit.clicked.connect(self._edit_selected_rule)
        filter_bar.addWidget(self.btn_edit)

        self.btn_delete = QPushButton("🗑️ 删除选中")
        self.btn_delete.clicked.connect(self._delete_selected_rule)
        filter_bar.addWidget(self.btn_delete)

        main_layout.addLayout(filter_bar)

        # 3. 主路由规则表格
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "特征模式 (Pattern)", "资产形态", "拓扑角色", "PE特征 / 发布者",
            "建议分类 (Category)", "规划子路径模板", "知识来源 (Provenance)", "命中 / 时间"
        ])

        # 严格执行 44px 行高铁律
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)

        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit_selected_rule)

        # 列宽策略
        h_header = self.table.horizontalHeader()
        h_header.setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.setColumnWidth(0, 180)  # Pattern
        h_header.setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.setColumnWidth(1, 90)   # Morphology
        h_header.setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.setColumnWidth(2, 110)  # Role
        h_header.setSectionResizeMode(3, QHeaderView.Interactive)
        self.table.setColumnWidth(3, 130)  # PE
        h_header.setSectionResizeMode(4, QHeaderView.Interactive)
        self.table.setColumnWidth(4, 160)  # Category
        h_header.setSectionResizeMode(5, QHeaderView.Stretch)      # Subpath
        h_header.setSectionResizeMode(6, QHeaderView.Interactive)
        self.table.setColumnWidth(6, 120)  # Provenance
        h_header.setSectionResizeMode(7, QHeaderView.Interactive)
        self.table.setColumnWidth(7, 110)  # Hits & time

        main_layout.addWidget(self.table, 1)

        # 4. 底部说明与关闭栏
        bottom_bar = QHBoxLayout()
        tip_lbl = QLabel("🛡️ 铁律说明：用户就地手动修改的规则具有最高优先级 (USER_CONFIRMED)，绝对锁定且永不被 AI 自学覆盖。")
        tip_lbl.setStyleSheet("color: #38BDF8; font-size: 11px;")
        bottom_bar.addWidget(tip_lbl)
        bottom_bar.addStretch()

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        bottom_bar.addWidget(btn_close)

        main_layout.addLayout(bottom_bar)

    def refresh_table(self):
        """重新加载主路由规则并刷新表格呈现"""
        rules = self.routing_table.get_master_rules()
        search_kw = self.edt_search.text().strip().lower()
        prov_filter = self.cbo_prov_filter.currentData()
        morph_filter = self.cbo_morph_filter.currentData()

        filtered_rules: List[MasterRoutingRule] = []
        user_conf_count = 0
        ai_learned_count = 0
        sys_builtin_count = 0

        for r in rules:
            if r.provenance == KnowledgeProvenance.USER_CONFIRMED:
                user_conf_count += 1
            elif r.provenance == KnowledgeProvenance.AI_LEARNED:
                ai_learned_count += 1
            else:
                sys_builtin_count += 1

            prov_val = r.provenance.value if isinstance(r.provenance, KnowledgeProvenance) else str(r.provenance)
            morph_val = r.morphology.value if isinstance(r.morphology, MorphologyType) else str(r.morphology)
            role_val = r.topology_role.value if isinstance(r.topology_role, TopologyRole) else str(r.topology_role)

            if prov_filter and prov_val != prov_filter:
                continue
            if morph_filter and morph_val != morph_filter:
                continue
            if search_kw:
                matchable = f"{r.pattern} {r.target_category} {r.target_subpath_template} {r.pe_signature or ''} {role_val}".lower()
                if search_kw not in matchable:
                    continue
            filtered_rules.append(r)

        self.lbl_stats.setText(
            f"主规则总计: <b>{len(rules)}</b> 条 (当前筛选呈现: {len(filtered_rules)} 条) | "
            f"<span style='color: #F59E0B;'>用户锁定: {user_conf_count}</span> | "
            f"<span style='color: #38BDF8;'>AI自学: {ai_learned_count}</span> | "
            f"<span style='color: #94A3B8;'>内置: {sys_builtin_count}</span>"
        )

        self.table.setRowCount(len(filtered_rules))
        for row_idx, r in enumerate(filtered_rules):
            # Col 0: Pattern
            item_pat = QTableWidgetItem(f"🏷️ {r.pattern}")
            item_pat.setData(Qt.UserRole, r)
            item_pat.setToolTip(f"规则 ID: {r.rule_id}\n模式: {r.pattern}")
            self.table.setItem(row_idx, 0, item_pat)

            # Col 1: Morphology
            morph_labels = {
                MorphologyType.INDEPENDENT_ASSET: "独立资产",
                MorphologyType.SEALED_COLLECTIVE: "密封集合",
                MorphologyType.LOOSE_MEDIA: "离散媒体"
            }
            morph_fallback = r.morphology.value if isinstance(r.morphology, MorphologyType) else str(r.morphology)
            item_morph = QTableWidgetItem(morph_labels.get(r.morphology, morph_fallback))
            item_morph.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 1, item_morph)

            # Col 2: Role
            role_labels = {
                TopologyRole.APP_COLLECTIVE: "软件集体",
                TopologyRole.STAGING_BUCKET: "中转容器"
            }
            role_fallback = r.topology_role.value if isinstance(r.topology_role, TopologyRole) else str(r.topology_role)
            item_role = QTableWidgetItem(role_labels.get(r.topology_role, role_fallback))
            item_role.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 2, item_role)

            # Col 3: PE Signature
            item_pe = QTableWidgetItem(r.pe_signature or "-")
            item_pe.setToolTip(r.pe_signature or "")
            self.table.setItem(row_idx, 3, item_pe)

            # Col 4: Category
            item_cat = QTableWidgetItem(r.target_category)
            item_cat.setForeground(QBrush(QColor("#38BDF8")))
            item_cat.setToolTip(r.target_category)
            self.table.setItem(row_idx, 4, item_cat)

            # Col 5: Subpath Template
            item_tpl = QTableWidgetItem(r.target_subpath_template or "-")
            item_tpl.setToolTip(r.target_subpath_template or "")
            self.table.setItem(row_idx, 5, item_tpl)

            # Col 6: Provenance
            prov_text = "用户确认 (P1)" if r.provenance == KnowledgeProvenance.USER_CONFIRMED else ("AI自学 (P2)" if r.provenance == KnowledgeProvenance.AI_LEARNED else "系统内置 (P3)")
            item_prov = QTableWidgetItem(prov_text)
            item_prov.setTextAlignment(Qt.AlignCenter)
            if r.provenance == KnowledgeProvenance.USER_CONFIRMED:
                item_prov.setForeground(QBrush(QColor("#F59E0B")))  # 琥珀金
            elif r.provenance == KnowledgeProvenance.AI_LEARNED:
                item_prov.setForeground(QBrush(QColor("#38BDF8")))  # 天蓝
            else:
                item_prov.setForeground(QBrush(QColor("#94A3B8")))  # 灰
            self.table.setItem(row_idx, 6, item_prov)

            # Col 7: Hits & time
            up_time_str = time.strftime("%m-%d %H:%M", time.localtime(r.updated_at)) if r.updated_at else "-"
            item_stat = QTableWidgetItem(f"{r.hit_count}次 | {up_time_str}")
            item_stat.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 7, item_stat)

    def _get_selected_rule(self) -> Optional[MasterRoutingRule]:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if not item:
            return None
        return item.data(Qt.UserRole)

    def _add_rule(self):
        dlg = RoutingRuleEditDialog(None, self)
        if dlg.exec() == QDialog.Accepted and hasattr(dlg, "result_rule"):
            self.routing_table.upsert_master_rule(dlg.result_rule, force_override=True)
            self.refresh_table()

    def _edit_selected_rule(self):
        rule = self._get_selected_rule()
        if not rule:
            QMessageBox.information(self, "提示", "请先在列表中选中一条需要编辑的主路由规则。")
            return
        dlg = RoutingRuleEditDialog(rule, self)
        if dlg.exec() == QDialog.Accepted and hasattr(dlg, "result_rule"):
            self.routing_table.upsert_master_rule(dlg.result_rule, force_override=True)
            self.refresh_table()

    def _delete_selected_rule(self):
        rule = self._get_selected_rule()
        if not rule:
            QMessageBox.information(self, "提示", "请先在列表中选中一条需要删除的主路由规则。")
            return

        res = QMessageBox.question(
            self, "确认删除",
            f"确定要删除主路由规则「{rule.pattern}」吗？\n删除后该规则将不再参与秒级路由命中。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if res == QMessageBox.Yes:
            self.routing_table.delete_master_rule(rule.pattern)
            self.refresh_table()

    def _import_rules(self):
        """导入外部主路由规则 (支持 merge 增量合并与 overwrite 完全覆盖)"""
        path_str, _ = QFileDialog.getOpenFileName(
            self, "选择要导入的主路由规则 JSON 文件", "", "JSON Files (*.json);;All Files (*)"
        )
        if not path_str:
            return

        # 弹出策略选择对话框
        strategy_msg = QMessageBox(self)
        strategy_msg.setWindowTitle("选择导入策略")
        strategy_msg.setText("请选择主路由规则的导入策略：\n\n1. 增量合并 (Merge)：保留现有规则，仅更新或添加外部规则；\n2. 完全覆盖 (Overwrite)：清空当前主路由规则，完全采用文件内容。")
        btn_merge = strategy_msg.addButton("增量合并 (推荐)", QMessageBox.AcceptRole)
        btn_overwrite = strategy_msg.addButton("完全覆盖", QMessageBox.DestructiveRole)
        btn_cancel = strategy_msg.addButton("取消", QMessageBox.RejectRole)
        strategy_msg.exec()

        clicked = strategy_msg.clickedButton()
        if clicked == btn_cancel:
            return
        strategy = "overwrite" if clicked == btn_overwrite else "merge"

        imported_cnt, overwrote_cnt = self.routing_table.import_master_rules(Path(path_str), strategy=strategy)
        QMessageBox.information(
            self, "导入完成",
            f"主路由规则导入完成！\n新增规则: {imported_cnt} 条\n覆盖/更新规则: {overwrote_cnt} 条"
        )
        self.refresh_table()

    def _export_rules(self):
        """导出全量主路由规则至 JSON"""
        path_str, _ = QFileDialog.getSaveFileName(
            self, "保存主路由规则 JSON 文件", "master_routing_rules_export.json", "JSON Files (*.json);;All Files (*)"
        )
        if not path_str:
            return

        success = self.routing_table.export_master_rules(Path(path_str))
        if success:
            QMessageBox.information(self, "导出成功", f"主路由规则已成功导出至:\n{path_str}")
        else:
            QMessageBox.critical(self, "导出失败", "导出主路由规则发生异常，请检查写入权限。")

    def _open_ai_audit_policy(self):
        """打开 AI 审查与自省策略配置对话框"""
        dlg = AIAuditPolicyDialog(self)
        dlg.exec()
