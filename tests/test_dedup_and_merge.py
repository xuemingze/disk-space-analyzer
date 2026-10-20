"""
tests/test_dedup_and_merge.py
方案三「文件查重与融合」专项单元测试套件
涵盖：三阶哈希漏斗、完全重复组聚类、同名异内容冲突检测、排他锁安全跳过、跨盘原子融合与可回滚 Manifest 凭据、UI 铁律与主窗口导航
"""
import os
import time
import shutil
import tempfile
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication, QHeaderView, QPushButton, QRadioButton

from app.dedup.models import (
    DedupScanConfig,
    DedupFileItem,
    DedupGroup,
    CollisionItem,
    MergeAction,
    DedupScanResult
)
from app.dedup.hasher import DedupHasher
from app.dedup.detector import DedupDetector
from app.dedup.executor import MergeExecutor
from app.dedup.task_config_manager import DedupTaskConfigManager


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_hasher_small_and_large_files(tmp_path):
    """测试小文件与大文件（稀疏采样）哈希计算"""
    f_small = tmp_path / "small.txt"
    f_small.write_text("Hello World", encoding="utf-8")

    stat_sm = f_small.stat()
    s_hash_sm = DedupHasher.compute_sample_hash(str(f_small), stat_sm.st_size, stat_sm.st_mtime, algorithm="sha256")
    f_hash_sm = DedupHasher.compute_full_hash(str(f_small), stat_sm.st_size, stat_sm.st_mtime, algorithm="sha256")

    assert s_hash_sm is not None
    assert f_hash_sm is not None
    # 小于 64KB 时 sample_hash 与 full_hash 应该完全相同
    assert s_hash_sm == f_hash_sm

    # 大文件 (>64KB)
    f_large1 = tmp_path / "large1.dat"
    content = b"A" * 70000
    f_large1.write_bytes(content)

    f_large2 = tmp_path / "large2.dat"
    # 前后一样，但中间不同
    content2 = bytearray(b"A" * 70000)
    mid_offset = (70000 - 8192) // 2
    content2[mid_offset + 10] = ord(b"Z")
    f_large2.write_bytes(content2)

    stat_l1 = f_large1.stat()
    stat_l2 = f_large2.stat()

    sh1 = DedupHasher.compute_sample_hash(str(f_large1), stat_l1.st_size, stat_l1.st_mtime)
    sh2 = DedupHasher.compute_sample_hash(str(f_large2), stat_l2.st_size, stat_l2.st_mtime)

    # 采样哈希能立即区分出中间修改！
    assert sh1 != sh2


def test_dedup_detector_three_stages_and_collisions(tmp_path):
    """
    测试 DedupDetector 多源目录扫描：
    1. 相同内容完全重复
    2. 同名不同内容 (冲突)
    3. 独立唯一文件
    """
    src1 = tmp_path / "Source1"
    src2 = tmp_path / "Source2"
    src1.mkdir()
    src2.mkdir()

    # 1. 完全重复项: doc1.txt 在两个源目录中内容相同
    (src1 / "doc1.txt").write_text("Unique duplicated content 12345", encoding="utf-8")
    (src2 / "doc1.txt").write_text("Unique duplicated content 12345", encoding="utf-8")

    # 2. 同名异内容冲突项: config.json 在两个源目录中内容不同
    (src1 / "config.json").write_text('{"env": "prod"}', encoding="utf-8")
    (src2 / "config.json").write_text('{"env": "dev", "debug": true}', encoding="utf-8")

    # 3. 独立唯一文件: only_in_src1.txt, only_in_src2.txt
    (src1 / "only_in_src1.txt").write_text("I am lonely 1", encoding="utf-8")
    (src2 / "only_in_src2.txt").write_text("I am lonely 2", encoding="utf-8")

    # 确保度过冷却期
    past_time = time.time() - 10.0
    for p in [src1 / "doc1.txt", src2 / "doc1.txt", src1 / "config.json", src2 / "config.json", src1 / "only_in_src1.txt", src2 / "only_in_src2.txt"]:
        os.utime(str(p), (past_time, past_time))

    config = DedupScanConfig(
        source_dirs=[str(src1), str(src2)],
        min_file_size=1,
        dedup_keep_preference="keep_primary"
    )

    detector = DedupDetector(config)
    result = detector.scan_and_analyze()

    assert result.total_files == 6
    assert result.total_duplicates_count == 1
    assert len(result.duplicate_groups) == 1

    dup_group = result.duplicate_groups[0]
    assert dup_group.duplicate_count == 1
    # 验证推荐保留项归属于主源目录 Source1
    assert str(src1 / "doc1.txt") == dup_group.recommended_keep_path

    # 验证同名冲突项
    assert len(result.collisions) == 1
    col = result.collisions[0]
    assert col.rel_path == "config.json"
    assert len(col.files) == 2

    # 验证唯一文件数量
    unique_paths = [f.path for f in result.unique_files]
    assert any("only_in_src1.txt" in p for p in unique_paths)
    assert any("only_in_src2.txt" in p for p in unique_paths)


def test_merge_executor_plan_and_execution(tmp_path):
    """
    测试 MergeExecutor 融合计划构建、执行与 Manifest 凭据生成
    """
    src1 = tmp_path / "SrcA"
    src2 = tmp_path / "SrcB"
    target = tmp_path / "TargetMerged"
    iso = tmp_path / "Isolation"
    src1.mkdir()
    src2.mkdir()
    target.mkdir()
    iso.mkdir()

    # 准备文件
    (src1 / "common.txt").write_text("Identical text", encoding="utf-8")
    (src2 / "common.txt").write_text("Identical text", encoding="utf-8")
    (src1 / "clash.txt").write_text("version 1", encoding="utf-8")
    (src2 / "clash.txt").write_text("version 2", encoding="utf-8")
    (src2 / "solo.txt").write_text("only solo", encoding="utf-8")

    past_time = time.time() - 10.0
    for p in [src1 / "common.txt", src2 / "common.txt", src1 / "clash.txt", src2 / "clash.txt", src2 / "solo.txt"]:
        os.utime(str(p), (past_time, past_time))

    config = DedupScanConfig(
        source_dirs=[str(src1), str(src2)],
        target_dir=str(target),
        isolation_dir=str(iso),
        dedup_keep_preference="keep_primary"
    )

    detector = DedupDetector(config)
    scan_res = detector.scan_and_analyze()

    # 1. 构建计划
    actions = MergeExecutor.build_merge_plan(
        scan_result=scan_res,
        target_dir=str(target),
        isolation_dir=str(iso),
        collision_strategy="rename"
    )

    # 校验计划
    valid, errors = MergeExecutor.validate_plan(actions, str(target), [str(src1), str(src2)])
    assert valid is True
    assert len(errors) == 0

    # 检查动作分布
    types = [a.action_type for a in actions]
    assert "keep" in types
    assert "isolate_archive" in types
    assert "rename_merge" in types
    assert "move_merge" in types

    # 2. 执行计划
    exec_res = MergeExecutor.execute_plan(actions, str(target))

    assert exec_res["failed"] == 0
    assert exec_res["success"] > 0
    manifest_p = Path(exec_res["manifest_file"])
    assert manifest_p.exists()

    # 验证目标目录中的文件落位
    target_files = [f.name for f in target.glob("**/*") if f.is_file()]
    assert any("solo.txt" in name for name in target_files)
    # 冲突文件带源目录名称标识重命名
    assert any("clash_from_Src" in name for name in target_files)

    # 验证隔离目录中有重复冗余项
    iso_files = list(iso.glob("**/*"))
    assert len(iso_files) > 0


def test_merge_executor_topology_validation_blocks_recursion(tmp_path):
    """测试防止源目录与目标目录嵌套包含的拓扑拦截"""
    src = tmp_path / "RootSource"
    src.mkdir()
    target_inside = src / "SubMerged"  # 嵌套在源目录内部，非法！
    target_inside.mkdir()

    actions = [MergeAction(action_type="move_merge", source_path=str(src / "a.txt"), target_path=str(target_inside / "a.txt"))]
    valid, errors = MergeExecutor.validate_plan(actions, str(target_inside), [str(src)])

    assert valid is False
    assert any("拓扑冲突" in e or "嵌套" in e or "相同" in e for e in errors)


def test_table_ui_design_rules_in_dedup(qapp, tmp_path):
    """
    验证方案三所有表格严格遵循 UI 铁律:
    - 垂直表头行高锁死 44px (defaultSectionSize == 44 + Fixed)
    - 列宽明确分层
    - 操作栏与按钮独立包装，固定 28px 高度保底
    """
    from app.ui.dedup.directory_select_step import DirectorySelectStep
    from app.ui.dedup.review_table_step import ReviewTableStep

    # 1. 验证步骤 1: 源目录表格
    step1 = DirectorySelectStep()
    table_src = step1.table_sources
    assert table_src.verticalHeader().defaultSectionSize() == 44
    assert table_src.verticalHeader().sectionResizeMode(0) == QHeaderView.Fixed
    assert table_src.horizontalHeader().sectionResizeMode(0) == QHeaderView.Fixed
    assert table_src.columnWidth(0) == 60
    assert table_src.columnWidth(2) == 100

    # 添加一行并验证按钮包装尺寸
    step1.source_dirs = [str(tmp_path / "demo")]
    step1._refresh_source_table()
    cell_act = table_src.cellWidget(0, 2)
    assert cell_act is not None
    btn_del = cell_act.findChild(QPushButton)
    assert btn_del is not None
    assert btn_del.height() == 28
    assert btn_del.width() == 56

    # 2. 验证步骤 3: 重复文件与冲突表格
    step3 = ReviewTableStep()
    assert step3.table_dups.verticalHeader().defaultSectionSize() == 44
    assert step3.table_dups.verticalHeader().sectionResizeMode(0) == QHeaderView.Fixed
    assert step3.table_collisions.verticalHeader().defaultSectionSize() == 44
    assert step3.table_collisions.verticalHeader().sectionResizeMode(0) == QHeaderView.Fixed

    # 模拟数据填充并验证单选保留项按钮高度
    f1 = DedupFileItem(path=str(tmp_path / "a.txt"), name="a.txt", rel_path="a.txt", size=100, mtime=1000.0, source_dir="D:/src")
    f2 = DedupFileItem(path=str(tmp_path / "b.txt"), name="b.txt", rel_path="b.txt", size=100, mtime=1000.0, source_dir="D:/src2")
    grp = DedupGroup(group_id="GRP_001", size=100, full_hash="hash123", items=[f1, f2], recommended_keep_path=f1.path)
    res = DedupScanResult(total_files=2, total_bytes=200, duplicate_groups=[grp], scanned_sources=["D:/src", "D:/src2"])
    step3.load_scan_result(res)

    # 验证单选保留项被独立容器包装且高度为 28px
    cell_keep = step3.table_dups.cellWidget(0, 1)
    assert cell_keep is not None
    radio = cell_keep.findChild(QRadioButton)
    assert radio is not None
    assert radio.height() == 28


def test_main_window_dedup_navigation(qapp):
    """验证主窗口导航栏注册了查重与融合视图，并支持流畅切换"""
    from app.ui.main_window import MainWindow
    from app.ui.dedup import DedupMergeView

    win = MainWindow()
    assert hasattr(win, "dedup_view")
    assert isinstance(win.dedup_view, DedupMergeView)

    # 切换到查重融合视图 (索引 3)
    win.switch_view(3)
    assert win.stacked_widget.currentIndex() == 3
    assert win.btn_nav_dedup.isChecked()

    # 切换到自动化中心 (索引 2)
    win.switch_view(2, sub_index=0)
    assert win.stacked_widget.currentIndex() == 2
    assert win.btn_nav_automation.isChecked()

    # 切换回首页 (索引 0)
    win.switch_view(0)
    assert win.stacked_widget.currentIndex() == 0


def test_task_config_persistence(tmp_path, monkeypatch):
    """验证查重配置管理器持久化"""
    cfg_file = tmp_path / "test_dedup_cfg.json"
    monkeypatch.setattr("app.dedup.task_config_manager.CONFIG_FILE_PATH", cfg_file)

    cfg = DedupScanConfig(
        source_dirs=["D:/src_a", "D:/src_b"],
        target_dir="D:/merged",
        isolation_dir="D:/iso",
        dedup_keep_preference="keep_newest"
    )
    saved = DedupTaskConfigManager.save_config(cfg)
    assert saved is True
    assert cfg_file.exists()

    loaded = DedupTaskConfigManager.load_config()
    assert loaded.source_dirs == ["D:/src_a", "D:/src_b"]
    assert loaded.target_dir == "D:/merged"
    assert loaded.isolation_dir == "D:/iso"
    assert loaded.dedup_keep_preference == "keep_newest"
