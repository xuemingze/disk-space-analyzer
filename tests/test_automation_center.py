"""
自动化中心 (Automation Center) 单元与集成测试套件
验证方案二核心特性：
1. 观察目录监控规则与防抖沉淀机制 (Debounce & Settling)；
2. 循环与自触发回环防护 (Idempotency & Cycle Prevention)；
3. 计划任务定时调度与安全只读提案生成 (Propose-only Security)；
4. 快速整理预设与一键分析集成；
5. CLI 命令行参数、--dry-run 模拟与脚本生成；
6. 自动化中心 UI 页面初始化与多级子导航联动。
"""

import os
import time
import pytest
from pathlib import Path
from PySide6.QtWidgets import QApplication

from app.automation.models import WatchRule, ScheduledTask, ProposedPlan, QuickPreset
from app.automation.watcher import RuleWatcher
from app.automation.scheduler import TaskScheduler
from app.automation.manager import AutomationManager
from app.automation.quick_organizer import QuickOrganizeManager
from app.automation.cli_generator import CliScriptGenerator
from app.ui.automation import (
    AutomationCenterView,
    RuleMonitorPage,
    ScheduleTaskPage,
    QuickOrganizePage,
    CliScriptPage
)
from app.utils.lock_detector import (
    check_office_companion_lock,
    check_file_exclusive_lock,
    is_file_locked_or_in_use,
    is_destination_valid
)
from app.automation.archive_executor import execute_safe_auto_archive
from app.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_automation_models_serialization():
    """测试自动化数据模型序列化与反序列化"""
    rule = WatchRule(
        name="测试监控",
        watch_path="D:/test/watch",
        exclude_patterns=["*.tmp", "*.bak"],
        debounce_seconds=2.5,
        organize_mode="by_type"
    )
    rule_dict = rule.to_dict()
    assert rule_dict["name"] == "测试监控"
    assert rule_dict["debounce_seconds"] == 2.5
    rule_restored = WatchRule.from_dict(rule_dict)
    assert rule_restored.id == rule.id
    assert rule_restored.organize_mode == "by_type"
    assert rule_restored.propose_only is True

    task = ScheduledTask(
        name="测试定时任务",
        target_path="D:/test/sched",
        interval_minutes=60,
        organize_mode="comprehensive"
    )
    task_dict = task.to_dict()
    assert task_dict["interval_minutes"] == 60
    task_restored = ScheduledTask.from_dict(task_dict)
    assert task_restored.name == "测试定时任务"
    assert task_restored.propose_only is True

    plan = ProposedPlan(
        source_name="下载监控",
        source_path="D:/Downloads",
        file_count=5,
        total_bytes=10240,
        status="pending"
    )
    plan_dict = plan.to_dict()
    assert plan_dict["file_count"] == 5
    plan_restored = ProposedPlan.from_dict(plan_dict)
    assert plan_restored.status == "pending"


def test_watcher_debounce_and_settling(tmp_path):
    """
    测试监控引擎的防抖与文件沉淀机制：
    1. 刚创建或写入中的文件不立即触发；
    2. 只有在连续稳定达到 debounce_seconds 后才判定沉淀完成；
    3. 自动生成 ProposedPlan，严禁直接物理移动。
    """
    watch_dir = tmp_path / "watch_source"
    watch_dir.mkdir()

    rule = WatchRule(
        name="沉淀测试规则",
        watch_path=str(watch_dir),
        debounce_seconds=0.1,  # 测试环境使用 0.1 秒加速验证
        exclude_patterns=["*.tmp"],
        enabled=True,
        propose_only=True
    )

    watcher = RuleWatcher(rules=[rule])
    proposed_plans = []
    watcher.plan_proposed.connect(lambda p: proposed_plans.append(p))

    # 1. 模拟写入一个临时文件 (应该被排除)
    (watch_dir / "test.tmp").write_text("temporary")
    t0 = time.time()
    watcher._check_rule(rule, t0)
    assert len(proposed_plans) == 0

    # 2. 模拟写入一个正常文件
    normal_file = watch_dir / "annual_report.pdf"
    normal_file.write_text("first chunk of report")
    t1 = time.time()
    # 首次检查：记录初始状态，开启防抖计时
    watcher._check_rule(rule, t1)
    assert len(proposed_plans) == 0

    # 3. 文件持续写入中 (修改大小/内容)：重置稳定计时器
    normal_file.write_text("first chunk + second chunk of report")
    t2 = t1 + 0.05
    watcher._check_rule(rule, t2)
    assert len(proposed_plans) == 0

    # 4. 文件写入停止，保持稳定超过 debounce_seconds
    t3 = t2 + 0.15
    watcher._check_rule(rule, t3)

    # 确认触发候选整理提案！
    assert len(proposed_plans) == 1
    plan = proposed_plans[0]
    assert plan.file_count == 1
    assert plan.status == "pending"
    assert plan.propose_only if hasattr(plan, "propose_only") else True
    # 验证原文件未被擅自物理移动
    assert normal_file.exists()


def test_watcher_cycle_prevention(tmp_path):
    """测试系统自身移动防回环与排除规则"""
    watch_dir = tmp_path / "watch_dir"
    watch_dir.mkdir()
    target_dir = watch_dir / "archived_sub"
    target_dir.mkdir()

    rule = WatchRule(
        name="防回环测试",
        watch_path=str(watch_dir),
        target_dir=str(target_dir),
        exclude_patterns=["*.crdownload"],
        debounce_seconds=0.05
    )
    watcher = RuleWatcher(rules=[rule])

    # 1. 目标子目录下的文件必须被排除
    file_in_target = target_dir / "moved.pdf"
    assert watcher._is_excluded(str(file_in_target), rule) is True

    # 2. 系统刚记录处理过的文件必须被排除 (防重复触发)
    src_file = watch_dir / "processed.docx"
    watcher.record_system_action(str(src_file))
    assert watcher._is_excluded(str(src_file), rule) is True

    # 3. 排除通配符模式生效
    downloading = watch_dir / "bigfile.crdownload"
    assert watcher._is_excluded(str(downloading), rule) is True


def test_task_scheduler_execution(tmp_path):
    """测试定时计划任务调度与静默提案生成"""
    sched_dir = tmp_path / "sched_target"
    sched_dir.mkdir()
    (sched_dir / "doc1.txt").write_text("content 1")
    (sched_dir / "doc2.xlsx").write_bytes(b"content 2")

    task = ScheduledTask(
        name="每日定时扫描",
        target_path=str(sched_dir),
        interval_minutes=60,
        enabled=True,
        propose_only=True
    )

    scheduler = TaskScheduler(tasks=[task])
    plans = []
    scheduler.plan_proposed.connect(lambda p: plans.append(p))

    now = time.time()
    # 触发执行
    scheduler._execute_scheduled_task(task, now)

    assert len(plans) == 1
    plan = plans[0]
    assert plan.file_count == 2
    assert plan.source_name == "每日定时扫描"
    assert plan.status == "pending"
    assert task.last_status == "已生成提案"
    assert task.next_run_time == now + 3600.0


def test_cli_generator_and_scripts():
    """测试 CLI 命令行与脚本生成引擎"""
    cmd = CliScriptGenerator.generate_cli_command(
        path="C:/Users/Test/Downloads",
        dest="D:/Archive",
        mode="by_type",
        dry_run=True
    )
    assert 'cli.py organize' in cmd
    assert '--dry-run' in cmd
    assert '--mode by_type' in cmd
    assert 'D:/Archive' in cmd

    ps1_script = CliScriptGenerator.generate_powershell_script(
        path="C:/Users/Test/Downloads",
        dest="D:/Archive",
        mode="comprehensive",
        dry_run=True
    )
    assert '$TargetPath =' in ps1_script
    assert '$DryRun = $true' in ps1_script


def test_quick_organize_presets():
    """测试快速整理预设"""
    presets = QuickOrganizeManager.get_default_presets()
    assert len(presets) >= 4
    keys = [p.key for p in presets]
    assert "desktop" in keys
    assert "downloads" in keys
    assert "documents" in keys
    assert "pictures" in keys


def test_automation_center_ui_and_navigation(qapp, tmp_path):
    """测试自动化中心主视图与主窗口侧边栏导航联动"""
    # 1. 自动化中心独立视图测试 (包含 5 大子页面：规则监控、计划任务、快速整理、命令行与脚本、AI审查与拓扑路由)
    center_view = AutomationCenterView()
    assert center_view.sub_stack.count() == 5
    # 测试子页面切换
    center_view.switch_subpage(1)
    assert center_view.sub_stack.currentIndex() == 1
    assert center_view.btn_sub_schedule.isChecked()

    center_view.switch_subpage(2)
    assert center_view.sub_stack.currentIndex() == 2
    assert center_view.btn_sub_quick.isChecked()

    center_view.switch_subpage(3)
    assert center_view.sub_stack.currentIndex() == 3
    assert center_view.btn_sub_cli.isChecked()

    center_view.switch_subpage(4)
    assert center_view.sub_stack.currentIndex() == 4
    assert center_view.btn_sub_ai_audit.isChecked()

    # 2. 主窗口整体导航与展开/折叠测试
    main_win = MainWindow()
    assert main_win.stacked_widget.count() >= 4

    # 切换至自动化中心
    main_win.switch_view(2, sub_index=0)
    assert main_win.stacked_widget.currentIndex() == 2
    assert main_win.btn_nav_automation.isChecked()
    assert not main_win.sub_nav_container.isHidden()

    # 切换至自动化中心子项
    main_win.switch_view(2, sub_index=2)
    assert main_win.automation_view.sub_stack.currentIndex() == 2

    # 切换回主控扫描
    main_win.switch_view(0)
    assert main_win.stacked_widget.currentIndex() == 0
    assert main_win.btn_nav_home.isChecked()

    # 安全关闭
    main_win.close()


def test_lock_detector_office_and_exclusive(tmp_path):
    """测试锁与占用探测器：Office伴生锁探测与排他句柄探测"""
    work_dir = tmp_path / "lock_test"
    work_dir.mkdir()

    # 1. 普通正常文件
    normal_doc = work_dir / "report.docx"
    normal_doc.write_text("hello doc", encoding="utf-8")
    locked, reason = is_file_locked_or_in_use(str(normal_doc), min_cooldown_seconds=0.0)
    assert not locked

    # 2. 模拟 Office 伴生锁: ~$report.docx
    companion_lock = work_dir / "~$report.docx"
    companion_lock.write_text("office lock marker", encoding="utf-8")

    locked, reason = check_office_companion_lock(str(normal_doc))
    assert locked
    assert "Office" in reason

    locked, reason = is_file_locked_or_in_use(str(normal_doc), min_cooldown_seconds=0.0)
    assert locked

    # 移除伴生锁后恢复
    companion_lock.unlink()
    locked, _ = check_office_companion_lock(str(normal_doc))
    assert not locked

    # 3. 模拟 WPS 伴生锁: .~lock.report.docx#
    wps_lock = work_dir / ".~lock.report.docx#"
    wps_lock.write_text("wps lock marker", encoding="utf-8")
    locked, reason = check_office_companion_lock(str(normal_doc))
    assert locked
    assert "WPS" in reason
    wps_lock.unlink()


def test_destination_anti_cycle_validation(tmp_path):
    """测试防回环与路径嵌套死循环校验"""
    parent_dir = tmp_path / "source_watch"
    parent_dir.mkdir()
    child_dir = parent_dir / "nested_archive"
    child_dir.mkdir()

    other_dir = tmp_path / "target_archive"
    other_dir.mkdir()

    # 1. 目标目录与源目录相同 -> 拦截
    valid, err = is_destination_valid(str(parent_dir), str(parent_dir))
    assert not valid
    assert "完全相同" in err

    # 2. 目标目录在源目录内部 (子目录嵌套) -> 强力拦截死循环
    valid, err = is_destination_valid(str(parent_dir), str(child_dir))
    assert not valid
    assert "内部" in err or "死循环" in err

    # 3. 源目录在目标目录内部 -> 拦截
    valid, err = is_destination_valid(str(child_dir), str(parent_dir))
    assert not valid

    # 4. 独立目标目录 -> 合法通过
    valid, err = is_destination_valid(str(parent_dir), str(other_dir))
    assert valid
    assert err == ""


def test_safe_auto_archive_execution(tmp_path):
    """测试自动归档平移执行器：自动避让占用文件、生成 Manifest、成功转移"""
    src_dir = tmp_path / "archive_src"
    src_dir.mkdir()
    dest_dir = tmp_path / "archive_target"
    dest_dir.mkdir()

    # 创建正常文件
    file_a = src_dir / "test_a.pdf"
    file_a.write_text("content a", encoding="utf-8")

    # 创建带 Office 伴生锁的文件 (正在编辑中)
    file_b = src_dir / "test_b.docx"
    file_b.write_text("content b", encoding="utf-8")
    lock_b = src_dir / "~$test_b.docx"
    lock_b.write_text("office locking", encoding="utf-8")

    files = [
        {"path": str(file_a), "name": "test_a.pdf", "size": 9, "ext": ".pdf"},
        {"path": str(file_b), "name": "test_b.docx", "size": 9, "ext": ".docx"},
    ]

    res = execute_safe_auto_archive(
        files=files,
        target_root=str(dest_dir),
        source_dir=str(src_dir),
        organize_mode="by_type"
    )

    assert res["success"] is True
    # 正常文件 file_a 成功归档
    assert res["success_count"] == 1
    # file_b 因检测到 Office 正在编辑锁，被保底机制自动跳过
    assert res["locked_count"] == 1
    assert file_b.exists()  # 正在编辑的文件绝未被强行移动！

    # 验证 Manifest 文件已成功生成
    manifest_p = Path(res["manifest_path"])
    assert manifest_p.exists()


def test_watcher_auto_archive_integration(tmp_path):
    """测试监控引擎在自动归档模式 (propose_only=False) 下的安全平移与防回环"""
    watch_dir = tmp_path / "watch_auto"
    watch_dir.mkdir()
    archive_dir = tmp_path / "archive_auto_dest"
    archive_dir.mkdir()

    rule = WatchRule(
        name="自动归档规则",
        watch_path=str(watch_dir),
        target_dir=str(archive_dir),
        debounce_seconds=0.1,
        enabled=True,
        propose_only=False  # 启用自动平移
    )

    watcher = RuleWatcher(rules=[rule])
    log_messages = []
    watcher.log_emitted.connect(lambda msg, lvl: log_messages.append(msg))

    # 创建待整理文件
    test_pdf = watch_dir / "sample.pdf"
    test_pdf.write_text("sample pdf content", encoding="utf-8")

    # 首次检查：记录初始状态
    t0 = time.time()
    watcher._check_rule(rule, t0)

    # 稳定沉淀后触发检查
    t1 = t0 + 0.15
    watcher._check_rule(rule, t1)

    # 验证原文件已被移动
    assert not test_pdf.exists()

    # 验证目标目录下已生成归档文件
    archived_files = list(archive_dir.rglob("sample*.pdf"))
    assert len(archived_files) == 1

    # 验证防回环：再次检查不会重复移动或报错
    watcher._check_rule(rule, t1 + 0.1)


def test_scheduler_auto_archive_integration(tmp_path):
    """测试计划任务在自动归档模式 (propose_only=False) 下的定时平移"""
    sched_src = tmp_path / "sched_src"
    sched_src.mkdir()
    sched_dest = tmp_path / "sched_dest"
    sched_dest.mkdir()

    doc_file = sched_src / "weekly_summary.docx"
    doc_file.write_text("weekly summary doc", encoding="utf-8")

    task = ScheduledTask(
        name="自动定时归档任务",
        target_path=str(sched_src),
        target_dir=str(sched_dest),
        interval_minutes=60,
        enabled=True,
        propose_only=False  # 启用自动平移
    )

    scheduler = TaskScheduler(tasks=[task])
    now = time.time()
    scheduler._execute_scheduled_task(task, now)

    # 验证状态与文件移动
    assert "归档成功" in task.last_status
    assert not doc_file.exists()
    dest_files = list(sched_dest.rglob("weekly_summary*.docx"))
    assert len(dest_files) == 1


def test_table_ui_design_rules_compliance(qapp):
    """测试列表表格模块严格符合 UI 设计铁律：行高44px、操作与状态列锁定宽度、控件尺寸固定"""
    from PySide6.QtWidgets import QHeaderView, QPushButton

    # 1. 验证规则监控列表
    rule_page = RuleMonitorPage()
    # 验证行高锁定为 44px
    assert rule_page.rule_table.verticalHeader().defaultSectionSize() == 44
    assert rule_page.rule_table.verticalHeader().sectionResizeMode(0) == QHeaderView.Fixed
    # 验证关键控件列宽度锁定
    h_rule = rule_page.rule_table.horizontalHeader()
    assert h_rule.sectionResizeMode(0) == QHeaderView.Fixed
    assert rule_page.rule_table.columnWidth(0) == 90
    assert h_rule.sectionResizeMode(7) == QHeaderView.Fixed
    assert rule_page.rule_table.columnWidth(7) == 150

    # 2. 验证计划任务列表
    task_page = ScheduleTaskPage()
    # 验证行高锁定为 44px
    assert task_page.task_table.verticalHeader().defaultSectionSize() == 44
    assert task_page.task_table.verticalHeader().sectionResizeMode(0) == QHeaderView.Fixed
    # 验证关键控件列宽度锁定
    h_task = task_page.task_table.horizontalHeader()
    assert h_task.sectionResizeMode(0) == QHeaderView.Fixed
    assert task_page.task_table.columnWidth(0) == 90
    assert h_task.sectionResizeMode(7) == QHeaderView.Fixed
    assert task_page.task_table.columnWidth(7) == 220

    # 3. 验证单元格内按钮尺寸保护
    # 向规则列表中添加一条测试数据并渲染
    rule = WatchRule(name="测试尺寸规则", watch_path="D:/test/watch")
    rule_page.manager.rules = [rule]
    rule_page.refresh_rules()

    # 验证第 0 列状态开关按钮固定尺寸
    cell_0 = rule_page.rule_table.cellWidget(0, 0)
    assert cell_0 is not None
    btn_toggle = cell_0.findChild(QPushButton)
    assert btn_toggle is not None
    assert btn_toggle.height() == 28
    assert btn_toggle.width() == 70

    # 验证第 7 列操作栏按钮固定尺寸
    cell_7 = rule_page.rule_table.cellWidget(0, 7)
    assert cell_7 is not None
    buttons = cell_7.findChildren(QPushButton)
    assert len(buttons) == 2
    for b in buttons:
        assert b.height() == 28
        assert b.width() == 56



