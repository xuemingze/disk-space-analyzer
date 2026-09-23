import os
from typing import List, Dict, Any

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QProgressBar, QTextEdit, QFileDialog,
    QGroupBox, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QTabWidget, QWidget, QAbstractItemView
)
from PySide6.QtCore import Qt

from app.config import app_config
from app.core.migrator import AppFileMigratorWorker
from app.utils.file_helper import format_size


class MigrationDialog(QDialog):
    """
    智能应用程序与大文件深度迁移向导 (含前置冲突检测、快捷方式/注册表审查及可回滚支持)
    """
    def __init__(self, selected_paths: List[str], parent=None):
        super().__init__(parent)
        self.selected_paths = selected_paths
        self.worker: AppFileMigratorWorker = None
        self.audit_data: Dict[str, Any] = {}
        self.last_manifest_path: str = ""

        self.setWindowTitle("📦 智能应用与文件迁移向导 (可回滚 / 关联项审计)")
        self.resize(860, 640)
        self.setModal(True)

        self.init_ui()
        self.run_pre_audit()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # 顶部标题
        title_lbl = QLabel("📦 智能迁移：无损释放 C 盘存储空间")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #38BDF8;")
        layout.addWidget(title_lbl)

        # 目标路径选择
        path_box = QGroupBox("📍 迁移目标根路径")
        path_layout = QHBoxLayout(path_box)
        
        default_dir = app_config.get("migration_dir", default="D:/软件与文件迁移")
        self.dest_input = QLineEdit(default_dir)
        self.dest_input.textChanged.connect(self.run_pre_audit)
        
        self.browse_btn = QPushButton("📁 浏览...")
        self.browse_btn.setProperty("class", "SecondaryButton")
        self.browse_btn.clicked.connect(self.browse_dest_dir)
        
        path_layout.addWidget(self.dest_input, 1)
        path_layout.addWidget(self.browse_btn)
        layout.addWidget(path_box)

        # 选项与审计标签页
        self.tabs = QTabWidget()

        # Tab 1: 审计与冲突预览
        audit_widget = QWidget()
        audit_layout = QVBoxLayout(audit_widget)
        audit_layout.setContentsMargins(10, 10, 10, 10)
        audit_layout.setSpacing(8)

        self.audit_summary_label = QLabel("正在扫描目标磁盘可用容量与潜在冲突...")
        self.audit_summary_label.setStyleSheet("color: #E2E8F0; font-size: 12px; font-weight: bold;")
        audit_layout.addWidget(self.audit_summary_label)

        # 快捷方式与注册表选择表
        self.assoc_table = QTableWidget()
        self.assoc_table.setColumnCount(4)
        self.assoc_table.setHorizontalHeaderLabels(["同步", "类型", "关联项路径 / 键值", "安全评级"])
        self.assoc_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.assoc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.assoc_table.setColumnWidth(0, 50)
        self.assoc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.assoc_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.assoc_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        audit_layout.addWidget(self.assoc_table, 1)

        self.tabs.addTab(audit_widget, "🔍 前置关联项与冲突审计")

        # Tab 2: 选项配置
        opt_widget = QWidget()
        opt_layout = QVBoxLayout(opt_widget)
        opt_layout.setContentsMargins(12, 12, 12, 12)
        opt_layout.setSpacing(10)

        self.chk_junction = QCheckBox("🔗 创建 NTFS 目录联接 (mklink /J，原路径绝对透明兼容，强烈推荐)")
        self.chk_junction.setChecked(app_config.get("migration_options", "create_junction", default=True))
        
        self.chk_shortcuts = QCheckBox("📌 自动同步修改桌面与开始菜单快捷方式 (.lnk 指向)")
        self.chk_shortcuts.setChecked(app_config.get("migration_options", "sync_shortcuts", default=True))
        
        self.chk_registry = QCheckBox("🧩 自动同步更新 Windows 注册表键值 (HKCU/HKLM)")
        self.chk_registry.setChecked(app_config.get("migration_options", "sync_registry", default=True))
        
        self.chk_manifest = QCheckBox("📑 强制生成可回滚 Manifest 备份记录 (支持一键完全还原)")
        self.chk_manifest.setChecked(True)

        opt_layout.addWidget(self.chk_junction)
        opt_layout.addWidget(self.chk_shortcuts)
        opt_layout.addWidget(self.chk_registry)
        opt_layout.addWidget(self.chk_manifest)
        opt_layout.addStretch()

        self.tabs.addTab(opt_widget, "⚙️ 同步与回滚选项")

        layout.addWidget(self.tabs, 1)

        # 实时进度与日志
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, len(self.selected_paths))
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(120)
        self.log_text.setStyleSheet("background-color: #0F172A; font-family: Consolas, monospace; font-size: 11px;")
        layout.addWidget(self.log_text)

        # 底部操作栏
        bottom_row = QHBoxLayout()
        self.rollback_btn = QPushButton("🔄 一键回滚上一次迁移")
        self.rollback_btn.setProperty("class", "SecondaryButton")
        self.rollback_btn.setEnabled(False)
        self.rollback_btn.clicked.connect(self.execute_rollback)
        
        self.start_btn = QPushButton("🚀 确认并开始智能迁移")
        self.start_btn.setStyleSheet("font-size: 13px; font-weight: bold; background-color: #059669; border-color: #10B981; padding: 8px 20px;")
        self.start_btn.clicked.connect(self.start_migration)
        
        self.cancel_btn = QPushButton("⏹️ 中止")
        self.cancel_btn.setProperty("class", "DangerButton")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_migration)
        
        self.close_btn = QPushButton("关闭")
        self.close_btn.setProperty("class", "SecondaryButton")
        self.close_btn.clicked.connect(self.accept)

        bottom_row.addWidget(self.rollback_btn)
        bottom_row.addStretch()
        bottom_row.addWidget(self.start_btn)
        bottom_row.addWidget(self.cancel_btn)
        bottom_row.addWidget(self.close_btn)
        layout.addLayout(bottom_row)

    def browse_dest_dir(self):
        curr = self.dest_input.text().strip() or "D:/"
        selected = QFileDialog.getExistingDirectory(self, "选择迁移目标目录", curr)
        if selected:
            self.dest_input.setText(selected)
            app_config.set("migration_dir", selected)

    def run_pre_audit(self):
        """执行前置审计"""
        dest = self.dest_input.text().strip()
        if not dest:
            return
        
        self.audit_data = AppFileMigratorWorker.pre_scan_associations(self.selected_paths, dest)
        
        src_size_str = format_size(self.audit_data["total_size"])
        free_space_str = format_size(self.audit_data["target_free_space"])
        conflicts = len(self.audit_data["conflicts"])
        
        status_text = f"待迁移数据量: {src_size_str} | 目标盘可用空间: {free_space_str}"
        if not self.audit_data["space_sufficient"]:
            status_text += " ❌ (目标磁盘空间不足！)"
            self.audit_summary_label.setStyleSheet("color: #EF4444; font-weight: bold;")
        elif conflicts > 0:
            status_text += f" ⚠️ (检测到 {conflicts} 处同名文件冲突，系统将自动增量重命名)"
            self.audit_summary_label.setStyleSheet("color: #F59E0B; font-weight: bold;")
        else:
            status_text += " ✅ (空间充裕，无同名冲突)"
            self.audit_summary_label.setStyleSheet("color: #10B981; font-weight: bold;")
            
        self.audit_summary_label.setText(status_text)
        
        # 填充关联表
        shortcuts = self.audit_data.get("shortcuts", [])
        reg_items = self.audit_data.get("registry_items", [])
        
        total_rows = len(shortcuts) + len(reg_items)
        self.assoc_table.setRowCount(total_rows)
        
        row = 0
        for sc in shortcuts:
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked)
            self.assoc_table.setItem(row, 0, chk)
            
            self.assoc_table.setItem(row, 1, QTableWidgetItem("快捷方式 (.lnk)"))
            self.assoc_table.setItem(row, 2, QTableWidgetItem(sc["shortcut_path"]))
            
            safe_item = QTableWidgetItem("安全更新")
            safe_item.setForeground(Qt.green)
            self.assoc_table.setItem(row, 3, safe_item)
            row += 1

        for reg in reg_items:
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked if reg["safe_to_update"] else Qt.Unchecked)
            self.assoc_table.setItem(row, 0, chk)
            
            self.assoc_table.setItem(row, 1, QTableWidgetItem(f"注册表 ({reg['root']})"))
            self.assoc_table.setItem(row, 2, QTableWidgetItem(f"{reg['key_path']} -> {reg['value_name']}"))
            
            safe_item = QTableWidgetItem("安全更新" if reg["safe_to_update"] else "需人工确认")
            safe_item.setForeground(Qt.green if reg["safe_to_update"] else Qt.yellow)
            self.assoc_table.setItem(row, 3, safe_item)
            row += 1

    def append_log(self, msg: str, level: str = "info"):
        color = "#10B981" if level == "success" else ("#F59E0B" if level == "warn" else ("#EF4444" if level == "error" else "#CBD5E1"))
        self.log_text.append(f'<span style="color: {color};">{msg}</span>')
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def start_migration(self):
        dest = self.dest_input.text().strip()
        if not dest:
            QMessageBox.warning(self, "提示", "请选择有效的迁移目标目录！")
            return

        if not self.audit_data.get("space_sufficient", True):
            QMessageBox.critical(self, "空间不足", "目标磁盘剩余空间不足以容纳所选迁移数据！")
            return

        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.close_btn.setEnabled(False)
        self.log_text.clear()

        self.worker = AppFileMigratorWorker(
            source_paths=self.selected_paths,
            destination_dir=dest,
            create_junction=self.chk_junction.isChecked(),
            sync_shortcuts=self.chk_shortcuts.isChecked(),
            sync_registry=self.chk_registry.isChecked()
        )
        self.worker.progress_signal.connect(lambda cur, tot: self.progress_bar.setValue(cur))
        self.worker.log_signal.connect(self.append_log)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def cancel_migration(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)

    def on_finished(self, success: bool, summary: dict):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.close_btn.setEnabled(True)
        
        self.last_manifest_path = summary.get("manifest_path", "")
        if self.last_manifest_path:
            self.rollback_btn.setEnabled(True)

        msg = (
            f"迁移流程执行完成！\n"
            f"成功项: {summary['success_count']} | 失败项: {summary['failed_count']}\n"
            f"累计迁移空间: {format_size(summary['migrated_bytes'])}\n"
            f"NTFS 目录联接: {summary['junctions_created']} 处\n"
            f"快捷方式重定向: {summary['shortcuts_updated']} 个\n"
            f"注册表同步配置: {summary['registry_keys_updated']} 处\n"
            f"回滚凭证: {os.path.basename(self.last_manifest_path)}"
        )
        QMessageBox.information(self, "迁移完成", msg)

    def execute_rollback(self):
        if not self.last_manifest_path or not os.path.exists(self.last_manifest_path):
            QMessageBox.warning(self, "无法回滚", "未发现有效的回滚清单文件！")
            return

        reply = QMessageBox.question(
            self, "确认一键回滚",
            "确定要回滚还原上一次迁移的所有文件、NTFS联接、快捷方式与注册表项吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        ok, msg = AppFileMigratorWorker.rollback_manifest(self.last_manifest_path)
        if ok:
            QMessageBox.information(self, "回滚成功", msg)
            self.rollback_btn.setEnabled(False)
        else:
            QMessageBox.critical(self, "回滚失败", msg)
