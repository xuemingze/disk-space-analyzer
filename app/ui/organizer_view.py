import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QSplitter, QFrame, QGroupBox,
    QSlider, QComboBox, QMessageBox, QProgressBar, QListWidget,
    QListWidgetItem
)
from PySide6.QtCore import Qt, QThread, Signal

from app.config import app_config
from app.core.ai_service import AIService
from app.core.app_detector import AppDetector
from app.ui.components.data_table import FileDataGridWidget
from app.ui.components.organize_dialog import OrganizePreviewDialog
from app.utils.file_helper import categorize_file_by_ext, format_size
from app.utils.logger import app_logger


class DirectoryScanWorker(QThread):
    """后台目录扫描工作线程 (杜绝选择大目录时主线程卡死)"""
    scan_completed = Signal(list)
    scan_error = Signal(str)

    def __init__(self, directory_path: str, parent=None):
        super().__init__(parent)
        self.directory_path = directory_path

    def run(self):
        try:
            items = []
            with os.scandir(self.directory_path) as it:
                for entry in it:
                    try:
                        st = entry.stat()
                        is_dir = entry.is_dir()
                        fsize = st.st_size if not is_dir else 0
                        cat = "文件夹" if is_dir else categorize_file_by_ext(Path(entry.path))
                        
                        items.append({
                            "name": entry.name,
                            "path": entry.path,
                            "size": fsize,
                            "is_dir": is_dir,
                            "category": cat,
                            "mtime": st.st_mtime,
                            "is_recommended": False,
                            "phase_status": "已就绪"
                        })
                    except (PermissionError, FileNotFoundError):
                        continue
            
            # 按大小降序排序
            items.sort(key=lambda x: x["size"], reverse=True)
            self.scan_completed.emit(items)
        except Exception as e:
            self.scan_error.emit(str(e))


class OrganizerView(QWidget):
    """
    智能文件整理与归档管理页 (支持以 App / 工具链为原子单元的树状目录整理规划)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_dir = str(Path.home() / "Downloads")
        self.current_file_items: List[Dict[str, Any]] = []
        self.scan_worker: Optional[DirectoryScanWorker] = None

        self.init_ui()
        self.load_directory(self.current_dir)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 1. 顶部当前路径选择与导航条
        nav_card = QFrame()
        nav_card.setProperty("class", "CardFrame")
        nav_layout = QHBoxLayout(nav_card)
        nav_layout.setContentsMargins(12, 10, 12, 10)
        nav_layout.setSpacing(8)

        nav_layout.addWidget(QLabel("📂 当前浏览目录:"))
        self.dir_input = QLineEdit(self.current_dir)
        self.dir_input.returnPressed.connect(self.on_dir_input_entered)
        nav_layout.addWidget(self.dir_input, 1)

        self.btn_browse = QPushButton("浏览...")
        self.btn_browse.setProperty("class", "SecondaryButton")
        self.btn_browse.clicked.connect(self.browse_directory)
        nav_layout.addWidget(self.btn_browse)

        self.btn_reload = QPushButton("🔄 刷新")
        self.btn_reload.setProperty("class", "SecondaryButton")
        self.btn_reload.clicked.connect(lambda: self.load_directory(self.current_dir))
        nav_layout.addWidget(self.btn_reload)

        main_layout.addWidget(nav_card)

        # 2. 中间主体 (左侧配置面板 + 右侧文件表格)
        splitter = QSplitter(Qt.Horizontal)

        # 左侧控制面板
        left_panel = QFrame()
        left_panel.setProperty("class", "CardFrame")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(12)

        # 常用目录快捷入口
        quick_box = QGroupBox("📌 常用目录快捷入口")
        quick_box_layout = QVBoxLayout(quick_box)
        self.quick_list = QListWidget()
        self.quick_list.setStyleSheet("background-color: #0F172A; border: 1px solid #334155; border-radius: 4px;")
        self.quick_list.addItem(QListWidgetItem("📥 用户下载目录 (Downloads)"))
        self.quick_list.addItem(QListWidgetItem("🖥️ 桌面常用目录 (Desktop)"))
        self.quick_list.addItem(QListWidgetItem("📄 文档存储目录 (Documents)"))
        self.quick_list.itemClicked.connect(self.on_quick_folder_clicked)
        quick_box_layout.addWidget(self.quick_list)
        left_layout.addWidget(quick_box)

        # App 与工具链识别策略配置
        scheme_box = QGroupBox("⚙️ App/工具链识别与归档偏好配置")
        scheme_layout = QVBoxLayout(scheme_box)
        scheme_layout.setContentsMargins(10, 12, 10, 10)
        scheme_layout.setSpacing(8)

        # 维度权重滑块
        self.app_weight_slider = self._create_weight_slider("App / 软件特征权重:", 90, scheme_layout)
        self.tree_depth_slider = self._create_weight_slider("父目录层级聚类权重:", 85, scheme_layout)
        self.heuristics_slider = self._create_weight_slider("启发式配置文件探测:", 80, scheme_layout)

        # 冲突策略
        conflict_row = QHBoxLayout()
        conflict_lbl = QLabel("同名冲突策略:")
        conflict_lbl.setStyleSheet("font-size: 11px; color: #94A3B8;")
        self.conflict_combo = QComboBox()
        self.conflict_combo.addItems(["自动增量重命名 (_1)", "跳过冲突文件", "直接覆盖旧文件"])
        conflict_row.addWidget(conflict_lbl)
        conflict_row.addWidget(self.conflict_combo, 1)
        scheme_layout.addLayout(conflict_row)

        # 归档目标目录
        dest_box = QVBoxLayout()
        dest_lbl = QLabel("归档目标根路径:")
        dest_lbl.setStyleSheet("font-size: 11px; color: #94A3B8;")
        
        dest_row = QHBoxLayout()
        self.dest_input = QLineEdit(app_config.get("archive_dir", default="D:/归档备份"))
        self.btn_dest_browse = QPushButton("📁")
        self.btn_dest_browse.setFixedWidth(32)
        self.btn_dest_browse.clicked.connect(self.browse_destination)
        dest_row.addWidget(self.dest_input, 1)
        dest_row.addWidget(self.btn_dest_browse)
        
        dest_box.addWidget(dest_lbl)
        dest_box.addLayout(dest_row)
        scheme_layout.addLayout(dest_box)

        left_layout.addWidget(scheme_box)
        left_layout.addStretch()

        splitter.addWidget(left_panel)

        # 右侧文件列表表格
        right_panel = QFrame()
        right_panel.setProperty("class", "CardFrame")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(8)

        self.file_table = FileDataGridWidget(is_selectable=True)
        self.file_table.selection_changed_signal.connect(self.on_selection_changed)
        right_layout.addWidget(self.file_table, 1)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(1, 3)

        main_layout.addWidget(splitter, 1)

        # 3. 底部交互操作栏
        bottom_bar = QFrame()
        bottom_bar.setProperty("class", "CardFrame")
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(12, 8, 12, 8)
        bottom_layout.setSpacing(10)

        # 选中统计
        self.sel_stat_lbl = QLabel("已选中: 0 个文件 (0 B)")
        self.sel_stat_lbl.setStyleSheet("color: #38BDF8; font-weight: bold;")
        bottom_layout.addWidget(self.sel_stat_lbl)
        bottom_layout.addStretch()

        # 仅选推荐
        self.btn_select_rec = QPushButton("📌 仅选安全推荐项")
        self.btn_select_rec.setProperty("class", "SecondaryButton")
        self.btn_select_rec.clicked.connect(self.execute_select_recommended_only)
        bottom_layout.addWidget(self.btn_select_rec)

        # 预览归档计划
        self.btn_preview_plan = QPushButton("🌳 预览目录树归档计划")
        self.btn_preview_plan.setStyleSheet("background-color: #0284C7; border-color: #38BDF8; font-weight: bold;")
        self.btn_preview_plan.clicked.connect(self.preview_organize_plan)
        bottom_layout.addWidget(self.btn_preview_plan)

        # AI 自动处理
        self.btn_ai_auto = QPushButton("🤖 AI 目录级自动规划与归档")
        self.btn_ai_auto.setStyleSheet("background-color: #059669; border-color: #10B981; font-weight: bold; padding: 8px 18px;")
        self.btn_ai_auto.clicked.connect(self.execute_ai_auto_process)
        bottom_layout.addWidget(self.btn_ai_auto)

        main_layout.addWidget(bottom_bar)

    def _create_weight_slider(self, label_text: str, default_val: int, layout: QVBoxLayout) -> QSlider:
        row = QHBoxLayout()
        lbl = QLabel(f"{label_text} {default_val}%")
        lbl.setStyleSheet("font-size: 11px; color: #94A3B8;")
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(default_val)
        slider.valueChanged.connect(lambda val, l=lbl, t=label_text: l.setText(f"{t} {val}%"))
        
        row.addWidget(lbl)
        layout.addLayout(row)
        layout.addWidget(slider)
        return slider

    def get_classification_weights(self) -> Dict[str, Any]:
        return {
            "app_weight": self.app_weight_slider.value() / 100.0,
            "tree_depth_weight": self.tree_depth_slider.value() / 100.0,
            "heuristics_weight": self.heuristics_slider.value() / 100.0,
            "conflict_policy": "auto_rename" if self.conflict_combo.currentIndex() == 0 else ("skip" if self.conflict_combo.currentIndex() == 1 else "overwrite")
        }

    def on_quick_folder_clicked(self, item: QListWidgetItem):
        txt = item.text()
        if "Downloads" in txt:
            self.load_directory(str(Path.home() / "Downloads"))
        elif "Desktop" in txt:
            self.load_directory(str(Path.home() / "Desktop"))
        elif "Documents" in txt:
            self.load_directory(str(Path.home() / "Documents"))

    def browse_directory(self):
        selected = QFileDialog.getExistingDirectory(self, "选择整理目录", self.current_dir)
        if selected:
            self.load_directory(selected)

    def browse_destination(self):
        selected = QFileDialog.getExistingDirectory(self, "选择归档目标目录", self.dest_input.text().strip() or "D:/")
        if selected:
            self.dest_input.setText(selected)
            app_config.set("archive_dir", selected)

    def on_dir_input_entered(self):
        text = self.dir_input.text().strip()
        if os.path.exists(text) and os.path.isdir(text):
            self.load_directory(text)
        else:
            QMessageBox.warning(self, "提示", "输入的路径不存在或不是有效目录！")

    def load_directory(self, dir_path: str):
        if not os.path.exists(dir_path):
            return

        self.current_dir = os.path.normpath(dir_path)
        self.dir_input.setText(self.current_dir)
        self.sel_stat_lbl.setText("正在加载目录文件...")

        self.scan_worker = DirectoryScanWorker(self.current_dir)
        self.scan_worker.scan_completed.connect(self.on_directory_loaded)
        self.scan_worker.scan_error.connect(lambda err: QMessageBox.warning(self, "读取异常", f"加载目录失败: {err}"))
        self.scan_worker.start()

    def on_directory_loaded(self, items: List[Dict[str, Any]]):
        self.current_file_items = items
        self.file_table.populate_data(items)
        self.on_selection_changed(0, 0)

    def on_selection_changed(self, count: int, total_bytes: int):
        self.sel_stat_lbl.setText(f"已选中: {count} 个文件 ({format_size(total_bytes)})")

    def preview_organize_plan(self):
        """生成并预览基于 App/工具链的树状目录归档计划"""
        checked_paths = self.file_table.get_checked_paths()
        
        target_items = []
        if checked_paths:
            target_items = [f for f in self.current_file_items if f["path"] in checked_paths]
        else:
            target_items = self.current_file_items

        if not target_items:
            QMessageBox.warning(self, "提示", "当前目录中没有可整理的文件！")
            return

        dest_root = self.dest_input.text().strip()
        if not dest_root:
            QMessageBox.warning(self, "提示", "请先配置有效的归档目标根路径！")
            return

        weights = self.get_classification_weights()
        llm_cfg = app_config.get("llm", default={})

        classified_groups = AIService.classify_files_with_ai(
            base_url=llm_cfg.get("base_url", ""),
            api_key=llm_cfg.get("api_key", ""),
            model=llm_cfg.get("model", ""),
            file_items=target_items,
            destination_root=dest_root,
            weights=weights
        )

        dlg = OrganizePreviewDialog(
            classification_items=classified_groups,
            destination_root=dest_root,
            conflict_policy=weights["conflict_policy"],
            parent=self
        )
        if dlg.exec():
            self.load_directory(self.current_dir)

    def execute_select_recommended_only(self):
        """仅勾选低风险、免确认的安全推荐项，不执行任何磁盘移动"""
        if not self.current_file_items:
            return
        
        dest_root = self.dest_input.text().strip()
        weights = self.get_classification_weights()
        llm_cfg = app_config.get("llm", default={})

        classified_groups = AIService.classify_files_with_ai(
            base_url=llm_cfg.get("base_url", ""),
            api_key=llm_cfg.get("api_key", ""),
            model=llm_cfg.get("model", ""),
            file_items=self.current_file_items,
            destination_root=dest_root,
            weights=weights
        )

        recommended_paths = []
        for g in classified_groups:
            if not g.get("require_confirmation", False) and g.get("confidence", 0) >= 0.7 and "低风险" in g.get("risk_level", ""):
                for sub in g.get("sub_items", []):
                    recommended_paths.append(sub["original_path"])

        self.file_table.select_ai_recommended_paths(recommended_paths)
        QMessageBox.information(
            self, "仅选推荐就绪",
            f"已基于 App/工具链特征为您勾选了 {len(recommended_paths)} 个低风险推荐文件。\n未执行任何移动，您可在列表中进一步修改勾选。"
        )

    def execute_ai_auto_process(self):
        """AI 自动处理：一键生成计划并在用户树状目录确认后后台安全归档"""
        if not self.current_file_items:
            QMessageBox.warning(self, "提示", "当前目录无文件！")
            return

        self.preview_organize_plan()
