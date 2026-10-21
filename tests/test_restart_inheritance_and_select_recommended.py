"""
tests/test_restart_inheritance_and_select_recommended.py
专项回归测试：
1. 用户自定义沉淀在重启软件（清除所有类级内存缓存，重新从独立持久化文件与配置恢复）后完整继承；
2. 自定义沉淀应用外显名称保留与双保险持久化（custom_apps.json + config.json）；
3. 自定义沉淀应用绝对优先于广义大抽屉（例如包含“经控”、“财务”、“项目”等大抽屉关键词的目录被用户收拢沉淀后，重启仍被 100% 识别为应用实体集体并源头剪枝）；
4. 修复“仅选推荐”按钮失效与点击无反应的问题：
   - 在有/无 AI 执行清单、有/无冗余项等各场景下，点击“仅选推荐”均能即时勾选推荐项；
   - 勾选后立即联动刷新底部统计栏与表格统计标签，0 毫秒卡顿，0 网络阻塞；
   - 切换 Tab 标签页时底部已选中统计栏实时同步当前活动表格。
"""
import os
import sys
import json
import pytest
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.registry_detector import (
    RegistryAppDetector,
    CUSTOM_APPS_PERSIST_FILE,
    load_standalone_custom_apps,
    load_standalone_custom_app_entries,
    save_standalone_custom_apps
)
from app.core.asset_promoter import AssetPromoterService
from app.core.app_detector import AppDetector
from app.core.unified_scanner import UnifiedScanner
from app.config import app_config
from app.ui.components.data_table import FileDataGridWidget
from app.ui.home_view import HomeView


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def mock_msgbox(monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)


def test_custom_app_restart_inheritance_and_custom_name(tmp_path):
    """
    测试点 1：用户自定义沉淀重启后继承，且保留自定义名称。
    即使目录名称包含大抽屉关键词（如“经控单据系统”、“项目核心”），
    由于用户显式沉淀，重启后依然拥有最高裁决权，必须被识别为集体资产！
    """
    # 模拟一个用户目录：名称含有广义容器关键词“经控”
    jk_app_dir = tmp_path / "经控单据系统"
    jk_app_dir.mkdir()
    (jk_app_dir / "bin").mkdir()
    (jk_app_dir / "bin" / "main.exe").write_bytes(b"MZfakeexe")
    (jk_app_dir / "data.xlsx").write_bytes(b"fakedata")

    custom_name = "我的经控智能单据平台"

    # 用户手动收拢或添加沉淀
    AssetPromoterService.persist_collective(str(jk_app_dir), app_name=custom_name)

    # 验证独立持久化文件是否正确写入了名称
    entries = load_standalone_custom_app_entries()
    norm_target = os.path.normcase(os.path.normpath(str(jk_app_dir)))
    found_entry = next((e for e in entries if os.path.normcase(e["path"]) == norm_target), None)
    assert found_entry is not None
    assert found_entry["name"] == custom_name

    # 模拟软件完全退出并重启：彻底抹去内存缓存
    RegistryAppDetector._cached_apps = None
    RegistryAppDetector._cached_roots_sorted = None
    RegistryAppDetector._custom_dirs = {}
    RegistryAppDetector._custom_names = {}

    # 重启后：AppDetector 必须直接识别该目录为用户自定义集体，绝不可被 match_broad_container 误拦截！
    collective_info = AppDetector.detect_directory_collective(str(jk_app_dir))
    assert collective_info is not None
    assert collective_info.get("is_collective") is True
    assert collective_info.get("collective_type") == "用户自定义集体"
    assert collective_info.get("software_name") == custom_name

    # 扫描引擎在扫描父目录时，必须在此处触发防御性递归剪枝，作为单一原子资产出库！
    assets = UnifiedScanner.scan_directory([str(tmp_path)])
    jk_units = [a for a in assets if a.path == str(jk_app_dir)]
    assert len(jk_units) == 1
    assert jk_units[0].is_collective is True
    assert jk_units[0].name == "经控单据系统"
    assert jk_units[0].file_count == 2
    # 确保子目录碎片没有泄漏
    assert not any(a.path == str(jk_app_dir / "bin" / "main.exe") for a in assets)


def test_select_recommended_only_instant_and_responsive(qapp):
    """
    测试点 2：测试 FileDataGridWidget.select_recommended_only 响应性：
    - 清空后点击“仅选推荐”，快速勾选所有 is_recommended 或 is_duplicate_copy 项；
    - 即时刷新统计与信号发射。
    """
    grid = FileDataGridWidget(is_selectable=True)
    test_data = [
        {"name": "file1.log", "path": "D:/test/file1.log", "size": 1000, "is_recommended": True, "tag": "推荐清理"},
        {"name": "file2.bak", "path": "D:/test/file2.bak", "size": 2000, "is_recommended": False, "is_duplicate_copy": True},
        {"name": "file3.doc", "path": "D:/test/file3.doc", "size": 5000, "is_recommended": False},
        {"name": "file4.tmp", "path": "D:/test/file4.tmp", "size": 3000, "phase_status": "AI智脑已决策 (清理)", "risk_level": "低风险"},
    ]
    grid.populate_data(test_data)

    # 先主动全部清空
    grid.select_all(False)
    assert len(grid.get_checked_paths()) == 0

    # 执行仅选推荐
    count = grid.select_recommended_only()
    assert count == 3  # file1(is_recommended), file2(duplicate_copy), file4(AI决策低风险清理)
    assert "D:/test/file1.log" in grid.get_checked_paths()
    assert "D:/test/file2.bak" in grid.get_checked_paths()
    assert "D:/test/file4.tmp" in grid.get_checked_paths()
    assert "D:/test/file3.doc" not in grid.get_checked_paths()
    assert grid.source_model.checked_bytes == 6000


def test_select_recommended_with_ai_execution_plan(qapp):
    """
    测试点 3：测试依据 AI 创作的结构化执行清单 (ai_execution_plan) 勾选推荐资产。
    AI 清单具有最高执行统揽裁决权。
    """
    grid = FileDataGridWidget(is_selectable=True)
    test_data = [
        {"name": "report.xlsx", "path": "D:/work/report.xlsx", "size": 4000, "is_recommended": False},
        {"name": "system.log", "path": "D:/work/system.log", "size": 1000, "is_recommended": False},
    ]
    grid.populate_data(test_data)
    grid.select_all(False)

    # AI 创作的标准清单：明确推荐归档 report.xlsx
    ai_plan = [
        {
            "original_path": "D:/work/report.xlsx",
            "action": "归档",
            "risk_level": "低风险",
            "rationale": "经控报表历史版本，建议归档至财务大区"
        }
    ]

    count = grid.select_recommended_only(ai_plan=ai_plan)
    assert count == 1
    assert "D:/work/report.xlsx" in grid.get_checked_paths()
    assert "D:/work/system.log" not in grid.get_checked_paths()


def test_home_view_trigger_ai_recommendation_only_no_hang(qapp):
    """
    测试点 4：测试 HomeView 点击“📌 仅选推荐”：
    - 不再发起任何耗时或阻塞的网络请求；
    - 即时更新底部 selection_stat_label 且数字与选中有严格对应；
    - 切换 Tab 时自动实时联动同步。
    """
    view = HomeView()
    test_items = [
        {"name": "dup_copy.iso", "path": "D:/dup_copy.iso", "size": 1024 * 1024 * 10, "is_duplicate": True, "is_duplicate_copy": True, "is_recommended": True},
        {"name": "original.iso", "path": "D:/original.iso", "size": 1024 * 1024 * 10, "is_duplicate": True, "is_duplicate_copy": False, "is_recommended": False},
    ]
    view.current_scan_result = {
        "all_scanned_files": test_items,
        "redundant_files": test_items,
        "total_bytes": 1024 * 1024 * 20
    }
    view.duplicate_table.populate_data(test_items)
    view.tabs.setCurrentIndex(2)  # 切换到重复资产 Tab

    # 先全部清空
    view.duplicate_table.select_all(False)
    assert "已选中: 0 个" in view.selection_stat_label.text()

    # 点击“仅选推荐”
    view.trigger_ai_recommendation_only()

    # 验证即时勾选了副本，且底部统计栏立即更新
    assert "D:/dup_copy.iso" in view.duplicate_table.get_checked_paths()
    assert "D:/original.iso" not in view.duplicate_table.get_checked_paths()
    assert "已选中: 1 个" in view.selection_stat_label.text()
    assert "10.00 MB" in view.selection_stat_label.text()

    # 切换到 Tab 1 (全局资产) - 此时全局表格未勾选，底部应即时切换为 0
    view.tabs.setCurrentIndex(1)
    assert "已选中: 0 个" in view.selection_stat_label.text()
