from PySide6.QtWidgets import QWidget, QVBoxLayout, QSplitter, QTextBrowser
from PySide6.QtCore import Qt

def create_ai_insight_wrapper(main_widget, title_text):
    wrapper = QWidget()
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    
    splitter = QSplitter(Qt.Vertical)
    
    # AI Insight panel
    ai_panel = QTextBrowser()
    ai_panel.setOpenExternalLinks(False)
    ai_panel.setStyleSheet("""
        QTextBrowser {
            background-color: #1E293B;
            color: #CBD5E1;
            border: 1px solid #334155;
            border-radius: 4px;
            padding: 8px;
            font-size: 13px;
        }
    """)
    ai_panel.setMarkdown(f"**{title_text}**\n\n暂无有效 AI 分析数据。")
    
    splitter.addWidget(ai_panel)
    splitter.addWidget(main_widget)
    splitter.setSizes([100, 400])
    
    layout.addWidget(splitter)
    wrapper.ai_panel = ai_panel # Save reference
    return wrapper
