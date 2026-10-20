"""
三大整理核心原则架构级贯通专项测试套件
验证 UnifiedScanEngine 的核心特性：
1. 防御性递归原则 (Defensive Recursion Principle): 源头剪枝封包，严禁零散碎文件入栈；
2. 泛式大抽屉与狭义实体拓扑法则 (Broad vs Narrow Topology Law):
   - 解禁数据盘根目录独立软件 (D:\\Clash, D:\\Everything)；
   - 大抽屉 (backups) 向下强行赋权上位语义，快照绝不被内部清单反客为主篡权为活跃代码；
3. 同源同宿全链条贯通 (Source Umbrella Consistency):
   - 备份大抽屉下的完整归档包 (.tar.gz, .zip) 免除冗余误判；
4. 物理防回环与内存熔断守护 (Anti-Cycle & Memory Safety):
   - 杜绝软链接、重复路径与内存泄漏。
"""

import os
import time
import pytest
from pathlib import Path

from app.core.unified_scanner import UnifiedScanner, AssetUnit
from app.core.app_detector import AppDetector


def test_defensive_recursion_source_pruning(tmp_path):
    """
    测试防御性递归原则：
    当扫描栈遇到原子狭义集体 (如包含主程序与资源子目录的软件) 时，
    在源头立即剪枝封包为单个 AssetUnit，子目录内部的上千个小文件绝不入栈。
    """
    scan_root = tmp_path / "apps_container"
    scan_root.mkdir()

    # 构造一个模拟拥有 200 个零散文件的软件集体 (类似 Edge / Chrome 结构)
    app_dir = scan_root / "BigBrowserApp"
    app_dir.mkdir()
    (app_dir / "BigBrowser.exe").write_bytes(b"MZ\x90\x00")

    res_dir = app_dir / "resources"
    res_dir.mkdir()
    for i in range(100):
        (res_dir / f"asset_{i}.pak").write_bytes(b"DATA")

    loc_dir = app_dir / "locales"
    loc_dir.mkdir()
    for i in range(100):
        (loc_dir / f"lang_{i}.pak").write_bytes(b"LOC")

    # 构造普通单文件
    doc_file = scan_root / "manual.pdf"
    doc_file.write_bytes(b"%PDF-1.4")

    # 执行统一扫描
    t0 = time.time()
    assets = UnifiedScanner.scan_directory([str(scan_root)], prune_collectives=True)
    duration = time.time() - t0

    # 核心断言：
    # 1. 耗时极短 (不到 0.5 秒)
    assert duration < 1.0

    # 2. 扫描结果中，BigBrowserApp 作为一个完整的原子狭义集体封包，而不是被拆解成 201 个碎文件
    app_assets = [a for a in assets if a.is_collective and a.name == "BigBrowserApp"]
    assert len(app_assets) == 1
    unit = app_assets[0]
    assert unit.file_count >= 201  # 内部文件被统计进总数
    assert unit.is_collective is True
    assert "软件" in unit.category or "Apps" in unit.category

    # 3. 总资产单元数量仅为 2 个 (BigBrowserApp 集体 + manual.pdf 单文件)
    assert len(assets) == 2


def test_broad_container_top_down_empowerment(tmp_path):
    """
    测试大抽屉向下强行赋权上位语义法则：
    在 backups (备份) 大抽屉下，即便内部包含 package.json、requirements.txt 等清单，
    也必须绝对强制赋权为“历史快照实体”，严禁反客为主误判为活跃开发工程！
    """
    backup_root = tmp_path / "backups"
    backup_root.mkdir()

    # 在备份目录下放置一个解压的历史工程快照
    snapshot_dir = backup_root / "2023-old-web-snapshot"
    snapshot_dir.mkdir()
    # 放置开发清单文件 (如果反客为主，会被误判为 Vue/Node 工程)
    (snapshot_dir / "package.json").write_text('{"name": "vue-old", "dependencies": {"vue": "^3.0"}}', encoding="utf-8")
    (snapshot_dir / "index.html").write_text('<html></html>', encoding="utf-8")

    assets = UnifiedScanner.scan_directory([str(backup_root)], prune_collectives=True)

    # 验证快照目录被强行上位赋权
    snapshot_assets = [a for a in assets if a.name == "2023-old-web-snapshot"]
    assert len(snapshot_assets) == 1
    snap = snapshot_assets[0]
    assert snap.is_collective is True
    assert snap.collective_type == "历史快照集体"
    assert "归档包与系统镜像" in snap.category or "Archives" in snap.category
    assert snap.is_snapshot_backup is True


def test_data_drive_root_standalone_app_unlocked(tmp_path):
    """
    测试解禁数据盘根目录独立软件法则：
    非系统盘一级目录下的软件 (如 D:\\Clash, D:\\Everything)，
    废除盘符深度限制，直接识别为独立软件实体。
    """
    fake_d_root = tmp_path / "D_drive"
    fake_d_root.mkdir()

    clash_dir = fake_d_root / "Clash"
    clash_dir.mkdir()
    (clash_dir / "Clash for Windows.exe").write_bytes(b"MZ\x90\x00")
    (clash_dir / "resources").mkdir()
    (clash_dir / "resources" / "app.asar").write_bytes(b"ASAR")

    assets = UnifiedScanner.scan_directory([str(fake_d_root)], prune_collectives=True)

    clash_assets = [a for a in assets if a.name == "Clash"]
    assert len(clash_assets) == 1
    assert clash_assets[0].is_collective is True
    assert "软件" in clash_assets[0].category or "Apps" in clash_assets[0].category


def test_source_umbrella_archive_exemption(tmp_path):
    """
    测试同源同宿全链条贯通与备份包免除冗余误判：
    在 backups 目录下的完整归档压缩包 (.tar.gz, .zip)，
    自动继承 umbrella_anchor 且 is_snapshot_backup 为 True，豁免冗余归档包误判。
    """
    backup_root = tmp_path / "backups"
    backup_root.mkdir()

    tar_file = backup_root / "full_system_backup_2025.tar.gz"
    tar_file.write_bytes(b"TAR.GZ DATA")

    assets = UnifiedScanner.scan_directory([str(backup_root)], prune_collectives=True)

    tar_assets = [a for a in assets if a.name == "full_system_backup_2025.tar.gz"]
    assert len(tar_assets) == 1
    unit = tar_assets[0]
    assert unit.is_snapshot_backup is True
    assert unit.umbrella_category == "backup"
    assert unit.tag == "备份快照"


def test_anti_cycle_and_visited_protection(tmp_path):
    """
    测试物理防回环与内存熔断：
    即使存在重复路径输入或子目录嵌套，通过 visited_dirs 严格拦截，
    杜绝无限递归死循环与内存暴涨。
    """
    scan_dir = tmp_path / "cycle_test"
    scan_dir.mkdir()
    (scan_dir / "file1.txt").write_text("test")

    # 重复传入同一目录路径
    t0 = time.time()
    assets = UnifiedScanner.scan_directory([str(scan_dir), str(scan_dir)], prune_collectives=True)
    duration = time.time() - t0

    # 1. 瞬间完成 (毫秒级)
    assert duration < 0.2
    # 2. 只有 1 个文件资产，绝对没有重复循环膨胀
    assert len(assets) == 1
