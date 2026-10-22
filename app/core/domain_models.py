"""
核心领域模型与面向对象实体契约 (Domain Models)

本模块确立工程底层强类型、防撕裂领域实体标准：
1. ScannedAsset: 统一全景资产对象 (兼容属性访问与 dict 下标访问，彻底消除键名不一致 Bug)
2. AtomicCollectiveAsset: 不可拆分的原子实体集体对象 (开发工程/独立软件/业务账套)
3. GovernancePlan: 治理规划方案实体
4. ScanSessionSummary: 扫描会话综合统计快照
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union


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
    metadata: Dict[str, Any] = field(default_factory=dict)
    normalized_name: str = ""
    _extra: Dict[str, Any] = field(default_factory=dict)

    # 属性映射与别名兼容
    @property
    def display_name(self) -> str:
        return self.normalized_name or self.name

    @property
    def software_name(self) -> str:
        if self.metadata and isinstance(self.metadata, dict):
            return self.metadata.get("software_name", "")
        return ""

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
            "metadata": self.metadata,
            "normalized_name": self.normalized_name,
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
            "state", "redundant_type", "match_rule",
            "metadata", "normalized_name"
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


@dataclass
class VersionClusterItem:
    """
    多版本聚类单项实体 (Multi-version Cluster Member Entity)
    封装单份文件版本特征、脱敏文本指纹及保留裁决建议
    """
    path: str = ""
    name: str = ""
    size: int = 0
    mtime: float = field(default_factory=time.time)
    stem: str = ""
    version_suffix: str = ""
    category: str = "文档/多版本"
    content_snippet: str = ""
    is_recommended_keep: bool = False
    retention_action: str = "建议归档"
    decision_reason: str = ""
    _extra: Dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if key in self._extra:
            return self._extra[key]
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if hasattr(self, key) and key != "_extra":
            setattr(self, key, value)
        else:
            self._extra[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        try:
            val = self[key]
            return val if val is not None else default
        except (KeyError, AttributeError):
            return default

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "path": self.path,
            "name": self.name,
            "size": self.size,
            "mtime": self.mtime,
            "stem": self.stem,
            "version_suffix": self.version_suffix,
            "category": self.category,
            "content_snippet": self.content_snippet,
            "is_recommended_keep": self.is_recommended_keep,
            "retention_action": self.retention_action,
            "decision_reason": self.decision_reason,
        }
        if self._extra:
            d.update(self._extra)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VersionClusterItem:
        if isinstance(data, cls):
            return data
        known_fields = {
            "path", "name", "size", "mtime", "stem", "version_suffix",
            "category", "content_snippet", "is_recommended_keep",
            "retention_action", "decision_reason"
        }
        kwargs = {}
        extra = {}
        for k, v in data.items():
            if k in known_fields:
                kwargs[k] = v
            else:
                extra[k] = v
        obj = cls(**kwargs)
        if extra:
            obj._extra.update(extra)
        return obj


@dataclass
class VersionClusterGroup:
    """
    同源多版本文件聚类实体组 (Multi-version Cluster Group)
    用于同族文档/工程版本比对与 AI 统揽研判
    """
    group_id: str = ""
    normalized_stem: str = ""
    directory: str = ""
    items: List[VersionClusterItem] = field(default_factory=list)
    recommended_keep_path: str = ""
    ai_summary: str = ""
    ai_evaluated: bool = False
    _extra: Dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if key in self._extra:
            return self._extra[key]
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if hasattr(self, key) and key != "_extra":
            setattr(self, key, value)
        else:
            self._extra[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        try:
            val = self[key]
            return val if val is not None else default
        except (KeyError, AttributeError):
            return default

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "group_id": self.group_id,
            "normalized_stem": self.normalized_stem,
            "directory": self.directory,
            "items": [it.to_dict() for it in self.items],
            "recommended_keep_path": self.recommended_keep_path,
            "ai_summary": self.ai_summary,
            "ai_evaluated": self.ai_evaluated,
        }
        if self._extra:
            d.update(self._extra)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VersionClusterGroup:
        if isinstance(data, cls):
            return data
        known_fields = {
            "group_id", "normalized_stem", "directory",
            "recommended_keep_path", "ai_summary", "ai_evaluated"
        }
        kwargs = {}
        extra = {}
        for k, v in data.items():
            if k == "items" and isinstance(v, list):
                kwargs["items"] = [VersionClusterItem.from_dict(it) for it in v]
            elif k in known_fields:
                kwargs[k] = v
            else:
                extra[k] = v
        obj = cls(**kwargs)
        if extra:
            obj._extra.update(extra)
        return obj


@dataclass
class SemanticDiffDecision:
    """
    AI 语义差异比对与保留建议决策契约
    """
    recommended_path: str = ""
    explanation: str = ""
    version_comparison: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommended_path": self.recommended_path,
            "explanation": self.explanation,
            "version_comparison": self.version_comparison,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SemanticDiffDecision:
        return cls(
            recommended_path=data.get("recommended_path", ""),
            explanation=data.get("explanation", ""),
            version_comparison=data.get("version_comparison", []),
            confidence=float(data.get("confidence", 1.0)),
        )


@dataclass(frozen=True)
class ArchiveDestinationPath:
    """
    归档目标规划路径值对象 (Archive Destination Path Value Object)
    
    统一封装归档目标路径的构建、相邻重复段折叠、路径安全性校验与子路径相对派生：
    1. 彻底解决形如 ~/发票/发票/XXX、~/live2D/live2D/XXX 的重复段嵌套 Bug；
    2. 严格遵循面向对象不可变值对象契约；
    3. 支持安全检验 (is_safe)，阻断根盘误擦除与上卷遍历跨盘；
    4. 支持 relative_join 高性能相对拼接。
    """
    raw_path: str

    @classmethod
    def collapse_duplicate_segments(cls, parts: List[str]) -> List[str]:
        """
        折叠相邻重复的路径段，彻底消除如 '发票/发票'、'live2D/live2D' 的嵌套。
        """
        if not parts:
            return []
        
        collapsed: List[str] = []
        for part in parts:
            if not part:
                continue
            # 分割可能夹带斜杠的复合子路径 (例如 '发票/2026' 或 '发票\\2026')
            norm_sub = str(part).replace("\\", "/").strip("/")
            sub_segments = [s.strip() for s in norm_sub.split("/") if s.strip()]
            for seg in sub_segments:
                if not collapsed:
                    collapsed.append(seg)
                    continue
                prev = collapsed[-1]
                # 大小写不敏感的相邻完全重复段判定
                if prev.lower() == seg.lower():
                    continue
                collapsed.append(seg)
        return collapsed

    @classmethod
    def build(
        cls,
        dest_root: Union[str, Path],
        category: str = "",
        subpath: str = "",
        entity_name: str = "",
        is_dir: bool = True
    ) -> "ArchiveDestinationPath":
        """
        面向对象构建标准化归档目标规划路径，内建防撕裂、去冗余与路径规范化契约
        """
        dest_root_p = Path(dest_root)

        # 收集待拼接的语义段
        extra_parts: List[str] = []
        if category and str(category).strip():
            extra_parts.append(str(category).strip())
        if subpath and str(subpath).strip():
            extra_parts.append(str(subpath).strip())
        if entity_name and str(entity_name).strip() and is_dir:
            extra_parts.append(str(entity_name).strip())

        collapsed_extras = cls.collapse_duplicate_segments(extra_parts)

        # 检查 collapsed_extras 的首段是否与 dest_root 的尾段重复 (例如 dest_root='D:\\发票', category='发票')
        if collapsed_extras and dest_root_p.name:
            if dest_root_p.name.lower() == collapsed_extras[0].lower():
                collapsed_extras = collapsed_extras[1:]

        if collapsed_extras:
            final_p = dest_root_p
            for seg in collapsed_extras:
                final_p = final_p / seg
            return cls(raw_path=str(final_p))
        else:
            return cls(raw_path=str(dest_root_p))

    def relative_join(self, rel_path: str) -> str:
        """
        计算子文件或子目录在当前规划目标下的绝对目标路径
        """
        if not rel_path or str(rel_path).strip() in (".", "./", ".\\"):
            return self.raw_path
        clean_rel = str(rel_path).replace("\\", "/").strip("/")
        return str(Path(self.raw_path) / Path(clean_rel))

    def is_safe(self) -> Tuple[bool, str]:
        """
        检验目标规划路径的安全性（严禁越界、空路径或系统保护根盘擦除）
        """
        if not self.raw_path or not self.raw_path.strip():
            return False, "规划路径不能为空"
        p = Path(self.raw_path)
        # 严禁目标路径为盘符根目录 (如 C:\, D:\)
        if len(p.parts) <= 1:
            return False, "规划路径不能直接设为系统磁盘根目录"
        if ".." in p.parts:
            return False, "规划路径不能包含上卷遍历符 (..)"
        return True, "路径安全"

    def __str__(self) -> str:
        return self.raw_path

    @property
    def path(self) -> Path:
        return Path(self.raw_path)

    @property
    def name(self) -> str:
        return Path(self.raw_path).name


class HistorySuggestionProvider:
    """
    归档分类与规划路径历史建议供给服务 (Domain Service)
    用于提供就地微调输入时的历史数据联想与候选预览 (QCompleter)
    """
    _recent_paths: List[str] = []
    _max_recent_paths: int = 50

    @classmethod
    def record_path(cls, path_str: str) -> None:
        if not path_str or not str(path_str).strip():
            return
        p_clean = str(Path(str(path_str).strip()))
        if p_clean in cls._recent_paths:
            cls._recent_paths.remove(p_clean)
        cls._recent_paths.insert(0, p_clean)
        if len(cls._recent_paths) > cls._max_recent_paths:
            cls._recent_paths = cls._recent_paths[:cls._max_recent_paths]

    @classmethod
    def get_category_suggestions(cls) -> List[str]:
        """
        获取分类候选建议（包含标准 8 大有序业务领域分类、用户自定义及自沉淀分类）
        """
        suggestions: List[str] = []
        try:
            from app.core.metadata_extractor import ORDERED_DOMAIN_SECTORS
            for s in ORDERED_DOMAIN_SECTORS:
                if s not in suggestions:
                    suggestions.append(s)
        except Exception:
            pass

        try:
            from app.core.category_manager import global_category_manager
            active_cats = global_category_manager.get_active()
            for c in active_cats:
                name = c.get("name", "")
                if name and name not in suggestions:
                    suggestions.append(name)
        except Exception:
            pass
        if "未分类/待人工确认" not in suggestions:
            suggestions.append("未分类/待人工确认")
        return suggestions

    @classmethod
    def get_path_suggestions(
        cls,
        dest_root: str,
        current_cat: str = "",
        app_name: str = ""
    ) -> List[str]:
        """
        获取规划路径候选建议（包含智能生成路径、现有物理子目录、历史归档路径）
        """
        suggestions: List[str] = []
        dest_p = Path(dest_root) if dest_root else Path(".")
        
        # 1. 推荐的标准模板规划路径
        if current_cat and app_name:
            rec_p = ArchiveDestinationPath.build(
                dest_root=dest_root,
                category=current_cat,
                entity_name=app_name,
                is_dir=True
            )
            suggestions.append(str(rec_p))

        # 2. 简化的主分类规划路径
        if current_cat:
            cat_p = ArchiveDestinationPath.build(
                dest_root=dest_root,
                category=current_cat,
                is_dir=False
            )
            if str(cat_p) not in suggestions:
                suggestions.append(str(cat_p))

        # 3. 目标根目录下实际已存在的物理子目录 (方便用户归拢到已有目录)
        try:
            if dest_p.exists() and dest_p.is_dir():
                for sub in sorted(dest_p.iterdir()):
                    if sub.is_dir() and not sub.name.startswith("."):
                        p_str = str(sub)
                        if p_str not in suggestions:
                            suggestions.append(p_str)
        except Exception:
            pass

        # 4. 历史记录
        for p in cls._recent_paths:
            if p not in suggestions:
                suggestions.append(p)

        return suggestions


@dataclass
class ArchivePlanningUnit:
    """
    统一归档规划实体单元模型 (Archive Planning Unit Domain Model)
    封装全景明细列表与 AI 树状预览中的归档规划实体，具备同构属性与字典访问能力
    """
    group_id: str = ""
    original_root: str = ""
    app_name: str = ""
    suggested_category: str = "未分类/待人工确认"
    effective_category: str = ""
    target_root: str = ""
    recommended_subpath: str = ""
    is_directory_group: bool = True
    sub_items: List[Dict[str, Any]] = field(default_factory=list)
    source: str = "离线规则"
    risk_level: str = "低风险"
    confidence: float = 1.0
    action: str = "建议归档"
    rationale: str = ""
    require_confirmation: bool = True
    source_umbrella: str = ""
    report_id: str = "-"
    task_id: str = "-"
    _extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.effective_category:
            self.effective_category = self.suggested_category

    @property
    def destination_path(self) -> ArchiveDestinationPath:
        return ArchiveDestinationPath(self.target_root)

    def update_category(self, new_cat: str, dest_root: str) -> None:
        self.effective_category = new_cat
        self.suggested_category = new_cat
        self.source = "User"
        self.require_confirmation = True
        dest_obj = ArchiveDestinationPath.build(
            dest_root=dest_root,
            category=new_cat,
            subpath=self.recommended_subpath,
            entity_name=Path(self.original_root).name,
            is_dir=self.is_directory_group
        )
        self.target_root = str(dest_obj)
        for sub in self.sub_items:
            rel = sub.get("relative_path", "")
            if rel and self.is_directory_group:
                sub["target_path"] = dest_obj.relative_join(rel)
            else:
                sub["target_path"] = dest_obj.relative_join(sub.get("name", Path(rel).name if rel else "unnamed"))

    def update_target_path(self, new_path: str) -> None:
        self.target_root = new_path
        self.source = "User"
        self.require_confirmation = True
        dest_obj = ArchiveDestinationPath(new_path)
        for sub in self.sub_items:
            rel = sub.get("relative_path", "")
            if rel and self.is_directory_group:
                sub["target_path"] = dest_obj.relative_join(rel)
            else:
                sub["target_path"] = dest_obj.relative_join(sub.get("name", Path(rel).name if rel else "unnamed"))

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if key in self._extra:
            return self._extra[key]
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if hasattr(self, key) and key != "_extra":
            setattr(self, key, value)
        else:
            self._extra[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        try:
            val = self[key]
            return val if val is not None else default
        except (KeyError, AttributeError):
            return default

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "group_id": self.group_id,
            "original_root": self.original_root,
            "app_name": self.app_name,
            "suggested_category": self.suggested_category,
            "effective_category": self.effective_category,
            "target_root": self.target_root,
            "recommended_subpath": self.recommended_subpath,
            "is_directory_group": self.is_directory_group,
            "sub_items": self.sub_items,
            "source": self.source,
            "risk_level": self.risk_level,
            "confidence": self.confidence,
            "action": self.action,
            "rationale": self.rationale,
            "require_confirmation": self.require_confirmation,
            "source_umbrella": self.source_umbrella,
            "report_id": self.report_id,
            "task_id": self.task_id,
        }
        if self._extra:
            d.update(self._extra)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ArchivePlanningUnit:
        if isinstance(data, cls):
            return data
        known_fields = {
            "group_id", "original_root", "app_name", "suggested_category",
            "effective_category", "target_root", "recommended_subpath",
            "is_directory_group", "sub_items", "source", "risk_level",
            "confidence", "action", "rationale", "require_confirmation",
            "source_umbrella", "report_id", "task_id"
        }
        kwargs = {}
        extra = {}
        for k, v in data.items():
            if k in known_fields:
                kwargs[k] = v
            else:
                extra[k] = v
        obj = cls(**kwargs)
        if extra:
            obj._extra.update(extra)
        return obj

