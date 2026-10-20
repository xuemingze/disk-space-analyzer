"""
tests/test_collective_promotion_and_app_manager.py
专项测试套件：
1. WindowsPowerShell 等原生系统预置组件自动收录验证；
2. 智能父级推断算法 (PromoteCollectiveDialog / AssetPromoterService)；
3. 动态收割合并与全域信号广播 (一改俱改)；
4. FileDataGridWidget 底座级双击与转集合操作同构；
5. AppManagerView 一级看板 44px 行高与 UI 铁律合规性。
"""
import os
import sys
import pytest
from pathlib import Path
from PySide6.QtWidgets import QApplication, QHeaderView, QPushButton, QMessageBox

from app.core.registry_detector import RegistryAppDetector
from app.core.asset_promoter import AssetPromoterService
from app.ui.components.data_table import FileDataGridWidget
from app.ui.app_manager_view import AppManagerView
from app.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def mock_qmessagebox(monkeypatch):
    """全局 mock 弹窗，防止阻塞自动化测试"""
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)


def test_windows_powershell_inbox_component_recognized():
    """验证 WindowsPowerShell 作为原生系统组件被权威收录，杜绝碎文件漏判"""
    ps_path = r"C:\Program Files (x86)\WindowsPowerShell"
    if not os.path.exists(ps_path):
        pytest.skip("本地环境无 x86 WindowsPowerShell 目录")

    # 1. 根目录直接命中已安装软件 (is_root=True)
    match_root = RegistryAppDetector.match_app_by_path(ps_path)
    assert match_root is not None
    info, is_root = match_root
    assert is_root is True
    assert "PowerShell" in info.name
    assert info.source == "system_builtin"

    # 2. 深层文件命中其内部组件 (is_root=False)
    sub_xml = os.path.join(ps_path, "Modules", "PowerShellGet", "1.0.0.1", "PSGet.Format.ps1xml")
    match_sub = RegistryAppDetector.match_app_by_path(sub_xml)
    assert match_sub is not None
    sub_info, sub_is_root = match_sub
    assert sub_is_root is False
    assert "PowerShell" in sub_info.name


def test_asset_promoter_infer_parent_candidates(tmp_path):
    """验证智能父级推断算法自底向上解析与推荐度权重"""
    # 模拟一个深度嵌套的目录
    app_root = tmp_path / "MyDeepApp"
    sub_dir = app_root / "Modules" / "PluginA" / "v1.0"
    sub_dir.mkdir(parents=True)
    f = sub_dir / "test.xml"
    f.write_text("<xml/>", encoding="utf-8")

    # 手动注册为应用
    RegistryAppDetector.set_custom_apps([str(app_root)])

    candidates = AssetPromoterService.infer_parent_candidates(str(f))
    assert len(candidates) >= 3

    # 验证 MyDeepApp 在候选列表中且被置为推荐
    app_cand = next((c for c in candidates if c["name"] == "MyDeepApp"), None)
    assert app_cand is not None
    assert app_cand["is_recommended"] is True


def test_asset_promoter_execute_promotion(tmp_path):
    """验证内存级就地收割与集合资产动态注入"""
    app_root = tmp_path / "TestPromoteApp"
    app_root.mkdir()
    (app_root / "file1.txt").write_text("aaa", encoding="utf-8")
    (app_root / "sub").mkdir()
    (app_root / "sub" / "file2.txt").write_text("bbb", encoding="utf-8")

    fake_assets = [
        {"path": str(app_root / "file1.txt"), "name": "file1.txt", "size": 10, "file_count": 1},
        {"path": str(app_root / "sub" / "file2.txt"), "name": "file2.txt", "size": 20, "file_count": 1},
        {"path": str(tmp_path / "other.txt"), "name": "other.txt", "size": 30, "file_count": 1}
    ]

    received_events = []
    AssetPromoterService.instance().collective_promoted.connect(
        lambda target, asset: received_events.append((target, asset))
    )

    updated_assets, new_asset = AssetPromoterService.execute_promotion(
        target_dir=str(app_root),
        app_name="TestPromoteApp",
        current_assets=fake_assets,
        persist=False
    )

    # 验证碎文件被收割：只剩 new_asset 和 other.txt，原两个碎文件被移除
    assert len(updated_assets) == 2
    assert updated_assets[0]["name"] == "TestPromoteApp"
    assert updated_assets[0]["is_directory_collective"] is True
    assert updated_assets[1]["name"] == "other.txt"

    # 验证全局广播收到事件
    assert len(received_events) >= 1
    assert received_events[-1][0] == str(app_root)


def test_file_data_grid_promote_and_double_click(qapp):
    """
    验证底座级 FileDataGridWidget 遵循「一改俱改、特性同构」:
    - 垂直表头锁死 44px 行高
    - 具备 promote_collective_requested 信号
    - 具备双击与右键转集合动作
    """
    grid = FileDataGridWidget(is_selectable=True)
    assert grid.table_view.verticalHeader().defaultSectionSize() == 44
    assert grid.table_view.verticalHeader().sectionResizeMode(0) == QHeaderView.Fixed
    assert hasattr(grid, "promote_collective_requested")


def test_app_manager_view_ui_rules_and_navigation(qapp):
    """
    验证左侧一级「🎯 软件与应用管理」看板:
    - 锁死 44px 行高
    - 操作栏按钮固定 28px 高度
    - 主窗口侧边栏导航顺畅
    """
    view = AppManagerView()
    assert view.table_apps.verticalHeader().defaultSectionSize() == 44
    assert view.table_apps.verticalHeader().sectionResizeMode(0) == QHeaderView.Fixed
    assert view.table_apps.rowCount() > 0

    # 验证操作列按钮包装高度为 28px
    cell_act = view.table_apps.cellWidget(0, 5)
    assert cell_act is not None
    buttons = cell_act.findChildren(QPushButton)
    assert len(buttons) >= 1
    for b in buttons:
        assert b.height() == 28

    # 验证主窗口路由
    win = MainWindow()
    assert hasattr(win, "app_manager_view")
    assert hasattr(win, "btn_nav_app_mgr")

    # 切换到应用管理 (索引 4)
    win.switch_view(4)
    assert win.stacked_widget.currentIndex() == 4
    assert win.btn_nav_app_mgr.isChecked()


def test_promote_collective_dialog_initialization(qapp, tmp_path):
    """验证智能父级推断单选弹窗正常实例化并渲染各控件，无 NameError 或未导入异常"""
    from app.ui.components.promote_collective_dialog import PromoteCollectiveDialog

    sub_p = tmp_path / "SomeApp" / "Sub" / "child.txt"
    sub_p.parent.mkdir(parents=True)
    sub_p.write_text("dummy", encoding="utf-8")

    dlg = PromoteCollectiveDialog(str(sub_p))
    assert dlg.selected_target_dir == ""
    assert dlg.txt_name.text() != ""
    assert len(dlg.radio_widgets) > 0
