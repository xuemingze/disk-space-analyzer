import os
import heapq
import time
import threading
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QThread, Signal

from app.config import app_config
from app.core.hash_cache import hash_cache
from app.utils.file_helper import (
    categorize_file_by_ext,
    is_system_critical_path,
    get_heuristic_redundant_tag,
    calculate_file_hash,
    calculate_partial_hash,
    format_size
)
from app.utils.logger import app_logger


class ScanWorker(QThread):
    """
    分阶段、多线程并发、带持久化缓存的高性能磁盘空间与查重扫描引擎
    """
    # 阶段一信号：文件系统快速索引与大小统计完成 (立即展示图表与 Top100)
    phase1_completed = Signal(dict)
    
    # 阶段二信号：哈希比对实时进度与阶段二完成
    phase2_progress = Signal(object, object, str, int, int, int) # (已处理字节, 候选总字节, 速度, ETA秒, 已比对组, 总组数)
    phase2_completed = Signal(dict)
    
    # 阶段三信号：全量汇总与分析完成
    phase3_completed = Signal(dict)
    
    # 全局状态信号
    progress_updated = Signal(str, object, object)  # (当前扫描目录, 已扫描文件数, 已扫描总字节数)
    phase_changed = Signal(str)                     # 阶段提示
    scan_error = Signal(str)                        # 异常

    def __init__(
        self,
        target_paths: List[str],
        enable_duplicate_detection: bool = True,
        hash_algorithm: str = "md5",
        skip_system_protected: bool = True,
        concurrency: int = 4,
        task_id: Optional[str] = None,
        parent=None
    ):
        super().__init__(parent)
        self.target_paths = [os.path.abspath(p) for p in target_paths if os.path.exists(p)]
        self.enable_duplicate_detection = enable_duplicate_detection
        self.hash_algorithm = hash_algorithm.lower()
        self.skip_system_protected = skip_system_protected
        self.concurrency = max(1, min(16, concurrency))
        self.task_id = task_id
        
        # 线程控制标志
        self._is_running = True
        self._pause_event = threading.Event()
        self._pause_event.set() # 默认非暂停

    def pause(self):
        """暂停扫描"""
        self._pause_event.clear()

    def resume(self):
        """恢复扫描"""
        self._pause_event.set()

    def cancel(self):
        """取消中止扫描"""
        self._is_running = False
        self._pause_event.set() # 唤醒以快速退出

    def stop(self):
        self.cancel()

    def run(self):
        try:
            total_start_time = time.time()
            app_logger.info(f"启动扫描任务: 目标={self.target_paths}, 并发={self.concurrency}, 查重={self.enable_duplicate_detection}")

            # ==========================================
            # 阶段一：快速文件系统遍历与大小桶分类
            # ==========================================
            self.phase_changed.emit("阶段 1/3: 正在快速遍历目录与统计空间结构 (os.scandir 高速索引)...")
            p1_start = time.time()
            
            total_files = 0
            total_bytes = 0
            category_bytes = defaultdict(int)
            category_counts = defaultdict(int)
            top_heap = []
            size_candidates = defaultdict(list)
            all_scanned_files = []
            
            last_ui_update = time.time()
            throttle_interval = app_config.get("perf_options", "ui_throttle_ms", default=60) / 1000.0

            for root_path in self.target_paths:
                if not self._is_running:
                    break
                
                # 使用递归 os.scandir 高效遍历
                self._fast_scandir_traverse(
                    root_path=root_path,
                    total_files_ref=[total_files],
                    total_bytes_ref=[total_bytes],
                    category_bytes=category_bytes,
                    category_counts=category_counts,
                    top_heap=top_heap,
                    size_candidates=size_candidates,
                    all_scanned_files=all_scanned_files,
                    last_ui_update_ref=[last_ui_update],
                    throttle_interval=throttle_interval
                )
                total_files = len(all_scanned_files)
                total_bytes = sum(f["size"] for f in all_scanned_files)

            if not self._is_running:
                app_logger.info("扫描在阶段一被用户取消")
                return

            p1_duration = round(time.time() - p1_start, 2)
            top_100_files = [item[2] for item in sorted(top_heap, key=lambda x: x[0], reverse=True)]

            # 筛选出有重复可能的大小候选组 (仅统计大小大于 1KB 的文件)
            dup_candidates_count = sum(len(group) for size, group in size_candidates.items() if len(group) > 1 and size > 1024)
            dup_candidate_groups_count = len([g for s, g in size_candidates.items() if len(g) > 1 and s > 1024])

            # 封装阶段一成果并立即发出信号
            phase1_result = {
                "elapsed_seconds": p1_duration,
                "total_files": total_files,
                "total_bytes": total_bytes,
                "category_stats": {
                    cat: {
                        "bytes": c_bytes,
                        "count": category_counts[cat],
                        "percent": round((c_bytes / total_bytes * 100), 2) if total_bytes > 0 else 0.0
                    }
                    for cat, c_bytes in sorted(category_bytes.items(), key=lambda x: x[1], reverse=True)
                },
                "top_100_files": top_100_files,
                "dup_candidate_files_count": dup_candidates_count,
                "dup_candidate_groups_count": dup_candidate_groups_count
            }
            
            app_logger.info(f"阶段一完成: 耗时 {p1_duration}s, 发现 {total_files} 个文件, 待比对候选组 {dup_candidate_groups_count} 组")
            self.phase1_completed.emit(phase1_result)

            # ==========================================
            # 阶段二：多线程采样与全量哈希深度精准查重
            # ==========================================
            duplicate_groups = {}
            duplicate_wasted_bytes = 0
            file_to_duplicate_group = {}
            p2_duration = 0.0
            cache_hits = 0

            if self.enable_duplicate_detection and self._is_running:
                self.phase_changed.emit(f"阶段 2/3: 正在进行大小初筛与分块哈希深度比对 (并发数: {self.concurrency})...")
                p2_start = time.time()
                
                # 过滤出大小相同的组
                candidate_groups = [group for size, group in size_candidates.items() if len(group) > 1 and size > 1024]
                total_cand_groups = len(candidate_groups)
                total_cand_bytes = sum(g[0]["size"] * len(g) for g in candidate_groups)
                
                processed_cand_bytes = 0
                checked_groups_count = 0
                group_id_counter = 1
                
                hash_speed_timer = time.time()
                bytes_since_last_calc = 0

                # 采用 ThreadPool 并发处理哈希计算
                use_cache = app_config.get("perf_options", "use_hash_cache", default=True)

                for group in candidate_groups:
                    if not self._is_running:
                        break
                    self._pause_event.wait()

                    # 1. 第一小步：样本采样哈希 (头部 8KB)
                    sample_hash_map = defaultdict(list)
                    for finfo in group:
                        fpath = finfo["path"]
                        s_hash, _ = hash_cache.get_hashes(fpath, finfo["size"], finfo["mtime"], self.hash_algorithm) if use_cache else (None, None)
                        if s_hash:
                            cache_hits += 1
                        else:
                            s_hash = calculate_partial_hash(fpath)
                            if use_cache and s_hash:
                                hash_cache.put_hashes(fpath, finfo["size"], finfo["mtime"], self.hash_algorithm, s_hash, None)
                        
                        if s_hash:
                            sample_hash_map[s_hash].append(finfo)

                    # 2. 第二小步：对样本哈希一致的子组进行全量分块哈希
                    for s_hash, sample_group in sample_hash_map.items():
                        if len(sample_group) <= 1:
                            continue

                        # 并发分块计算完整哈希
                        full_hash_map = defaultdict(list)
                        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                            future_to_finfo = {}
                            for finfo in sample_group:
                                fpath = finfo["path"]
                                _, f_hash = hash_cache.get_hashes(fpath, finfo["size"], finfo["mtime"], self.hash_algorithm) if use_cache else (None, None)
                                if f_hash:
                                    cache_hits += 1
                                    full_hash_map[f_hash].append(finfo)
                                else:
                                    future = executor.submit(calculate_file_hash, fpath, self.hash_algorithm)
                                    future_to_finfo[future] = finfo

                            for future in as_completed(future_to_finfo):
                                if not self._is_running:
                                    break
                                finfo = future_to_finfo[future]
                                f_hash = future.result()
                                if f_hash:
                                    full_hash_map[f_hash].append(finfo)
                                    if use_cache:
                                        hash_cache.put_hashes(finfo["path"], finfo["size"], finfo["mtime"], self.hash_algorithm, None, f_hash)

                        # 记录确认重复的组
                        for f_hash, dup_files in full_hash_map.items():
                            if len(dup_files) > 1:
                                gid = f"DUP-{group_id_counter:04d}"
                                duplicate_groups[gid] = dup_files
                                group_id_counter += 1
                                
                                single_size = dup_files[0]["size"]
                                duplicate_wasted_bytes += single_size * (len(dup_files) - 1)
                                
                                for d_idx, df in enumerate(dup_files):
                                    file_to_duplicate_group[df["path"]] = {
                                        "group_id": gid,
                                        "is_original": (d_idx == 0),
                                        "copy_index": d_idx + 1,
                                        "total_copies": len(dup_files),
                                        "hash": f_hash
                                    }

                    # 更新进度与速度
                    group_bytes = group[0]["size"] * len(group)
                    processed_cand_bytes += group_bytes
                    bytes_since_last_calc += group_bytes
                    checked_groups_count += 1

                    now = time.time()
                    if now - hash_speed_timer >= 0.5:
                        duration = now - hash_speed_timer
                        speed_bytes_sec = bytes_since_last_calc / duration
                        speed_str = f"{format_size(int(speed_bytes_sec))}/s"
                        remaining_bytes = max(0, total_cand_bytes - processed_cand_bytes)
                        eta_sec = int(remaining_bytes / speed_bytes_sec) if speed_bytes_sec > 0 else 0
                        
                        self.phase2_progress.emit(
                            processed_cand_bytes, total_cand_bytes, speed_str, eta_sec, checked_groups_count, total_cand_groups
                        )
                        hash_speed_timer = now
                        bytes_since_last_calc = 0

                p2_duration = round(time.time() - p2_start, 2)
                app_logger.info(f"阶段二完成: 耗时 {p2_duration}s, 发现确认重复组 {len(duplicate_groups)} 组, 缓存命中 {cache_hits} 次")

            phase2_result = {
                "elapsed_seconds": p2_duration,
                "duplicate_groups_count": len(duplicate_groups),
                "duplicate_wasted_bytes": duplicate_wasted_bytes,
                "cache_hits": cache_hits
            }
            self.phase2_completed.emit(phase2_result)

            if not self._is_running:
                return

            # ==========================================
            # 阶段三：冗余聚合、启发式标记与全量汇总
            # ==========================================
            self.phase_changed.emit("阶段 3/3: 正在汇总全景分析数据并生成智能治理建议...")
            p3_start = time.time()
            
            redundant_list = []
            reclaimable_bytes = 0
            
            for finfo in all_scanned_files:
                fpath = finfo["path"]
                dup_info = file_to_duplicate_group.get(fpath)
                heuristic = get_heuristic_redundant_tag(fpath)
                
                is_duplicate = dup_info is not None
                is_duplicate_copy = (dup_info is not None and not dup_info["is_original"])
                
                # 状态标记
                if is_duplicate or heuristic is not None:
                    tag = "重复副本" if is_duplicate_copy else ("重复原件" if is_duplicate else heuristic[0])
                    reason = f"与同组副本内容哈希相同 ({dup_info['group_id']})" if is_duplicate_copy else (
                        f"作为查重基准源 ({dup_info['group_id']})" if is_duplicate else heuristic[1]
                    )
                    
                    is_recommended = is_duplicate_copy or (heuristic is not None and heuristic[0] in ["安全可清理", "临时与日志", "冗余归档包"])
                    
                    item_dict = {
                        "name": finfo["name"],
                        "path": fpath,
                        "size": finfo["size"],
                        "category": finfo["category"],
                        "ext": finfo["ext"],
                        "mtime": finfo["mtime"],
                        "tag": tag,
                        "reason": reason,
                        "is_duplicate": is_duplicate,
                        "duplicate_group_id": dup_info["group_id"] if dup_info else "",
                        "is_duplicate_copy": is_duplicate_copy,
                        "is_recommended": is_recommended,
                        "phase_status": "哈希已确认" if is_duplicate else "规则已识别"
                    }
                    redundant_list.append(item_dict)
                    
                    if is_recommended:
                        reclaimable_bytes += finfo["size"]

            total_elapsed = round(time.time() - total_start_time, 2)

            full_payload = {
                "target_paths": self.target_paths,
                "total_elapsed_seconds": total_elapsed,
                "phase1_duration": p1_duration,
                "phase2_duration": p2_duration,
                "total_files": total_files,
                "total_bytes": total_bytes,
                "category_stats": phase1_result["category_stats"],
                "top_100_files": top_100_files,
                "redundant_files": sorted(redundant_list, key=lambda x: x["size"], reverse=True),
                "duplicate_groups_count": len(duplicate_groups),
                "duplicate_wasted_bytes": duplicate_wasted_bytes,
                "reclaimable_bytes": reclaimable_bytes,
                "cache_hits": cache_hits
            }

            self.phase3_completed.emit(full_payload)
            app_logger.info(f"全流程扫描与分析完毕，总耗时 {total_elapsed}s")

        except Exception as e:
            app_logger.exception("扫描引擎运行异常")
            self.scan_error.emit(str(e))

    def _fast_scandir_traverse(
        self,
        root_path: str,
        total_files_ref: list,
        total_bytes_ref: list,
        category_bytes: dict,
        category_counts: dict,
        top_heap: list,
        size_candidates: dict,
        all_scanned_files: list,
        last_ui_update_ref: list,
        throttle_interval: float
    ):
        """利用 os.scandir 进行高性能递归遍历"""
        stack = [root_path]
        
        while stack and self._is_running:
            self._pause_event.wait()
            curr_dir = stack.pop()
            
            # 检查系统核心目录保护
            if self.skip_system_protected and is_system_critical_path(curr_dir):
                continue
                
            try:
                with os.scandir(curr_dir) as it:
                    for entry in it:
                        if not self._is_running:
                            break
                            
                        # 忽略系统隐藏临时目录
                        if entry.name.startswith("$") and entry.name != "$Recycle.Bin":
                            continue

                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                            elif entry.is_file(follow_symlinks=False):
                                stat_res = entry.stat()
                                f_size = int(stat_res.st_size)
                                mtime = stat_res.st_mtime
                                
                                total_files_ref[0] += 1
                                total_bytes_ref[0] += f_size
                                
                                category = categorize_file_by_ext(Path(entry.name))
                                category_bytes[category] += f_size
                                category_counts[category] += 1
                                
                                finfo = {
                                    "name": entry.name,
                                    "path": entry.path,
                                    "size": f_size,
                                    "category": category,
                                    "mtime": mtime,
                                    "ext": Path(entry.name).suffix.lower()
                                }
                                
                                # Top 100 最小堆
                                if len(top_heap) < 100:
                                    heapq.heappush(top_heap, (f_size, finfo["path"], finfo))
                                else:
                                    if f_size > top_heap[0][0]:
                                        heapq.heappushpop(top_heap, (f_size, finfo["path"], finfo))
                                        
                                if self.enable_duplicate_detection and f_size > 1024:
                                    size_candidates[f_size].append(finfo)
                                    
                                all_scanned_files.append(finfo)
                        except (PermissionError, FileNotFoundError, OSError):
                            continue
            except (PermissionError, FileNotFoundError, OSError):
                continue

            # 进度节流更新
            now = time.time()
            if now - last_ui_update_ref[0] >= throttle_interval:
                self.progress_updated.emit(curr_dir, total_files_ref[0], total_bytes_ref[0])
                last_ui_update_ref[0] = now
