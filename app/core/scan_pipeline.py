"""
统一扫描计算管线 (Unified Scan Pipeline)

采用面向对象管线与策略模式 (Pipeline & Strategy Pattern):
1. ScanPipelineContext: 扫描会话上下文容器
2. ScanPipelineStep: 可插拔的流水线处理阶段抽象基类
3. FastMetadataDiscoveryStep: 流式遍历与三大原则狭义实体防御性剪枝
4. RedundancyHeuristicsStep: 冗余项识别与全景指标聚合
5. ScanPipeline: 管线编排器，支持分块流式发射 (Streaming Batching)
"""

from __future__ import annotations

import heapq
import os
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List, Optional, Set, Tuple

from app.config import app_config
from app.core.app_detector import AppDetector
from app.core.domain_models import ScannedAsset, ScanSessionSummary
from app.core.unified_scanner import UnifiedScanner
from app.utils.file_helper import (
    categorize_file_by_ext,
    format_size,
    get_heuristic_redundant_tag,
    is_system_critical_path,
)
from app.utils.logger import app_logger


@dataclass
class ScanPipelineContext:
    """管线流转上下文状态机"""
    target_paths: List[str]
    skip_system_protected: bool = True
    enable_duplicate_detection: bool = True
    prune_collectives: bool = True
    ignore_folders: List[str] = field(default_factory=list)
    min_top_file_size: int = 300 * 1024 * 1024
    cancel_check: Optional[Callable[[], bool]] = None
    progress_callback: Optional[Callable[[str, int, int], None]] = None
    batch_size: int = 500

    # 运行期产物
    start_time: float = field(default_factory=time.time)
    elapsed_seconds: float = 0.0
    total_files: int = 0
    total_bytes: int = 0
    skipped_ignored_count: int = 0
    scanned_assets: List[ScannedAsset] = field(default_factory=list)
    top_heap: List[Tuple[int, str, ScannedAsset]] = field(default_factory=list)
    size_candidates: Dict[int, List[ScannedAsset]] = field(default_factory=lambda: defaultdict(list))
    category_bytes: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    category_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    summary: Optional[ScanSessionSummary] = None

    def is_cancelled(self) -> bool:
        if self.cancel_check:
            return not self.cancel_check()
        return False


class ScanPipelineStep(ABC):
    """流水线处理步骤抽象基类"""
    @abstractmethod
    def execute(self, ctx: ScanPipelineContext) -> None:
        pass


class FastMetadataDiscoveryStep(ScanPipelineStep):
    """阶段一：高效流式元数据扫描与三大原则源头剪枝"""
    def execute(self, ctx: ScanPipelineContext) -> None:
        def _on_ignore(p):
            ctx.skipped_ignored_count += 1

        raw_units = UnifiedScanner.scan_directory(
            root_paths=ctx.target_paths,
            prune_collectives=ctx.prune_collectives,
            skip_system_protected=ctx.skip_system_protected,
            ignore_folders=ctx.ignore_folders,
            progress_callback=ctx.progress_callback,
            cancel_check=ctx.cancel_check,
            on_ignore_callback=_on_ignore,
        )

        for raw in raw_units:
            if ctx.is_cancelled():
                return
            asset = ScannedAsset.from_dict(raw.to_dict()) if hasattr(raw, "to_dict") else raw
            
            f_size = asset.size
            f_files = asset.file_count
            ctx.total_files += f_files
            ctx.total_bytes += f_size

            cat = asset.category
            ctx.category_bytes[cat] += f_size
            ctx.category_counts[cat] += 1

            if asset.is_collective:
                c_tag = asset.collective_type or "实体集体"
                asset.tag = f"原子保全 ({c_tag})"
                asset.reason = asset.reason or "检测为不可拆分原子实体集体，整盘保全"
                asset.phase_status = "阶段一已归类 (原子保全)"
            else:
                heuristic = get_heuristic_redundant_tag(asset.path, asset.name, f_size)
                f_tag = heuristic[0] if heuristic else "独立资产项"
                f_reason = heuristic[1] if heuristic else f"标准{cat}单项文件"
                f_phase = f"规则识别 ({heuristic[0]})" if heuristic else "阶段一已归类"
                f_is_rec = heuristic[2] if (heuristic and len(heuristic) > 2) else False

                if asset.metadata and asset.metadata.get("is_obfuscated_name"):
                    f_tag = "已还原真实软件铭牌"
                    s_name = asset.metadata.get("software_name") or asset.name
                    s_ver = asset.metadata.get("product_version") or ""
                    ver_str = f" (v{s_ver})" if s_ver else ""
                    f_reason = f"从 PE/安装包元数据解析真实名称: {s_name}{ver_str}，原始文件名含哈希下载特征"
                    f_phase = "阶段一已归类 (真实铭牌确权)"
                    f_is_rec = False
                elif asset.is_snapshot_backup:
                    f_tag = "备份快照资产"
                    f_reason = "属于历史备份大抽屉归档资产，免除冗余误判"
                    f_phase = "阶段一已归类 (同源同宿保全)"
                    f_is_rec = False

                asset.tag = f_tag
                asset.reason = f_reason
                asset.phase_status = f_phase
                asset.is_recommended = f_is_rec

            # Top 100 最小堆筛选
            if f_size >= ctx.min_top_file_size:
                if len(ctx.top_heap) < 100:
                    heapq.heappush(ctx.top_heap, (f_size, asset.path, asset))
                else:
                    if f_size > ctx.top_heap[0][0]:
                        heapq.heappushpop(ctx.top_heap, (f_size, asset.path, asset))

            # 查重候选
            if ctx.enable_duplicate_detection and f_size > 1024:
                ctx.size_candidates[f_size].append(asset)

            ctx.scanned_assets.append(asset)


class RedundancyHeuristicsStep(ScanPipelineStep):
    """阶段二：全景统计汇总与指标组装"""
    def execute(self, ctx: ScanPipelineContext) -> None:
        ctx.elapsed_seconds = round(time.time() - ctx.start_time, 2)
        top_100_files = [item[2] for item in sorted(ctx.top_heap, key=lambda x: x[0], reverse=True)]

        collective_items = [f for f in ctx.scanned_assets if f.is_collective]
        standalone_items = [f for f in ctx.scanned_assets if not f.is_collective]

        cat_stats = {
            cat: {
                "bytes": cb,
                "count": ctx.category_counts[cat],
                "percent": round((cb / ctx.total_bytes * 100), 2) if ctx.total_bytes > 0 else 0.0,
            }
            for cat, cb in sorted(ctx.category_bytes.items(), key=lambda x: x[1], reverse=True)
        }

        ctx.summary = ScanSessionSummary(
            task_id=f"scan_{int(ctx.start_time)}",
            total_files=ctx.total_files,
            total_bytes=ctx.total_bytes,
            standalone_file_count=len(standalone_items),
            collective_count=len(collective_items),
            elapsed_seconds=ctx.elapsed_seconds,
            target_paths=ctx.target_paths,
            category_stats=cat_stats,
            top_100_files=top_100_files,
            all_scanned_files=ctx.scanned_assets,
        )


class ScanPipeline:
    """
    通用扫描管线编排器 (Scan Pipeline Orchestrator)
    """
    def __init__(self, steps: Optional[List[ScanPipelineStep]] = None):
        self.steps = steps or [
            FastMetadataDiscoveryStep(),
            RedundancyHeuristicsStep(),
        ]

    def run(self, ctx: ScanPipelineContext) -> ScanSessionSummary:
        """同步运行完整管线"""
        for step in self.steps:
            if ctx.is_cancelled():
                break
            step.execute(ctx)
        return ctx.summary or ScanSessionSummary()

    @classmethod
    def stream_batches(cls, ctx: ScanPipelineContext) -> Generator[List[ScannedAsset], None, ScanSessionSummary]:
        """
        流式分块产生资产流，降低巨量数据渲染内存峰值
        """
        pipeline = cls()
        pipeline.run(ctx)
        batch: List[ScannedAsset] = []
        for asset in ctx.scanned_assets:
            batch.append(asset)
            if len(batch) >= ctx.batch_size:
                yield batch
                batch = []
        if batch:
            yield batch
        return ctx.summary or ScanSessionSummary()
