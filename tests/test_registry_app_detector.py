"""
tests/test_registry_app_detector.py
Windows 注册表与自定义软件拓扑索引专项测试
验证：
1. 注册表已安装软件的毫秒级读取与路径前缀树索引；
2. 通用子目录 (如 \\Application) 智能收拢至软件根；
3. EdgeWebView 等庞大应用从源头直接剪枝封包，杜绝 .pma 等碎片泄漏；
4. 用户自定义软件目录配置与优先级；
5. 设置页面 CRUD 与配置持久化。
"""
import os
import sys
import pytest
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.registry_detector import RegistryAppDetector, InstalledAppInfo
from app.core.app_detector import AppDetector
from app.core.unified_scanner import UnifiedScanner
from app.config import app_config


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


def test_registry_apps_parsing():
    """验证从 Windows 注册表能够正确读取并解析应用"""
    apps = RegistryAppDetector.get_installed_apps(force_reload=True)
    if sys.platform == "win32":
        assert len(apps) > 0
        # 验证返回的实体结构
        sample_info = next(iter(apps.values()))
        assert isinstance(sample_info, InstalledAppInfo)
        assert bool(sample_info.name)
        assert bool(sample_info.install_root)


def test_edgewebview_and_edge_matched_and_pruned():
    """
    针对用户事故用例深度复现测试：
    验证 EdgeWebView 目录不再泄漏内部 SetupMetrics/*.pma 碎片文件，
    而是作为单一应用原子单元从源头剪枝出库！
    """
    edge_wv_path = r"C:\Program Files (x86)\Microsoft\EdgeWebView"
    if not os.path.exists(edge_wv_path):
        pytest.skip("本地未安装 EdgeWebView，跳过物理目录扫描验证")

    # 1. 注册表匹配验证
    match_res = RegistryAppDetector.match_app_by_path(edge_wv_path)
    assert match_res is not None
    app_info, is_root = match_res
    assert is_root is True
    assert "Edge" in app_info.name or "WebView" in app_info.name

    # 2. AppDetector 识别验证
    coll_info = AppDetector.detect_directory_collective(edge_wv_path)
    assert coll_info is not None
    assert coll_info.get("is_collective") is True
    assert coll_info.get("collective_type") == "已安装应用"

    # 3. UnifiedScanner 扫描验证：绝不泄漏零散碎文件
    assets = UnifiedScanner.scan_directory([edge_wv_path])
    assert len(assets) == 1
    asset = assets[0]
    assert asset.name == "EdgeWebView"
    assert asset.is_collective is True
    assert asset.file_count > 100
    assert not any(a.name.endswith(".pma") for a in assets)


def test_custom_app_registration_and_precedence(tmp_path):
    """验证用户手动添加的免安装独立应用目录优先匹配并剪枝"""
    my_tool = tmp_path / "MyPortableTool"
    my_tool.mkdir()
    (my_tool / "tool.exe").write_bytes(b"MZfakeexe")
    (my_tool / "sub").mkdir()
    (my_tool / "sub" / "data.bin").write_bytes(b"datadatadata")

    # 手动注册
    RegistryAppDetector.set_custom_apps([str(my_tool)])

    # 1. 验证匹配
    match_res = RegistryAppDetector.match_app_by_path(str(my_tool))
    assert match_res is not None
    app_info, is_root = match_res
    assert is_root is True
    assert app_info.source == "custom"
    assert app_info.name == "MyPortableTool"

    # 2. 验证子目录归属
    sub_match = RegistryAppDetector.match_app_by_path(str(my_tool / "sub"))
    assert sub_match is not None
    sub_info, sub_is_root = sub_match
    assert sub_is_root is False
    assert sub_info.name == "MyPortableTool"

    # 3. 验证扫描器剪枝
    assets = UnifiedScanner.scan_directory([str(tmp_path)])
    # 整个 MyPortableTool 应该作为一个集体资产被剪枝封包
    matched_units = [a for a in assets if "MyPortableTool" in a.name or a.path == str(my_tool)]
    assert len(matched_units) == 1
    assert matched_units[0].is_collective is True
    assert matched_units[0].file_count == 2


def test_settings_view_custom_apps_crud_and_persistence(qapp, tmp_path, monkeypatch):
    """验证在设置界面中对自定义软件目录的 CRUD 与持久化"""
    from app.ui.settings_view import SettingsView

    view = SettingsView()
    # 模拟添加一个自定义应用目录
    demo_app_dir = str(tmp_path / "DemoCustomApp")
    os.makedirs(demo_app_dir, exist_ok=True)

    view.custom_app_list.clear()
    view.custom_app_list.addItem(demo_app_dir)
    assert view.custom_app_list.count() == 1

    # 执行保存
    view.save_settings(level="global")

    # 从 config 读取验证
    saved_dirs = app_config.get("custom_app_dirs", default=[])
    assert demo_app_dir in saved_dirs

    # 清理并重新装载验证
    view.load_settings()
    items = [view.custom_app_list.item(i).text() for i in range(view.custom_app_list.count())]
    assert demo_app_dir in items
