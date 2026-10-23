"""
AI 审查机制与全域生态拓扑路由联动管理子页面 (AI Audit & Topology Routing Page)
写入左侧主菜单「自动化中心」子菜单下。

核心能力：
1. 人为可操控的 AI 审查策略配置 (开关、置信度阈值、严格剥离中转名、自定义 Prompt 提示词)；
2. 全局拓扑主路由知识库自省管理 (44px 严格固定行高、搜索过滤、增删改查、JSON 导入导出)；
3. 全域同构联动：配置保存后即刻热更新，与主控扫描、快速整理、目录树归档等生态深度同步。
"""

import os
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QFileDialog, QFrame, QComboBox, QTextEdit, QDoubleSpinBox,
    QCheckBox, QGroupBox, QSplitter
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush, QFont

from app.core.domain_models import (
    TopologyRoutingTable, MasterRoutingRule, MorphologyType, KnowledgeProvenance,
    TopologyRole, AIAuditPolicyConfig
)
from app.ui.components.routing_table_viewer import RoutingRuleEditDialog


class AiAuditRoutingPage(QWidget):
    """自动化中心 - AI审查与拓扑路由子视图"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.routing_table = TopologyRoutingTable.instance()
        self.policy_config = AIAuditPolicyConfig.get_instance()
        self.init_ui()
        self.refresh_table()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(14)

        # 头部标题
        header_box = QVBoxLayout()
        lbl_title = QLabel("🌐 AI 审查机制与全域生态拓扑路由 (AI Auditor & Topology Routing)")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #38BDF8;")
        lbl_desc = QLabel("人为操控 AI 审查准则与自定义 Prompt，结合全局主路由知识库实现 0 Token 秒级精准归档。")
        lbl_desc.setStyleSheet("color: #94A3B8; font-size: 12px;")
        header_box.addWidget(lbl_title)
        header_box.addWidget(lbl_desc)
        main_layout.addLayout(header_box)

        # -------------------------------------------------------------
        # 1. AI 审查机制与自省策略配置卡片 (可折叠/常驻面板)
        # -------------------------------------------------------------
        policy_group = QGroupBox("⚙️ 人为可操控的 AI 审查与自省策略配置 (AI Audit Policy)")
        policy_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: #38BDF8;
                border: 1px solid #334155;
                border-radius: 6px;
                margin-top: 6px;
                padding-top: 10px;
                background-color: #0F172A;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
            }
        """)
        policy_layout = QVBoxLayout(policy_group)
        policy_layout.setContentsMargins(12, 10, 12, 10)
        policy_layout.setSpacing(8)

        # 控制行 1: 开关与阈值
        row1 = QHBoxLayout()
        self.chk_enabled = QCheckBox("启用 AI 智能审查机制 (AI Audit Engine Enabled)")
        self.chk_enabled.setStyleSheet("color: #F8FAFC; font-size: 12px;")
        self.chk_enabled.setChecked(self.policy_config.enabled)
        row1.addWidget(self.chk_enabled)

        self.chk_strip = QCheckBox("严格剥离原材料与中转容器名 (如 '共用文件', 'Downloads', '待分类')")
        self.chk_strip.setStyleSheet("color: #F8FAFC; font-size: 12px;")
        self.chk_strip.setChecked(self.policy_config.strict_strip_staging_containers)
        row1.addWidget(self.chk_strip)

        row1.addStretch()

        conf_lbl = QLabel("置信度阈值:")
        conf_lbl.setStyleSheet("color: #94A3B8; font-size: 12px;")
        self.spin_conf = QDoubleSpinBox()
        self.spin_conf.setRange(0.10, 1.00)
        self.spin_conf.setSingleStep(0.05)
        self.spin_conf.setValue(self.policy_config.confidence_threshold)
        self.spin_conf.setFixedWidth(75)
        self.spin_conf.setStyleSheet("background: #1E293B; color: #F8FAFC; border: 1px solid #334155; border-radius: 4px; padding: 2px;")
        row1.addWidget(conf_lbl)
        row1.addWidget(self.spin_conf)

        policy_layout.addLayout(row1)

        # 控制行 2: 自定义 Prompt 提示词
        row2 = QHBoxLayout()
        prompt_lbl = QLabel("自定义 Prompt 审查准则:")
        prompt_lbl.setStyleSheet("color: #94A3B8; font-size: 12px;")
        row2.addWidget(prompt_lbl)

        self.txt_prompt = QLineEdit()
        self.txt_prompt.setPlaceholderText("填入专属归档审计准则（例如：禁止在路径中保留临时批次编号，统一按财务年-月归类等）")
        self.txt_prompt.setText(self.policy_config.custom_instruction_prompt)
        self.txt_prompt.setStyleSheet("""
            QLineEdit {
                background: #1E293B;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #38BDF8;
            }
        """)
        row2.addWidget(self.txt_prompt, 1)

        btn_reset_policy = QPushButton("恢复默认")
        btn_reset_policy.setStyleSheet("background: #1E293B; color: #94A3B8; border: 1px solid #334155; border-radius: 4px; padding: 4px 10px; font-size: 11px;")
        btn_reset_policy.clicked.connect(self._reset_policy_defaults)
        row2.addWidget(btn_reset_policy)

        btn_save_policy = QPushButton("💾 保存策略并生效")
        btn_save_policy.setStyleSheet("background: #0284C7; color: white; font-weight: bold; border-radius: 4px; padding: 4px 14px; font-size: 12px;")
        btn_save_policy.clicked.connect(self._save_policy)
        row2.addWidget(btn_save_policy)

        policy_layout.addLayout(row2)

        self.lbl_policy_status = QLabel("🟢 AI 审查策略运行中：已启用")
        self.lbl_policy_status.setStyleSheet("color: #10B981; font-size: 11px;")
        policy_layout.addWidget(self.lbl_policy_status)

        main_layout.addWidget(policy_group)

        # -------------------------------------------------------------
        # 2. 全局拓扑主路由知识库自省表格 (44px 铁律)
        # -------------------------------------------------------------
        routing_group = QGroupBox("📚 全局拓扑主路由知识库自省管理 (Master Routing Table)")
        routing_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: #38BDF8;
                border: 1px solid #334155;
                border-radius: 6px;
                margin-top: 6px;
                padding-top: 10px;
                background-color: #0F172A;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
            }
        """)
        routing_layout = QVBoxLayout(routing_group)
        routing_layout.setContentsMargins(12, 10, 12, 10)
        routing_layout.setSpacing(10)

        # 工具栏
        toolbar = QHBoxLayout()
        self.edt_search = QLineEdit()
        self.edt_search.setPlaceholderText("🔍 搜索特征模式、分类、模板或发布者...")
        self.edt_search.textChanged.connect(self.refresh_table)
        self.edt_search.setStyleSheet("""
            QLineEdit {
                background: #1E293B;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 5px 10px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #38BDF8;
            }
        """)
        toolbar.addWidget(self.edt_search, 2)

        self.cbo_prov_filter = QComboBox()
        self.cbo_prov_filter.addItem("全部来源", "")
        self.cbo_prov_filter.addItem("用户确认 (USER_CONFIRMED)", KnowledgeProvenance.USER_CONFIRMED.value)
        self.cbo_prov_filter.addItem("AI自学 (AI_LEARNED)", KnowledgeProvenance.AI_LEARNED.value)
        self.cbo_prov_filter.addItem("系统内置 (SYSTEM_BUILTIN)", KnowledgeProvenance.SYSTEM_BUILTIN.value)
        self.cbo_prov_filter.currentIndexChanged.connect(self.refresh_table)
        self.cbo_prov_filter.setStyleSheet("background: #1E293B; color: #F8FAFC; border: 1px solid #334155; border-radius: 4px; padding: 4px 6px;")
        toolbar.addWidget(self.cbo_prov_filter, 1)

        self.cbo_morph_filter = QComboBox()
        self.cbo_morph_filter.addItem("全部形态", "")
        self.cbo_morph_filter.addItem("独立资产", MorphologyType.INDEPENDENT_ASSET.value)
        self.cbo_morph_filter.addItem("密封集合", MorphologyType.SEALED_COLLECTIVE.value)
        self.cbo_morph_filter.addItem("离散媒体", MorphologyType.LOOSE_MEDIA.value)
        self.cbo_morph_filter.currentIndexChanged.connect(self.refresh_table)
        self.cbo_morph_filter.setStyleSheet("background: #1E293B; color: #F8FAFC; border: 1px solid #334155; border-radius: 4px; padding: 4px 6px;")
        toolbar.addWidget(self.cbo_morph_filter, 1)

        toolbar.addSpacing(6)

        btn_style = "background: #1E293B; color: #F8FAFC; border: 1px solid #334155; border-radius: 4px; padding: 5px 12px; font-size: 12px;"
        
        self.btn_add = QPushButton("➕ 新增")
        self.btn_add.setStyleSheet("background: #0284C7; color: white; font-weight: bold; border-radius: 4px; padding: 5px 12px; font-size: 12px;")
        self.btn_add.clicked.connect(self._add_rule)
        toolbar.addWidget(self.btn_add)

        self.btn_edit = QPushButton("✏️ 编辑")
        self.btn_edit.setStyleSheet(btn_style)
        self.btn_edit.clicked.connect(self._edit_selected_rule)
        toolbar.addWidget(self.btn_edit)

        self.btn_del = QPushButton("🗑️ 删除")
        self.btn_del.setStyleSheet(btn_style)
        self.btn_del.clicked.connect(self._delete_selected_rule)
        toolbar.addWidget(self.btn_del)

        self.btn_import = QPushButton("📥 导入")
        self.btn_import.setStyleSheet(btn_style)
        self.btn_import.clicked.connect(self._import_rules)
        toolbar.addWidget(self.btn_import)

        self.btn_export = QPushButton("📤 导出")
        self.btn_export.setStyleSheet(btn_style)
        self.btn_export.clicked.connect(self._export_rules)
        toolbar.addWidget(self.btn_export)

        self.btn_refresh = QPushButton("🔄")
        self.btn_refresh.setToolTip("刷新规则列表")
        self.btn_refresh.setStyleSheet(btn_style)
        self.btn_refresh.clicked.connect(self.refresh_table)
        toolbar.addWidget(self.btn_refresh)

        routing_layout.addLayout(toolbar)

        # 统计标签
        self.lbl_stats = QLabel("当前主规则: 0 条")
        self.lbl_stats.setStyleSheet("color: #94A3B8; font-size: 12px;")
        routing_layout.addWidget(self.lbl_stats)

        # 核心表格
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "特征匹配模式 (Pattern)", "资产形态", "拓扑角色", "PE特征 / 发布者",
            "建议归档分类 (Category)", "目标规划模板", "知识来源 (Provenance)", "命中 / 时间"
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
        self.table.setColumnWidth(0, 190)  # Pattern
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

        self.table.setStyleSheet("""
            QTableWidget {
                background: #0B1120;
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

        routing_layout.addWidget(self.table, 1)

        # 提示栏
        tip_lbl = QLabel("🛡️ 顶格统治力法则：用户就地手动修改的规则为 USER_CONFIRMED (P1)，拥有最高统治优先级，永不被 AI 自动覆盖。")
        tip_lbl.setStyleSheet("color: #38BDF8; font-size: 11px;")
        routing_layout.addWidget(tip_lbl)

        main_layout.addWidget(routing_group, 1)

    # -------------------------------------------------------------
    # 策略与控制逻辑
    # -------------------------------------------------------------
    def _reset_policy_defaults(self):
        self.chk_enabled.setChecked(True)
        self.chk_strip.setChecked(True)
        self.spin_conf.setValue(0.85)
        self.txt_prompt.setText("")
        self._save_policy()

    def _save_policy(self):
        self.policy_config.enabled = self.chk_enabled.isChecked()
        self.policy_config.strict_strip_staging_containers = self.chk_strip.isChecked()
        self.policy_config.confidence_threshold = round(self.spin_conf.value(), 2)
        self.policy_config.custom_instruction_prompt = self.txt_prompt.text().strip()
        self.policy_config.save()

        status_text = "🟢 AI 审查策略运行中：已启用" if self.policy_config.enabled else "🟡 AI 审查策略已暂停"
        self.lbl_policy_status.setText(f"{status_text} (已落盘: {time.strftime('%H:%M:%S')})")
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            QMessageBox.information(self, "策略已生效", "AI 审查机制与自定义 Prompt 策略已保存并全域即刻生效！")

    # -------------------------------------------------------------
    # 主路由表数据逻辑
    # -------------------------------------------------------------
    def refresh_table(self):
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
            f"主规则总计: <b>{len(rules)}</b> 条 (当前筛选: {len(filtered_rules)} 条) | "
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
                item_prov.setForeground(QBrush(QColor("#F59E0B")))
            elif r.provenance == KnowledgeProvenance.AI_LEARNED:
                item_prov.setForeground(QBrush(QColor("#38BDF8")))
            else:
                item_prov.setForeground(QBrush(QColor("#94A3B8")))
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
        if dlg.exec() == 1 and hasattr(dlg, "result_rule"):
            self.routing_table.upsert_master_rule(dlg.result_rule, force_override=True)
            self.refresh_table()

    def _edit_selected_rule(self):
        rule = self._get_selected_rule()
        if not rule:
            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                QMessageBox.information(self, "提示", "请先在列表中选中一条需要编辑的主路由规则。")
            return
        dlg = RoutingRuleEditDialog(rule, self)
        if dlg.exec() == 1 and hasattr(dlg, "result_rule"):
            self.routing_table.upsert_master_rule(dlg.result_rule, force_override=True)
            self.refresh_table()

    def _delete_selected_rule(self):
        rule = self._get_selected_rule()
        if not rule:
            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                QMessageBox.information(self, "提示", "请先在列表中选中一条需要删除的主路由规则。")
            return

        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            res = QMessageBox.question(
                self, "确认删除",
                f"确定要删除主路由规则「{rule.pattern}」吗？\n删除后该规则将不再参与秒级路由命中。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if res != QMessageBox.Yes:
                return

        self.routing_table.delete_master_rule(rule.pattern)
        self.refresh_table()

    def _import_rules(self):
        path_str, _ = QFileDialog.getOpenFileName(
            self, "选择要导入的主路由规则 JSON 文件", "", "JSON Files (*.json);;All Files (*)"
        )
        if not path_str:
            return

        strategy = "merge"
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
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
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            QMessageBox.information(
                self, "导入完成",
                f"主路由规则导入完成！\n新增规则: {imported_cnt} 条\n覆盖/更新规则: {overwrote_cnt} 条"
            )
        self.refresh_table()

    def _export_rules(self):
        path_str, _ = QFileDialog.getSaveFileName(
            self, "保存主路由规则 JSON 文件", "master_routing_rules_export.json", "JSON Files (*.json);;All Files (*)"
        )
        if not path_str:
            return

        success = self.routing_table.export_master_rules(Path(path_str))
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            if success:
                QMessageBox.information(self, "导出成功", f"主路由规则已成功导出至:\n{path_str}")
            else:
                QMessageBox.critical(self, "导出失败", "导出主路由规则发生异常，请检查写入权限。")
