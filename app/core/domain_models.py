"""
核心领域模型与面向对象实体契约 (Domain Models)

本模块确立工程底层强类型、防撕裂领域实体标准：
1. ScannedAsset: 统一全景资产对象 (兼容属性访问与 dict 下标访问，彻底消除键名不一致 Bug)
2. AtomicCollectiveAsset: 不可拆分的原子实体集体对象 (开发工程/独立软件/业务账套)
3. GovernancePlan: 治理规划方案实体
4. ScanSessionSummary: 扫描会话综合统计快照
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass
class ScannedAsset:
    """
    统一全景资产领域模型 (Universal Scanned Asset Domain Model)
    
    兼具面向对象强类型属性访问与字典兼容协议 (Subscriptable & Dict-Like):
    - 强类型访问: asset.path, asset.name, asset.size, asset.target_subpath, asset.is_collective
    - 字段别名解耦: asset.planning_path / asset.suggested_archive_path 统一映射到 asset.target_subpath
    - 字典向下兼容: 支持 asset["path"], asset.get("target_subpath"), "category" in asset
    - 序列化标准: to_dict(), from_dict()
    """
    id: str = ""
    name: str = ""
    path: str = ""
    size: int = 0
    mtime: float = field(default_factory=time.time)
    file_count: int = 1
    is_collective: bool = False
    collective_type: str = ""
    category: str = "其他文件"
    ext: str = ""
    scan_root: str = ""
    umbrella_anchor: str = ""
    umbrella_category: str = ""
    is_snapshot_backup: bool = False
    collective_info: Dict[str, Any] = field(default_factory=dict)
    tag: str = ""
    reason: str = ""
    phase_status: str = "阶段一已归类"
    is_recommended: bool = False
    target_subpath: str = ""
    action: str = "建议归档"
    state: str = "正常"
    redundant_type: str = "无冗余"
    match_rule: str = ""
    _extra: Dict[str, Any] = field(default_factory=dict)

    # 属性映射与别名兼容
    @property
    def is_directory_collective(self) -> bool:
        return self.is_collective

    @is_directory_collective.setter
    def is_directory_collective(self, val: bool) -> None:
        self.is_collective = bool(val)

    @property
    def suggested_archive_path(self) -> str:
        return self.target_subpath

    @suggested_archive_path.setter
    def suggested_archive_path(self, val: str) -> None:
        self.target_subpath = str(val) if val is not None else ""

    @property
    def planning_path(self) -> str:
        return self.target_subpath

    @planning_path.setter
    def planning_path(self, val: str) -> None:
        self.target_subpath = str(val) if val is not None else ""

    def __getitem__(self, key: str) -> Any:
        if key in ("planning_path", "suggested_archive_path", "target_subpath"):
            return self.target_subpath
        if key in ("is_directory_collective", "is_collective"):
            return self.is_collective
        if hasattr(self, key):
            return getattr(self, key)
        if key in self._extra:
            return self._extra[key]
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if key in ("planning_path", "suggested_archive_path", "target_subpath"):
            self.target_subpath = str(value) if value is not None else ""
        elif key in ("is_directory_collective", "is_collective"):
            self.is_collective = bool(value)
        elif hasattr(self, key) and key != "_extra":
            setattr(self, key, value)
        else:
            self._extra[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        try:
            val = self[key]
            return val if val is not None else default
        except (KeyError, AttributeError):
            return default

    def __contains__(self, key: str) -> bool:
        if key in ("planning_path", "suggested_archive_path", "target_subpath", "is_directory_collective", "is_collective"):
            return True
        return hasattr(self, key) or (key in self._extra)

    def to_dict(self) -> Dict[str, Any]:
        """导出为全字段标准字典，保障向后兼容性"""
        d = {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "size": self.size,
            "mtime": self.mtime,
            "file_count": self.file_count,
            "is_collective": self.is_collective,
            "is_directory_collective": self.is_collective,
            "collective_type": self.collective_type,
            "category": self.category,
            "ext": self.ext,
            "scan_root": self.scan_root,
            "umbrella_anchor": self.umbrella_anchor,
            "umbrella_category": self.umbrella_category,
            "is_snapshot_backup": self.is_snapshot_backup,
            "collective_info": self.collective_info,
            "tag": self.tag,
            "reason": self.reason,
            "phase_status": self.phase_status,
            "is_recommended": self.is_recommended,
            "target_subpath": self.target_subpath,
            "suggested_archive_path": self.target_subpath,
            "planning_path": self.target_subpath,
            "action": self.action,
            "state": self.state,
            "redundant_type": self.redundant_type,
            "match_rule": self.match_rule,
        }
        if self._extra:
            d.update(self._extra)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ScannedAsset:
        """从字典解析构建强类型实体"""
        if isinstance(data, cls):
            return data
        known_fields = {
            "id", "name", "path", "size", "mtime", "file_count", "is_collective",
            "collective_type", "category", "ext", "scan_root", "umbrella_anchor",
            "umbrella_category", "is_snapshot_backup", "collective_info", "tag",
            "reason", "phase_status", "is_recommended", "target_subpath", "action",
            "state", "redundant_type", "match_rule"
        }
        kwargs = {}
        extra = {}
        for k, v in data.items():
            if k in known_fields:
                kwargs[k] = v
            elif k in ("is_directory_collective",):
                kwargs["is_collective"] = bool(v)
            elif k in ("suggested_archive_path", "planning_path"):
                if "target_subpath" not in kwargs or not kwargs["target_subpath"]:
                    kwargs["target_subpath"] = str(v) if v else ""
            else:
                extra[k] = v
        obj = cls(**kwargs)
        if extra:
            obj._extra.update(extra)
        return obj


# 兼容既有 UnifiedScanner 别名
AssetUnit = ScannedAsset


@dataclass
class GovernancePlan:
    """
    AI 编排或本地规则生成的单项资产治理规划方案
    """
    original_root: str
    suggested_category: str
    target_subpath: str
    action: str = "建议归档"
    confidence: float = 1.0
    risk_level: str = "低风险"
    require_confirmation: bool = False
    reason: str = ""
    app_name: str = ""
    is_collective: bool = False
    file_count: int = 1
    total_bytes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_root": self.original_root,
            "suggested_category": self.suggested_category,
            "target_subpath": self.target_subpath,
            "action": self.action,
            "confidence": self.confidence,
            "risk_level": self.risk_level,
            "require_confirmation": self.require_confirmation,
            "reason": self.reason,
            "app_name": self.app_name,
            "is_collective": self.is_collective,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GovernancePlan:
        return cls(
            original_root=data.get("original_root", ""),
            suggested_category=data.get("suggested_category", "其他"),
            target_subpath=data.get("target_subpath", ""),
            action=data.get("action", "建议归档"),
            confidence=float(data.get("confidence", 1.0)),
            risk_level=data.get("risk_level", "低风险"),
            require_confirmation=bool(data.get("require_confirmation", False)),
            reason=data.get("reason", ""),
            app_name=data.get("app_name", ""),
            is_collective=bool(data.get("is_collective", False)),
            file_count=int(data.get("file_count", 1)),
            total_bytes=int(data.get("total_bytes", 0)),
        )


@dataclass
class ScanSessionSummary:
    """
    扫描会话综合指标数据模型
    """
    task_id: str = ""
    total_files: int = 0
    total_bytes: int = 0
    standalone_file_count: int = 0
    collective_count: int = 0
    elapsed_seconds: float = 0.0
    target_paths: List[str] = field(default_factory=list)
    category_stats: Dict[str, Any] = field(default_factory=dict)
    top_100_files: List[ScannedAsset] = field(default_factory=list)
    redundant_files: List[ScannedAsset] = field(default_factory=list)
    duplicate_groups_count: int = 0
    duplicate_wasted_bytes: int = 0
    reclaimable_bytes: int = 0
    all_scanned_files: List[ScannedAsset] = field(default_factory=list)
