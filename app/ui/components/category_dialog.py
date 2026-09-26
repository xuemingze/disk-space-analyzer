from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLineEdit, QTextEdit, QLabel, QFormLayout, QGroupBox,
    QCheckBox, QSpinBox, QMessageBox
)
from PySide6.QtCore import Qt
from app.core.category_manager import global_category_manager

class CategoryManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🏷️ 全局归档分类管理")
        self.resize(750, 500)
        self.current_category_id = None

        layout = QHBoxLayout(self)

        # Left: List of categories
        left_layout = QVBoxLayout()
        self.cat_list = QListWidget()
        self.cat_list.currentRowChanged.connect(self.on_row_changed)
        left_layout.addWidget(self.cat_list)

        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("➕ 新增")
        self.btn_add.clicked.connect(self.on_add_clicked)
        self.btn_del = QPushButton("➖ 删除")
        self.btn_del.clicked.connect(self.on_del_clicked)
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_del)
        left_layout.addLayout(btn_layout)

        layout.addLayout(left_layout, 1)

        # Right: Details form
        right_group = QGroupBox("分类详情")
        self.right_layout = QVBoxLayout(right_group)

        self.form_layout = QFormLayout()
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
        self.lbl_info.setStyleSheet("color: #64748B;")
        
        self.right_layout.addLayout(self.form_layout)
        self.right_layout.addWidget(self.lbl_info)
        self.right_layout.addStretch()

        self.btn_save = QPushButton("💾 保存当前分类")
        self.btn_save.setProperty("class", "PrimaryButton")
        self.btn_save.clicked.connect(self.on_save_clicked)
        self.right_layout.addWidget(self.btn_save)

        layout.addWidget(right_group, 2)

        self.refresh_list()
        self.enable_form(False)

    def refresh_list(self):
        self.cat_list.clear()
        categories = global_category_manager.get_all()
        for cat in categories:
            item = QListWidgetItem(f"{cat.get('name')} (优先级: {cat.get('priority', 0)})")
            item.setData(Qt.UserRole, cat.get('category_id'))
            if not cat.get('enabled', True):
                item.setForeground(Qt.gray)
            self.cat_list.addItem(item)

    def enable_form(self, enabled=True):
        self.txt_name.setEnabled(enabled)
        self.txt_desc.setEnabled(enabled)
        self.txt_template.setEnabled(enabled)
        self.spin_priority.setEnabled(enabled)
        self.chk_enabled.setEnabled(enabled)
        self.btn_save.setEnabled(enabled)

    def on_row_changed(self, row):
        if row < 0:
            self.enable_form(False)
            self.current_category_id = None
            return

        item = self.cat_list.item(row)
        cat_id = item.data(Qt.UserRole)
        self.current_category_id = cat_id
        self.enable_form(True)

        categories = global_category_manager.get_all()
        cat = next((c for c in categories if c.get("category_id") == cat_id), None)
        if cat:
            self.txt_name.setText(cat.get("name", ""))
            self.txt_desc.setText(cat.get("description", ""))
            self.txt_template.setText(cat.get("target_path_template", ""))
            self.spin_priority.setValue(cat.get("priority", 0))
            self.chk_enabled.setChecked(cat.get("enabled", True))
            
            source = cat.get("source", "unknown")
            self.lbl_info.setText(f"分类ID: {cat_id}\n来源: {source}")

    def on_add_clicked(self):
        global_category_manager.add_category({
            "name": "新建分类",
            "description": "",
            "target_path_template": "{archive_root}/New_Category/{app_name}",
            "priority": 50,
            "enabled": True
        })
        self.refresh_list()
        self.cat_list.setCurrentRow(self.cat_list.count() - 1)

    def on_del_clicked(self):
        if self.current_category_id:
            reply = QMessageBox.question(self, "确认删除", "确认删除该全局分类吗？")
            if reply == QMessageBox.Yes:
                global_category_manager.delete_category(self.current_category_id)
                self.refresh_list()

    def on_save_clicked(self):
        if not self.current_category_id: return
        
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
        self.refresh_list()
