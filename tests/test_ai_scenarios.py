import sys
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from app.core.ai_service import AIService
from app.core.ai_service import AIResponse

def test_ai_response_parsing():
    print("--- 场景 1: HTTP 200 且返回有效目录级规划 ---")
    valid_json = {
        "choices": [{
            "message": {
                "content": '{"groups": [{"original_root": "C:/test", "suggested_category": "Test"}]}'
            }
        }]
    }
    resp1 = AIService._parse_ai_response(valid_json)
    print("解析状态:", resp1.parse_status)

    print("\n--- 场景 2: HTTP 200 但 content 为空 ---")
    empty_json = {
        "choices": [{
            "message": {
                "content": ''
            }
        }]
    }
    resp2 = AIService._parse_ai_response(empty_json)
    print("解析状态:", resp2.parse_status, "错误信息:", resp2.error_message)

    print("\n--- 场景 3: HTTP 200 但仅返回思考内容 ---")
    think_json = {
        "choices": [{
            "message": {
                "content": '<think>思考中...</think>'
            }
        }]
    }
    resp3 = AIService._parse_ai_response(think_json)
    print("解析状态:", resp3.parse_status, "错误信息:", resp3.error_message)


def test_home_view_standalone_count_over_100_decision_flow(monkeypatch):
    """
    准则一核心编排架构与用户决策权保全测试：
    当扫描独立资产数量 > 100 时：
    1. 80% 可能性为集合判断错误；
    2. AI 界面必须直接输出独立资产数量并展示决策卡片；
    3. 严禁未经授权自动后台触发 AI 分析越权处理；
    4. 明确提供【运行文件整理】与【强制 AI 总结】两个选项由用户定夺。
    """
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    app = QApplication.instance() or QApplication(sys.argv)
    from app.ui.home_view import HomeView
    view = HomeView()

    mock_result = {
        "task_id": "test_scan_task_1",
        "total_files": 250,
        "standalone_file_count": 180,
        "collective_count": 2,
        "total_bytes": 1024 * 1024 * 500,
        "reclaimable_bytes": 1024 * 1024 * 50,
        "duplicate_wasted_bytes": 1024 * 1024 * 20,
        "duplicate_groups_count": 3,
        "total_elapsed_seconds": 2.5,
        "target_paths": ["D:/Work/TestProject"],
        "redundant_files": [],
        "all_scanned_files": []
    }

    # 模拟扫描阶段 3 完成
    view.show()
    view.on_phase3_completed(mock_result)

    # 1. 验证决策横幅已唤起呈现
    assert view.ai_decision_banner.isVisible() is True
    assert "180" in view.decision_title_lbl.text()
    assert "80% 可能性为集合判断错误" in view.decision_title_lbl.text()

    # 2. 验证选项按钮就绪
    assert view.btn_decision_organize.isVisible() is True
    assert view.btn_decision_force_ai.isVisible() is True

    # 3. 验证未私自越权在后台启动 AIWorker
    assert view.ai_worker is None

    # 4. 验证文本框中已输出详细决策指引
    report_content = view.report_text_edit.toPlainText()
    assert "扫描独立资产数量为 180 项" in report_content
    assert "运行文件整理" in report_content
    assert "强制 AI 总结" in report_content

    # 5. 验证点击【运行文件整理】发出跳转信号并带入目标路径 (切忌重写脚本)
    captured_paths = []
    view.navigate_to_organizer.connect(lambda p: captured_paths.append(p))
    view.btn_decision_organize.click()
    assert len(captured_paths) == 1
    assert captured_paths[0] == "D:/Work/TestProject"


def test_home_view_standalone_count_under_100_auto_flow(monkeypatch):
    """
    当独立资产 <= 100 时：
    已处于紧凑安全的特征范围内，自动隐藏决策横幅，启动常规分析流程。
    """
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    app = QApplication.instance() or QApplication(sys.argv)
    from app.ui.home_view import HomeView
    view = HomeView()

    mock_result = {
        "task_id": "test_scan_task_2",
        "total_files": 45,
        "standalone_file_count": 45,
        "collective_count": 0,
        "total_bytes": 1024 * 1024 * 100,
        "reclaimable_bytes": 0,
        "duplicate_wasted_bytes": 0,
        "duplicate_groups_count": 0,
        "total_elapsed_seconds": 1.0,
        "target_paths": ["D:/CleanDir"],
        "redundant_files": [],
        "all_scanned_files": []
    }

    # 拦截实际 worker 启动以防真实发网络请求
    monkeypatch.setattr(view, "generate_ai_report", MagicMock())
    view.on_phase3_completed(mock_result)

    assert view.ai_decision_banner.isVisible() is False
    view.generate_ai_report.assert_called_once_with(auto_triggered=True)


def test_home_view_on_ai_failed_user_decision_and_fallback(monkeypatch):
    """
    验证 AI 调用超时或异常时：
    1. 不因超时直接越权覆盖；
    2. 提供重试、整理和载入本地应急报告由用户定夺；
    3. 仅在用户主动点击【载入本地专家应急报告】时才载入本地应急分析。
    """
    app = QApplication.instance() or QApplication(sys.argv)
    from app.ui.home_view import HomeView
    view = HomeView()
    view.current_scan_result = {
        "target_paths": ["D:/Work/TimeoutDir"],
        "total_bytes": 1024 * 1024 * 100,
        "redundant_files": [{"path": "D:/Work/TimeoutDir/temp.zip", "size": 1024 * 1024 * 10, "is_recommended": True}]
    }

    # 模拟超时失败
    view.show()
    view.on_ai_failed("读取响应超时 (300.38s)")

    # 验证决策卡片呈现，展示原因
    assert view.ai_decision_banner.isVisible() is True
    assert "AI 深度分析报告请求超时或异常" in view.decision_title_lbl.text()
    assert view.btn_decision_load_fallback.isVisible() is True
    assert view.btn_decision_retry_ai.isVisible() is True
    assert view.btn_decision_organize.isVisible() is True

    # 此时未点击前，文本框未被静默覆盖为本地报告，保持契约说明
    assert "本系统严格恪守" in view.report_text_edit.toPlainText()

    # 用户明确点击【载入本地专家应急报告】
    view.btn_decision_load_fallback.click()

    # 验证授权后成功载入本地报告且横幅关闭
    assert view.ai_decision_banner.isVisible() is False
    assert "本地智能专家离线分析引擎" in view.report_text_edit.toPlainText()
    assert "ai_execution_plan" in view.current_scan_result


if __name__ == '__main__':
    app = QApplication.instance() or QApplication(sys.argv)
    test_ai_response_parsing()
    print("\n✅ 测试脚本执行完毕。")
