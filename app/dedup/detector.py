"""
app/dedup/detector.py
多源目录索引构建、三阶哈希查重与拓扑冲突检测器
基于 UnifiedScanner 底座，贯通防御性剪枝、上位大抽屉赋权与同源同宿映射
"""
import os
import time
from collections import defaultdict
from typing import List, Dict, Optional, Callable, Set, Tuple

from app.core.unified_scanner import UnifiedScanner, AssetUnit
from app.dedup.models import (
    DedupScanConfig,
    DedupScanResult,
    DedupFileItem,
    DedupGroup,
    CollisionItem
)
from app.dedup.hasher import DedupHasher
from app.utils.lock_detector import is_file_locked_or_in_use
from app.utils.logger import app_logger


class DedupDetector:
    """多源目录查重与冲突检测引擎"""

    def __init__(self, config: DedupScanConfig):
        self.config = config

    def scan_and_analyze(
        self,
        progress_cb: Optional[Callable[[str, int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> DedupScanResult:
        """
        执行完整的全景查重与冲突分析流程
        progress_cb 格式: (阶段名, 当前处理数, 总数, 描述文本)
        """
        valid_sources = [os.path.normpath(s) for s in self.config.source_dirs if os.path.exists(s)]
        if not valid_sources:
            return DedupScanResult()

        def _is_cancelled():
            return cancel_check is not None and not cancel_check()

        # ---------------------------------------------------------
        # 阶段 1: 基于 UnifiedScanner 底座多源目录并发/快速扫描
        # ---------------------------------------------------------
        if progress_cb:
            progress_cb("phase1_scan", 0, len(valid_sources), "正在扫描源目录并构建资产元数据...")

        all_file_items: List[DedupFileItem] = []
        total_scanned_bytes = 0

        # 对每个源目录独立扫描以准确计算相对路径 rel_path
        for s_idx, src in enumerate(valid_sources):
            if _is_cancelled():
                return DedupScanResult()

            if progress_cb:
                progress_cb("phase1_scan", s_idx + 1, len(valid_sources), f"正在遍历源目录: {os.path.basename(src)}")

            asset_units = UnifiedScanner.scan_directory(
                root_paths=[src],
                prune_collectives=self.config.prune_collectives,
                skip_system_protected=self.config.skip_system_protected,
                ignore_folders=self.config.ignore_folders,
                cancel_check=cancel_check
            )

            for unit in asset_units:
                if _is_cancelled():
                    return DedupScanResult()

                # 如果是原子狭义集体目录，记录为集体资产 (可选跳过逐文件查重以防破坏集体)
                if unit.is_collective:
                    # 集体目录作为整体记录
                    rel_p = os.path.relpath(unit.path, src)
                    item = DedupFileItem(
                        path=unit.path,
                        name=unit.name,
                        rel_path=rel_p,
                        size=unit.size,
                        mtime=unit.mtime,
                        source_dir=src,
                        category=unit.category,
                        ext="",
                        is_collective=True
                    )
                    all_file_items.append(item)
                    total_scanned_bytes += unit.size
                else:
                    # 单文件
                    if unit.size < self.config.min_file_size:
                        continue
                    rel_p = os.path.relpath(unit.path, src)
                    item = DedupFileItem(
                        path=unit.path,
                        name=unit.name,
                        rel_path=rel_p,
                        size=unit.size,
                        mtime=unit.mtime,
                        source_dir=src,
                        category=unit.category,
                        ext=unit.ext,
                        is_collective=False
                    )
                    all_file_items.append(item)
                    total_scanned_bytes += unit.size

        if not all_file_items or _is_cancelled():
            return DedupScanResult(
                total_files=len(all_file_items),
                total_bytes=total_scanned_bytes,
                scanned_sources=valid_sources
            )

        # ---------------------------------------------------------
        # 阶段 2: 一阶漏斗 - 文件精确字节大小聚类初筛 (Size Filter)
        # ---------------------------------------------------------
        if progress_cb:
            progress_cb("phase2_size", 0, len(all_file_items), "按文件字节体积进行一阶初筛...")

        size_groups: Dict[int, List[DedupFileItem]] = defaultdict(list)
        for item in all_file_items:
            size_groups[item.size].append(item)

        candidate_stage2: List[DedupFileItem] = []
        unique_files: List[DedupFileItem] = []

        for sz, group in size_groups.items():
            if len(group) == 1:
                unique_files.append(group[0])
            else:
                candidate_stage2.extend(group)

        app_logger.info("一阶初筛完成: 总文件 %d, 候选重复数 %d, 独立大小 %d",
                        len(all_file_items), len(candidate_stage2), len(unique_files))

        if not candidate_stage2 or _is_cancelled():
            return DedupScanResult(
                total_files=len(all_file_items),
                total_bytes=total_scanned_bytes,
                unique_files=unique_files,
                scanned_sources=valid_sources
            )

        # ---------------------------------------------------------
        # 阶段 3: 二阶漏斗 - 稀疏采样哈希 (Sparse Sample Hash)
        # ---------------------------------------------------------
        total_c2 = len(candidate_stage2)
        if progress_cb:
            progress_cb("phase3_sample", 0, total_c2, f"计算稀疏采样摘要 (共 {total_c2} 项)...")

        # 同 size 下根据 sample_hash 聚类
        sample_hash_map: Dict[Tuple[int, str], List[DedupFileItem]] = defaultdict(list)
        for idx, item in enumerate(candidate_stage2):
            if _is_cancelled():
                return DedupScanResult()

            if item.is_collective:
                # 狭义实体目录不参与逐文件单字节采样哈希，归为唯一资产
                unique_files.append(item)
                continue

            s_hash = DedupHasher.compute_sample_hash(
                item.path,
                item.size,
                item.mtime,
                algorithm=self.config.hash_algorithm
            )
            item.sample_hash = s_hash
            if s_hash:
                sample_hash_map[(item.size, s_hash)].append(item)
            else:
                unique_files.append(item)

            if progress_cb and (idx % 50 == 0 or idx == total_c2 - 1):
                progress_cb("phase3_sample", idx + 1, total_c2, f"正在计算二阶采样摘要: {item.name}")

        candidate_stage3: List[DedupFileItem] = []
        for key, group in sample_hash_map.items():
            if len(group) == 1:
                unique_files.append(group[0])
            else:
                candidate_stage3.extend(group)

        app_logger.info("二阶采样初筛完成: 候选复核数 %d 项", len(candidate_stage3))

        if not candidate_stage3 or _is_cancelled():
            return DedupScanResult(
                total_files=len(all_file_items),
                total_bytes=total_scanned_bytes,
                unique_files=unique_files,
                scanned_sources=valid_sources
            )

        # ---------------------------------------------------------
        # 阶段 4: 三阶漏斗 - 完整校验哈希 (Full SHA-256)
        # ---------------------------------------------------------
        total_c3 = len(candidate_stage3)
        if progress_cb:
            progress_cb("phase4_full", 0, total_c3, f"流式计算完整哈希 (共 {total_c3} 项)...")

        full_hash_map: Dict[Tuple[int, str], List[DedupFileItem]] = defaultdict(list)
        for idx, item in enumerate(candidate_stage3):
            if _is_cancelled():
                return DedupScanResult()

            f_hash = DedupHasher.compute_full_hash(
                item.path,
                item.size,
                item.mtime,
                algorithm=self.config.hash_algorithm,
                cancel_check=cancel_check
            )
            item.full_hash = f_hash
            if f_hash:
                full_hash_map[(item.size, f_hash)].append(item)
            else:
                unique_files.append(item)

            if progress_cb and (idx % 10 == 0 or idx == total_c3 - 1):
                progress_cb("phase4_full", idx + 1, total_c3, f"正在计算完整哈希校验码: {item.name}")

        duplicate_groups: List[DedupGroup] = []
        g_counter = 0

        for (sz, f_hash), group in full_hash_map.items():
            if len(group) == 1:
                unique_files.append(group[0])
            else:
                g_counter += 1
                group_id = f"DEDUP_GRP_{g_counter:04d}"
                rec_keep = self._recommend_keep_item(group, valid_sources)
                d_group = DedupGroup(
                    group_id=group_id,
                    size=sz,
                    full_hash=f_hash,
                    items=group,
                    recommended_keep_path=rec_keep
                )
                duplicate_groups.append(d_group)

        # 按浪费体积倒序排列
        duplicate_groups.sort(key=lambda g: g.wasted_bytes, reverse=True)

        # ---------------------------------------------------------
        # 阶段 5: 拓扑冲突分析与文件排他占用探针
        # ---------------------------------------------------------
        if progress_cb:
            progress_cb("phase5_collision", 0, len(all_file_items), "分析同名异内容冲突与检测文件独占锁...")

        collisions = self._detect_collisions(all_file_items)

        # 对所有待处理的文件执行排他锁与伴生锁探针
        files_to_probe: Set[str] = set()
        for g in duplicate_groups:
            for it in g.items:
                files_to_probe.add(it.path)
        for col in collisions:
            for it in col.files:
                files_to_probe.add(it.path)

        for it in all_file_items:
            if it.path in files_to_probe:
                is_locked, lock_reason = is_file_locked_or_in_use(it.path, min_cooldown_seconds=0.5)
                it.is_locked = is_locked
                it.lock_reason = lock_reason

        return DedupScanResult(
            scan_time=time.time(),
            total_files=len(all_file_items),
            total_bytes=total_scanned_bytes,
            duplicate_groups=duplicate_groups,
            collisions=collisions,
            unique_files=unique_files,
            scanned_sources=valid_sources
        )

    def _recommend_keep_item(self, group: List[DedupFileItem], valid_sources: List[str]) -> str:
        """
        根据用户的保留偏好，推荐保留的单份副本路径
        """
        pref = self.config.dedup_keep_preference
        if pref == "keep_newest":
            # 保留最新修改的
            best = max(group, key=lambda it: it.mtime)
            return best.path
        elif pref == "keep_oldest":
            # 保留最早创建/修改的
            best = min(group, key=lambda it: it.mtime)
            return best.path
        elif pref == "keep_shortest_path":
            # 保留路径层级最短的
            best = min(group, key=lambda it: len(it.path))
            return best.path
        else:
            # 默认 keep_primary: 优先保留属于主源目录 (valid_sources[0]) 的文件
            primary_src = valid_sources[0] if valid_sources else ""
            for it in group:
                if it.source_dir == primary_src:
                    return it.path
            return group[0].path

    def _detect_collisions(self, all_items: List[DedupFileItem]) -> List[CollisionItem]:
        """
        检测相对路径相同但内容/哈希不同的文件冲突 (同名异内容冲突)
        """
        rel_map: Dict[str, List[DedupFileItem]] = defaultdict(list)
        for it in all_items:
            # 标准化相对路径大小写
            norm_rel = os.path.normpath(it.rel_path).lower()
            rel_map[norm_rel].append(it)

        collisions: List[CollisionItem] = []
        for norm_rel, items in rel_map.items():
            if len(items) <= 1:
                continue

            # 检查这几个同名文件的内容是否不同
            hashes = set()
            for it in items:
                h = it.full_hash or it.sample_hash or f"size_{it.size}"
                hashes.add(h)

            if len(hashes) > 1:
                # 相对路径相同，但哈希/内容不同 -> 构成冲突！
                collisions.append(CollisionItem(
                    rel_path=items[0].rel_path,
                    files=items,
                    suggested_action="rename"
                ))

        return collisions
