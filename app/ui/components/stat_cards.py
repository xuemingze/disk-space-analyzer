from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

class StatCard(QFrame):
    """单项统计指标卡片"""
    def __init__(self, title: str, value: str, subtext: str = "", accent_color: str = "#38BDF8", parent=None):
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setProperty("class", "CardFrame")
        self.setStyleSheet(f"""
            QFrame#StatCard {{
                background-color: #161F2E;
                border: 1px solid #233247;
                border-left: 4px solid {accent_color};
                border-radius: 8px;
                padding: 8px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: 500;")
        
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(f"color: #FFFFFF; font-size: 20px; font-weight: bold;")
        
        self.subtext_label = QLabel(subtext)
        self.subtext_label.setStyleSheet("color: #64748B; font-size: 11px;")
        
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        if subtext:
            layout.addWidget(self.subtext_label)

    def set_value(self, value: str, subtext: str = None):
        self.value_label.setText(value)
        if subtext is not None:
            self.subtext_label.setText(subtext)


class StatCardsRow(QFrame):
    """主控页顶层统计卡片排布栏"""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        self.card_total_space = StatCard("已扫描空间总量", "0 B", "涵盖所有目标目录", "#38BDF8")
        self.card_reclaimable = StatCard("可释放冗余预估", "0 B", "含重复副本与临时项", "#10B981")
        self.card_total_files = StatCard("已索引文件总数", "0 个", "不含受保护系统目录", "#818CF8")
        self.card_duplicates = StatCard("精准查重浪费空间", "0 B", "共 0 组重复文件", "#F59E0B")
        
        layout.addWidget(self.card_total_space)
        layout.addWidget(self.card_reclaimable)
        layout.addWidget(self.card_total_files)
        layout.addWidget(self.card_duplicates)

    def update_stats(self, total_bytes_str: str, reclaimable_str: str, files_count_str: str, dup_waste_str: str, dup_groups_count: int):
        self.card_total_space.set_value(total_bytes_str)
        self.card_reclaimable.set_value(reclaimable_str, "推荐一键清理或归档")
        self.card_total_files.set_value(files_count_str)
        self.card_duplicates.set_value(dup_waste_str, f"发现 {dup_groups_count} 组相同内容副本")
