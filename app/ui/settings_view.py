import os
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QGroupBox, QFileDialog, QMessageBox,
    QFrame, QCheckBox, QSpinBox, QInputDialog, QListView, QTextEdit,
    QListWidget, QListWidgetItem, QAbstractItemView, QScrollArea,
    QSizePolicy, QMenu, QApplication
)
from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QClipboard, QAction

from app.config import app_config, BUILTIN_PROFILES
from app.core.ai_service import AIService
from app.core.hash_cache import hash_cache
from app.utils.logger import app_logger


class FetchModelsWorker(QThread):
    finished_signal = Signal(bool, list, str)

    def __init__(self, base_url: str, api_key: str, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.api_key = api_key

    def run(self):
        ok, models, msg = AIService.fetch_models(self.base_url, self.api_key)
        self.finished_signal.emit(ok, models, msg)


class TestConnectionWorker(QThread):
    finished_signal = Signal(bool, str)

    def __init__(self, base_url: str, api_key: str, model: str, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    def run(self):
        ok, msg = AIService.test_connection(self.base_url, self.api_key, self.model)
        self.finished_signal.emit(ok, msg)


class SettingsView(QWidget):
    """
    配置继承追踪、AI 模型拉取、忽略路径与全局参数管理页面 (Settings)
    支持：
    - 完整 QScrollArea 布局与字体缩放自适应（100%, 125%, 150% 等高 DPI 无截断）
    - 忽略文件夹列表查看、浏览添加、手动输入、双击/选中编辑、单条/多条删除、清空及持久化
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.fetch_worker: Optional[FetchModelsWorker] = None
        self.test_worker: Optional[TestConnectionWorker] = None
        self.init_ui()
        self.load_profiles_to_ui()
        self.load_settings()

    def init_ui(self):
        # 顶层主布局使用无边框 QScrollArea 承载内容，防止高 DPI 或大字体缩放下内容被挤压截断
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("SettingsScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.content_widget = QWidget()
        self.content_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(28, 18, 28, 24)
        self.content_layout.setSpacing(14)

        # 标题区域
        title_label = QLabel("⚙️ 系统配置、配置继承与 AI 大模型管理")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #38BDF8;")
        title_label.setWordWrap(True)
        self.content_layout.addWidget(title_label)

        sub_label = QLabel("支持多层配置继承（系统默认 ➔ 全局配置 ➔ 任务级预设），实时展示参数来源与生效值。")
        sub_label.setStyleSheet("color: #94A3B8; font-size: 12px;")
        sub_label.setWordWrap(True)
        self.content_layout.addWidget(sub_label)

        # 0. 配置方案与继承链
        profile_box = QGroupBox("📑 配置预设方案与继承链 (Configuration Profiles)")
        profile_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        profile_layout = QVBoxLayout(profile_box)
        profile_layout.setContentsMargins(14, 14, 14, 14)
        profile_layout.setSpacing(10)

        p_row = QHBoxLayout()
        p_row.setSpacing(10)
        p_lbl = QLabel("当前激活方案:")
        p_lbl.setMinimumWidth(110)
        p_lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        
        self.profile_combo = QComboBox()
        self.profile_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.profile_combo.setView(QListView())
        self.profile_combo.currentIndexChanged.connect(self.on_profile_changed)
        
        self.create_profile_btn = QPushButton("➕ 新建继承方案...")
        self.create_profile_btn.setProperty("class", "SecondaryButton")
        self.create_profile_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.create_profile_btn.clicked.connect(self.create_new_profile)
        
        self.del_profile_btn = QPushButton("🗑️ 删除方案")
        self.del_profile_btn.setProperty("class", "SecondaryButton")
        self.del_profile_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.del_profile_btn.clicked.connect(self.delete_current_profile)
        
        p_row.addWidget(p_lbl)
        p_row.addWidget(self.profile_combo, 1)
        p_row.addWidget(self.create_profile_btn)
        p_row.addWidget(self.del_profile_btn)
        profile_layout.addLayout(p_row)

        self.inheritance_info_label = QLabel("🔗 当前继承链路: Base Config -> default")
        self.inheritance_info_label.setStyleSheet("color: #10B981; font-size: 11px; font-weight: bold;")
        self.inheritance_info_label.setWordWrap(True)
        profile_layout.addWidget(self.inheritance_info_label)

        self.content_layout.addWidget(profile_box)

        # 1. AI 模型接口配置卡片
        llm_box = QGroupBox("🤖 OpenAI 兼容大模型接入配置")
        llm_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        llm_layout = QVBoxLayout(llm_box)
        llm_layout.setContentsMargins(14, 14, 14, 14)
        llm_layout.setSpacing(10)

        # Base URL
        url_layout = QHBoxLayout()
        url_layout.setSpacing(10)
        url_label = QLabel("API Base URL:")
        url_label.setMinimumWidth(110)
        url_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.base_url_input = QLineEdit()
        self.base_url_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.base_url_input.setPlaceholderText("例如: https://api.openai.com/v1 或 https://api.deepseek.com/v1")
        self.src_url_lbl = self._create_source_badge()
        
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.base_url_input, 1)
        url_layout.addWidget(self.src_url_lbl)
        llm_layout.addLayout(url_layout)

        # API Key
        key_layout = QHBoxLayout()
        key_layout.setSpacing(10)
        key_label = QLabel("API Key 密钥:")
        key_label.setMinimumWidth(110)
        key_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.api_key_input = QLineEdit()
        self.api_key_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setPlaceholderText("sk-...")
        self.src_key_lbl = self._create_source_badge()
        
        self.toggle_pwd_btn = QPushButton("👁️ 显示")
        self.toggle_pwd_btn.setProperty("class", "SecondaryButton")
        self.toggle_pwd_btn.setMinimumWidth(72)
        self.toggle_pwd_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.toggle_pwd_btn.clicked.connect(self.toggle_key_visibility)
        
        key_layout.addWidget(key_label)
        key_layout.addWidget(self.api_key_input, 1)
        key_layout.addWidget(self.toggle_pwd_btn)
        key_layout.addWidget(self.src_key_lbl)
        llm_layout.addLayout(key_layout)

        # 模型选择与拉取
        model_layout = QHBoxLayout()
        model_layout.setSpacing(10)
        model_label = QLabel("指定/选择大模型:")
        model_label.setMinimumWidth(110)
        model_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        
        self.model_combo = QComboBox()
        self.model_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.model_combo.setEditable(True)
        self.model_combo.setView(QListView())
        self.model_combo.setMaxVisibleItems(15)
        self.model_combo.setPlaceholderText("选择模型或手动输入 Model ID")
        self.src_model_lbl = self._create_source_badge()
        
        self.fetch_models_btn = QPushButton("🔄 自动拉取远端模型列表")
        self.fetch_models_btn.setStyleSheet("background-color: #4F46E5; border-color: #6366F1; font-weight: bold;")
        self.fetch_models_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.fetch_models_btn.clicked.connect(self.fetch_remote_models)
        
        self.test_conn_btn = QPushButton("⚡ 测试连接")
        self.test_conn_btn.setProperty("class", "SecondaryButton")
        self.test_conn_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.test_conn_btn.clicked.connect(self.test_llm_connection)
        
        model_layout.addWidget(model_label)
        model_layout.addWidget(self.model_combo, 1)
        model_layout.addWidget(self.fetch_models_btn)
        model_layout.addWidget(self.test_conn_btn)
        model_layout.addWidget(self.src_model_lbl)
        llm_layout.addLayout(model_layout)

        self.llm_status_label = QLabel("")
        self.llm_status_label.setStyleSheet("color: #64748B; font-size: 11px;")
        self.llm_status_label.setWordWrap(True)
        llm_layout.addWidget(self.llm_status_label)

        self.content_layout.addWidget(llm_box)

        # 2. 性能与哈希参数卡片
        perf_box = QGroupBox("⚡ 扫描与哈希性能参数")
        perf_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        perf_layout = QVBoxLayout(perf_box)
        perf_layout.setContentsMargins(14, 14, 14, 14)
        perf_layout.setSpacing(10)

        p_row1 = QHBoxLayout()
        p_row1.setSpacing(10)
        c_lbl = QLabel("并发比对线程数:")
        c_lbl.setMinimumWidth(110)
        c_lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 16)
        self.concurrency_spin.setValue(4)
        self.concurrency_spin.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.src_conc_lbl = self._create_source_badge()
        
        h_lbl = QLabel("哈希算法:")
        h_lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.hash_combo = QComboBox()
        self.hash_combo.setView(QListView())
        self.hash_combo.addItems(["MD5 (极速推荐)", "SHA256 (高强度安全)"])
        self.hash_combo.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.src_hash_lbl = self._create_source_badge()
        
        p_row1.addWidget(c_lbl)
        p_row1.addWidget(self.concurrency_spin)
        p_row1.addWidget(self.src_conc_lbl)
        p_row1.addSpacing(16)
        p_row1.addWidget(h_lbl)
        p_row1.addWidget(self.hash_combo)
        p_row1.addWidget(self.src_hash_lbl)
        p_row1.addStretch()
        perf_layout.addLayout(p_row1)

        p_row2 = QHBoxLayout()
        p_row2.setSpacing(10)
        self.chk_use_cache = QCheckBox("启用 SQLite 持久化哈希缓存 (避免未修改文件重复读取)")
        self.chk_use_cache.setChecked(True)
        self.chk_use_cache.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.clear_cache_btn = QPushButton("🧹 清空哈希缓存库")
        self.clear_cache_btn.setProperty("class", "SecondaryButton")
        self.clear_cache_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.clear_cache_btn.clicked.connect(self.on_clear_hash_cache)
        
        p_row2.addWidget(self.chk_use_cache)
        p_row2.addStretch()
        p_row2.addWidget(self.clear_cache_btn)
        perf_layout.addLayout(p_row2)

        self.content_layout.addWidget(perf_box)

        # 3. 归档与迁移基准目录卡片
        archive_box = QGroupBox("📦 默认归档与迁移路径")
        archive_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        arch_layout = QVBoxLayout(archive_box)
        arch_layout.setContentsMargins(14, 14, 14, 14)
        arch_layout.setSpacing(10)

        arch_path_layout = QHBoxLayout()
        arch_path_layout.setSpacing(10)
        arch_lbl = QLabel("默认归档根路径:")
        arch_lbl.setMinimumWidth(110)
        arch_lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.default_arch_input = QLineEdit()
        self.default_arch_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.browse_arch_btn = QPushButton("📁 浏览...")
        self.browse_arch_btn.setProperty("class", "SecondaryButton")
        self.browse_arch_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.browse_arch_btn.clicked.connect(self.browse_default_archive)
        self.src_arch_lbl = self._create_source_badge()
        
        arch_path_layout.addWidget(arch_lbl)
        arch_path_layout.addWidget(self.default_arch_input, 1)
        arch_path_layout.addWidget(self.browse_arch_btn)
        arch_path_layout.addWidget(self.src_arch_lbl)
        arch_layout.addLayout(arch_path_layout)

        mig_path_layout = QHBoxLayout()
        mig_path_layout.setSpacing(10)
        mig_lbl = QLabel("默认迁移根路径:")
        mig_lbl.setMinimumWidth(110)
        mig_lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.default_mig_input = QLineEdit()
        self.default_mig_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.browse_mig_btn = QPushButton("📁 浏览...")
        self.browse_mig_btn.setProperty("class", "SecondaryButton")
        self.browse_mig_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.browse_mig_btn.clicked.connect(self.browse_default_migration)
        self.src_mig_lbl = self._create_source_badge()
        
        mig_path_layout.addWidget(mig_lbl)
        mig_path_layout.addWidget(self.default_mig_input, 1)
        mig_path_layout.addWidget(self.browse_mig_btn)
        mig_path_layout.addWidget(self.src_mig_lbl)
        arch_layout.addLayout(mig_path_layout)

        self.content_layout.addWidget(archive_box)

        # 4. 忽略文件夹配置卡片
        ignore_box = QGroupBox("🚫 忽略文件夹与目录过滤 (Ignore Folders)")
        ignore_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        ignore_layout = QVBoxLayout(ignore_box)
        ignore_layout.setContentsMargins(14, 14, 14, 14)
        ignore_layout.setSpacing(10)

        ignore_desc_layout = QHBoxLayout()
        ignore_desc = QLabel("扫描时将自动跳过以下文件夹及其所有子目录，可有效避免扫描构建产物、依赖缓存（如 node_modules, .git）或自定义目录。")
        ignore_desc.setStyleSheet("color: #94A3B8; font-size: 12px;")
        ignore_desc.setWordWrap(True)
        ignore_desc_layout.addWidget(ignore_desc, 1)

        self.ignore_count_lbl = QLabel("已配置 0 个忽略路径")
        self.ignore_count_lbl.setStyleSheet("color: #38BDF8; font-size: 11px; font-weight: bold;")
        ignore_desc_layout.addWidget(self.ignore_count_lbl)
        ignore_layout.addLayout(ignore_desc_layout)

        # 忽略文件夹列表展示
        self.ignore_list = QListWidget()
        self.ignore_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.ignore_list.setMinimumHeight(130)
        self.ignore_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.ignore_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ignore_list.customContextMenuRequested.connect(self.on_ignore_list_context_menu)
        self.ignore_list.itemDoubleClicked.connect(self.on_ignore_item_double_clicked)
        ignore_layout.addWidget(self.ignore_list)

        # 忽略文件夹操作按钮条
        ignore_btn_layout = QHBoxLayout()
        ignore_btn_layout.setSpacing(8)

        self.add_ignore_btn = QPushButton("📁 浏览添加...")
        self.add_ignore_btn.setProperty("class", "SecondaryButton")
        self.add_ignore_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.add_ignore_btn.clicked.connect(self.add_ignore_folder)

        self.manual_add_ignore_btn = QPushButton("✏️ 手动输入...")
        self.manual_add_ignore_btn.setProperty("class", "SecondaryButton")
        self.manual_add_ignore_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.manual_add_ignore_btn.clicked.connect(self.manual_add_ignore_folder)

        self.edit_ignore_btn = QPushButton("📝 编辑选中")
        self.edit_ignore_btn.setProperty("class", "SecondaryButton")
        self.edit_ignore_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.edit_ignore_btn.clicked.connect(self.edit_selected_ignore_folder)

        self.del_ignore_btn = QPushButton("🗑️ 删除选中")
        self.del_ignore_btn.setProperty("class", "SecondaryButton")
        self.del_ignore_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.del_ignore_btn.clicked.connect(self.del_ignore_folder)

        self.clear_ignore_btn = QPushButton("🧹 清空全部")
        self.clear_ignore_btn.setProperty("class", "SecondaryButton")
        self.clear_ignore_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.clear_ignore_btn.clicked.connect(self.clear_ignore_folders)

        ignore_btn_layout.addWidget(self.add_ignore_btn)
        ignore_btn_layout.addWidget(self.manual_add_ignore_btn)
        ignore_btn_layout.addWidget(self.edit_ignore_btn)
        ignore_btn_layout.addWidget(self.del_ignore_btn)
        ignore_btn_layout.addWidget(self.clear_ignore_btn)
        ignore_btn_layout.addStretch()

        self.src_ignore_lbl = self._create_source_badge()
        ignore_btn_layout.addWidget(self.src_ignore_lbl)

        ignore_layout.addLayout(ignore_btn_layout)
        self.content_layout.addWidget(ignore_box)

        self.content_layout.addStretch()

        # 底部保存按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        self.save_global_btn = QPushButton("💾 保存至全局配置 (Global)")
        self.save_global_btn.setProperty("class", "SecondaryButton")
        self.save_global_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.save_global_btn.clicked.connect(lambda: self.save_settings(level="global"))

        self.save_profile_btn = QPushButton("💾 保存至当前方案覆盖 (Profile Override)")
        self.save_profile_btn.setStyleSheet("font-size: 13px; font-weight: bold; background-color: #059669; border-color: #10B981; padding: 8px 18px;")
        self.save_profile_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.save_profile_btn.clicked.connect(lambda: self.save_settings(level="profile"))
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_global_btn)
        btn_layout.addWidget(self.save_profile_btn)
        self.content_layout.addLayout(btn_layout)

        # 装载进滚动区域
        self.scroll_area.setWidget(self.content_widget)
        main_layout.addWidget(self.scroll_area)

    def _create_source_badge(self) -> QLabel:
        lbl = QLabel("[全局配置]")
        lbl.setStyleSheet("color: #38BDF8; font-size: 10px; padding: 2px 6px; background-color: #1E293B; border-radius: 4px;")
        lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        return lbl

    def _update_source_badge(self, lbl: QLabel, source: str):
        lbl.setText(f"[{source}]")
        if source == "任务级预设":
            lbl.setStyleSheet("color: #F59E0B; font-size: 10px; padding: 2px 6px; background-color: #312E81; border-radius: 4px; font-weight: bold;")
        elif source == "全局配置":
            lbl.setStyleSheet("color: #10B981; font-size: 10px; padding: 2px 6px; background-color: #064E3B; border-radius: 4px;")
        else:
            lbl.setStyleSheet("color: #94A3B8; font-size: 10px; padding: 2px 6px; background-color: #1E293B; border-radius: 4px;")

    def _update_ignore_count(self):
        count = self.ignore_list.count()
        self.ignore_count_lbl.setText(f"已配置 {count} 个忽略路径")

    def _get_current_ignore_paths(self) -> List[str]:
        paths = []
        for i in range(self.ignore_list.count()):
            item = self.ignore_list.item(i)
            if item and item.text().strip():
                paths.append(item.text().strip())
        return paths

    def _add_single_ignore_path(self, raw_path: str, prompt_if_not_exist: bool = True) -> bool:
        cleaned = raw_path.strip().strip('"').strip("'")
        if not cleaned:
            return False

        norm_path = os.path.normpath(cleaned)

        # 检查是否重复（不区分大小写比较）
        norm_case = os.path.normcase(norm_path)
        existing_paths = [os.path.normcase(self.ignore_list.item(i).text()) for i in range(self.ignore_list.count())]
        if norm_case in existing_paths:
            QMessageBox.warning(self, "重复路径", f"该路径已在忽略列表中，无需重复添加：\n{norm_path}")
            return False

        # 校验路径在磁盘上是否存在
        if not os.path.exists(norm_path) and prompt_if_not_exist:
            reply = QMessageBox.question(
                self, "路径不存在确认",
                f"以下路径在当前磁盘上未检测到对应的文件夹：\n{norm_path}\n\n是否仍要将其添加为忽略规则？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if reply != QMessageBox.Yes:
                return False

        item = QListWidgetItem(norm_path)
        status_text = "本地存在" if os.path.exists(norm_path) else "本地未找到(规则仍生效)"
        item.setToolTip(f"忽略路径: {norm_path}\n状态: {status_text}\n双击或右键可编辑/删除/打开")
        self.ignore_list.addItem(item)
        self.ignore_list.scrollToItem(item)
        self._update_ignore_count()
        return True

    def add_ignore_folder(self):
        """通过系统文件夹对话框选择要忽略的路径"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择要忽略的文件夹")
        if dir_path:
            self._add_single_ignore_path(dir_path, prompt_if_not_exist=False)

    def manual_add_ignore_folder(self):
        """通过输入框手动输入路径（支持直接粘贴路径或环境变量路径）"""
        text, ok = QInputDialog.getText(
            self, "手动添加忽略路径",
            "请输入或粘贴需要忽略的文件夹完整路径 (例如: D:\\workspace\\build 或 %TEMP%):"
        )
        if ok and text.strip():
            expanded = os.path.expandvars(text.strip())
            self._add_single_ignore_path(expanded, prompt_if_not_exist=True)

    def edit_selected_ignore_folder(self):
        """编辑当前选中的单条忽略路径"""
        current_item = self.ignore_list.currentItem()
        if not current_item:
            if self.ignore_list.count() > 0:
                current_item = self.ignore_list.item(0)
            else:
                QMessageBox.information(self, "提示", "当前忽略列表为空，请先添加路径！")
                return

        old_path = current_item.text()
        new_path, ok = QInputDialog.getText(
            self, "编辑忽略路径",
            "修改忽略文件夹路径:",
            text=old_path
        )
        if ok and new_path.strip():
            cleaned = os.path.normpath(os.path.expandvars(new_path.strip()))
            norm_case = os.path.normcase(cleaned)
            old_norm_case = os.path.normcase(old_path)

            if norm_case != old_norm_case:
                existing_paths = [
                    os.path.normcase(self.ignore_list.item(i).text())
                    for i in range(self.ignore_list.count())
                    if self.ignore_list.item(i) is not current_item
                ]
                if norm_case in existing_paths:
                    QMessageBox.warning(self, "重复路径", f"修改后的路径已在列表中存在：\n{cleaned}")
                    return

            if not os.path.exists(cleaned):
                reply = QMessageBox.question(
                    self, "路径不存在确认",
                    f"修改后的路径在当前磁盘上未检测到：\n{cleaned}\n\n是否仍要保存？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
                )
                if reply != QMessageBox.Yes:
                    return

            current_item.setText(cleaned)
            status_text = "本地存在" if os.path.exists(cleaned) else "本地未找到(规则仍生效)"
            current_item.setToolTip(f"忽略路径: {cleaned}\n状态: {status_text}\n双击或右键可编辑/删除/打开")

    def on_ignore_item_double_clicked(self, item: QListWidgetItem):
        """双击列表项直接触发编辑"""
        if item:
            self.ignore_list.setCurrentItem(item)
            self.edit_selected_ignore_folder()

    def del_ignore_folder(self):
        """删除选中的一条或多条忽略路径"""
        selected_items = self.ignore_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "提示", "请先在列表中选中要删除的路径项！")
            return

        for item in selected_items:
            self.ignore_list.takeItem(self.ignore_list.row(item))
        self._update_ignore_count()

    def clear_ignore_folders(self):
        """清空所有已配置的忽略路径（带确认提示）"""
        if self.ignore_list.count() == 0:
            return

        reply = QMessageBox.question(
            self, "清空确认",
            f"确定要清空全部 {self.ignore_list.count()} 条忽略路径规则吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.ignore_list.clear()
            self._update_ignore_count()

    def on_ignore_list_context_menu(self, pos):
        """右键快捷菜单：复制、打开目录、编辑、删除"""
        item = self.ignore_list.itemAt(pos)
        menu = QMenu(self)

        action_add = QAction("📁 浏览添加路径...", self)
        action_add.triggered.connect(self.add_ignore_folder)
        menu.addAction(action_add)

        action_manual = QAction("✏️ 手动输入路径...", self)
        action_manual.triggered.connect(self.manual_add_ignore_folder)
        menu.addAction(action_manual)

        menu.addSeparator()

        if item:
            path_str = item.text()
            action_copy = QAction("📋 复制完整路径", self)
            action_copy.triggered.connect(lambda: QApplication.clipboard().setText(path_str))
            menu.addAction(action_copy)

            action_open = QAction("📂 在文件资源管理器中打开", self)
            action_open.triggered.connect(lambda: self._open_in_explorer(path_str))
            menu.addAction(action_open)

            action_edit = QAction("📝 编辑此路径", self)
            action_edit.triggered.connect(self.edit_selected_ignore_folder)
            menu.addAction(action_edit)

            action_del = QAction("🗑️ 删除选中项", self)
            action_del.triggered.connect(self.del_ignore_folder)
            menu.addAction(action_del)

            menu.addSeparator()

        action_clear = QAction("🧹 清空全部路径", self)
        action_clear.triggered.connect(self.clear_ignore_folders)
        menu.addAction(action_clear)

        menu.exec(self.ignore_list.mapToGlobal(pos))

    def _open_in_explorer(self, path_str: str):
        if os.path.exists(path_str):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path_str))
        else:
            QMessageBox.warning(self, "无法打开", f"目标路径在磁盘上不存在：\n{path_str}")

    def load_profiles_to_ui(self):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        
        profiles = app_config.list_profiles()
        active = app_config.get_active_profile_name()
        
        for p_id, p_val in profiles.items():
            disp_name = f"{p_val.get('name', p_id)} (继承: {p_val.get('parent', 'base')})"
            self.profile_combo.addItem(disp_name, p_id)

        for i in range(self.profile_combo.count()):
            if self.profile_combo.itemData(i) == active:
                self.profile_combo.setCurrentIndex(i)
                break

        self.profile_combo.blockSignals(False)
        self.update_inheritance_label()

    def on_profile_changed(self, index: int):
        p_id = self.profile_combo.itemData(index)
        if p_id:
            app_config.set_active_profile(p_id)
            self.update_inheritance_label()
            self.load_settings()

    def update_inheritance_label(self):
        p_id = app_config.get_active_profile_name()
        profiles = app_config.list_profiles()
        
        chain = ["Base Config"]
        curr = p_id
        temp_chain = []
        while curr and curr != "base" and curr in profiles:
            temp_chain.append(curr)
            curr = profiles[curr].get("parent", "base")
            
        for c in reversed(temp_chain):
            chain.append(c)
            
        self.inheritance_info_label.setText(f"🔗 配置继承链路: {' ➔ '.join(chain)} (未覆盖属性自动继承上一层)")
        self.del_profile_btn.setEnabled(p_id not in BUILTIN_PROFILES)

    def create_new_profile(self):
        p_id, ok1 = QInputDialog.getText(self, "新建方案", "请输入方案唯一标识 (例如: extreme_clean):")
        if not ok1 or not p_id.strip():
            return
        p_id = p_id.strip().lower().replace(" ", "_")
        
        p_name, ok2 = QInputDialog.getText(self, "方案名称", "请输入方案显示名称:", text=f"方案 ({p_id})")
        if not ok2 or not p_name.strip():
            return
            
        current_active = app_config.get_active_profile_name()
        ok = app_config.create_custom_profile(p_id, p_name.strip(), f"用户自定义方案，继承自 {current_active}", parent=current_active)
        if ok:
            app_config.set_active_profile(p_id)
            self.load_profiles_to_ui()
            QMessageBox.information(self, "创建成功", f"方案 [{p_name}] 已创建并激活！")
        else:
            QMessageBox.warning(self, "创建失败", "方案 ID 已存在！")

    def delete_current_profile(self):
        p_id = app_config.get_active_profile_name()
        if p_id in BUILTIN_PROFILES:
            QMessageBox.warning(self, "不可删除", "内置默认方案无法删除！")
            return
            
        reply = QMessageBox.question(self, "确认删除", f"确定删除方案 [{p_id}] 吗？", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            app_config.delete_custom_profile(p_id)
            self.load_profiles_to_ui()
            self.load_settings()

    def toggle_key_visibility(self):
        if self.api_key_input.echoMode() == QLineEdit.Password:
            self.api_key_input.setEchoMode(QLineEdit.Normal)
            self.toggle_pwd_btn.setText("🙈 隐藏")
        else:
            self.api_key_input.setEchoMode(QLineEdit.Password)
            self.toggle_pwd_btn.setText("👁️ 显示")

    def browse_default_archive(self):
        curr = self.default_arch_input.text().strip() or "D:/"
        selected = QFileDialog.getExistingDirectory(self, "选择默认归档根路径", curr)
        if selected:
            self.default_arch_input.setText(selected)

    def browse_default_migration(self):
        curr = self.default_mig_input.text().strip() or "D:/"
        selected = QFileDialog.getExistingDirectory(self, "选择默认迁移目标根路径", curr)
        if selected:
            self.default_mig_input.setText(selected)

    def load_settings(self):
        """从三层配置引擎中加载并装填所有 UI 参数"""
        # 1. Base URL
        val, src = app_config.get_with_source("llm", "base_url", default="https://api.openai.com/v1")
        self.base_url_input.setText(val)
        self._update_source_badge(self.src_url_lbl, src)

        # 2. API Key
        val, src = app_config.get_with_source("llm", "api_key", default="")
        self.api_key_input.setText(val)
        self._update_source_badge(self.src_key_lbl, src)

        # 3. Available Models & Model
        models = app_config.get("llm", "available_models", default=["gpt-4o-mini", "gpt-4o", "deepseek-chat", "qwen-max"])
        curr_model, src = app_config.get_with_source("llm", "model", default="gpt-4o-mini")
        
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(models)
        
        idx = self.model_combo.findText(curr_model)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        else:
            self.model_combo.setEditText(curr_model)
        self.model_combo.blockSignals(False)
        self._update_source_badge(self.src_model_lbl, src)

        # 4. Concurrency
        val, src = app_config.get_with_source("perf_options", "concurrency", default=4)
        self.concurrency_spin.setValue(val)
        self._update_source_badge(self.src_conc_lbl, src)

        # 5. Hash Algorithm
        val, src = app_config.get_with_source("hash_algorithm", default="md5")
        if "sha" in str(val).lower():
            self.hash_combo.setCurrentIndex(1)
        else:
            self.hash_combo.setCurrentIndex(0)
        self._update_source_badge(self.src_hash_lbl, src)

        # 6. Archive & Migration
        val, src = app_config.get_with_source("archive_dir", default="D:/归档备份")
        self.default_arch_input.setText(val)
        self._update_source_badge(self.src_arch_lbl, src)

        val, src = app_config.get_with_source("migration_dir", default="D:/软件与文件迁移")
        self.default_mig_input.setText(val)
        self._update_source_badge(self.src_mig_lbl, src)

        # 7. Ignore Folders 路径装载与展示
        ignore_folders, src = app_config.get_with_source("ignore_folders", default=[])
        self.ignore_list.blockSignals(True)
        self.ignore_list.clear()
        if isinstance(ignore_folders, list):
            for path_str in ignore_folders:
                if str(path_str).strip():
                    norm_p = os.path.normpath(str(path_str).strip())
                    item = QListWidgetItem(norm_p)
                    status_text = "本地存在" if os.path.exists(norm_p) else "本地未找到(规则仍生效)"
                    item.setToolTip(f"忽略路径: {norm_p}\n状态: {status_text}\n双击或右键可编辑/删除/打开")
                    self.ignore_list.addItem(item)
        self.ignore_list.blockSignals(False)
        self._update_source_badge(self.src_ignore_lbl, src)
        self._update_ignore_count()

    def fetch_remote_models(self):
        base_url = self.base_url_input.text().strip()
        api_key = self.api_key_input.text().strip()

        if not base_url:
            QMessageBox.warning(self, "提示", "请先输入 API Base URL！")
            return

        self.fetch_models_btn.setEnabled(False)
        self.llm_status_label.setText("⏳ 正在请求 /v1/models 获取可用模型列表...")
        self.llm_status_label.setStyleSheet("color: #38BDF8;")

        self.fetch_worker = FetchModelsWorker(base_url, api_key)
        self.fetch_worker.finished_signal.connect(self.on_fetch_models_finished)
        self.fetch_worker.start()

    def on_fetch_models_finished(self, success: bool, models: List[str], msg: str):
        self.fetch_models_btn.setEnabled(True)
        if success and models:
            curr_model = self.model_combo.currentText().strip()
            self.model_combo.blockSignals(True)
            self.model_combo.clear()
            self.model_combo.addItems(models)
            
            idx = self.model_combo.findText(curr_model)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
            else:
                self.model_combo.setCurrentIndex(0)
            self.model_combo.blockSignals(False)

            self.llm_status_label.setText(f"✅ 成功拉取到 {len(models)} 个可用模型并已装填下拉列表！")
            self.llm_status_label.setStyleSheet("color: #10B981;")
            
            # 主动弹出下拉菜单供用户立即查看
            self.model_combo.showPopup()
            QMessageBox.information(self, "拉取成功", f"成功拉取到 {len(models)} 个可用模型！\n请在下拉框中选择或直接输入所需模型。")
        else:
            self.llm_status_label.setText(f"❌ 拉取模型列表失败: {msg}")
            self.llm_status_label.setStyleSheet("color: #EF4444;")
            QMessageBox.warning(self, "拉取失败", f"无法获取远端模型列表:\n{msg}\n您可直接在输入框中手动指定 Model ID。")

    def test_llm_connection(self):
        base_url = self.base_url_input.text().strip()
        api_key = self.api_key_input.text().strip()
        model = self.model_combo.currentText().strip()

        if not base_url or not model:
            QMessageBox.warning(self, "提示", "请确保 Base URL 与 Model 均已填写！")
            return

        self.test_conn_btn.setEnabled(False)
        self.llm_status_label.setText("⚡ 正在测试 API 连通性...")
        self.llm_status_label.setStyleSheet("color: #38BDF8;")

        self.test_worker = TestConnectionWorker(base_url, api_key, model)
        self.test_worker.finished_signal.connect(self.on_test_connection_finished)
        self.test_worker.start()

    def on_test_connection_finished(self, success: bool, msg: str):
        self.test_conn_btn.setEnabled(True)
        if success:
            self.llm_status_label.setText(f"✅ {msg}")
            self.llm_status_label.setStyleSheet("color: #10B981;")
            QMessageBox.information(self, "连通性测试", "🎉 API 连通性测试通过！模型握手正常。")
        else:
            self.llm_status_label.setText(f"❌ {msg}")
            self.llm_status_label.setStyleSheet("color: #EF4444;")
            QMessageBox.warning(self, "连接失败", f"API 连通测试失败:\n{msg}")

    def on_clear_hash_cache(self):
        reply = QMessageBox.question(self, "清空缓存", "确定要清空所有已缓存的文件哈希记录吗？", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            hash_cache.clear_cache()
            QMessageBox.information(self, "缓存已清空", "SQLite 哈希缓存数据库已清空！")

    def save_settings(self, level: str = "global"):
        """将当前 UI 中所有配置（含大模型、性能、路径及忽略文件夹列表）持久化保存"""
        all_models = [self.model_combo.itemText(i) for i in range(self.model_combo.count())]
        curr_model = self.model_combo.currentText().strip()
        if curr_model and curr_model not in all_models:
            all_models.insert(0, curr_model)

        algo = "sha256" if self.hash_combo.currentIndex() == 1 else "md5"
        ignore_folders = self._get_current_ignore_paths()

        app_config.set("llm", {
            "base_url": self.base_url_input.text().strip(),
            "api_key": self.api_key_input.text().strip(),
            "model": curr_model,
            "available_models": all_models
        }, level=level)

        app_config.set("perf_options", {
            "concurrency": self.concurrency_spin.value(),
            "use_hash_cache": self.chk_use_cache.isChecked()
        }, level=level)

        app_config.set("hash_algorithm", algo, level=level)
        app_config.set("archive_dir", self.default_arch_input.text().strip(), level=level)
        app_config.set("migration_dir", self.default_mig_input.text().strip(), level=level)
        app_config.set("ignore_folders", ignore_folders, level=level)

        # 重新装载确保 UI 显示与持久化数据严格一致
        self.load_settings()
        target_name = "全局通用配置" if level == "global" else f"当前方案 [{app_config.get_active_profile_name()}] 覆盖"
        QMessageBox.information(self, "保存成功", f"✅ 参数与 {len(ignore_folders)} 条忽略规则已成功持久化保存至 {target_name}！")
