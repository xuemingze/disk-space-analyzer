import os
import sys
import tempfile
import shutil
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt

from app.config import ConfigManager, app_config, BASE_CONFIG_SCHEMA
from app.ui.settings_view import SettingsView
from app.core.scanner import DirectoryScanTask, ScanWorker


@pytest.fixture(scope="session")
def qapp():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def temp_config(tmp_path):
    config_file = tmp_path / "test_config.json"
    cfg_mgr = ConfigManager(config_file=config_file)
    return cfg_mgr


@pytest.fixture(autouse=True)
def mock_qmessagebox(monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)


def test_config_ignore_folders_schema(temp_config):
    """验证 config 基础模式与 ignore_folders 持久化与继承"""
    assert "ignore_folders" in BASE_CONFIG_SCHEMA
    assert temp_config.get("ignore_folders") == []

    # 全局级别写入
    temp_config.set("ignore_folders", ["D:\\test\\a", "D:\\test\\b"], level="global")
    assert temp_config.get("ignore_folders") == ["D:\\test\\a", "D:\\test\\b"]
    val, src = temp_config.get_with_source("ignore_folders")
    assert src == "全局配置"
    assert val == ["D:\\test\\a", "D:\\test\\b"]

    # 预设级别覆盖
    temp_config.create_custom_profile("custom_prof", "测试方案", "描述", parent="default")
    temp_config.set_active_profile("custom_prof")
    temp_config.set("ignore_folders", ["D:\\custom_ignore"], level="profile")
    assert temp_config.get("ignore_folders") == ["D:\\custom_ignore"]
    val2, src2 = temp_config.get_with_source("ignore_folders")
    assert src2 == "任务级预设"


def test_settings_view_init_and_scroll_area(qapp, temp_config, monkeypatch):
    """验证 SettingsView 正确初始化、包含 QScrollArea 且各控件可响应"""
    monkeypatch.setattr("app.ui.settings_view.app_config", temp_config)
    view = SettingsView()
    assert hasattr(view, "scroll_area")
    assert view.scroll_area is not None
    assert view.scroll_area.widgetResizable() is True
    assert view.ignore_list is not None
    assert view.ignore_list.count() == 0


def test_settings_view_font_scaling_adaptation(qapp, temp_config, monkeypatch):
    """
    验证常规字体、系统字体放大 125% (16pt) 和 150% (20pt) 下布局自适应
    确保 QScrollArea 容器与卡片在不同字体比例下均能正常计算布局几何，无崩溃或固定高度截断
    """
    monkeypatch.setattr("app.ui.settings_view.app_config", temp_config)
    view = SettingsView()
    view.resize(1000, 700)
    view.show()

    scales = [
        ("100% 常规字体", 9),
        ("125% 放大字体", 12),
        ("150% 放大字体", 15),
        ("200% 特大字体", 18),
    ]

    for label, pt_size in scales:
        font = QFont("Microsoft YaHei", pt_size)
        view.setFont(font)
        view.content_widget.setFont(font)
        qapp.processEvents()

        # 检查滚动区域与内容几何尺寸
        content_hint = view.content_widget.sizeHint()
        assert content_hint.height() > 0
        assert content_hint.width() > 0
        # 验证 ignore_list 及按钮大小自适应
        assert view.ignore_list.height() >= 100
        assert view.save_global_btn.height() > 0
        assert view.save_profile_btn.height() > 0

    view.close()


def test_settings_view_ignore_folders_crud_and_persistence(qapp, temp_config, monkeypatch, tmp_path):
    """
    验证忽略文件夹列表：添加、重复过滤、规范化、删除、清空以及持久化保存
    """
    monkeypatch.setattr("app.ui.settings_view.app_config", temp_config)

    # 创建测试本地真实目录
    test_dir1 = tmp_path / "folder_a"
    test_dir2 = tmp_path / "folder_b"
    test_dir1.mkdir()
    test_dir2.mkdir()

    view = SettingsView()

    # 1. 正常添加路径 (包含规范化)
    ok1 = view._add_single_ignore_path(str(test_dir1), prompt_if_not_exist=False)
    assert ok1 is True
    assert view.ignore_list.count() == 1
    assert view._get_current_ignore_paths() == [os.path.normpath(str(test_dir1))]

    # 2. 重复添加 (相同路径不同大小写/斜杠)
    dup_path = str(test_dir1).replace("\\", "/") + "/"
    ok_dup = view._add_single_ignore_path(dup_path, prompt_if_not_exist=False)
    assert ok_dup is False
    assert view.ignore_list.count() == 1

    # 3. 添加第二个路径
    ok2 = view._add_single_ignore_path(str(test_dir2), prompt_if_not_exist=False)
    assert ok2 is True
    assert view.ignore_list.count() == 2

    # 4. 持久化保存 (Global)
    view.save_settings(level="global")

    # 验证持久化配置中已被写入
    saved_paths = temp_config.get("ignore_folders")
    assert len(saved_paths) == 2
    assert os.path.normpath(str(test_dir1)) in saved_paths
    assert os.path.normpath(str(test_dir2)) in saved_paths

    # 5. 重新实例化 SettingsView，验证重启后自动加载已保存的列表
    view2 = SettingsView()
    assert view2.ignore_list.count() == 2
    assert view2._get_current_ignore_paths() == saved_paths

    # 6. 删除单条路径
    view2.ignore_list.setCurrentRow(0)
    view2.ignore_list.item(0).setSelected(True)
    view2.del_ignore_folder()
    assert view2.ignore_list.count() == 1

    # 7. 保存并验证
    view2.save_settings(level="global")
    assert len(temp_config.get("ignore_folders")) == 1

    # 8. 清空
    view2.ignore_list.clear()
    view2._update_ignore_count()
    assert view2.ignore_list.count() == 0
    view2.save_settings(level="global")
    assert temp_config.get("ignore_folders") == []


def test_scanner_with_ignore_folders_integration(tmp_path):
    """
    验证扫描引擎在配置 ignore_folders 时的过滤准确性
    """
    root_dir = tmp_path / "scan_root"
    root_dir.mkdir()

    # 正常目录
    normal_dir = root_dir / "src"
    normal_dir.mkdir()
    (normal_dir / "main.py").write_text("print('hello')", encoding="utf-8")

    # 忽略目录及其子目录
    ignore_dir = root_dir / "node_modules"
    ignore_dir.mkdir()
    (ignore_dir / "package.json").write_text("{}", encoding="utf-8")
    sub_ignore = ignore_dir / ".cache"
    sub_ignore.mkdir()
    (sub_ignore / "cache.bin").write_text("cache", encoding="utf-8")

    # 运行 DirectoryScanTask
    task = DirectoryScanTask(
        target_paths=[str(root_dir)],
        skip_system_protected=False,
        enable_duplicate_detection=False,
        ignore_folders=[str(ignore_dir)]
    )

    result_holder = {}
    task.finished_ok.connect(lambda r: result_holder.update(r))

    task.run()

    assert "all_scanned_files" in result_holder
    scanned_paths = [f["path"] for f in result_holder["all_scanned_files"]]

    # 正常文件应被扫描到
    assert any("main.py" in p for p in scanned_paths)
    # 忽略目录下的文件均不应被扫描到
    assert not any("package.json" in p for p in scanned_paths)
    assert not any("cache.bin" in p for p in scanned_paths)
    assert result_holder.get("skipped_ignored_count", 0) >= 1
