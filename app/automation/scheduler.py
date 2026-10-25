"""
自动化计划任务引擎 (Scheduled Tasks Engine)
特点：
1. 定时检查与调度计划任务；
2. 周期性扫描目标目录并自动生成整理候选方案；
3. 统一接入 AutomationPlanResolver (主路由表优先、PE元数据仲裁、在线 AI 核心编排、主动纠偏与分析即沉淀)；
4. 遵循安全准则：初期只生成整理计划/预览，或经由 AI 安全门禁审核后执行自动归档；
5. 记录每次执行状态、上次运行时间与下次触发时间。
"""

import os
import time
from typing import List, Dict, Any, Optional

from PySide6.QtCore import QThread, Signal

from app.automation.models import ScheduledTask, ProposedPlan
from app.automation.archive_executor import execute_safe_auto_archive
from app.automation.plan_resolver import AutomationPlanResolver
from app.core.unified_scanner import UnifiedScanner, AssetUnit
from app.core.app_detector import AppDetector
from app.core.organize_models import OrganizeOptions, OrganizeMode
from app.utils.lock_detector import is_file_locked_or_in_use
from app.utils.file_helper import format_size
from app.utils.logger import app_logger


class TaskScheduler(QThread):
    """
    后台计划任务调度工作线程
    """
    plan_proposed = Signal(object)       # 发射 ProposedPlan 对象
    task_updated = Signal(object)        # 发射更新后的 ScheduledTask 对象
    log_emitted = Signal(str, str)        # (message, level)
    status_changed = Signal(str)         # 调度状态

    def __init__(self, tasks: Optional[List[ScheduledTask]] = None, parent=None):
        super().__init__(parent)
        self.tasks: List[ScheduledTask] = tasks or []
        self._is_running = True
        self._check_interval = 5.0       # 心跳检测周期 (秒)

        # 初始化下次运行时间
        now = time.time()
        for t in self.tasks:
            if t.enabled and (not t.next_run_time or t.next_run_time < now):
                t.next_run_time = now + t.interval_minutes * 60.0

    def update_tasks(self, tasks: List[ScheduledTask]):
        """动态更新计划任务列表"""
        now = time.time()
        self.tasks = tasks
        for t in self.tasks:
            if t.enabled and (not t.next_run_time or t.next_run_time < now):
                t.next_run_time = now + t.interval_minutes * 60.0
        self.log_emitted.emit(f"📅 计划任务列表已更新，当前有效任务数: {len([t for t in self.tasks if t.enabled])}", "info")

    def run_task_immediately(self, task_id: str):
        """立即手动触发单条计划任务执行"""
        for t in self.tasks:
            if t.id == task_id:
                now = time.time()
                self._execute_scheduled_task(t, now)
                break

    def stop(self):
        """平滑停止调度线程"""
        self._is_running = False
        self.wait(3000)

    def run(self):
        app_logger.info("自动化中心: 计划任务调度器已启动")
        self.status_changed.emit("正在调度中")

        while self._is_running:
            try:
                now = time.time()
                for task in self.tasks:
                    if not self._is_running:
                        break
                    if task.enabled and task.next_run_time and now >= task.next_run_time:
                        self._execute_scheduled_task(task, now)

            except Exception as e:
                app_logger.error("计划任务调度循环异常: %s", e)
                self.log_emitted.emit(f"调度异常: {e}", "error")

            # 细粒度可中断休眠 (每 0.1 秒检查一次退出标志，杜绝 5s 大粗粒度 sleep 导致析构超时)
            for _ in range(int(self._check_interval * 10)):
                if not self._is_running:
                    break
                time.sleep(0.1)

        self.status_changed.emit("已停止")
        app_logger.info("自动化中心: 计划任务调度器已停止")

    def _execute_scheduled_task(self, task: ScheduledTask, now: float):
        """执行具体的计划任务（扫描目标目录并经由 AI 编排与主路由表生成提案或执行归档）"""
        target_dir = task.target_path
        if not target_dir or not os.path.isdir(target_dir):
            task.last_status = "目录不存在"
            task.last_run_time = now
            task.next_run_time = now + task.interval_minutes * 60.0
            task.last_result_summary = f"目标目录不存在: {target_dir}"
            self.task_updated.emit(task)
            self.log_emitted.emit(f"⚠️ 计划任务 [{task.name}] 失败: 目录不存在 ({target_dir})", "warn")
            return

        self.log_emitted.emit(f"⏳ 计划任务 [{task.name}] 触发，正在生成整理提案...", "info")
        scanned_files = []

        try:
            assets = UnifiedScanner.scan_directory(
                root_paths=[target_dir],
                prune_collectives=True,
                skip_system_protected=True,
                cancel_check=lambda: self._is_running
            )

            for asset in assets:
                scanned_files.append({
                    "path": asset.path,
                    "name": asset.name,
                    "size": asset.size,
                    "mtime": asset.mtime,
                    "ext": asset.ext,
                    "category": asset.category,
                    "is_directory_collective": asset.is_collective,
                    "collective_info": asset.collective_info,
                    "umbrella_anchor": asset.umbrella_anchor,
                    "metadata": asset.metadata
                })

            if not scanned_files:
                task.last_status = "成功 (无文件)"
                task.last_run_time = now
                task.next_run_time = now + task.interval_minutes * 60.0
                task.last_result_summary = "扫描完成，目录无待整理文件"
                self.task_updated.emit(task)
                self.log_emitted.emit(f"✅ 计划任务 [{task.name}] 执行完毕，无文件需整理", "info")
                return

            dest_root = task.target_dir or "D:/归档备份"

            # 统一委托 AutomationPlanResolver 执行主路由表匹配、PE元数据仲裁、在线 AI 核心编排、主动纠偏与分析即沉淀
            plan, enforce_propose_only = AutomationPlanResolver.resolve_scheduled_task_plan(
                task=task,
                scanned_files=scanned_files,
                now=now
            )
            is_ai_powered = "AI 核心编排" in (plan.notes or "")

            # 若配置为仅提议，或在线 AI 审查门禁触发拦截（低置信度/高风险），则产出提案待人工确认
            if task.propose_only or (is_ai_powered and enforce_propose_only):
                if not task.propose_only and enforce_propose_only:
                    task.last_status = "安全门禁转提案"
                    task.last_result_summary = f"触发 AI 审查安全门禁，已转为人工审核提案 ({len(scanned_files)} 项)"
                    self.log_emitted.emit(
                        f"🛡️ 计划任务 [{task.name}] 触发 AI 审查安全门禁，已转为待确认提案",
                        "warn"
                    )
                else:
                    task.last_status = "已生成提案"
                    origin_tag = "AI核心编排" if is_ai_powered else "拓扑规则"
                    task.last_result_summary = f"成功生成方案 ({origin_tag}): 包含 {len(scanned_files)} 个文件，待用户确认"
                    prefix = "🤖" if is_ai_powered else "🎯"
                    self.log_emitted.emit(
                        f"{prefix} 计划任务 [{task.name}] 已由 {origin_tag} 生成整理提案 (共 {len(scanned_files)} 个文件，待确认)",
                        "success"
                    )

                task.last_run_time = now
                task.next_run_time = now + task.interval_minutes * 60.0
                self.task_updated.emit(task)
                self.plan_proposed.emit(plan)
            else:
                # 模式 2: 自动归档平移 (直接复用已通过 AI 编排与主路由表纠偏的 proposed_groups)
                res = execute_safe_auto_archive(
                    files=scanned_files,
                    target_root=dest_root,
                    source_dir=task.target_path,
                    organize_mode=task.organize_mode or "comprehensive",
                    source_name=f"计划任务-{task.name}",
                    log_callback=lambda msg, lvl: self.log_emitted.emit(msg, lvl),
                    proposed_groups=plan.proposed_groups
                )

                task.last_run_time = now
                task.next_run_time = now + task.interval_minutes * 60.0
                if res.get("success"):
                    task.last_status = f"归档成功 ({res['success_count']} 项)"
                    task.last_result_summary = f"已自动归档 {res['success_count']} 个文件至 {dest_root}"
                    self.log_emitted.emit(f"⚡ 计划任务 [{task.name}] 自动归档执行完成！成功: {res['success_count']}", "success")
                else:
                    task.last_status = f"归档终止: {res.get('error', '未知错误')}"
                    task.last_result_summary = res.get("error", "未知错误")

                self.task_updated.emit(task)

        except Exception as e:
            task.last_status = f"异常: {e}"
            task.last_run_time = now
            task.next_run_time = now + task.interval_minutes * 60.0
            task.last_result_summary = str(e)
            self.task_updated.emit(task)
            self.log_emitted.emit(f"❌ 计划任务 [{task.name}] 发生异常: {e}", "error")
