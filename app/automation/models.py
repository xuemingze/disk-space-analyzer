"""
自动化中心数据模型定义 (Automation Center Models)
包含：监控规则 (WatchRule)、计划任务 (ScheduledTask)、候选整理方案 (ProposedPlan)、快速整理预设 (QuickPreset)
"""

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from pathlib import Path


@dataclass
class WatchRule:
    """观察目录监控规则"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "默认监控规则"
    watch_path: str = ""
    exclude_patterns: List[str] = field(default_factory=lambda: ["*.tmp", "*.crdownload", "*.part", ".git", "node_modules"])
    file_extensions: List[str] = field(default_factory=list)  # 空列表表示监控所有文件
    organize_mode: str = "comprehensive"  # comprehensive | by_type | by_prefix | by_date | by_app
    target_dir: str = ""                  # 目标归档目录 (若为空则采用全局配置)
    debounce_seconds: float = 3.0         # 防抖与文件沉淀时长 (秒)，必须持续平稳才视为写入完成
    min_file_size: int = 0                # 最小关注文件体积 (字节)
    enabled: bool = True
    propose_only: bool = True             # 安全铁律：默认只提议、不执行
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WatchRule":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ScheduledTask:
    """定时计划任务"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "每日自动整理规划"
    target_path: str = ""
    interval_minutes: int = 1440           # 默认 24 小时 (1440 分钟)
    organize_mode: str = "comprehensive"
    target_dir: str = ""
    enabled: bool = True
    propose_only: bool = True              # 安全铁律：默认只生成整理计划，不自动物理移动
    last_run_time: Optional[float] = None
    next_run_time: Optional[float] = None
    last_status: str = "就绪"              # 就绪 | 运行中 | 成功 | 失败
    last_result_summary: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduledTask":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ProposedPlan:
    """自动化候选整理方案 (只提议、不移动，待用户审核并确认)"""
    id: str = field(default_factory=lambda: f"PLAN_{int(time.time()*1000)}")
    source_type: str = "rule_monitor"     # rule_monitor | scheduled_task | quick_organize
    source_name: str = ""
    source_path: str = ""
    target_root: str = ""
    created_at: float = field(default_factory=time.time)
    file_count: int = 0
    total_bytes: int = 0
    proposed_groups: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "pending"                # pending (待审核) | applied (已执行) | dismissed (已忽略)
    notes: str = ""
    is_corrected: bool = False
    correction_records: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProposedPlan":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class QuickPreset:
    """快速整理预设"""
    key: str
    name: str
    icon: str
    path: str
    description: str
