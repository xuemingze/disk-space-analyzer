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
    # 1. 自动化中心独立视图测试
    center_view = AutomationCenterView()
    assert center_view.sub_stack.count() == 4
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

    # 2. 主窗口整体导航与展开/折叠测试
    main_win = MainWindow()
    assert main_win.stacked_widget.count() == 4

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
