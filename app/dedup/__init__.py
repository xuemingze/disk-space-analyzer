"""
app/dedup 模块
文件查重、拓扑冲突分析与安全原子跨盘融合
"""
from app.dedup.models import (
    DedupFileItem,
    DedupGroup,
    CollisionItem,
    MergeAction,
    DedupScanConfig,
    DedupScanResult
)
from app.dedup.hasher import DedupHasher
from app.dedup.detector import DedupDetector
from app.dedup.executor import MergeExecutor
from app.dedup.task_config_manager import DedupTaskConfigManager

__all__ = [
    "DedupFileItem",
    "DedupGroup",
    "CollisionItem",
    "MergeAction",
    "DedupScanConfig",
    "DedupScanResult",
    "DedupHasher",
    "DedupDetector",
    "MergeExecutor",
    "DedupTaskConfigManager"
]
