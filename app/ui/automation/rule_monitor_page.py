"""
规则监控子页面 (Rule Monitor Page)
功能：
1. 观察目录与排除规则配置；
2. 防抖与沉淀时长调整；
3. 候选整理方案 (Proposed Plans) 审核卡片流；
4. 绝不在用户不知情时直接移动，必须用户预览确认。
"""

import os
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
    QFormLayout, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QMessageBox, QFileDialog, QGroupBox, QScrollArea, QFrame
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont

from app.automation.models import WatchRule, ProposedPlan
from app.automation.manager import AutomationManager
from app.ui.components.organize_dialog import OrganizePreviewDialog
from app.utils.file_helper import format_size
from app.utils.lock_detector import is_destination_valid


class RuleEditDialog(QDialog):
    """添加/编辑监控规则对话框"""
    def __init__(self, rule: Optional[WatchRule] = None, parent=None):
        super().__init__(parent)
        self.rule = rule or WatchRule()
        self.setWindowTitle("编辑监控规则" if rule else "添加新监控规则")
        self.resize(520, 360)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        form = QFormLayout()
        form.setSpacing(12)

        self.name_input = QLineEdit(self.rule.name)
        form.addRow("规则名称:", self.name_input)

        path_row = QHBoxLayout()
        self.path_input = QLineEdit(self.rule.watch_path)
        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self._browse_dir)
        path_row.addWidget(self.path_input)
        path_row.addWidget(btn_browse)
        form.addRow("观察目录:", path_row)

        self.exclude_input = QLineEdit(", ".join(self.rule.exclude_patterns))
        self.exclude_input.setPlaceholderText("例如: *.tmp, *.crdownload, *.part, .git")
        form.addRow("排除通配符:", self.exclude_input)

        self.ext_input = QLineEdit(", ".join(self.rule.file_extensions))
        self.ext_input.setPlaceholderText("留空表示监控所有文件，或指定: .pdf, .docx, .zip")
        form.addRow("扩展名限制:", self.ext_input)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("综合智能规划 (comprehensive)", "comprehensive")
        self.mode_combo.addItem("按格式类型 (by_type)", "by_type")
        self.mode_combo.addItem("按前缀聚类 (by_prefix)", "by_prefix")
        self.mode_combo.addItem("按修改日期 (by_date)", "by_date")
        self.mode_combo.addItem("按应用工具链 (by_app)", "by_app")
        idx = self.mode_combo.findData(self.rule.organize_mode)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        form.addRow("整理模式:", self.mode_combo)

        self.debounce_spin = QDoubleSpinBox()
        self.debounce_spin.setRange(1.0, 60.0)
        self.debounce_spin.setValue(self.rule.debounce_seconds)
        self.debounce_spin.setSuffix(" 秒 (文件大小不再变化持续时长)")
        form.addRow("防抖沉淀时长:", self.debounce_spin)

        # 专属归档目录
        target_row = QHBoxLayout()
        self.target_dir_input = QLineEdit(self.rule.target_dir)
        self.target_dir_input.setPlaceholderText("留空则采用系统默认归档根目录 (D:/归档备份)")
        btn_browse_target = QPushButton("浏览...")
        btn_browse_target.clicked.connect(self._browse_target_dir)
        target_row.addWidget(self.target_dir_input)
        target_row.addWidget(btn_browse_target)
        form.addRow("归档目标目录:", target_row)

        # 执行模式切换
        self.exec_mode_combo = QComboBox()
        self.exec_mode_combo.addItem("💡 仅生成提议方案 (默认安全，生成待审核卡片)", True)
        self.exec_mode_combo.addItem("⚡ 自动归档平移 (无人值守，沉淀稳定且无进程锁占用后自动分类移动)", False)
        if not self.rule.propose_only:
            self.exec_mode_combo.setCurrentIndex(1)
        else:
            self.exec_mode_combo.setCurrentIndex(0)
        form.addRow("执行模式:", self.exec_mode_combo)

        layout.addLayout(form)

        # 安全声明与保底机制提示
        tip = QLabel(
            "🛡️ 保底机制：已内置 Windows 排他探针与 Office/WPS 伴生锁检测。"
            "正在编辑、写入中或被程序占用的文件将自动挂起，绝不强行移动导致损坏。"
        )
        tip.setStyleSheet("color: #38BDF8; font-size: 12px; background: #0F172A; padding: 8px; border-radius: 4px;")
        layout.addWidget(tip)

        btns = QHBoxLayout()
        btns.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("保存规则")
        btn_ok.setStyleSheet("background-color: #2563EB; color: white; font-weight: bold; padding: 6px 16px;")
        btn_ok.clicked.connect(self._save)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        layout.addLayout(btns)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择观察目录", self.path_input.text() or str(Path.home()))
        if d:
            self.path_input.setText(d)

    def _browse_target_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择专属归档目标目录", self.target_dir_input.text() or "D:/归档备份")
        if d:
            self.target_dir_input.setText(d)

    def _save(self):
        name = self.name_input.text().strip()
        path = self.path_input.text().strip()
        target_dir = self.target_dir_input.text().strip()
        propose_only = self.exec_mode_combo.currentData()

        if not name or not path:
            QMessageBox.warning(self, "提示", "规则名称和观察目录不能为空。")
            return
        if not os.path.exists(path):
            QMessageBox.warning(self, "提示", f"观察目录不存在: {path}")
            return

        # 若配置了专属归档目录，进行防死循环校验
        if target_dir:
            valid, err = is_destination_valid(path, target_dir)
            if not valid:
                QMessageBox.critical(self, "防回环安全拦截", f"归档目标目录无效:\n{err}")
                return
        elif not propose_only:
            # 自动归档模式下，若未指定归档目录，默认设为 D:/归档备份
            target_dir = "D:/归档备份"

        self.rule.name = name
        self.rule.watch_path = path
        self.rule.target_dir = target_dir
        self.rule.propose_only = propose_only
        excludes = [p.strip() for p in self.exclude_input.text().split(",") if p.strip()]
        self.rule.exclude_patterns = excludes or ["*.tmp", "*.part"]
        exts = [e.strip() for e in self.ext_input.text().split(",") if e.strip()]
        self.rule.file_extensions = exts
        self.rule.organize_mode = self.mode_combo.currentData()
        self.rule.debounce_seconds = self.debounce_spin.value()
        self.accept()


class RuleMonitorPage(QWidget):
    """规则监控视图"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = AutomationManager.get_instance()
        self.init_ui()
        self._bind_events()
        self.refresh_rules()
        self.refresh_plans()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)

        # 头部操作栏
        top_bar = QHBoxLayout()
        title_box = QVBoxLayout()
        lbl_title = QLabel("👁️ 规则监控 (Rule Watcher)")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #38BDF8;")
        lbl_desc = QLabel("配置目录监视、排除策略与防抖沉淀；监控捕获后提议整理方案供人工审核")
        lbl_desc.setStyleSheet("color: #94A3B8; font-size: 12px;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_desc)
        top_bar.addLayout(title_box)

        top_bar.addStretch()

        self.btn_add_rule = QPushButton("➕ 添加监控规则")
        self.btn_add_rule.setStyleSheet("background-color: #0284C7; color: white; font-weight: bold; padding: 8px 16px; border-radius: 4px;")
        self.btn_add_rule.clicked.connect(self._add_rule)
        top_bar.addWidget(self.btn_add_rule)

        main_layout.addLayout(top_bar)

        # 规则表格
        self.rule_table = QTableWidget()
        self.rule_table.setColumnCount(8)
        self.rule_table.setHorizontalHeaderLabels(["状态", "规则名称", "观察路径", "归档目标", "整理模式", "执行模式", "防抖", "操作"])
        self.rule_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.rule_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.rule_table.verticalHeader().setVisible(False)
        self.rule_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.rule_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.rule_table.setStyleSheet("QTableWidget { background: #1E293B; border: 1px solid #334155; border-radius: 6px; }")
        main_layout.addWidget(self.rule_table, 2)

        # 候选待审方案区
        plans_group = QGroupBox("💡 待审候选整理提案 (Pending Proposed Plans)")
        plans_group.setStyleSheet("QGroupBox { font-weight: bold; color: #38BDF8; margin-top: 8px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; }")
        plans_layout = QVBoxLayout(plans_group)

        self.plans_scroll = QScrollArea()
        self.plans_scroll.setWidgetResizable(True)
        self.plans_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.plans_container = QWidget()
        self.plans_list_layout = QVBoxLayout(self.plans_container)
        self.plans_list_layout.setSpacing(10)
        self.plans_list_layout.addStretch()
        self.plans_scroll.setWidget(self.plans_container)

        plans_layout.addWidget(self.plans_scroll)
        main_layout.addWidget(plans_group, 3)

    def _bind_events(self):
        self.manager.rules_changed.connect(self.refresh_rules)
        self.manager.plan_added.connect(lambda p: self.refresh_plans())

    def refresh_rules(self):
        """刷新规则列表表格"""
        rules = self.manager.rules
        self.rule_table.setRowCount(len(rules))
        for row, rule in enumerate(rules):
            # 状态开关按钮
            btn_toggle = QPushButton("已启用" if rule.enabled else "已停用")
            btn_toggle.setCheckable(True)
            btn_toggle.setChecked(rule.enabled)
            btn_toggle.setStyleSheet(
                "background: #10B981; color: white; border-radius: 3px; padding: 4px;" if rule.enabled
                else "background: #64748B; color: white; border-radius: 3px; padding: 4px;"
            )
            btn_toggle.clicked.connect(lambda checked, r_id=rule.id: self._toggle_rule(r_id, checked))
            self.rule_table.setCellWidget(row, 0, btn_toggle)

            self.rule_table.setItem(row, 1, QTableWidgetItem(rule.name))
            self.rule_table.setItem(row, 2, QTableWidgetItem(rule.watch_path))
            self.rule_table.setItem(row, 3, QTableWidgetItem(rule.target_dir or "默认(D:/归档备份)"))
            self.rule_table.setItem(row, 4, QTableWidgetItem(rule.organize_mode))

            mode_item = QTableWidgetItem("💡 仅提议" if rule.propose_only else "⚡ 自动归档")
            mode_item.setForeground(QColor("#38BDF8" if rule.propose_only else "#10B981"))
            self.rule_table.setItem(row, 5, mode_item)

            self.rule_table.setItem(row, 6, QTableWidgetItem(f"{rule.debounce_seconds:.1f}s"))

            # 操作按钮栏
            ops_widget = QWidget()
            ops_layout = QHBoxLayout(ops_widget)
            ops_layout.setContentsMargins(4, 2, 4, 2)
            ops_layout.setSpacing(6)

            btn_edit = QPushButton("编辑")
            btn_edit.setStyleSheet("background: #3B82F6; color: white; padding: 2px 8px; border-radius: 3px;")
            btn_edit.clicked.connect(lambda _, r=rule: self._edit_rule(r))
            ops_layout.addWidget(btn_edit)

            btn_del = QPushButton("删除")
            btn_del.setStyleSheet("background: #EF4444; color: white; padding: 2px 8px; border-radius: 3px;")
            btn_del.clicked.connect(lambda _, r_id=rule.id: self._delete_rule(r_id))
            ops_layout.addWidget(btn_del)

            self.rule_table.setCellWidget(row, 7, ops_widget)

    def refresh_plans(self):
        """刷新候选整理提案卡片流"""
        # 清除现有卡片
        while self.plans_list_layout.count() > 1:
            child = self.plans_list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        pending_plans = self.manager.get_pending_plans()
        if not pending_plans:
            lbl_empty = QLabel("暂无待审候选整理提案。当监控到稳定文件或计划任务触发时，方案将自动呈现于此。")
            lbl_empty.setStyleSheet("color: #64748B; font-style: italic; padding: 20px; text-align: center;")
            self.plans_list_layout.insertWidget(0, lbl_empty)
            return

        for plan in pending_plans:
            card = self._create_plan_card(plan)
            self.plans_list_layout.insertWidget(self.plans_list_layout.count() - 1, card)

    def _create_plan_card(self, plan: ProposedPlan) -> QFrame:
        """构建单个方案审核卡片"""
        frame = QFrame()
        frame.setStyleSheet("QFrame { background: #1E293B; border: 1px solid #334155; border-radius: 8px; padding: 10px; }")
        layout = QHBoxLayout(frame)

        info_box = QVBoxLayout()
        t_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(plan.created_at))
        header = QLabel(f"📦 提案 #{plan.id} · 来自 [{plan.source_name}] ({t_str})")
        header.setStyleSheet("font-weight: bold; color: #F8FAFC; font-size: 13px;")

        details = QLabel(
            f"目标路径: {plan.source_path}  |  文件数: {plan.file_count} 项  |  总体积: {format_size(plan.total_bytes)}  |  规划归属组: {len(plan.proposed_groups)} 组"
        )
        details.setStyleSheet("color: #94A3B8; font-size: 12px;")

        notes = QLabel(plan.notes)
        notes.setStyleSheet("color: #38BDF8; font-size: 11px;")

        info_box.addWidget(header)
        info_box.addWidget(details)
        info_box.addWidget(notes)
        layout.addLayout(info_box)

        layout.addStretch()

        btns = QVBoxLayout()
        btn_preview = QPushButton("🔍 预览与确认")
        btn_preview.setStyleSheet("background: #10B981; color: white; font-weight: bold; padding: 6px 14px; border-radius: 4px;")
        btn_preview.clicked.connect(lambda _, p=plan: self._review_plan(p))

        btn_dismiss = QPushButton("忽略方案")
        btn_dismiss.setStyleSheet("background: #475569; color: #E2E8F0; padding: 4px 10px; border-radius: 4px;")
        btn_dismiss.clicked.connect(lambda _, p=plan: self._dismiss_plan(p.id))

        btns.addWidget(btn_preview)
        btns.addWidget(btn_dismiss)
        layout.addLayout(btns)

        return frame

    def _add_rule(self):
        dlg = RuleEditDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.manager.add_rule(dlg.rule)

    def _edit_rule(self, rule: WatchRule):
        dlg = RuleEditDialog(rule=rule, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.manager.update_rule(dlg.rule)

    def _delete_rule(self, rule_id: str):
        if QMessageBox.question(self, "确认删除", "确定要删除该监控规则吗？") == QMessageBox.Yes:
            self.manager.delete_rule(rule_id)

    def _toggle_rule(self, rule_id: str, checked: bool):
        self.manager.toggle_rule(rule_id, checked)

    def _review_plan(self, plan: ProposedPlan):
        """弹出整理预览确认窗口"""
        dlg = OrganizePreviewDialog(
            classification_items=plan.proposed_groups,
            destination_root=plan.target_root,
            conflict_policy="auto_rename",
            allow_execute=True,
            parent=self
        )
        if dlg.exec() == QDialog.Accepted:
            self.manager.mark_plan_applied(plan.id)
            self.refresh_plans()

    def _dismiss_plan(self, plan_id: str):
        self.manager.dismiss_plan(plan_id)
        self.refresh_plans()
