"""
自动化中心模块 (Automation Center)
包含：规则监控 (Watcher)、计划任务 (Scheduler)、快速整理 (QuickOrganizer)、CLI与脚本生成器 (CliScriptGenerator)
"""

from app.automation.models import WatchRule, ScheduledTask, ProposedPlan, QuickPreset
from app.automation.watcher import RuleWatcher
from app.automation.scheduler import TaskScheduler
from app.automation.manager import AutomationManager
from app.automation.quick_organizer import QuickOrganizeManager
from app.automation.cli_generator import CliScriptGenerator

__all__ = [
    "WatchRule",
    "ScheduledTask",
    "ProposedPlan",
    "QuickPreset",
    "RuleWatcher",
    "TaskScheduler",
    "AutomationManager",
    "QuickOrganizeManager",
    "CliScriptGenerator",
]
