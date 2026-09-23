import os
import sys
from pathlib import Path
from unittest.mock import patch

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QMessageBox
from app.ui.home_view import HomeView


def test_trigger_ai_auto_process_without_scan():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance() or QApplication(sys.argv)

    home = HomeView()
    # 模拟在没有扫描结果时点击 AI 自动处理
    assert home.current_scan_result is None
    
    with patch.object(QMessageBox, "warning") as mock_warn:
        home.trigger_ai_auto_process()
        assert mock_warn.called, "应弹出警告提示用户先完成有效扫描"
        print("✅ 成功拦截并警告：在无扫描结果时触发 AI 自动处理不会抛出 NoneType 异常！")


if __name__ == "__main__":
    test_trigger_ai_auto_process_without_scan()
