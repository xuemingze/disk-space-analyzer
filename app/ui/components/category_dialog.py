import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLineEdit, QTextEdit, QLabel, QFormLayout, QGroupBox,
    QCheckBox, QSpinBox, QMessageBox, QFileDialog, QHeaderView
)
from PySide6.QtCore import Qt, QEvent, QSize
from PySide6.QtGui import QBrush, QColor, QFont
from app.core.category_manager import global_category_manager
from app.core.ai_service import AIService

class CategoryManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🏷️ 全局多级归档分类管理")
        self.resize(860, 560)
        self.current_category_id = None
        self.setAcceptDrops(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)

        # Left: 2~3 level Category Tree
        left_layout = QVBoxLayout()
        left_layout.setSpacing(8)

        lbl_tree_title = QLabel("📁 全局分类拓扑树 (2~3 级)")
        lbl_tree_title.setStyleSheet("font-weight: bold; color: #38BDF8; font-size: 13px;")
        left_layout.addWidget(lbl_tree_title)

        self.cat_tree = QTreeWidget()
        self.cat_tree.setColumnCount(2)
        self.cat_tree.setHeaderLabels(["分类名称拓扑", "优先级"])
        self.cat_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.cat_tree.header().setSectionResizeMode(1, QHeaderView.Interactive)
        self.cat_tree.setColumnWidth(1, 75)
        # 全局设计铁律：坚决禁用白黑交叉混杂，保持统一清晰对比度
        self.cat_tree.setAlternatingRowColors(False)
        self.cat_tree.setAcceptDrops(True)
        self.cat_tree.installEventFilter(self)
        self.cat_tree.currentItemChanged.connect(self.on_current_item_changed)
        self.cat_tree.setStyleSheet("""
            QTreeWidget {
                background-color: #0F172A;
                color: #FFFFFF;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px;
                outline: none;
            }
            QTreeWidget::item {
                margin: 2px 0px;
                border-radius: 4px;
                padding: 4px 6px;
                color: #FFFFFF;
            }
            QTreeWidget::item:selected {
                border: 1px solid #38BDF8;
                background-color: #1D4ED8;
                color: #FFFFFF;
            }
            QTreeWidget::item:hover:!selected {
                background-color: #1E293B;
                color: #FFFFFF;
            }
            QHeaderView::section {
                background-color: #1E293B;
                color: #FFFFFF;
                padding: 6px 8px;
                border: none;
                border-bottom: 2px solid #38BDF8;
                font-weight: bold;
            }
        """)
        left_layout.addWidget(self.cat_tree)

        # 兼容旧属性访问
        self.cat_list = self.cat_tree

        # 示范目录建树输入与捕捉组件 (支持文本直输、对话框选择与直接拖放)
        self.txt_capture_path = QLineEdit()
        self.txt_capture_path.setPlaceholderText("示范目录 (输入/粘贴路径，或直接拖拽文件夹至此)...")
        self.txt_capture_path.returnPressed.connect(self.on_capture_clicked)
        left_layout.addWidget(self.txt_capture_path)

        # 示范目录建树按钮
        self.btn_capture = QPushButton("🔍 捕捉示范目录建树...")
        self.btn_capture.setProperty("class", "SecondaryButton")
        self.btn_capture.setToolTip("选择或根据上方输入框指定本地示范目录 (如 F:\\运维工具)，AI 极速统揽生成 2~3 级分类树并落盘 (支持拖拽文件夹至此窗口)")
        self.btn_capture.clicked.connect(self.on_capture_clicked)
        left_layout.addWidget(self.btn_capture)

        # 增删按钮组
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)
        self.btn_add = QPushButton("➕ 新增顶级")
        self.btn_add.clicked.connect(self.on_add_clicked)
        self.btn_add_child = QPushButton("➕ 新增子级")
        self.btn_add_child.clicked.connect(self.on_add_child_clicked)
        self.btn_del = QPushButton("➖ 删除")
        self.btn_del.clicked.connect(self.on_del_clicked)
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_add_child)
        btn_layout.addWidget(self.btn_del)
        left_layout.addLayout(btn_layout)

        layout.addLayout(left_layout, 1)

        # Right: Details form
        right_group = QGroupBox("分类节点属性")
        self.right_layout = QVBoxLayout(right_group)
        self.right_layout.setContentsMargins(12, 12, 12, 12)
        self.right_layout.setSpacing(10)

        self.form_layout = QFormLayout()
        self.form_layout.setSpacing(8)
        self.txt_name = QLineEdit()
        self.txt_desc = QTextEdit()
        self.txt_desc.setMaximumHeight(80)
        self.txt_template = QLineEdit()
        self.txt_template.setPlaceholderText("{archive_root}/Category_Name/{app_name}")
        self.spin_priority = QSpinBox()
        self.spin_priority.setRange(0, 999)
        self.chk_enabled = QCheckBox("启用此分类")

        self.form_layout.addRow("分类名称 (*):", self.txt_name)
        self.form_layout.addRow("优先级:", self.spin_priority)
        self.form_layout.addRow("描述 (适用范围):", self.txt_desc)
        self.form_layout.addRow("目标路径模板 (*):", self.txt_template)
        self.form_layout.addRow("", self.chk_enabled)

        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet("color: #64748B; font-size: 11px;")
        
        self.right_layout.addLayout(self.form_layout)
        self.right_layout.addWidget(self.lbl_info)
        self.right_layout.addStretch()

        self.btn_save = QPushButton("💾 保存当前分类")
        self.btn_save.setProperty("class", "PrimaryButton")
        self.btn_save.clicked.connect(self.on_save_clicked)
        self.right_layout.addWidget(self.btn_save)

        layout.addWidget(right_group, 1)

        self.refresh_tree()
        self.enable_form(False)

    def refresh_list(self):
        """兼容既有接口"""
        self.refresh_tree()

    def refresh_tree(self):
        """重新加载并完整展开 2~3 级分类树，严格遵循蓝底白字、绿底白字规范"""
        self.cat_tree.clear()
        tree = global_category_manager.get_tree()

        def _add_nodes(parent_item, nodes):
            for node in nodes:
                name = node.get("name", "")
                pri = str(node.get("priority", 0))
                if parent_item is None:
                    item = QTreeWidgetItem(self.cat_tree, [name, pri])
                    # 顶级分类：蓝底白字 (沉稳深蓝底 + 高亮纯白字，粗体)
                    bg_brush = QBrush(QColor("#1E3A8A"))
                    text_brush = QBrush(QColor("#FFFFFF"))
                    font = item.font(0)
                    font.setBold(True)
                    for col in range(2):
                        item.setBackground(col, bg_brush)
                        item.setForeground(col, text_brush)
                        item.setFont(col, font)
                        item.setSizeHint(col, QSize(0, 32))
                else:
                    item = QTreeWidgetItem(parent_item, [name, pri])
                    # 子级分类：绿底白字 (沉稳深绿底 + 高亮纯白字)
                    bg_brush = QBrush(QColor("#065F46"))
                    text_brush = QBrush(QColor("#FFFFFF"))
                    font = item.font(0)
                    font.setBold(False)
                    for col in range(2):
                        item.setBackground(col, bg_brush)
                        item.setForeground(col, text_brush)
                        item.setFont(col, font)
                        item.setSizeHint(col, QSize(0, 30))

                item.setData(0, Qt.UserRole, node.get("category_id"))
                if not node.get("enabled", True):
                    dim_text = QBrush(QColor("#94A3B8"))
                    item.setForeground(0, dim_text)
                    item.setForeground(1, dim_text)

                children = node.get("children", [])
                if children:
                    _add_nodes(item, children)

        _add_nodes(None, tree)
        self.cat_tree.expandAll()

    def enable_form(self, enabled=True):
        self.txt_name.setEnabled(enabled)
        self.txt_desc.setEnabled(enabled)
        self.txt_template.setEnabled(enabled)
        self.spin_priority.setEnabled(enabled)
        self.chk_enabled.setEnabled(enabled)
        self.btn_save.setEnabled(enabled)

    def on_current_item_changed(self, current, previous):
        if not current:
            self.enable_form(False)
            self.current_category_id = None
            self.lbl_info.setText("")
            return

        cat_id = current.data(0, Qt.UserRole)
        self.current_category_id = cat_id
        self.enable_form(True)

        node = global_category_manager.find_node_by_id(cat_id)
        if node:
            self.txt_name.setText(node.get("name", ""))
            self.txt_desc.setText(node.get("description", ""))
            self.txt_template.setText(node.get("target_path_template", ""))
            self.spin_priority.setValue(node.get("priority", 0))
            self.chk_enabled.setChecked(node.get("enabled", True))
            
            source = node.get("source", "unknown")
            lvl = node.get("level", 1)
            self.lbl_info.setText(f"分类ID: {cat_id}\n层级: L{lvl} | 来源: {source}")

    def eventFilter(self, obj, event):
        if obj == getattr(self, "cat_tree", None):
            if event.type() in (QEvent.DragEnter, QEvent.DragMove):
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    return True
            elif event.type() == QEvent.Drop:
                self.dropEvent(event)
                return True
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(url.isLocalFile() for url in urls):
                event.acceptProposedAction()
                return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(url.isLocalFile() for url in urls):
                event.acceptProposedAction()
                return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    local_p = os.path.normpath(url.toLocalFile())
                    if os.path.exists(local_p):
                        target_dir = local_p if os.path.isdir(local_p) else os.path.dirname(local_p)
                        if hasattr(self, "txt_capture_path"):
                            self.txt_capture_path.setText(target_dir)
                        event.acceptProposedAction()
                        self.capture_directory(target_dir)
                        return
        super().dropEvent(event)

    def capture_directory(self, dir_path: str):
        """核心建树执行逻辑 (由点击、回车或拖拽统一调用)"""
        if not dir_path or not dir_path.strip():
            return
        clean_dir = dir_path.strip()
        try:
            tree = AIService.capture_and_build_category_tree(clean_dir)
            self.refresh_tree()
            QMessageBox.information(
                self,
                "建树完成",
                f"已成功对示范目录【{clean_dir}】完成特征捕捉与 AI 统揽建树！\n"
                f"生成 2~3 级分类拓扑节点共 {len(tree)} 个一级分支，已一字不差落盘。"
            )
        except Exception as e:
            QMessageBox.critical(self, "建树失败", f"示范目录建树失败: {e}")

    def on_capture_clicked(self):
        """捕捉本地示范目录，由 AI 统揽构建 2~3 级分类树并落盘 (支持文本直输与文件选择)"""
        input_p = self.txt_capture_path.text().strip() if hasattr(self, "txt_capture_path") else ""
        if input_p and os.path.exists(input_p) and os.path.isdir(input_p):
            dir_path = input_p
        else:
            dir_path = QFileDialog.getExistingDirectory(self, "选择本地示范目录 (如 F:\\运维工具)", dir=input_p or "")
            if not dir_path:
                return
            if hasattr(self, "txt_capture_path"):
                self.txt_capture_path.setText(dir_path)

        self.capture_directory(dir_path)

    def on_add_clicked(self):
        """新增一级分类"""
        global_category_manager.add_category({
            "name": "新建分类",
            "description": "",
            "target_path_template": "{archive_root}/New_Category/{app_name}",
            "priority": 50,
            "enabled": True,
            "level": 1,
            "children": []
        })
        self.refresh_tree()

    def on_add_child_clicked(self):
        """在当前选中分类下新增子级分类"""
        if not self.current_category_id:
            self.on_add_clicked()
            return

        parent = global_category_manager.find_node_by_id(self.current_category_id)
        p_name = parent.get("name", "Category") if parent else "Category"
        p_lvl = parent.get("level", 1) if parent else 1
        p_pri = parent.get("priority", 50) if parent else 50

        global_category_manager.add_category({
            "name": "新建子类",
            "description": "",
            "target_path_template": f"{{archive_root}}/{p_name}/New_Sub/{{app_name}}",
            "priority": max(0, p_pri - 5),
            "enabled": True,
            "level": p_lvl + 1,
            "children": []
        }, parent_id=self.current_category_id)
        self.refresh_tree()

    def on_del_clicked(self):
        if self.current_category_id:
            reply = QMessageBox.question(self, "确认删除", "确认删除该分类节点及其所有下级子分类吗？")
            if reply == QMessageBox.Yes:
                global_category_manager.delete_category(self.current_category_id)
                self.refresh_tree()

    def on_save_clicked(self):
        if not self.current_category_id:
            return
        
        name = self.txt_name.text().strip()
        template = self.txt_template.text().strip()
        
        if not name or not template:
            QMessageBox.warning(self, "警告", "分类名称和目标路径模板不能为空！")
            return
            
        global_category_manager.update_category(self.current_category_id, {
            "name": name,
            "description": self.txt_desc.toPlainText(),
            "target_path_template": template,
            "priority": self.spin_priority.value(),
            "enabled": self.chk_enabled.isChecked()
        })
        QMessageBox.information(self, "成功", "分类已保存！")
        self.refresh_tree()
