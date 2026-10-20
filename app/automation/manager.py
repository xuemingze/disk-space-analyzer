"""
自动化中心中控管理器 (Automation Manager)
单例模式，统筹调度规则监控 (Watcher)、计划任务 (Scheduler)、快速整理 (QuickOrganizer) 与方案持久化。
"""

import os
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtCore import QObject, Signal

from app.automation.models import WatchRule, ScheduledTask, ProposedPlan
from app.automation.watcher import RuleWatcher
from app.automation.scheduler import TaskScheduler
from app.utils.logger import app_logger

AUTOMATION_DATA_FILE = Path.home() / ".disk_space_analyzer" / "automation.json"


class AutomationManager(QObject):
    """
    自动化中控管理单例
    """
    plan_added = Signal(object)       # 当有新整理提案生成时通知 UI (ProposedPlan)
    rules_changed = Signal()         # 规则列表变更通知
    tasks_changed = Signal()         # 任务列表变更通知
    log_emitted = Signal(str, str)    # 日志信号 (message, level)

    _instance = None

    @classmethod
    def get_instance(cls) -> "AutomationManager":
        if cls._instance is None:
            cls._instance = AutomationManager()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rules: List[WatchRule] = []
        self.tasks: List[ScheduledTask] = []
        self.proposed_plans: List[ProposedPlan] = []

        self.watcher = RuleWatcher(parent=self)
        self.scheduler = TaskScheduler(parent=self)

        self._bind_signals()
        self.load_data()

    def _bind_signals(self):
        # 绑定来自 Watcher 与 Scheduler 的提案与日志信号
        self.watcher.plan_proposed.connect(self._on_plan_received)
        self.watcher.log_emitted.connect(self.log_emitted)

        self.scheduler.plan_proposed.connect(self._on_plan_received)
        self.scheduler.log_emitted.connect(self.log_emitted)
        self.scheduler.task_updated.connect(self._on_task_updated)

    def _on_plan_received(self, plan: ProposedPlan):
        """接收到监控或调度器提议的整理方案"""
        self.proposed_plans.insert(0, plan)
        # 最多保留 50 条历史候选提案
        if len(self.proposed_plans) > 50:
            self.proposed_plans = self.proposed_plans[:50]
        self.save_data()
        self.plan_added.emit(plan)

    def _on_task_updated(self, task: ScheduledTask):
        """计划任务执行状态更新"""
        self.save_data()
        self.tasks_changed.emit()

    def start_services(self):
        """启动后台监控与调度线程"""
        if not self.watcher.isRunning():
            self.watcher.update_rules(self.rules)
            self.watcher.start()
        if not self.scheduler.isRunning():
            self.scheduler.update_tasks(self.tasks)
            self.scheduler.start()
        app_logger.info("自动化中心服务已就绪并启动")

    def stop_services(self):
        """安全停止后台服务"""
        if self.watcher.isRunning():
            self.watcher.stop()
        if self.scheduler.isRunning():
            self.scheduler.stop()
        app_logger.info("自动化中心服务已停止")

    # ==================== 规则管理 ====================

    def add_rule(self, rule: WatchRule):
        self.rules.append(rule)
        self.save_data()
        self.watcher.update_rules(self.rules)
        self.rules_changed.emit()

    def update_rule(self, rule: WatchRule):
        for i, r in enumerate(self.rules):
            if r.id == rule.id:
                self.rules[i] = rule
                break
        self.save_data()
        self.watcher.update_rules(self.rules)
        self.rules_changed.emit()

    def delete_rule(self, rule_id: str):
        self.rules = [r for r in self.rules if r.id != rule_id]
        self.save_data()
        self.watcher.update_rules(self.rules)
        self.rules_changed.emit()

    def toggle_rule(self, rule_id: str, enabled: bool):
        for r in self.rules:
            if r.id == rule_id:
                r.enabled = enabled
                break
        self.save_data()
        self.watcher.update_rules(self.rules)
        self.rules_changed.emit()

    # ==================== 计划任务管理 ====================

    def add_task(self, task: ScheduledTask):
        self.tasks.append(task)
        self.save_data()
        self.scheduler.update_tasks(self.tasks)
        self.tasks_changed.emit()

    def update_task(self, task: ScheduledTask):
        for i, t in enumerate(self.tasks):
            if t.id == task.id:
                self.tasks[i] = task
                break
        self.save_data()
        self.scheduler.update_tasks(self.tasks)
        self.tasks_changed.emit()

    def delete_task(self, task_id: str):
        self.tasks = [t for t in self.tasks if t.id != task_id]
        self.save_data()
        self.scheduler.update_tasks(self.tasks)
        self.tasks_changed.emit()

    def toggle_task(self, task_id: str, enabled: bool):
        for t in self.tasks:
            if t.id == task_id:
                t.enabled = enabled
                break
        self.save_data()
        self.scheduler.update_tasks(self.tasks)
        self.tasks_changed.emit()

    def run_task_now(self, task_id: str):
        self.scheduler.run_task_immediately(task_id)

    # ==================== 方案审核与处理 ====================

    def get_pending_plans(self) -> List[ProposedPlan]:
        return [p for p in self.proposed_plans if p.status == "pending"]

    def dismiss_plan(self, plan_id: str):
        for p in self.proposed_plans:
            if p.id == plan_id:
                p.status = "dismissed"
                break
        self.save_data()

    def mark_plan_applied(self, plan_id: str):
        for p in self.proposed_plans:
            if p.id == plan_id:
                p.status = "applied"
                break
        self.save_data()

    # ==================== 持久化存储 ====================

    def load_data(self):
        """从本地 JSON 文件加载自动化配置"""
        if not AUTOMATION_DATA_FILE.exists():
            self._load_defaults()
            self.save_data()
            return

        try:
            with open(AUTOMATION_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.rules = [WatchRule.from_dict(r) for r in data.get("rules", [])]
            self.tasks = [ScheduledTask.from_dict(t) for t in data.get("tasks", [])]
            self.proposed_plans = [ProposedPlan.from_dict(p) for p in data.get("proposed_plans", [])]
            
            # 若初次无规则，注入一个默认的下载目录监控规则 (默认未启用，待用户开启)
            if not self.rules:
                self._load_defaults()
                self.save_data()

        except Exception as e:
            app_logger.error("加载自动化数据失败: %s", e)
            self._load_defaults()

    def _load_defaults(self):
        downloads_dir = str(Path.home() / "Downloads")
        self.rules = [
            WatchRule(
                name="下载目录自动监测 (提议模式)",
                watch_path=downloads_dir,
                exclude_patterns=["*.tmp", "*.crdownload", "*.part", "*.download"],
                debounce_seconds=3.0,
                enabled=False,  # 默认关闭，让用户自主决定开启
                propose_only=True
            )
        ]
        self.tasks = [
            ScheduledTask(
                name="每日桌面与下载待整理盘点",
                target_path=downloads_dir,
                interval_minutes=1440,
                enabled=False,
                propose_only=True
            )
        ]

    def save_data(self):
        """保存配置到本地 JSON"""
        try:
            AUTOMATION_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "rules": [r.to_dict() for r in self.rules],
                "tasks": [t.to_dict() for t in self.tasks],
                "proposed_plans": [p.to_dict() for p in self.proposed_plans]
            }
            with open(AUTOMATION_DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            app_logger.error("保存自动化数据失败: %s", e)
