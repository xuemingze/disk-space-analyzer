"""
app/ui/dedup/directory_select_step.py
步骤 1: 源目录与目标融合目录配置卡片
严格遵循表格行高 44px、操作栏独立容器固定 28px 高度保底铁律
"""
import os
from typing import List, Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
    QLineEdit, QComboBox, QCheckBox, QGroupBox, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from app.dedup.models import DedupScanConfig
from app.dedup.task_config_manager import DedupTaskConfigManager
from app.utils.lock_detector import is_destination_valid


class DirectorySelectStep(QWidget):
    """步骤 1: 目录配置卡片"""
    config_ready = Signal(DedupScanConfig)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.source_dirs: List[str] = []
        self._init_ui()
        self._load_saved_config()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # 头部说明
        header_box = QWidget()
        h_layout = QVBoxLayout(header_box)
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(4)
        title = QLabel("📂 步骤 1: 选择查重与融合目录")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1e293b;")
        desc = QLabel("配置需要联合查重的多个源目录，并指定最终融合汇聚的目标目录。系统将自动进行拓扑防嵌套检查。")
        desc.setStyleSheet("font-size: 12px; color: #64748b;")
        h_layout.addWidget(title)
        h_layout.addWidget(desc)
        layout.addWidget(header_box)

        # 源目录配置组
        src_group = QGroupBox("源目录列表 (多源联合索引)")
        src_group.setStyleSheet("QGroupBox { font-weight: bold; color: #334155; }")
        src_layout = QVBoxLayout(src_group)
        src_layout.setSpacing(8)

        # 工具栏按钮
        btn_bar = QHBoxLayout()
        self.btn_add_src = QPushButton("➕ 添加源目录")
        self.btn_add_src.setFixedHeight(30)
        self.btn_add_src.setStyleSheet("background-color: #3b82f6; color: white; border-radius: 4px; padding: 0 12px; font-weight: bold;")
        self.btn_add_src.clicked.connect(self._add_source_dir)

        self.btn_clear_src = QPushButton("🗑️ 清空列表")
        self.btn_clear_src.setFixedHeight(30)
        self.btn_clear_src.setStyleSheet("background-color: #f1f5f9; color: #64748b; border: 1px solid #cbd5e1; border-radius: 4px; padding: 0 10px;")
        self.btn_clear_src.clicked.connect(self._clear_sources)

        btn_bar.addWidget(self.btn_add_src)
        btn_bar.addWidget(self.btn_clear_src)
        btn_bar.addStretch()
        src_layout.addLayout(btn_bar)

        # 源目录表格 - 严格遵循 UI 铁律
        self.table_sources = QTableWidget()
        self.table_sources.setColumnCount(3)
        self.table_sources.setHorizontalHeaderLabels(["序号", "源目录物理路径", "操作"])
        self.table_sources.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_sources.setEditTriggers(QTableWidget.NoEditTriggers)

        # 铁律 1: 锁死行高 44px
        v_header = self.table_sources.verticalHeader()
        v_header.setDefaultSectionSize(44)
        v_header.setSectionResizeMode(QHeaderView.Fixed)
        v_header.setVisible(False)

        # 铁律 2: 列宽明确分层
        h_header = self.table_sources.horizontalHeader()
        h_header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table_sources.setColumnWidth(0, 60)
        h_header.setSectionResizeMode(1, QHeaderView.Stretch)
        h_header.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table_sources.setColumnWidth(2, 100)

        src_layout.addWidget(self.table_sources)
        layout.addWidget(src_group)

        # 目标融合目录与隔离区配置组
        dest_group = QGroupBox("目标汇聚与隔离配置")
        dest_group.setStyleSheet("QGroupBox { font-weight: bold; color: #334155; }")
        dest_layout = QVBoxLayout(dest_group)
        dest_layout.setSpacing(10)

        # 目标融合目录
        t_row = QHBoxLayout()
        t_label = QLabel("🎯 目标融合目录:")
        t_label.setFixedWidth(110)
        t_label.setStyleSheet("color: #475569;")
        self.txt_target_dir = QLineEdit()
        self.txt_target_dir.setPlaceholderText("请选择融合最终归宿的目标根目录...")
        self.txt_target_dir.setFixedHeight(32)
        btn_browse_target = QPushButton("📁 浏览...")
        btn_browse_target.setFixedHeight(32)
        btn_browse_target.setFixedWidth(80)
        btn_browse_target.clicked.connect(self._browse_target_dir)
        t_row.addWidget(t_label)
        t_row.addWidget(self.txt_target_dir)
        t_row.addWidget(btn_browse_target)
        dest_layout.addLayout(t_row)

        # 重复项隔离目录
        iso_row = QHBoxLayout()
        iso_label = QLabel("🛡️ 重复隔离目录:")
        iso_label.setFixedWidth(110)
        iso_label.setStyleSheet("color: #475569;")
        self.txt_iso_dir = QLineEdit()
        self.txt_iso_dir.setPlaceholderText("冗余副本将移入此目录，留空默认移入目标目录下的 _Duplicate_Isolation...")
        self.txt_iso_dir.setFixedHeight(32)
        btn_browse_iso = QPushButton("📁 浏览...")
        btn_browse_iso.setFixedHeight(32)
        btn_browse_iso.setFixedWidth(80)
        btn_browse_iso.clicked.connect(self._browse_iso_dir)
        iso_row.addWidget(iso_label)
        iso_row.addWidget(self.txt_iso_dir)
        iso_row.addWidget(btn_browse_iso)
        dest_layout.addLayout(iso_row)

        # 策略与偏好设置
        opt_row = QHBoxLayout()
        p_label = QLabel("⚖️ 重复正本保留偏好:")
        p_label.setStyleSheet("color: #475569;")
        self.cmb_pref = QComboBox()
        self.cmb_pref.addItem("优先保留主源目录 (首选目录)", "keep_primary")
        self.cmb_pref.addItem("优先保留最新修改的文件", "keep_newest")
        self.cmb_pref.addItem("优先保留最早创建/归档的文件", "keep_oldest")
        self.cmb_pref.addItem("优先保留路径层级最短的文件", "keep_shortest_path")
        self.cmb_pref.setFixedHeight(30)

        self.chk_prune = QCheckBox("启用原子狭义实体源头剪枝 (保护软件/代码工程)")
        self.chk_prune.setChecked(True)
        self.chk_sys = QCheckBox("跳过系统保护关键目录")
        self.chk_sys.setChecked(True)

        opt_row.addWidget(p_label)
        opt_row.addWidget(self.cmb_pref)
        opt_row.addSpacing(16)
        opt_row.addWidget(self.chk_prune)
        opt_row.addWidget(self.chk_sys)
        opt_row.addStretch()
        dest_layout.addLayout(opt_row)

        layout.addWidget(dest_group)

        # 底部下一步操作栏
        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch()
        self.btn_next = QPushButton("下一步: 启动联合索引与查重 ➔")
        self.btn_next.setFixedHeight(36)
        self.btn_next.setStyleSheet(
            "background-color: #2563eb; color: white; font-weight: bold; border-radius: 6px; padding: 0 20px; font-size: 13px;"
        )
        self.btn_next.clicked.connect(self._on_next_clicked)
        bottom_bar.addWidget(self.btn_next)
        layout.addLayout(bottom_bar)

    def _load_saved_config(self):
        cfg = DedupTaskConfigManager.load_config()
        self.source_dirs = [d for d in cfg.source_dirs if os.path.exists(d)]
        if cfg.target_dir:
            self.txt_target_dir.setText(cfg.target_dir)
        if cfg.isolation_dir:
            self.txt_iso_dir.setText(cfg.isolation_dir)
        self.chk_prune.setChecked(cfg.prune_collectives)
        self.chk_sys.setChecked(cfg.skip_system_protected)
        idx = self.cmb_pref.findData(cfg.dedup_keep_preference)
        if idx >= 0:
            self.cmb_pref.setCurrentIndex(idx)
        self._refresh_source_table()

    def _refresh_source_table(self):
        self.table_sources.setRowCount(len(self.source_dirs))
        for row, path in enumerate(self.source_dirs):
            # 序号
            item_idx = QTableWidgetItem(str(row + 1))
            item_idx.setTextAlignment(Qt.AlignCenter)
            self.table_sources.setItem(row, 0, item_idx)

            # 路径
            item_path = QTableWidgetItem(path)
            item_path.setToolTip(path)
            self.table_sources.setItem(row, 1, item_path)

            # 铁律 3: 操作栏独立 QWidget 居中包装，固定 28px 高度
            action_container = QWidget()
            action_layout = QHBoxLayout(action_container)
            action_layout.setContentsMargins(0, 0, 0, 0)
            action_layout.setAlignment(Qt.AlignCenter)

            btn_del = QPushButton("删除")
            btn_del.setFixedSize(56, 28)
            btn_del.setStyleSheet(
                "QPushButton { background-color: #fee2e2; color: #ef4444; border: 1px solid #fca5a5; border-radius: 4px; font-size: 11px; }"
                "QPushButton:hover { background-color: #fecaca; color: #dc2626; }"
            )
            btn_del.clicked.connect(lambda _, r=row: self._remove_source_dir(r))
            action_layout.addWidget(btn_del)
            self.table_sources.setCellWidget(row, 2, action_container)

    def _add_source_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择源目录")
        if d:
            norm_d = os.path.normpath(d)
            if norm_d not in self.source_dirs:
                self.source_dirs.append(norm_d)
                self._refresh_source_table()

    def _remove_source_dir(self, row: int):
        if 0 <= row < len(self.source_dirs):
            self.source_dirs.pop(row)
            self._refresh_source_table()

    def _clear_sources(self):
        self.source_dirs.clear()
        self._refresh_source_table()

    def _browse_target_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择目标融合目录")
        if d:
            self.txt_target_dir.setText(os.path.normpath(d))

    def _browse_iso_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择重复项隔离目录")
        if d:
            self.txt_iso_dir.setText(os.path.normpath(d))

    def _on_next_clicked(self):
        if not self.source_dirs:
            QMessageBox.warning(self, "提示", "请至少添加一个源目录！")
            return

        target_d = self.txt_target_dir.text().strip()
        if not target_d:
            QMessageBox.warning(self, "提示", "请指定目标融合目录！")
            return

        norm_target = os.path.normpath(target_d)

        # 拓扑冲突与包含校验
        for src in self.source_dirs:
            valid, msg = is_destination_valid(src, norm_target)
            if not valid:
                QMessageBox.critical(self, "拓扑冲突拦截", f"源目录 [{os.path.basename(src)}] 与目标目录产生拓扑冲突:\n{msg}")
                return

        cfg = DedupScanConfig(
            source_dirs=list(self.source_dirs),
            target_dir=norm_target,
            isolation_dir=self.txt_iso_dir.text().strip() or None,
            prune_collectives=self.chk_prune.isChecked(),
            skip_system_protected=self.chk_sys.isChecked(),
            dedup_keep_preference=self.cmb_pref.currentData()
        )

        # 持久化
        DedupTaskConfigManager.save_config(cfg)
        self.config_ready.emit(cfg)
