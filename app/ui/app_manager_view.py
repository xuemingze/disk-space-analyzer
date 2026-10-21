"""
app/ui/app_manager_view.py
左侧一级导航看板:「🎯 软件与应用管理 (App Manager)」
全量聚合呈现已识别软件集合 (注册表 + 系统原生内置组件 + 用户收拢沉淀自定义)
严格遵循《列表与表格模块 UI 设计铁律》:
- 表格垂直表头锁死 44px 行高 (setDefaultSectionSize(44) + QHeaderView.Fixed)
- 列宽清晰分层
- 操作按钮独立 QWidget 居中包装，高度固定 28px 保底
- 列表双击直接在资源管理器中打开物理目录
"""
import os
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QMessageBox, QFileDialog, QInputDialog
)
from PySide6.QtCore import Qt, Signal

from app.core.registry_detector import RegistryAppDetector, InstalledAppInfo
from app.core.asset_promoter import AssetPromoterService
from app.config import app_config


class AppManagerView(QWidget):
    """🎯 软件与应用管理一级看板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.all_apps: List[InstalledAppInfo] = []
        self._dirty: bool = False
        self._init_ui()
        self.reload_apps()

        # 接入全局沉淀事件，一改俱改
        AssetPromoterService.instance().collective_promoted.connect(self._on_collective_promoted)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        # 头部说明与摘要栏
        top_box = QHBoxLayout()
        header_box = QVBoxLayout()
        title = QLabel("🎯 软件与应用识别管理 (Installed Apps & Collective Rules)")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1e293b;")
        desc = QLabel(
            "全量汇集系统已识别的原子应用拓扑（Windows 注册表 + 系统原生内置组件 + 用户就地收拢沉淀）。\n"
            "双击任意条目可直接在资源管理器中打开物理根目录；扫描引擎依据此库在源头实施防御性剪枝，杜绝碎片泄漏。"
        )
        desc.setStyleSheet("font-size: 12px; color: #64748b; line-height: 140%;")
        header_box.addWidget(title)
        header_box.addWidget(desc)
        top_box.addLayout(header_box)
        top_box.addStretch()

        self.lbl_stats = QLabel("已收录 0 款应用")
        self.lbl_stats.setStyleSheet(
            "background-color: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; "
            "border-radius: 6px; padding: 6px 14px; font-weight: bold; font-size: 12px;"
        )
        top_box.addWidget(self.lbl_stats)
        layout.addLayout(top_box)

        # 工具栏 (搜索 + 添加 + 刷新)
        tool_bar = QHBoxLayout()
        tool_bar.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 快速搜索应用名称、物理根路径或发布商...")
        self.search_input.setFixedHeight(32)
        self.search_input.textChanged.connect(self._apply_filter)
        tool_bar.addWidget(self.search_input, 1)

        self.btn_add_folder = QPushButton("➕ 添加独立应用目录...")
        self.btn_add_folder.setFixedHeight(32)
        self.btn_add_folder.setStyleSheet("background-color: #2563eb; color: white; border-radius: 4px; font-weight: bold; padding: 0 12px;")
        self.btn_add_folder.clicked.connect(self._on_add_folder_clicked)
        tool_bar.addWidget(self.btn_add_folder)

        self.btn_reload = QPushButton("🔄 重新索引")
        self.btn_reload.setFixedHeight(32)
        self.btn_reload.setStyleSheet("border: 1px solid #cbd5e1; border-radius: 4px; padding: 0 12px;")
        self.btn_reload.clicked.connect(lambda: self.reload_apps(force=True))
        tool_bar.addWidget(self.btn_reload)

        self.btn_ai_insights = QPushButton("🤖 AI 智能应用研判")
        self.btn_ai_insights.setFixedHeight(32)
        self.btn_ai_insights.setStyleSheet(
            "QPushButton { background-color: #4f46e5; color: white; border-radius: 4px; font-weight: bold; padding: 0 14px; }"
            "QPushButton:hover { background-color: #4338ca; }"
        )
        self.btn_ai_insights.clicked.connect(self._on_ai_insights_clicked)
        tool_bar.addWidget(self.btn_ai_insights)

        layout.addLayout(tool_bar)

        # 全量软件资产表格 - 严格遵循 UI 铁律
        self.table_apps = QTableWidget()
        self.table_apps.setColumnCount(6)
        self.table_apps.setHorizontalHeaderLabels([
            "序号", "应用 / 实体名称", "来源类别", "发布商 / 版本", "物理安装根路径", "操作"
        ])
        self.table_apps.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_apps.setEditTriggers(QTableWidget.NoEditTriggers)

        # 铁律 1: 锁死 44px 行高
        vh = self.table_apps.verticalHeader()
        vh.setDefaultSectionSize(44)
        vh.setSectionResizeMode(QHeaderView.Fixed)
        vh.setVisible(False)

        # 铁律 2: 列宽分层
        hh = self.table_apps.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table_apps.setColumnWidth(0, 60)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        self.table_apps.setColumnWidth(1, 200)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table_apps.setColumnWidth(2, 120)
        hh.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table_apps.setColumnWidth(3, 160)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.Fixed)
        self.table_apps.setColumnWidth(5, 200)

        # 绑定双击事件：直接打开物理目录
        self.table_apps.cellDoubleClicked.connect(self._on_cell_double_clicked)

        layout.addWidget(self.table_apps)

    def reload_apps(self, force: bool = False):
        """重新拉取注册表、系统组件与自定义应用字典"""
        apps_dict = RegistryAppDetector.get_installed_apps(force_reload=force)
        self.all_apps = list(apps_dict.values())
        # 排序：自定义项与系统预置优先，其次按名称字母序
        self.all_apps.sort(key=lambda a: (0 if a.source == "custom" else (1 if a.source == "system_builtin" else 2), a.name.lower()))
        self._refresh_table(self.all_apps)

    def _refresh_table(self, app_list: List[InstalledAppInfo]):
        self.table_apps.setUpdatesEnabled(False)
        try:
            self._do_refresh_table(app_list)
        finally:
            self.table_apps.setUpdatesEnabled(True)

    def _do_refresh_table(self, app_list: List[InstalledAppInfo]):
        self.table_apps.setRowCount(len(app_list))

        reg_cnt = sum(1 for a in self.all_apps if a.source == "registry")
        sys_cnt = sum(1 for a in self.all_apps if a.source == "system_builtin")
        cus_cnt = sum(1 for a in self.all_apps if a.source == "custom")

        self.lbl_stats.setText(f"已收录 {len(self.all_apps)} 款应用 | 注册表: {reg_cnt} | 系统内置: {sys_cnt} | 自定义沉淀: {cus_cnt}")

        for row, app in enumerate(app_list):
            # 0: 序号
            it_idx = QTableWidgetItem(str(row + 1))
            it_idx.setTextAlignment(Qt.AlignCenter)
            self.table_apps.setItem(row, 0, it_idx)

            # 1: 软件名称
            it_name = QTableWidgetItem(f"📦 {app.name}")
            it_name.setToolTip(f"双击打开: {app.install_root}")
            self.table_apps.setItem(row, 1, it_name)

            # 2: 来源类别
            source_map = {
                "registry": ("系统注册表", "#2563eb", "#eff6ff"),
                "system_builtin": ("系统预置组件", "#7c3aed", "#f5f3ff"),
                "custom": ("自定义沉淀", "#16a34a", "#f0fdf4")
            }
            s_text, s_color, s_bg = source_map.get(app.source, ("已知应用", "#475569", "#f1f5f9"))
            it_src = QTableWidgetItem(s_text)
            it_src.setTextAlignment(Qt.AlignCenter)
            it_src.setForeground(Qt.GlobalColor(Qt.darkBlue if app.source == "registry" else (Qt.darkMagenta if app.source == "system_builtin" else Qt.darkGreen)))
            self.table_apps.setItem(row, 2, it_src)

            # 3: 发布商 / 版本
            pub_str = app.publisher or "未知厂商"
            if app.version:
                pub_str += f" ({app.version})"
            it_pub = QTableWidgetItem(pub_str)
            it_pub.setTextAlignment(Qt.AlignCenter)
            self.table_apps.setItem(row, 3, it_pub)

            # 4: 物理安装路径
            it_path = QTableWidgetItem(app.install_root)
            it_path.setToolTip(f"双击直接打开目录:\n{app.install_root}")
            self.table_apps.setItem(row, 4, it_path)

            # 5: 操作栏 - 铁律 3: 独立 QWidget 居中包装，固定 28px 高度
            act_container = QWidget()
            act_layout = QHBoxLayout(act_container)
            act_layout.setContentsMargins(0, 0, 0, 0)
            act_layout.setSpacing(6)
            act_layout.setAlignment(Qt.AlignCenter)

            btn_open = QPushButton("📂 打开")
            btn_open.setFixedSize(56, 28)
            btn_open.setStyleSheet(
                "QPushButton { background-color: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; border-radius: 4px; font-size: 11px; }"
                "QPushButton:hover { background-color: #e2e8f0; }"
            )
            btn_open.clicked.connect(lambda _, p=app.install_root: self._open_directory(p))
            act_layout.addWidget(btn_open)

            btn_ai = QPushButton("🤖 研判")
            btn_ai.setFixedSize(56, 28)
            btn_ai.setStyleSheet(
                "QPushButton { background-color: #eff6ff; color: #2563eb; border: 1px solid #bfdbfe; border-radius: 4px; font-size: 11px; font-weight: bold; }"
                "QPushButton:hover { background-color: #dbeafe; }"
            )
            btn_ai.clicked.connect(lambda _, a=app: self._open_ai_dialog_for_app(a))
            act_layout.addWidget(btn_ai)

            if app.source == "custom":
                btn_del = QPushButton("删除")
                btn_del.setFixedSize(56, 28)
                btn_del.setStyleSheet(
                    "QPushButton { background-color: #fee2e2; color: #ef4444; border: 1px solid #fca5a5; border-radius: 4px; font-size: 11px; }"
                    "QPushButton:hover { background-color: #fecaca; color: #dc2626; }"
                )
                btn_del.clicked.connect(lambda _, p=app.install_root: self._remove_custom_app(p))
                act_layout.addWidget(btn_del)

            self.table_apps.setCellWidget(row, 5, act_container)

    def _apply_filter(self, text: str):
        kw = text.strip().lower()
        if not kw:
            self._refresh_table(self.all_apps)
            return

        filtered = [
            a for a in self.all_apps
            if kw in a.name.lower() or kw in a.install_root.lower() or kw in a.publisher.lower()
        ]
        self._refresh_table(filtered)

    def _open_ai_dialog_for_app(self, app_info: InstalledAppInfo):
        from app.ui.components.ai_insight_dialog import AIAssetInsightDialog
        asset_dict = {
            "name": app_info.name,
            "path": app_info.install_root,
            "publisher": app_info.publisher,
            "category": "已安装应用",
            "is_directory_collective": True,
            "file_count": 1
        }
        dlg = AIAssetInsightDialog(asset_dict, self)
        dlg.exec()

    def _on_ai_insights_clicked(self):
        curr_row = self.table_apps.currentRow()
        if curr_row < 0:
            QMessageBox.information(self, "提示", "请先在表格中单击选中需要 AI 研判的应用条目！")
            return
        it_name = self.table_apps.item(curr_row, 1)
        it_path = self.table_apps.item(curr_row, 4)
        if it_name and it_path:
            name_clean = it_name.text().replace("📦 ", "").strip()
            from app.ui.components.ai_insight_dialog import AIAssetInsightDialog
            asset_dict = {
                "name": name_clean,
                "path": it_path.text().strip(),
                "category": "已安装应用",
                "is_directory_collective": True,
                "file_count": 1
            }
            dlg = AIAssetInsightDialog(asset_dict, self)
            dlg.exec()

    def _on_cell_double_clicked(self, row: int, col: int):
        it_path = self.table_apps.item(row, 4)
        if it_path and it_path.text():
            self._open_directory(it_path.text())

    def _open_directory(self, dir_path: str):
        norm = os.path.normpath(dir_path)
        if os.path.exists(norm):
            os.startfile(norm)
        else:
            QMessageBox.warning(self, "路径不存在", f"未找到该软件物理目录:\n{norm}")

    def _on_add_folder_clicked(self):
        d = QFileDialog.getExistingDirectory(self, "选择独立应用物理安装目录")
        if d:
            from app.ui.components.promote_collective_dialog import PromoteCollectiveDialog
            dlg = PromoteCollectiveDialog(d, self)
            if dlg.exec() == PromoteCollectiveDialog.Accepted:
                t_dir = dlg.selected_target_dir
                a_name = dlg.app_name
                AssetPromoterService.persist_collective(t_dir, app_name=a_name)
                self.reload_apps(force=True)

    def _remove_custom_app(self, app_path: str):
        norm_p = os.path.normpath(app_path)
        low_p = os.path.normcase(norm_p)
        reply = QMessageBox.question(self, "确认删除", f"确定从规则中移除自定义软件目录吗？\n{norm_p}", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            cfg_dirs = list(app_config.get("custom_app_dirs", default=[]))
            updated = []
            for item in cfg_dirs:
                p = item.get("path") if isinstance(item, dict) else str(item)
                if os.path.normcase(os.path.normpath(p)) != low_p:
                    updated.append(item)
            app_config.set("custom_app_dirs", updated, level="global")
            RegistryAppDetector.set_custom_apps(updated)
            self.reload_apps(force=True)

    def _on_collective_promoted(self, target_dir: str, new_asset: dict):
        """当外部表格触发收拢转集合时，若视图不可见则标记脏位，杜绝非活跃页面占用主线程"""
        if self.isVisible():
            self.reload_apps(force=True)
        else:
            self._dirty = True

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_dirty", False):
            self._dirty = False
            self.reload_apps(force=True)
