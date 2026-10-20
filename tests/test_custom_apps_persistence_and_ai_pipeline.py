"""
tests/test_custom_apps_persistence_and_ai_pipeline.py
专项测试:
1. custom_apps.json 独立持久化双保险机制与重启保全
2. 5 类核心高价值资产过滤管道 (应用集合、安装包、镜像、文档、APK) 及小碎片 0 Token 阻断
3. AIService.analyze_directory_or_app_with_ai 接口及本地兜底
4. PromoteCollectiveDialog 与 AppManagerView 的 AI 研判交互
5. FileDataGridWidget 的 AI 研判右键动作与同构覆盖
"""
import os
import json
import tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication

from app.core.registry_detector import (
    RegistryAppDetector,
    CUSTOM_APPS_PERSIST_FILE,
    save_standalone_custom_apps,
    load_standalone_custom_apps
)
from app.core.asset_promoter import AssetPromoterService
from app.core.ai_service import AIService
from app.ui.components.data_table import FileDataGridWidget
from app.ui.components.promote_collective_dialog import PromoteCollectiveDialog
from app.ui.app_manager_view import AppManagerView


def test_custom_apps_standalone_persistence(tmp_path):
    """测试 custom_apps.json 独立持久化文件的读写与去重机制"""
    test_dirs = [
        str(tmp_path / "AppOne"),
        str(tmp_path / "AppTwo"),
        str(tmp_path / "AppOne")  # 重复项
    ]
    # 测试写入
    ok = save_standalone_custom_apps(test_dirs)
    assert ok is True

    # 测试读取与去重
    loaded = load_standalone_custom_apps()
    norm_loaded = [os.path.normcase(p) for p in loaded]
    assert os.path.normcase(str(tmp_path / "AppOne")) in norm_loaded
    assert os.path.normcase(str(tmp_path / "AppTwo")) in norm_loaded


def test_asset_promoter_persist_double_insurance(tmp_path):
    """测试 AssetPromoterService.persist_collective 触发双保险落盘"""
    app_dir = tmp_path / "MyPromotedSoftware"
    app_dir.mkdir()

    AssetPromoterService.persist_collective(str(app_dir))

    # 验证独立持久化文件中必须存在该目录
    loaded = load_standalone_custom_apps()
    norm_loaded = [os.path.normcase(p) for p in loaded]
    assert os.path.normcase(str(app_dir)) in norm_loaded

    # 验证 RegistryAppDetector 能够直接识别出来
    apps = RegistryAppDetector.get_installed_apps(force_reload=True)
    norm_key = os.path.normcase(os.path.normpath(str(app_dir)))
    assert norm_key in apps
    assert apps[norm_key].source == "custom"


def test_ai_high_value_filter_pipeline():
    """测试 5 类高价值核心资产前置过滤与小碎片 0 Token 阻断"""
    items = [
        # 1. 应用集合
        {"name": "NodeApp", "path": "D:/NodeApp", "is_directory_collective": True, "size": 1000},
        # 2. 安装包
        {"name": "setup.exe", "path": "D:/setup.exe", "ext": ".exe", "size": 2000},
        {"name": "installer.msi", "path": "D:/installer.msi", "ext": ".msi", "size": 3000},
        # 3. 镜像归档
        {"name": "windows.iso", "path": "D:/windows.iso", "ext": ".iso", "size": 4000},
        {"name": "backup.7z", "path": "D:/backup.7z", "ext": ".7z", "size": 5000},
        # 4. 办公高价值文档
        {"name": "经控报表.xlsx", "path": "D:/经控报表.xlsx", "ext": ".xlsx", "size": 6000},
        {"name": "合同.pdf", "path": "D:/合同.pdf", "ext": ".pdf", "size": 7000},
        # 5. 移动端应用
        {"name": "wechat.apk", "path": "D:/wechat.apk", "ext": ".apk", "size": 8000},
        # 0 Token 阻断小碎片 (不应进入 AI 研判队列)
        {"name": "temp.tmp", "path": "D:/temp.tmp", "ext": ".tmp", "size": 10},
        {"name": "debug.log", "path": "D:/debug.log", "ext": ".log", "size": 20},
        {"name": "system.dll", "path": "D:/system.dll", "ext": ".dll", "size": 30},
        {"name": "core.sys", "path": "D:/core.sys", "ext": ".sys", "size": 40},
        {"name": "cache.dat", "path": "D:/cache.dat", "ext": ".dat", "size": 50},
    ]

    filtered = AIService.filter_high_value_assets_for_ai(items, max_items=50)

    # 验证只保留了高价值资产
    filtered_names = [f["name"] for f in filtered]
    assert "NodeApp" in filtered_names
    assert "setup.exe" in filtered_names
    assert "installer.msi" in filtered_names
    assert "windows.iso" in filtered_names
    assert "backup.7z" in filtered_names
    assert "经控报表.xlsx" in filtered_names
    assert "合同.pdf" in filtered_names
    assert "wechat.apk" in filtered_names

    # 验证小碎片被 100% 阻断 (0 Token 浪费)
    assert "temp.tmp" not in filtered_names
    assert "debug.log" not in filtered_names
    assert "system.dll" not in filtered_names
    assert "core.sys" not in filtered_names
    assert "cache.dat" not in filtered_names


def test_analyze_directory_or_app_with_ai_fallback(tmp_path):
    """测试单个应用研判接口的输出结构与本地启发式保底"""
    demo_dir = tmp_path / "Everything"
    demo_dir.mkdir()
    (demo_dir / "Everything.exe").write_bytes(b"0" * 100)

    res = AIService.analyze_directory_or_app_with_ai(
        base_url="",
        api_key="",
        model="gpt-4o-mini",
        target_path=str(demo_dir)
    )

    assert "official_name" in res
    assert res["official_name"] == "Everything"
    assert "suggested_category" in res
    assert "risk_level" in res
    assert "action_recommendation" in res


def test_ui_components_ai_actions(tmp_path):
    """测试 PromoteCollectiveDialog 与 FileDataGridWidget 的 AI 研判交互与信号"""
    app = QApplication.instance() or QApplication([])

    target_file = tmp_path / "dummy.txt"
    target_file.write_text("dummy")

    # 1. 验证 PromoteCollectiveDialog 中具备 AI 推荐按键
    dlg = PromoteCollectiveDialog(str(target_file))
    assert hasattr(dlg, "btn_ai_suggest")
    assert dlg.btn_ai_suggest is not None

    # 2. 验证 FileDataGridWidget 具备 ai_insight_requested 信号
    grid = FileDataGridWidget(is_selectable=True)
    assert hasattr(grid, "ai_insight_requested")
