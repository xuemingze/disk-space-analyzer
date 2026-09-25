import os
import time
import heapq
import threading
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QThread, Signal, QObject

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


class BaseScanTask(QThread):
    """后台任务基类：提供统一的生命周期与状态控制(支持暂停/恢复/取消)"""
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_running = True
        self._pause_event = threading.Event()
        self._pause_event.set()

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    def cancel(self):
        self._is_running = False
        self._pause_event.set()

    def check_pause_cancel(self) -> bool:
        if not self._is_running:
            return False
        self._pause_event.wait()
        return self._is_running


class DirectoryScanTask(BaseScanTask):
    """阶段一：轻量级目录遍历与元数据收集"""
    progress_updated = Signal(str, object, object)
    finished_ok = Signal(dict)

    def __init__(self, target_paths, skip_system_protected, enable_duplicate_detection, ignore_folders=None, parent=None):
        super().__init__(parent)
        self.target_paths = target_paths
        self.skip_system_protected = skip_system_protected
        self.enable_duplicate_detection = enable_duplicate_detection
        import os
        self.ignore_folders = [os.path.normcase(os.path.normpath(p)) for p in (ignore_folders or []) if p.strip()]

    def _is_ignored(self, current_dir: str) -> bool:
        import os
        if not self.ignore_folders: return False
        c_norm = os.path.normcase(os.path.normpath(current_dir))
        for ig in self.ignore_folders:
            if c_norm == ig or c_norm.startswith(ig + os.sep):
                return True
        return False

    def run(self):
        try:
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
                if not self.check_pause_cancel(): return
                stack = [root_path]
                while stack and self.check_pause_cancel():
                    curr_dir = stack.pop()
                    if self.skip_system_protected and is_system_critical_path(curr_dir):
                        continue
                    if self._is_ignored(curr_dir):
                        if not hasattr(self, 'skipped_ignored_count'): self.skipped_ignored_count = 0
                        self.skipped_ignored_count += 1
                        continue
                    try:
                        with os.scandir(curr_dir) as it:
                            for entry in it:
                                if not self.check_pause_cancel(): return
                                if entry.name.startswith("$") and entry.name != "$Recycle.Bin":
                                    continue
                                try:
                                    if entry.is_dir(follow_symlinks=False):
                                        stack.append(entry.path)
                                    elif entry.is_file(follow_symlinks=False):
                                        stat_res = entry.stat()
                                        f_size = int(stat_res.st_size)
                                        mtime = stat_res.st_mtime
                                        total_files += 1
                                        total_bytes += f_size
                                        
                                        category = categorize_file_by_ext(Path(entry.name))
                                        category_bytes[category] += f_size
                                        category_counts[category] += 1
                                        
                                        finfo = {
                                            "name": entry.name, "path": entry.path, "size": f_size,
                                            "category": category, "mtime": mtime, "ext": Path(entry.name).suffix.lower(),
                                            "scan_root": root_path
                                        }
                                        
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

                    now = time.time()
                    if now - last_ui_update >= throttle_interval:
                        self.progress_updated.emit(curr_dir, total_files, total_bytes)
                        last_ui_update = now
                        time.sleep(0.001)

            p1_duration = round(time.time() - p1_start, 2)
            top_100_files = [item[2] for item in sorted(top_heap, key=lambda x: x[0], reverse=True)]
            dup_candidates_count = sum(len(group) for size, group in size_candidates.items() if len(group) > 1 and size > 1024)
            dup_candidate_groups_count = len([g for s, g in size_candidates.items() if len(g) > 1 and s > 1024])

            self.finished_ok.emit({
                "elapsed_seconds": p1_duration,
                "skipped_ignored_count": getattr(self, 'skipped_ignored_count', 0),
                "total_files": total_files,
                "total_bytes": total_bytes,
                "category_stats": {
                    cat: {"bytes": cb, "count": category_counts[cat], "percent": round((cb/total_bytes*100), 2) if total_bytes>0 else 0.0}
                    for cat, cb in sorted(category_bytes.items(), key=lambda x: x[1], reverse=True)
                },
                "top_100_files": top_100_files,
                "dup_candidate_files_count": dup_candidates_count,
                "dup_candidate_groups_count": dup_candidate_groups_count,
                "all_scanned_files": all_scanned_files,
                "size_candidates": size_candidates
            })
        except Exception as e:
            app_logger.exception("DirectoryScanTask error")
            self.error.emit(str(e))


class HashTask(BaseScanTask):
    """阶段二：并发哈希比对 (全局单一 ThreadPool 避免频繁创建销毁)"""
    phase2_progress = Signal(object, object, str, int, int, int)
    finished_ok = Signal(dict)

    def __init__(self, size_candidates, concurrency, hash_algorithm, parent=None):
        super().__init__(parent)
        self.size_candidates = size_candidates
        self.concurrency = concurrency
        self.hash_algorithm = hash_algorithm

    def run(self):
        try:
            p2_start = time.time()
            duplicate_groups = {}
            duplicate_wasted_bytes = 0
            file_to_duplicate_group = {}
            cache_hits = 0
            
            candidate_groups = [group for size, group in self.size_candidates.items() if len(group) > 1 and size > 1024]
            total_cand_groups = len(candidate_groups)
            total_cand_bytes = sum(g[0]["size"] * len(g) for g in candidate_groups)
            
            processed_cand_bytes = 0
            checked_groups_count = 0
            group_id_counter = 1
            hash_speed_timer = time.time()
            bytes_since_last_calc = 0
            
            use_cache = app_config.get("perf_options", "use_hash_cache", default=True)

            with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                for group in candidate_groups:
                    if not self.check_pause_cancel(): return
                    
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

                    for s_hash, sample_group in sample_hash_map.items():
                        if not self.check_pause_cancel(): return
                        if len(sample_group) <= 1:
                            continue
                            
                        full_hash_map = defaultdict(list)
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
                            if not self.check_pause_cancel(): return
                            finfo = future_to_finfo[future]
                            f_hash = future.result()
                            if f_hash:
                                full_hash_map[f_hash].append(finfo)
                                if use_cache:
                                    hash_cache.put_hashes(finfo["path"], finfo["size"], finfo["mtime"], self.hash_algorithm, None, f_hash)

                        for f_hash, dup_files in full_hash_map.items():
                            if len(dup_files) > 1:
                                gid = f"DUP-{group_id_counter:04d}"
                                duplicate_groups[gid] = dup_files
                                group_id_counter += 1
                                single_size = dup_files[0]["size"]
                                duplicate_wasted_bytes += single_size * (len(dup_files) - 1)
                                for d_idx, df in enumerate(dup_files):
                                    file_to_duplicate_group[df["path"]] = {
                                        "group_id": gid, "is_original": (d_idx == 0),
                                        "copy_index": d_idx + 1, "total_copies": len(dup_files), "hash": f_hash
                                    }

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
                        self.phase2_progress.emit(processed_cand_bytes, total_cand_bytes, speed_str, eta_sec, checked_groups_count, total_cand_groups)
                        hash_speed_timer = now
                        bytes_since_last_calc = 0
                        
                    time.sleep(0.001)
                    
            self.finished_ok.emit({
                "elapsed_seconds": round(time.time() - p2_start, 2),
                "duplicate_groups_count": len(duplicate_groups),
                "duplicate_wasted_bytes": duplicate_wasted_bytes,
                "cache_hits": cache_hits,
                "file_to_duplicate_group": file_to_duplicate_group,
                "duplicate_groups": duplicate_groups
            })
        except Exception as e:
            app_logger.exception("HashTask error")
            self.error.emit(str(e))


class AggregateTask(BaseScanTask):
    """阶段三：结果汇总与启发式过滤"""
    finished_ok = Signal(dict)

    def __init__(self, target_paths, all_scanned_files, file_to_duplicate_group, duplicate_groups, total_start_time, p1_duration, p2_duration, cache_hits, parent=None):
        super().__init__(parent)
        self.target_paths = target_paths
        self.all_scanned_files = all_scanned_files
        self.file_to_duplicate_group = file_to_duplicate_group
        self.duplicate_groups = duplicate_groups
        self.total_start_time = total_start_time
        self.p1_duration = p1_duration
        self.p2_duration = p2_duration
        self.cache_hits = cache_hits

    def run(self):
        try:
            redundant_list = []
            reclaimable_bytes = 0
            
            for i, finfo in enumerate(self.all_scanned_files):
                if not self.check_pause_cancel(): return
                fpath = finfo["path"]
                dup_info = self.file_to_duplicate_group.get(fpath)
                heuristic = get_heuristic_redundant_tag(fpath)
                
                is_duplicate = dup_info is not None
                is_duplicate_copy = (dup_info is not None and not dup_info["is_original"])
                
                if is_duplicate or heuristic is not None:
                    tag = "重复副本" if is_duplicate_copy else ("重复原件" if is_duplicate else heuristic[0])
                    reason = f"与同组副本相同 ({dup_info['group_id']})" if is_duplicate_copy else (
                        f"作为查重基准源 ({dup_info['group_id']})" if is_duplicate else heuristic[1]
                    )
                    is_recommended = is_duplicate_copy or (heuristic is not None and heuristic[0] in ["安全可清理", "临时与日志", "冗余归档包"])
                    
                    redundant_list.append({
                        "name": finfo["name"], "path": fpath, "size": finfo["size"],
                        "category": finfo["category"], "ext": finfo["ext"], "mtime": finfo["mtime"],
                        "scan_root": finfo.get("scan_root", ""),
                        "tag": tag, "reason": reason, "is_duplicate": is_duplicate,
                        "duplicate_group_id": dup_info["group_id"] if dup_info else "",
                        "is_duplicate_copy": is_duplicate_copy, "is_recommended": is_recommended,
                        "phase_status": "哈希已确认" if is_duplicate else "规则已识别"
                    })
                    if is_recommended:
                        reclaimable_bytes += finfo["size"]

                if i % 2000 == 0:
                    time.sleep(0.001)

            total_elapsed = round(time.time() - self.total_start_time, 2)
            total_bytes = sum(f["size"] for f in self.all_scanned_files)
            
            self.finished_ok.emit({
                "target_paths": self.target_paths,
                "total_elapsed_seconds": total_elapsed,
                "phase1_duration": self.p1_duration,
                "phase2_duration": self.p2_duration,
                "total_files": len(self.all_scanned_files),
                "total_bytes": total_bytes,
                "redundant_files": sorted(redundant_list, key=lambda x: x["size"], reverse=True),
                "duplicate_groups_count": len(self.duplicate_groups),
                "duplicate_wasted_bytes": sum(g[0]["size"] * (len(g)-1) for g in self.duplicate_groups.values()) if self.duplicate_groups else 0,
                "reclaimable_bytes": reclaimable_bytes,
                "cache_hits": self.cache_hits
            })
        except Exception as e:
            app_logger.exception("AggregateTask error")
            self.error.emit(str(e))


class ScanWorker(QObject):
    """
    轻量级任务编排器 (Coordinator)
    不执行具体耗时工作，负责组装 Phase1 -> Phase2 -> Phase3，与主线程交互
    """
    phase1_completed = Signal(dict)
    phase2_progress = Signal(object, object, str, int, int, int)
    phase2_completed = Signal(dict)
    phase3_completed = Signal(dict)
    progress_updated = Signal(str, object, object)
    phase_changed = Signal(str)
    scan_error = Signal(str)

    def __init__(self, target_paths, enable_duplicate_detection=True, hash_algorithm="md5", skip_system_protected=True, concurrency=4, ignore_folders=None, task_id=None, parent=None):
        super().__init__(parent)
        self.target_paths = target_paths
        self.enable_duplicate_detection = enable_duplicate_detection
        self.hash_algorithm = hash_algorithm
        self.skip_system_protected = skip_system_protected
        self.concurrency = concurrency
        self.ignore_folders = ignore_folders if ignore_folders is not None else app_config.get("ignore_folders", default=[])
        self.task_id = task_id
        
        self.current_task: Optional[BaseScanTask] = None
        self._is_running = False
        self._is_canceled = False
        
        self.phase1_cache = {}
        self.total_start_time = 0

    def isRunning(self):
        return self._is_running

    def wait(self):
        if self.current_task and self.current_task.isRunning():
            self.current_task.wait()

    def pause(self):
        if self.current_task: self.current_task.pause()

    def resume(self):
        if self.current_task: self.current_task.resume()

    def cancel(self):
        self._is_canceled = True
        self._is_running = False
        if self.current_task:
            self.current_task.cancel()

    def start(self):
        self._is_running = True
        self._is_canceled = False
        self.total_start_time = time.time()
        self.phase_changed.emit("阶段 1/3: 正在快速遍历目录与统计空间结构 (os.scandir 高速索引)...")
        
        # 核心修复：扫描启动前，重新严格解析当前生效配置，避免复用旧快照
        from app.config import app_config
        from app.utils.logger import app_logger
        ignore_folders, source = app_config.get_with_source("ignore_folders", default=[])
        self.ignore_folders = ignore_folders
        
        app_logger.info(f"[ScanWorker] 启动扫描，目标路径: {self.target_paths}")
        app_logger.info(f"[ScanWorker] 加载忽略路径列表: {len(self.ignore_folders)} 条 (配置来源: {source})")
        
        self.current_task = DirectoryScanTask(
            self.target_paths, 
            self.skip_system_protected, 
            self.enable_duplicate_detection,
            ignore_folders=self.ignore_folders
        )
        self.current_task.progress_updated.connect(self.progress_updated)
        self.current_task.finished_ok.connect(self._on_phase1_finished)
        self.current_task.error.connect(self._on_error)
        self.current_task.start()

    def _on_phase1_finished(self, result: dict):
        if self._is_canceled: return
        
        self.phase1_cache = result
        emit_result = {k: v for k, v in result.items() if k not in ["all_scanned_files", "size_candidates"]}
        self.phase1_completed.emit(emit_result)
        
        if self.enable_duplicate_detection:
            self.phase_changed.emit(f"阶段 2/3: 正在进行大小初筛与分块哈希深度比对 (并发数: {self.concurrency})...")
            self.current_task = HashTask(result["size_candidates"], self.concurrency, self.hash_algorithm)
            self.current_task.phase2_progress.connect(self.phase2_progress)
            self.current_task.finished_ok.connect(self._on_phase2_finished)
            self.current_task.error.connect(self._on_error)
            # 在 PyQt 中，信号触发为同步（QueuedConnection），这里启动新线程是无阻塞的，主线程能立刻返回处理其他事件
            self.current_task.start()
        else:
            self._on_phase2_finished({"elapsed_seconds": 0, "duplicate_groups_count": 0, "duplicate_wasted_bytes": 0, "cache_hits": 0, "file_to_duplicate_group": {}, "duplicate_groups": {}})

    def _on_phase2_finished(self, result: dict):
        if self._is_canceled: return
        self.phase2_completed.emit(result)
        
        self.phase_changed.emit("阶段 3/3: 正在汇总全景分析数据并生成智能治理建议...")
        self.current_task = AggregateTask(
            self.target_paths,
            self.phase1_cache["all_scanned_files"],
            result.get("file_to_duplicate_group", {}),
            result.get("duplicate_groups", {}),
            self.total_start_time,
            self.phase1_cache["elapsed_seconds"],
            result["elapsed_seconds"],
            result["cache_hits"]
        )
        self.current_task.finished_ok.connect(self._on_phase3_finished)
        self.current_task.error.connect(self._on_error)
        self.current_task.start()

    def _on_phase3_finished(self, result: dict):
        if self._is_canceled: return
        self._is_running = False
        result["category_stats"] = self.phase1_cache.get("category_stats", {})
        result["top_100_files"] = self.phase1_cache.get("top_100_files", [])
        result["skipped_ignored_count"] = self.phase1_cache.get("skipped_ignored_count", 0)
        result["task_id"] = getattr(self, "task_id", "Unknown") or "Unknown"
        import datetime
        result["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        self.current_task = None
        self.phase1_cache.clear() # 释放内存
        self.phase3_completed.emit(result)

    def _on_error(self, err: str):
        self._is_running = False
        self.current_task = None
        self.scan_error.emit(err)
