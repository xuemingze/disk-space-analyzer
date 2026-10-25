"""
快速整理子页面 (Quick Organize Page)
功能：
1. 预置「桌面」、「下载」、「我的文档」、「图片素材」等高频目录的快捷治理卡片；
2. 一键触发快速扫描分析；
3. 严格遵循安全原则：扫描分析后立即弹出 OrganizePreviewDialog 预览审核对话框，
   由用户明确勾选确认后才调用底层 ArchiveWorker，绝不直接暗箱物理移动。
"""

import os
from pathlib import Path
from typing import List, Dict, Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGridLayout, QFrame, QMessageBox, QFileDialog, QLineEdit
)
from PySide6.QtCore import Qt

from app.automation.quick_organizer import QuickOrganizeManager
from app.automation.models import QuickPreset
from app.automation.plan_resolver import AutomationPlanResolver
from app.core.unified_scanner import UnifiedScanner
from app.core.app_detector import AppDetector
from app.core.organize_models import OrganizeOptions, OrganizeMode
from app.ui.components.organize_dialog import OrganizePreviewDialog
from app.utils.file_helper import format_size


class QuickOrganizePage(QWidget):
    """快速整理视图"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.presets = QuickOrganizeManager.get_default_presets()
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)

        # 头部
        header_layout = QHBoxLayout()
        top_box = QVBoxLayout()
        lbl_title = QLabel("⚡ 快速整理入口 (Quick Organize)")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #38BDF8;")
        lbl_desc = QLabel("针对高频杂乱系统目录提供一键分析与整理入口；一键扫描后展示完整预览与人工确认")
        lbl_desc.setStyleSheet("color: #94A3B8; font-size: 12px;")
        top_box.addWidget(lbl_title)
        top_box.addWidget(lbl_desc)
        header_layout.addLayout(top_box)

        header_layout.addStretch()

        btn_routing = QPushButton("🌐 拓扑路由知识库")
        btn_routing.setStyleSheet("""
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
        """)
        btn_routing.clicked.connect(self._open_routing_viewer)
        header_layout.addWidget(btn_routing)

        main_layout.addLayout(header_layout)

        # 卡片网格 (2x2)
        grid = QGridLayout()
        grid.setSpacing(16)

        for i, preset in enumerate(self.presets):
            row = i // 2
            col = i % 2
            card = self._create_preset_card(preset)
            grid.addWidget(card, row, col)

        main_layout.addLayout(grid)
        main_layout.addStretch()

        # 安全提示
        tip = QLabel("🛡️ 快速整理安全规约：一键操作只负责「一键扫描并打开规划预览」，必须经由您的复核与勾选确认后才会落盘执行。")
        tip.setStyleSheet("color: #38BDF8; font-size: 12px; background: #0F172A; padding: 10px; border-radius: 6px; border: 1px solid #1E293B;")
        main_layout.addWidget(tip)

    def _create_preset_card(self, preset: QuickPreset) -> QFrame:
        """构建单个预设卡片"""
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background: #1E293B;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 14px;
            }
            QFrame:hover {
                border-color: #38BDF8;
            }
        """)
        layout = QVBoxLayout(frame)
        layout.setSpacing(10)

        # 头部
        header_row = QHBoxLayout()
        lbl_icon = QLabel(preset.icon)
        lbl_icon.setStyleSheet("font-size: 24px;")
        lbl_name = QLabel(preset.name)
        lbl_name.setStyleSheet("font-size: 15px; font-weight: bold; color: #F8FAFC;")
        header_row.addWidget(lbl_icon)
        header_row.addWidget(lbl_name)
        header_row.addStretch()
        layout.addLayout(header_row)

        # 说明
        lbl_desc = QLabel(preset.description)
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #94A3B8; font-size: 12px; line-height: 140%;")
        layout.addWidget(lbl_desc)

        # 路径选择与微调
        path_row = QHBoxLayout()
        path_input = QLineEdit(preset.path)
        path_input.setStyleSheet("background: #0F172A; color: #CBD5E1; border: 1px solid #334155; border-radius: 3px; padding: 4px;")
        btn_browse = QPushButton("更改...")
        btn_browse.setStyleSheet("padding: 4px 8px;")
        btn_browse.clicked.connect(lambda _, inp=path_input: self._browse_dir(inp))
        path_row.addWidget(path_input, 1)
        path_row.addWidget(btn_browse)
        layout.addLayout(path_row)

        layout.addSpacing(6)

        # 操作按钮
        btn_run = QPushButton(f"⚡ 一键分析与整理预览")
        btn_run.setStyleSheet("""
            QPushButton {
                background-color: #0284C7;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #0369A1;
            }
        """)
        btn_run.clicked.connect(lambda _, inp=path_input, p=preset: self._run_quick_organize(inp.text().strip(), p.name))
        layout.addWidget(btn_run)

        return frame

    def _browse_dir(self, input_widget: QLineEdit):
        d = QFileDialog.getExistingDirectory(self, "选择整理路径", input_widget.text() or str(Path.home()))
        if d:
            input_widget.setText(d)

    def _run_quick_organize(self, target_dir: str, title: str):
        """执行快速分析（接入 UnifiedScanner + AutomationPlanResolver AI 核心编排与主动纠偏）并弹出预览审核对话框"""
        if not target_dir or not os.path.exists(target_dir):
            QMessageBox.warning(self, "提示", f"指定的目录不存在: {target_dir}")
            return

        scanned_files: List[Dict[str, Any]] = []
        try:
            assets = UnifiedScanner.scan_directory(
                root_paths=[target_dir],
                prune_collectives=True,
                skip_system_protected=True,
                max_depth=3
            )
            for asset in assets:
                scanned_files.append({
                    "path": asset.path,
                    "name": asset.name,
                    "size": asset.size,
                    "mtime": asset.mtime,
                    "ext": asset.ext,
                    "category": asset.category,
                    "is_directory_collective": asset.is_collective,
                    "collective_info": asset.collective_info,
                    "umbrella_anchor": asset.umbrella_anchor,
                    "metadata": asset.metadata
                })
        except Exception as e:
            QMessageBox.critical(self, "扫描异常", f"扫描目录发生错误: {e}")
            return

        if not scanned_files:
            QMessageBox.information(self, "提示", f"[{title}] 目录中暂无待整理文件。")
            return

        dest_root = "D:/归档备份"
        plan = AutomationPlanResolver.resolve_quick_organize_plan(
            title=title,
            target_dir=target_dir,
            dest_root=dest_root,
            scanned_files=scanned_files,
            organize_mode="comprehensive"
        )

        dlg = OrganizePreviewDialog(
            classification_items=plan.proposed_groups,
            destination_root=dest_root,
            conflict_policy="auto_rename",
            allow_execute=True,
            parent=self
        )
        dlg.exec()

    def _open_routing_viewer(self):
        """打开全局拓扑路由知识库对话框"""
        from app.ui.components.routing_table_viewer import RoutingTableViewerDialog
        dlg = RoutingTableViewerDialog(self)
        dlg.exec()
