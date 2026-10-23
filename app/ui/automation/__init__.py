"""
自动化中心 UI 模块
"""

from app.ui.automation.automation_view import AutomationCenterView
from app.ui.automation.rule_monitor_page import RuleMonitorPage
from app.ui.automation.schedule_task_page import ScheduleTaskPage
from app.ui.automation.quick_organize_page import QuickOrganizePage
from app.ui.automation.cli_script_page import CliScriptPage
from app.ui.automation.ai_audit_routing_page import AiAuditRoutingPage

__all__ = [
    "AutomationCenterView",
    "RuleMonitorPage",
    "ScheduleTaskPage",
    "QuickOrganizePage",
    "CliScriptPage",
    "AiAuditRoutingPage",
]
