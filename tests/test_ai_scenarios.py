import sys
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QWidget, QLineEdit
from PySide6.QtCore import Qt
from app.core.ai_service import AIService
from app.core.ai_service import AIResponse
from app.ui.components.decision_banner import AIDecisionBannerWidget
from app.ui.components.data_table import FileDataGridWidget, PlanningPathItemDelegate


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
    assert resp1.parse_status == "SUCCESS"

    print("\n--- 场景 2: HTTP 200 但 content 为空 ---")
    empty_json = {
        "choices": [{
            "message": {
                "content": ''
            }
        }]
    }
    resp2 = AIService._parse_ai_response(empty_json)
    assert resp2.parse_status != "SUCCESS"

    print("\n--- 场景 3: HTTP 200 但仅返回思考内容 ---")
    think_json = {
        "choices": [{
            "message": {
                "content": '<think>思考中...</think>'
            }
        }]
    }
    resp3 = AIService._parse_ai_response(think_json)
    assert resp3.parse_status != "SUCCESS"


def test_planning_path_delegate_in_place_edit():
    """
    规划路径就地编辑核心契约测试：
    1. 就地编辑必须在原规划路径基础上修改，绝不是先清空；
    2. 打开编辑器时预填原规划路径；
    3. 全选文字，光标就绪，方便就地微调；
    4. 提交后正确更新数据模型。
    """
    app = QApplication.instance() or QApplication(sys.argv)
    widget = FileDataGridWidget()
    test_files = [{
        "name": "Navicat.exe",
        "path": "D:/DevTools/Navicat/Navicat.exe",
        "size": 1024 * 1024 * 50,
        "category": "开发与运维工具",
        "target_subpath": "D:/运维工具/数据库客户端/Navicat",
        "action": "建议归档",
        "state": "正常",
        "redundant_type": "无冗余",
        "match_rule": "Navicat",
        "reason": "测试规则"
    }]
    widget.populate_data(test_files, 1024 * 1024 * 50)

    model = widget.proxy_model.sourceModel()
    idx = model.index(0, 3) # 第 3 列为建议规划路径
    assert idx.data(Qt.DisplayRole) == "D:/运维工具/数据库客户端/Navicat"
    assert idx.data(Qt.EditRole) == "D:/运维工具/数据库客户端/Navicat"

    delegate = widget.table_view.itemDelegateForColumn(3)
    assert isinstance(delegate, PlanningPathItemDelegate)

    editor = delegate.createEditor(widget.table_view, None, idx)
    assert isinstance(editor, QLineEdit)

    # 验证 setEditorData 保持原路径文本，未被清空
    delegate.setEditorData(editor, idx)
    assert editor.text() == "D:/运维工具/数据库客户端/Navicat"
    assert editor.hasSelectedText() is True

    # 模拟用户就地在原路径上微调
    editor.setText("D:/运维工具/数据库客户端/Navicat_Premium")
    delegate.setModelData(editor, model, idx)

    # 验证数据模型已更新为微调后的规划路径
    assert idx.data(Qt.DisplayRole) == "D:/运维工具/数据库客户端/Navicat_Premium"


def test_ai_decision_banner_widget_oop():
    """
    统一面向对象决策卡片 AIDecisionBannerWidget 契约测试：
    1. 超阈值诊断模式 (show_over_threshold_diagnosis)：
       展示 80% 可能性为集合判断错误，提供最大化明细与强制 AI 选项；
    2. 错误诊断模式 (show_ai_error_diagnosis)：
       展示超时/失败原因，提供重试 AI、载入本地应急报告与最大化明细；
    3. 信号投递正确性。
    """
    app = QApplication.instance() or QApplication(sys.argv)
    banner = AIDecisionBannerWidget()

    # 1. 验证超 100 项诊断
    banner.show_over_threshold_diagnosis(150, "AI 总结")
    assert banner.isVisible() is True
    assert "150" in banner.title_lbl.text()
    assert "80% 可能性为集合判断错误" in banner.title_lbl.text()
    assert banner.btn_inspect.isVisible() is True
    assert "最大化" in banner.btn_inspect.text()
    assert banner.btn_force_ai.isVisible() is True
    assert banner.btn_retry_ai.isVisible() is False
    assert banner.btn_load_fallback.isVisible() is False

    signals_received = []
    banner.inspect_details_requested.connect(lambda: signals_received.append("inspect"))
    banner.force_ai_requested.connect(lambda: signals_received.append("force"))
    banner.retry_ai_requested.connect(lambda: signals_received.append("retry"))
    banner.load_fallback_requested.connect(lambda: signals_received.append("fallback"))

    banner.btn_inspect.click()
    assert signals_received == ["inspect"]

    banner.btn_force_ai.click()
    assert signals_received == ["inspect", "force"]

    # 2. 验证 AI 超时/异常诊断
    banner.show_ai_error_diagnosis("读取响应超时 (300.38s)", "AI 全景总结")
    assert "AI 全景总结请求超时或异常" in banner.title_lbl.text()
    assert "读取响应超时 (300.38s)" in banner.sub_lbl.text()
    assert banner.btn_inspect.isVisible() is True
    assert banner.btn_force_ai.isVisible() is False
    assert banner.btn_retry_ai.isVisible() is True
    assert banner.btn_load_fallback.isVisible() is True

    banner.btn_retry_ai.click()
    assert signals_received == ["inspect", "force", "retry"]

    banner.btn_load_fallback.click()
    assert signals_received == ["inspect", "force", "retry", "fallback"]


def test_home_view_standalone_count_over_100_decision_flow(monkeypatch):
    """
    准则一核心编排架构与用户决策权保全测试：
    当扫描独立资产数量 > 100 时：
    1. 80% 可能性为集合判断错误；
    2. AI 界面必须直接输出独立资产数量并展示统一面向对象决策卡片；
    3. 严禁未经授权自动后台触发 AI 分析越权处理；
    4. 明确提供【查看全局扫描资产明细 (推荐并最大化)】与【强制 AI 总结】由用户定夺；
    5. 点击推荐选项时，直接跳转并最大化主控扫描菜单的「全局扫描资产明细」卡片。
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
        "all_scanned_files": [{"name": f"f_{i}.txt", "path": f"D:/Work/f_{i}.txt", "size": 100} for i in range(180)]
    }

    # 模拟扫描阶段 3 完成
    view.show()
    view.on_phase3_completed(mock_result)

    # 1. 验证统一面向对象决策横幅已唤起呈现
    assert view.ai_decision_banner.isVisible() is True
    assert "180" in view.ai_decision_banner.title_lbl.text()
    assert "80% 可能性为集合判断错误" in view.ai_decision_banner.title_lbl.text()

    # 2. 验证选项按钮就绪
    assert view.ai_decision_banner.btn_inspect.isVisible() is True
    assert view.ai_decision_banner.btn_force_ai.isVisible() is True

    # 3. 验证未私自越权在后台启动 AIWorker
    assert view.ai_worker is None

    # 4. 验证文本框中已输出详细决策指引
    report_content = view.report_text_edit.toPlainText()
    assert "扫描独立资产数量为 180 项" in report_content
    assert "查看全局扫描资产明细 (推荐并最大化)" in report_content
    assert "强制 AI" in report_content

    # 5. 验证点击【查看全局扫描资产明细 (推荐并最大化)】直接跳转并最大化展示 Tab 1
    view.ai_decision_banner.btn_inspect.click()
    assert view.tabs.currentIndex() == 1
    assert view.is_tab_fullscreen() is True


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
    2. 提供重试、查看明细和载入本地应急报告由用户定夺；
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
    assert "AI 全景总结请求超时或异常" in view.ai_decision_banner.title_lbl.text()
    assert view.ai_decision_banner.btn_load_fallback.isVisible() is True
    assert view.ai_decision_banner.btn_retry_ai.isVisible() is True
    assert view.ai_decision_banner.btn_inspect.isVisible() is True

    # 此时未点击前，文本框未被静默覆盖为本地报告，保持契约说明
    assert "本系统严格恪守" in view.report_text_edit.toPlainText()

    # 用户明确点击【载入本地专家应急报告】
    view.ai_decision_banner.btn_load_fallback.click()

    # 验证授权后成功载入本地报告且横幅关闭
    assert view.ai_decision_banner.isVisible() is False
    assert "本地智能专家离线分析引擎" in view.report_text_edit.toPlainText()
    assert "ai_execution_plan" in view.current_scan_result


def test_organizer_view_over_100_decision_flow(monkeypatch):
    """
    文件整理视图 (OrganizerView) 同构机制测试：
    1. 当扫描独立资产 > 100 项时，激活统一面向对象 AIDecisionBannerWidget；
    2. 绝不私自越权提交 AI 规划；
    3. 支持用户明确授权强制 AI 整理；
    4. 支持推荐选项跳转并最大化主控扫描的全局资产明细卡片。
    """
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    app = QApplication.instance() or QApplication(sys.argv)
    from app.ui.organizer_view import OrganizerView
    from app.ui.home_view import HomeView

    # 模拟顶层 MainWindow 环境
    class DummyMainWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.home_view = HomeView(parent=self)
            self.organizer_view = OrganizerView(parent=self)
            self.current_idx = 1
        def switch_view(self, idx):
            self.current_idx = idx

    dummy_main = DummyMainWindow()
    dummy_main.show()
    org_view = dummy_main.organizer_view

    mock_files = [{"name": f"file_{i}.dat", "path": f"D:/Data/file_{i}.dat", "size": 1024} for i in range(120)]
    mock_scan_res = {
        "all_scanned_files": mock_files,
        "total_bytes": 120 * 1024
    }

    # 拦截实际 worker 执行
    monkeypatch.setattr(org_view, "execute_ai_classify_worker", MagicMock())

    # 模拟扫描完成 (> 100 项)
    org_view.on_scan_completed(mock_scan_res)

    # 1. 验证横幅展示
    assert org_view.decision_banner.isVisible() is True
    assert "120" in org_view.decision_banner.title_lbl.text()
    assert "80% 可能性为集合判断错误" in org_view.decision_banner.title_lbl.text()
    # 2. 验证未自动执行 worker
    org_view.execute_ai_classify_worker.assert_not_called()

    # 3. 验证点击【强制 AI 整理】触发执行
    org_view.decision_banner.btn_force_ai.click()
    org_view.execute_ai_classify_worker.assert_called_once_with(mock_files)

    # 4. 验证点击【查看全局扫描资产明细 (推荐并最大化)】
    # 应该将结果注入 home_view，切换至主控菜单并最大化 Tab 1
    org_view.decision_banner.btn_inspect.click()
    assert dummy_main.current_idx == 0
    assert dummy_main.home_view.tabs.currentIndex() == 1
    assert dummy_main.home_view.is_tab_fullscreen() is True
    assert dummy_main.home_view.global_detail_table.proxy_model.rowCount() == 120


if __name__ == '__main__':
    app = QApplication.instance() or QApplication(sys.argv)
    test_ai_response_parsing()
    test_planning_path_delegate_in_place_edit()
    test_ai_decision_banner_widget_oop()
    print("\n✅ 所有场景测试均已就绪。")
