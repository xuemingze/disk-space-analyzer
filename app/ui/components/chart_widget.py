import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

from app.utils.file_helper import format_size

# 设置 Matplotlib 中文字体与暗黑主题样式
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Segoe UI', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False


class SpaceDistributionChartWidget(QWidget):
    """
    基于 Matplotlib 嵌入的高清空间分布饼图与柱状图组件
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建 Figure 与 Canvas
        self.figure = Figure(figsize=(6, 4), dpi=100, facecolor="#161F2E")
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setStyleSheet("background-color: transparent;")
        
        layout.addWidget(self.canvas)
        self.render_empty_chart()

    def render_empty_chart(self):
        """渲染无数据时的占位图"""
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.set_facecolor("#161F2E")
        ax.text(
            0.5, 0.5, "请选择目标目录并启动扫描以生成空间全景图",
            horizontalalignment='center', verticalalignment='center',
            transform=ax.transAxes, color='#64748B', fontsize=13
        )
        ax.axis('off')
        self.canvas.draw()

    def update_chart(self, category_stats: dict):
        """根据扫描结果更新空间分布饼图与条形图"""
        self.figure.clear()
        
        if not category_stats:
            self.render_empty_chart()
            return

        # 过滤出有数据的分类
        valid_items = [(cat, data["bytes"], data["percent"]) for cat, data in category_stats.items() if data["bytes"] > 0]
        if not valid_items:
            self.render_empty_chart()
            return

        # 取前 6 大类别，其余归入其他
        if len(valid_items) > 7:
            main_items = valid_items[:6]
            other_bytes = sum(item[1] for item in valid_items[6:])
            total_b = sum(item[1] for item in valid_items)
            other_percent = round((other_bytes / total_b * 100), 2)
            main_items.append(("其他类型", other_bytes, other_percent))
            display_items = main_items
        else:
            display_items = valid_items

        labels = [f"{item[0]} ({format_size(item[1])})" for item in display_items]
        sizes = [item[1] for item in display_items]
        
        # 现代配色调色盘 (Teal/Cyan/Blue/Indigo/Purple/Amber/Emerald)
        colors = ['#38BDF8', '#818CF8', '#34D399', '#FBBF24', '#F472B6', '#A78BFA', '#94A3B8']

        # 创建双子图: 左边甜甜圈饼图，右边水平条形图
        ax1 = self.figure.add_subplot(121)
        ax2 = self.figure.add_subplot(122)
        
        ax1.set_facecolor("#161F2E")
        ax2.set_facecolor("#161F2E")

        # 1. 绘制甜甜圈环形饼图
        wedges, texts, autotexts = ax1.pie(
            sizes,
            labels=None,
            autopct=lambda pct: f'{pct:.1f}%' if pct > 4 else '',
            startangle=140,
            colors=colors[:len(sizes)],
            pctdistance=0.75,
            wedgeprops=dict(width=0.45, edgecolor='#161F2E', linewidth=2)
        )
        for autotext in autotexts:
            autotext.set_color('#FFFFFF')
            autotext.set_fontsize(9)
            autotext.set_weight('bold')
            
        ax1.set_title("空间分类构成占比", color="#E2E8F0", fontsize=12, pad=10, weight='bold')

        # 2. 绘制水平条形图
        cats = [item[0] for item in reversed(display_items)]
        bytes_vals = [item[1] / (1024*1024) for item in reversed(display_items)] # MB
        
        y_pos = range(len(cats))
        bars = ax2.barh(y_pos, bytes_vals, color=list(reversed(colors[:len(cats)])), height=0.55)
        
        ax2.set_yticks(y_pos)
        ax2.set_yticklabels(cats, color="#CBD5E1", fontsize=10)
        ax2.set_xlabel("占用空间 (MB)", color="#94A3B8", fontsize=10)
        ax2.tick_params(axis='x', colors='#94A3B8')
        ax2.spines['top'].set_visible(False)
        ax2.spines['right'].set_visible(False)
        ax2.spines['bottom'].set_color('#334155')
        ax2.spines['left'].set_color('#334155')
        ax2.set_title("分类占用排行 (MB)", color="#E2E8F0", fontsize=12, pad=10, weight='bold')

        # 在条形图右侧标注格式化大小
        for bar, item in zip(bars, reversed(display_items)):
            width = bar.get_width()
            ax2.text(
                width, bar.get_y() + bar.get_height() / 2,
                f' {format_size(item[1])}',
                va='center', ha='left', color='#F8FAFC', fontsize=9
            )

        self.figure.tight_layout()
        self.canvas.draw()
