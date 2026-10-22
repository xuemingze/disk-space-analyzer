"""
tests/test_installer_pool_and_broad_container.py
针对“下载/安装包池”与“独立软件单体”辨识规则的专项回归测试

覆盖以下场景：
1. 广义大抽屉与系统大容器词典识别：安装包、软件安装包、安装程序等；
2. 系统大容器保护：下载、我的下载、安装包等绝对不被作为单体软件集体剪枝；
3. 独立软件 vs 安装包汇总池辨识：防止多个独立安装包散落被误判为单体软件集体；
4. 真实独立软件与绿色软件保全：Everything(同名exe)、Typora(伴生资源库)、PyInstaller(_internal) 依然 100% 正确识别为集体；
5. 根目录扫描展开验证：扫描安装包目录时，底层所有安装程序作为独立资产单元逐一扫描出库，绝不粗暴整包剪枝。
"""

import os
import pytest
from app.core.app_detector import AppDetector
from app.core.unified_scanner import UnifiedScanner


# ==============================================================================
# 1. 广义大抽屉词典与系统大容器测试
# ==============================================================================
@pytest.mark.parametrize("container_name, expected_broad_key", [
    ("安装包", "app"),
    ("软件安装包", "app"),
    ("安装程序", "app"),
    ("软件下载", "app"),
    ("installers", "app"),
    ("packages", "app"),
    ("setup", "app"),
])
def test_broad_container_installer_keywords(container_name, expected_broad_key):
    res = AppDetector.match_broad_container(container_name)
    assert res is not None, f"'{container_name}' should be recognized as a broad container"
    key, info = res
    assert key == expected_broad_key


@pytest.mark.parametrize("sys_container_name", [
    "下载", "我的下载", "下载内容", "downloads", "download", "临时下载"
])
def test_system_download_containers_not_collective(tmp_path, sys_container_name):
    d = tmp_path / sys_container_name
    d.mkdir()
    (d / "some_setup.exe").write_bytes(b"MZfake" * 50)
    (d / "another.exe").write_bytes(b"MZfake" * 50)
    assert AppDetector.detect_directory_collective(str(d)) is None


# ==============================================================================
# 2. 安装包池与多可执行程序汇总排除测试
# ==============================================================================
def test_installers_directory_is_not_collective(tmp_path):
    """
    测试：用户安装包目录 (如 D:\安装包，含有 15 个不同的软件安装包)
    绝对不能被判定为单个不可拆分的独立软件实体！
    """
    inst_dir = tmp_path / "安装包"
    inst_dir.mkdir()

    # 模拟常见的软件安装包
    installer_names = [
        "WeChatSetup.exe", "ChromeSetup.exe", "BaiduNetdisk_7.15.exe",
        "Python-3.12.exe", "VSCodeUserSetup-x64.exe", "Bandizip_Setup.exe",
        "7z2301-x64.exe", "Git-2.43.0-64-bit.exe"
    ]
    for name in installer_names:
        (inst_dir / name).write_bytes(b"MZfakeinstaller" * 50)

    # 1. AppDetector 必须判定为 None (不是软件集体)
    result = AppDetector.detect_directory_collective(str(inst_dir))
    assert result is None, f"Expected None for installers pool, but got {result}"


def test_generic_folder_with_multiple_loose_exes_not_collective(tmp_path):
    """
    测试：即使目录名是通用名称 (如 D:\工具汇总)，若只有多个独立可执行程序而无配套运行时与库，
    必须判定为普通散落文件，绝不能因 len(exe_files) > 1 误打包！
    """
    loose_dir = tmp_path / "工具汇总"
    loose_dir.mkdir()

    for i in range(5):
        (loose_dir / f"tool_{i}.exe").write_bytes(b"MZfaketool" * 50)

    result = AppDetector.detect_directory_collective(str(loose_dir))
    assert result is None, f"Loose exes without runtime should not be a collective, got {result}"


# ==============================================================================
# 3. 真实独立软件与绿色软件特征识别保全测试 (确保零回退)
# ==============================================================================
def test_real_portable_apps_still_recognized(tmp_path):
    """
    确保真实绿色独立软件依然 100% 正确识别：
    1. Everything (主程序与目录名同名)
    2. Typora (具备 companion resources 文件夹)
    3. Python 独立打包应用 (具备 _internal 运行时)
    """
    # 1. Everything 目录
    everything_dir = tmp_path / "Everything"
    everything_dir.mkdir()
    (everything_dir / "Everything.exe").write_bytes(b"MZfakeexe" * 50)
    (everything_dir / "Everything.lng").write_bytes(b"fakelang" * 10)

    res_everything = AppDetector.detect_directory_collective(str(everything_dir))
    assert res_everything is not None
    assert res_everything.get("is_collective") is True
    assert "Everything" in res_everything.get("software_name", "")

    # 2. Typora 目录 (伴生 resources 文件夹)
    typora_dir = tmp_path / "Typora"
    typora_dir.mkdir()
    (typora_dir / "Typora.exe").write_bytes(b"MZfakeexe" * 50)
    (typora_dir / "resources").mkdir()
    (typora_dir / "resources" / "app.asar").write_bytes(b"fakeasar" * 50)

    res_typora = AppDetector.detect_directory_collective(str(typora_dir))
    assert res_typora is not None
    assert res_typora.get("is_collective") is True

    # 3. PyInstaller 独立应用 (伴生 _internal)
    pyapp_dir = tmp_path / "MyClientApp"
    pyapp_dir.mkdir()
    (pyapp_dir / "client.exe").write_bytes(b"MZfakeexe" * 50)
    (pyapp_dir / "_internal").mkdir()
    (pyapp_dir / "_internal" / "python310.dll").write_bytes(b"fakedll" * 50)

    res_pyapp = AppDetector.detect_directory_collective(str(pyapp_dir))
    assert res_pyapp is not None
    assert res_pyapp.get("is_collective") is True


# ==============================================================================
# 4. 根目录扫描展开与独立资产单元生成测试 (还原用户报障场景)
# ==============================================================================
def test_scan_installers_root_produces_individual_assets(tmp_path):
    """
    还原用户报障场景：用户扫描 D:\安装包 (含有 25 个独立安装程序与镜像)
    扫描器必须将其作为 25 个独立单项资产扫描出库，绝不允许在深度 0 剪枝封存为 1 个集体！
    """
    inst_root = tmp_path / "安装包"
    inst_root.mkdir()

    # 创建 25 个独立的安装包与归档包
    for i in range(25):
        ext = ".exe" if i % 2 == 0 else ".zip"
        (inst_root / f"software_{i}_installer{ext}").write_bytes(b"MZorPKheader" * 100)

    # 运行扫描
    assets = UnifiedScanner.scan_directory([str(inst_root)])

    # 验证资产单元数量等于 25
    assert len(assets) == 25, f"Expected 25 independent assets, got {len(assets)}"

    # 验证每一个都是独立资产单元，is_collective 为 False
    assert all(not a.is_collective for a in assets), "All scanned installers must be standalone assets, not collective"

    # 验证归类为软件安装与程序
    for a in assets:
        assert "软件安装" in a.category or "归档" in a.category
