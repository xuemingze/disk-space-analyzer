"""
自动化规则监控引擎 (Rule Watcher)
特点：
1. 采用后台轮询 + 状态快照检测，不依赖外部 C 扩展；
2. 防抖与文件沉淀机制 (Debounce & Settling)：必须在指定秒数内文件大小与修改时间持续稳定不变，才视为写入完成；
3. 幂等与防回环死循环 (Cycle Prevention & Idempotency)：记录由系统自身转移或已生成计划的文件，杜绝自触发循环；
4. 默认安全准则：默认只生成候选整理计划 (ProposedPlan)，绝不暗中直接物理移动文件。
"""

import os
import time
import fnmatch
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple
from collections import defaultdict

from PySide6.QtCore import QThread, Signal

from app.automation.models import WatchRule, ProposedPlan
from app.automation.archive_executor import execute_safe_auto_archive
from app.core.unified_scanner import UnifiedScanner, AssetUnit
from app.core.app_detector import AppDetector
from app.core.organize_models import OrganizeOptions, OrganizeMode
from app.utils.lock_detector import is_file_locked_or_in_use
from app.utils.logger import app_logger


class RuleWatcher(QThread):
    """
    后台目录监控工作线程
    """
    plan_proposed = Signal(object)       # 发射 ProposedPlan 对象
    log_emitted = Signal(str, str)        # (message, level: "info" | "success" | "warn" | "error")
    status_changed = Signal(str)         # 监控状态文字

    def __init__(self, rules: Optional[List[WatchRule]] = None, parent=None):
        super().__init__(parent)
        self.rules: List[WatchRule] = rules or []
        self._is_running = True
        self._poll_interval = 1.0        # 心跳检测周期 (秒)

        # 状态快照：rule_id -> {file_path: {"size": int, "mtime": float, "stable_since": float, "settled": bool}}
        self._file_snapshots: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)

        # 幂等防回环记录：记录近期已处理或转移的文件路径 (路径 -> 处理时间戳)
        self._processed_cache: Dict[str, float] = {}
        self._cache_retention_seconds = 300.0  # 缓存保留 5 分钟

    def update_rules(self, rules: List[WatchRule]):
        """动态更新监控规则列表"""
        self.rules = rules
        self.log_emitted.emit(f"🔄 监控规则已更新，当前激活规则数: {len([r for r in self.rules if r.enabled])}", "info")

    def record_system_action(self, file_path: str):
        """记录系统自身执行的移动/写入，杜绝自身触发监控回环"""
        norm_path = os.path.normpath(file_path).lower()
        self._processed_cache[norm_path] = time.time()

    def stop(self):
        """平滑停止监控线程"""
        self._is_running = False
        self.wait(3000)

    def _cleanup_old_cache(self, now: float):
        """定期清理过期的防回环缓存"""
        expired = [p for p, ts in self._processed_cache.items() if now - ts > self._cache_retention_seconds]
        for p in expired:
            del self._processed_cache[p]

    def _is_excluded(self, file_path: str, rule: WatchRule) -> bool:
        """检查文件是否被排除或不符合规则白名单"""
        name = os.path.basename(file_path)
        name_lower = name.lower()

        # 1. 检查排除通配符模式
        for pat in rule.exclude_patterns:
            if fnmatch.fnmatch(name_lower, pat.lower()):
                return True

        # 2. 检查扩展名白名单 (若指定了扩展名)
        if rule.file_extensions:
            ext = os.path.splitext(name_lower)[1]
            valid_exts = [e.lower() if e.startswith(".") else f".{e.lower()}" for e in rule.file_extensions]
            if ext not in valid_exts:
                return True

        # 3. 检查防回环：若目标目录位于观察目录下，必须严格排除目标目录
        if rule.target_dir:
            norm_target = os.path.normpath(rule.target_dir).lower()
            norm_file = os.path.normpath(file_path).lower()
            if norm_file.startswith(norm_target):
                return True

        # 4. 检查是否在近期系统处理防回环缓存中
        norm_file = os.path.normpath(file_path).lower()
        if norm_file in self._processed_cache:
            return True

        return False

    def run(self):
        app_logger.info("自动化中心: 规则监控后台引擎已启动")
        self.status_changed.emit("正在监控中")

        while self._is_running:
            try:
                now = time.time()
                self._cleanup_old_cache(now)

                active_rules = [r for r in self.rules if r.enabled and r.watch_path and os.path.isdir(r.watch_path)]

                for rule in active_rules:
                    self._check_rule(rule, now)

            except Exception as e:
                app_logger.error("监控循环异常: %s", e)
                self.log_emitted.emit(f"监控异常: {e}", "error")

            # 细粒度可中断休眠 (每 0.1 秒检查一次退出标志)
            for _ in range(int(self._poll_interval * 10)):
                if not self._is_running:
                    break
                time.sleep(0.1)

        self.status_changed.emit("已停止")
        app_logger.info("自动化中心: 规则监控后台引擎已停止")

    def _check_rule(self, rule: WatchRule, now: float):
        """对单条规则的监控目录执行文件快照与沉淀防抖检查"""
        watch_dir = rule.watch_path
        rule_snapshot = self._file_snapshots[rule.id]
        settled_files_to_propose: List[Dict[str, Any]] = []

        try:
            # 统一委托统一扫描底座：兼顾源头剪枝、原子集体识别与防回环
            assets = UnifiedScanner.scan_directory(
                root_paths=[watch_dir],
                prune_collectives=True,
                skip_system_protected=True,
                max_depth=3,
                cancel_check=lambda: self._is_running
            )

            for asset in assets:
                if not self._is_running:
                    return

                file_path = asset.path
                if self._is_excluded(file_path, rule):
                    continue

                size = asset.size
                mtime = asset.mtime

                if rule.min_file_size > 0 and size < rule.min_file_size:
                    continue

                # 检查沉淀状态
                prev = rule_snapshot.get(file_path)
                if prev is None:
                    rule_snapshot[file_path] = {
                        "size": size,
                        "mtime": mtime,
                        "stable_since": now,
                        "settled": False
                    }
                else:
                    if prev["size"] == size and prev["mtime"] == mtime:
                        if not prev["settled"] and (now - prev["stable_since"] >= rule.debounce_seconds):
                            is_locked, lock_reason = is_file_locked_or_in_use(file_path, min_cooldown_seconds=0.0)
                            if is_locked:
                                app_logger.debug("资产被占用/编辑中，暂缓监控捕获: %s (%s)", file_path, lock_reason)
                            else:
                                prev["settled"] = True
                                settled_files_to_propose.append({
                                    "path": file_path,
                                    "name": asset.name,
                                    "size": size,
                                    "mtime": mtime,
                                    "ext": asset.ext,
                                    "category": asset.category,
                                    "is_directory_collective": asset.is_collective,
                                    "collective_info": asset.collective_info,
                                    "umbrella_anchor": asset.umbrella_anchor
                                })
                    else:
                        prev["size"] = size
                        prev["mtime"] = mtime
                        prev["stable_since"] = now
                        prev["settled"] = False

        except Exception as e:
            app_logger.debug("扫描观察目录 [%s] 异常: %s", watch_dir, e)

        # 若存在已沉淀稳定的新文件，依据规则模式生成提案或执行归档
        if settled_files_to_propose:
            if rule.propose_only:
                self._generate_candidate_plan(rule, settled_files_to_propose, now)
            else:
                self._execute_auto_archive_for_rule(rule, settled_files_to_propose, now)

    def _execute_auto_archive_for_rule(self, rule: WatchRule, settled_files: List[Dict[str, Any]], now: float):
        """执行自动归档平移 (仅在用户显式配置为自动归档时生效)"""
        target_root = rule.target_dir or "D:/归档备份"
        res = execute_safe_auto_archive(
            files=settled_files,
            target_root=target_root,
            source_dir=rule.watch_path,
            organize_mode=rule.organize_mode or "comprehensive",
            source_name=f"规则监控-{rule.name}",
            log_callback=lambda msg, lvl: self.log_emitted.emit(msg, lvl)
        )
        # 将源文件与移动落位后的目标文件都写入防回环缓存
        for f in settled_files:
            self.record_system_action(f["path"])
        for p in res.get("success_paths", []):
            self.record_system_action(p)

    def _generate_candidate_plan(self, rule: WatchRule, settled_files: List[Dict[str, Any]], now: float):
        """生成候选整理计划并通知 UI (默认只提议、绝不移动)"""
        target_root = rule.target_dir or "D:/归档备份"
        mode_val = rule.organize_mode or "comprehensive"
        try:
            mode_enum = OrganizeMode(mode_val)
        except Exception:
            mode_enum = OrganizeMode.COMPREHENSIVE

        options = OrganizeOptions(mode=mode_enum)

        # 基于核心分组引擎计算整理拓扑
        groups = AppDetector.group_files_by_parent_or_tool(settled_files, target_root, options)

        total_bytes = sum(f.get("size", 0) for f in settled_files)

        plan = ProposedPlan(
            source_type="rule_monitor",
            source_name=rule.name,
            source_path=rule.watch_path,
            target_root=target_root,
            created_at=now,
            file_count=len(settled_files),
            total_bytes=total_bytes,
            proposed_groups=groups,
            status="pending",
            notes=f"监控规则 [{rule.name}] 捕获到 {len(settled_files)} 个稳定文件，已生成整理候选计划待审核"
        )

        # 记录防回环
        for f in settled_files:
            self.record_system_action(f["path"])

        self.log_emitted.emit(
            f"💡 规则监控 [{rule.name}] 检测到 {len(settled_files)} 个文件沉淀稳定，已提议整理方案 (待审核)",
            "success"
        )
        self.plan_proposed.emit(plan)
