"""
app/dedup/models.py
文件查重与跨盘融合领域模型定义
"""
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


@dataclass
class DedupFileItem:
    """单个文件资产元数据"""
    path: str
    name: str
    rel_path: str
    size: int
    mtime: float
    source_dir: str
    category: str = ""
    ext: str = ""
    sample_hash: Optional[str] = None
    full_hash: Optional[str] = None
    is_locked: bool = False
    lock_reason: str = ""
    is_collective: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "rel_path": self.rel_path,
            "size": self.size,
            "mtime": self.mtime,
            "source_dir": self.source_dir,
            "category": self.category,
            "ext": self.ext,
            "sample_hash": self.sample_hash,
            "full_hash": self.full_hash,
            "is_locked": self.is_locked,
            "lock_reason": self.lock_reason,
            "is_collective": self.is_collective
        }


@dataclass
class DedupGroup:
    """完全重复文件组 (内容 100% 一致)"""
    group_id: str
    size: int
    full_hash: str
    items: List[DedupFileItem] = field(default_factory=list)
    recommended_keep_path: Optional[str] = None

    @property
    def duplicate_count(self) -> int:
        return max(0, len(self.items) - 1)

    @property
    def wasted_bytes(self) -> int:
        """可释放的冗余空间"""
        return self.size * self.duplicate_count

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "size": self.size,
            "full_hash": self.full_hash,
            "items": [item.to_dict() for item in self.items],
            "recommended_keep_path": self.recommended_keep_path,
            "duplicate_count": self.duplicate_count,
            "wasted_bytes": self.wasted_bytes
        }


@dataclass
class CollisionItem:
    """同名异内容冲突项 (相对路径相同但内容/哈希不同)"""
    rel_path: str
    files: List[DedupFileItem] = field(default_factory=list)
    suggested_action: str = "rename"  # rename | keep_source_tree | skip

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rel_path": self.rel_path,
            "files": [f.to_dict() for f in self.files],
            "suggested_action": self.suggested_action
        }


@dataclass
class MergeAction:
    """单个文件的融合操作指令"""
    action_type: str  # keep | move_merge | isolate_archive | rename_merge | skip
    source_path: str
    target_path: Optional[str] = None
    size: int = 0
    reason: str = ""
    is_locked: bool = False
    source_dir: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type,
            "source_path": self.source_path,
            "target_path": self.target_path,
            "size": self.size,
            "reason": self.reason,
            "is_locked": self.is_locked,
            "source_dir": self.source_dir
        }


@dataclass
class DedupScanConfig:
    """查重与融合任务配置"""
    source_dirs: List[str] = field(default_factory=list)
    target_dir: Optional[str] = None
    isolation_dir: Optional[str] = None
    prune_collectives: bool = True
    skip_system_protected: bool = True
    min_file_size: int = 1  # 过滤空文件或极小文件 (字节)
    hash_algorithm: str = "sha256"
    ignore_folders: List[str] = field(default_factory=list)
    dedup_keep_preference: str = "keep_primary"  # keep_primary | keep_newest | keep_oldest | keep_shortest_path


@dataclass
class DedupScanResult:
    """查重与冲突检测全景结果"""
    scan_time: float = field(default_factory=time.time)
    total_files: int = 0
    total_bytes: int = 0
    duplicate_groups: List[DedupGroup] = field(default_factory=list)
    collisions: List[CollisionItem] = field(default_factory=list)
    unique_files: List[DedupFileItem] = field(default_factory=list)
    scanned_sources: List[str] = field(default_factory=list)

    @property
    def total_duplicates_count(self) -> int:
        return sum(g.duplicate_count for g in self.duplicate_groups)

    @property
    def total_wasted_bytes(self) -> int:
        return sum(g.wasted_bytes for g in self.duplicate_groups)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scan_time": self.scan_time,
            "total_files": self.total_files,
            "total_bytes": self.total_bytes,
            "total_duplicates_count": self.total_duplicates_count,
            "total_wasted_bytes": self.total_wasted_bytes,
            "duplicate_groups": [g.to_dict() for g in self.duplicate_groups],
            "collisions": [c.to_dict() for c in self.collisions],
            "unique_count": len(self.unique_files),
            "scanned_sources": self.scanned_sources
        }
