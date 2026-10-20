"""
统一资产扫描底座 (Unified Scan Engine)
架构级贯通三大整理核心原则：
1. 防御性递归原则 (Defensive Recursion Principle):
   源头窥探剪枝，一旦探测到原子狭义集体立即整盘封包，严禁零散碎文件入栈，实现万级碎片文件秒级封包；
2. 泛式大抽屉与狭义实体拓扑法则 (Broad vs Narrow Topology Law):
   废除盘符深度硬限制，解禁数据盘根目录独立软件 (如 D:\\Clash, D:\\Everything)；
   广义大抽屉 (MovedApps, backups, 财务, Live2D) 自顶向下强行赋权上位语义，快照绝不被内部清单反客为主篡权为活跃代码；
3. 同源同宿全链条贯通 (Source Umbrella Consistency):
   全程携带 umbrella_anchor 伞状锚点，备份大抽屉下的归档包自动豁免冗余误判，迁移保持同构相对拓扑。

安全防护底线：
- 具备 visited_dirs 物理路径去重，绝对杜绝软链接回环与递归死循环；
- 具备最大递归深度限制与内存熔断保护 (Circuit Breaker)，严禁无休止消耗系统内存。
"""

import os
import time
from pathlib import Path
from dataclasses import dataclass, field
from collections import defaultdict
from typing import List, Dict, Any, Optional, Tuple, Callable, Set

from app.core.app_detector import AppDetector
from app.utils.file_helper import (
    categorize_file_by_ext,
    normalize_unified_category,
    is_system_critical_path,
    format_size
)
from app.utils.logger import app_logger


@dataclass
class AssetUnit:
    """统一治理资产单元契约 (Universal Asset Unit Contract)"""
    id: str                                  # 唯一资产 ID
    name: str                                # 文件名或集体目录名
    path: str                                # 物理规范路径
    size: int                                # 总体积字节数
    mtime: float                             # 最后修改时间戳
    file_count: int = 1                      # 文件数量 (单文件为1，原子集体为内部文件总数)
    is_collective: bool = False              # 是否为不可拆分的原子狭义集体
    collective_type: str = ""                # 独立软件 | 开发工程 | 历史快照 | 业务账套 | 依赖集体
    category: str = "其他文件"               # 归一化全景资产分类
    ext: str = ""                            # 扩展名 (集体为空)
    scan_root: str = ""                      # 扫描发起的顶层根路径
    umbrella_anchor: str = ""                # 祖先广义大抽屉路径/名称 (血统继承)
    umbrella_category: str = ""              # 广义分类 (app | backup | finance | design | project 等)
    is_snapshot_backup: bool = False         # 是否属于历史备份/快照资产 (免除冗余归档包误判)
    collective_info: Dict[str, Any] = field(default_factory=dict)
    tag: str = ""                            # 呈现标签
    reason: str = ""                         # 归类裁决理由

    def to_dict(self) -> Dict[str, Any]:
        return {
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
            "umbrella_anchor": self.umbrella_anchor,
            "umbrella_category": self.umbrella_category,
            "is_snapshot_backup": self.is_snapshot_backup,
            "collective_info": self.collective_info,
            "tag": self.tag,
            "reason": self.reason
        }


def fast_aggregate_directory(dir_path: str, max_files_limit: int = 150000) -> Tuple[int, int, float]:
    """
    轻量高速聚合目录内元数据：
    获取集体总大小、文件总数、最新修改时间。
    具备 visited 防死循环保护与 max_files_limit 熔断。
    返回: (total_bytes, total_files, latest_mtime)
    """
    total_bytes = 0
    total_files = 0
    latest_mtime = 0.0
    visited_subdirs: Set[str] = set()

    try:
        for root, dirs, files in os.walk(dir_path):
            try:
                norm_r = os.path.realpath(root).lower()
            except Exception:
                norm_r = os.path.normpath(root).lower()

            if norm_r in visited_subdirs:
                dirs.clear()
                continue
            visited_subdirs.add(norm_r)

            for f in files:
                total_files += 1
                try:
                    fpath = os.path.join(root, f)
                    st = os.stat(fpath)
                    total_bytes += getattr(st, "st_size", 0)
                    m = getattr(st, "st_mtime", 0.0)
                    if m > latest_mtime:
                        latest_mtime = m
                except (OSError, PermissionError):
                    pass

                if total_files >= max_files_limit:
                    break
            if total_files >= max_files_limit:
                break
    except Exception as e:
        app_logger.debug("快速聚合目录失败 %s: %s", dir_path, e)

    latest_mtime = latest_mtime or time.time()
    return total_bytes, total_files, latest_mtime


class UnifiedScanner:
    """
    统一资产扫描核心引擎
    贯通防御性源头剪枝、上位大抽屉强行赋权、数据盘解禁与同源同宿全链条
    """

    @classmethod
    def scan_directory(
        cls,
        root_paths: List[str],
        prune_collectives: bool = True,
        skip_system_protected: bool = True,
        ignore_folders: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        max_depth: int = 32,
        max_assets_limit: int = 200000,
        on_ignore_callback: Optional[Callable[[str], None]] = None
    ) -> List[AssetUnit]:
        """
        统一执行目录扫描并返回资产单元列表：
        - 遇到原子集体立即在源头截断剪枝封包，严禁零散碎文件入栈；
        - 大抽屉向下强行赋权上位语义；
        - 解禁非系统盘 (如 D:\\, E:\\) 一级目录独立软件识别；
        - 核心熔断与防回环：visited 集合去重 + 深度限制 + 数量上限。
        """
        results: List[AssetUnit] = []
        normalized_roots = [os.path.normpath(r) for r in root_paths if os.path.exists(r)]
        normalized_ignores = [os.path.normcase(os.path.normpath(ig)) for ig in (ignore_folders or []) if ig.strip()]

        def _is_ignored(path_str: str) -> bool:
            if not normalized_ignores:
                return False
            norm_c = os.path.normcase(os.path.normpath(path_str))
            for ig in normalized_ignores:
                if norm_c == ig or norm_c.startswith(ig + os.sep):
                    return True
            return False

        total_scanned_files = 0
        total_scanned_bytes = 0
        last_callback_time = time.time()

        # 核心防回环保护：记录所有已展开访问的真实物理路径
        visited_dirs: Set[str] = set()
        # 扫描会话级集体探测缓存 (微秒级直出)
        collective_cache: Dict[str, Optional[Dict[str, Any]]] = {}

        def _safe_detect_collective(p_dir: str):
            try:
                return AppDetector.detect_directory_collective(p_dir, cache=collective_cache)
            except TypeError:
                return AppDetector.detect_directory_collective(p_dir)

        for root in normalized_roots:
            if cancel_check and not cancel_check():
                break

            # 确定顶层是否有大抽屉语义
            root_name = os.path.basename(root)
            broad_match = AppDetector.match_broad_container(root_name)
            initial_umbrella = root_name if broad_match else ""
            initial_broad_cat = broad_match[0] if broad_match else ""

            # 扫描栈元素: (当前目录路径, 当前继承的祖先大抽屉名称, 当前大抽屉类型, 当前相对深度)
            stack: List[Tuple[str, str, str, int]] = [(root, initial_umbrella, initial_broad_cat, 0)]

            while stack:
                if cancel_check and not cancel_check():
                    break

                # 内存熔断保护：如果单次扫描累积对象超过安全阈值，立即熔断截断
                if len(results) >= max_assets_limit:
                    app_logger.warning("扫描达到安全资产上限 (%d 项)，触发熔断保底退出", max_assets_limit)
                    break

                curr_dir, parent_umbrella, parent_broad_cat, curr_depth = stack.pop()

                # 防回环校验：已访问过的物理目录绝不重复展开
                try:
                    real_curr = os.path.realpath(curr_dir).lower()
                except Exception:
                    real_curr = os.path.normpath(curr_dir).lower()

                if real_curr in visited_dirs:
                    continue
                visited_dirs.add(real_curr)

                # 深度熔断保护：超过最大限制深度则停止继续深潜
                if curr_depth > max_depth:
                    continue

                if skip_system_protected and is_system_critical_path(curr_dir):
                    continue
                if _is_ignored(curr_dir):
                    if on_ignore_callback:
                        on_ignore_callback(curr_dir)
                    continue

                curr_name = os.path.basename(curr_dir)

                # 检查当前目录是否更新广义大抽屉身份 (若自身是大抽屉，刷新下级上位语义)
                broad_check = AppDetector.match_broad_container(curr_name)
                if broad_check:
                    curr_umbrella = curr_name
                    curr_broad_cat = broad_check[0]
                else:
                    curr_umbrella = parent_umbrella
                    curr_broad_cat = parent_broad_cat

                # 顶层/当前目录原子集体拦截（仅对未经历入栈前置检查的根目录 curr_depth == 0 实施源头封存）
                if prune_collectives and curr_depth == 0:
                    curr_collective = _safe_detect_collective(curr_dir)
                    if curr_collective and isinstance(curr_collective, dict) and (
                        curr_collective.get("is_collective") or "software_name" in curr_collective
                    ):
                        c_bytes, c_files, c_mtime = fast_aggregate_directory(curr_dir)
                        c_cat = normalize_unified_category(
                            curr_collective.get("suggested_category", "软件安装与程序 (Apps & Installers)")
                        )
                        c_type = curr_collective.get("collective_type") or "已安装应用"
                        asset = AssetUnit(
                            id=f"COLL_{int(time.time()*1000)}_{len(results)}",
                            name=curr_name,
                            path=curr_dir,
                            size=c_bytes,
                            mtime=c_mtime,
                            file_count=c_files,
                            is_collective=True,
                            collective_type=c_type,
                            category=c_cat,
                            ext="",
                            scan_root=root,
                            umbrella_anchor=curr_umbrella,
                            umbrella_category=curr_broad_cat,
                            is_snapshot_backup=(curr_broad_cat == "backup"),
                            collective_info=curr_collective,
                            tag=f"原子保全 ({c_type})",
                            reason=curr_collective.get("reason", "不可拆分原子集体整体治理")
                        )
                        results.append(asset)
                        total_scanned_files += c_files
                        total_scanned_bytes += c_bytes
                        continue

                # 读取当前目录项
                try:
                    entries = []
                    with os.scandir(curr_dir) as it:
                        for entry in it:
                            entries.append(entry)
                except (OSError, PermissionError):
                    continue

                # 分离文件与子目录
                dirs_to_evaluate = []
                for entry in entries:
                    if entry.name.startswith("$") and entry.name != "$Recycle.Bin":
                        continue

                    try:
                        if entry.is_dir(follow_symlinks=False):
                            dirs_to_evaluate.append(entry)
                        elif entry.is_file(follow_symlinks=False):
                            if _is_ignored(entry.path):
                                if on_ignore_callback:
                                    on_ignore_callback(entry.path)
                                continue
                            # 单文件资产构建
                            stat_res = entry.stat()
                            f_size = stat_res.st_size
                            f_mtime = stat_res.st_mtime
                            f_ext = os.path.splitext(entry.name)[1].lower()

                            # 判定分类
                            cat_raw = categorize_file_by_ext(Path(entry.path))
                            unified_cat = normalize_unified_category(cat_raw)

                            # 同源同宿：判断是否在备份大抽屉下
                            is_backup_pack = (curr_broad_cat == "backup") and (f_ext in {".zip", ".tar", ".gz", ".7z", ".rar", ".iso"})
                            if is_backup_pack:
                                unified_cat = "归档包与系统镜像 (Archives & Images)"

                            asset = AssetUnit(
                                id=f"FILE_{int(time.time()*1000)}_{total_scanned_files}",
                                name=entry.name,
                                path=entry.path,
                                size=f_size,
                                mtime=f_mtime,
                                file_count=1,
                                is_collective=False,
                                category=unified_cat,
                                ext=f_ext,
                                scan_root=root,
                                umbrella_anchor=curr_umbrella,
                                umbrella_category=curr_broad_cat,
                                is_snapshot_backup=is_backup_pack,
                                tag="备份快照" if is_backup_pack else "",
                                reason="历史备份大抽屉归档资产" if is_backup_pack else ""
                            )
                            results.append(asset)
                            total_scanned_files += 1
                            total_scanned_bytes += f_size
                    except (OSError, PermissionError):
                        continue

                # 核心机制：防御性递归原则 (Defensive Recursion Principle)
                # 在子目录入栈前，立即在前置做狭义原子集体窥探！
                for d_entry in dirs_to_evaluate:
                    d_path = d_entry.path
                    if skip_system_protected and is_system_critical_path(d_path):
                        continue
                    if _is_ignored(d_path):
                        if on_ignore_callback:
                            on_ignore_callback(d_path)
                        continue

                    # 防回环快速预检：若已访问过，不再入栈
                    try:
                        real_d = os.path.realpath(d_path).lower()
                        if real_d in visited_dirs:
                            continue
                    except Exception:
                        pass

                    # 若启用集体剪枝，执行前置特征快查 (带会话级快速缓存)
                    if prune_collectives:
                        collective_info = _safe_detect_collective(d_path)

                        # 上位大抽屉强行赋权裁决 (Top-Down Precedence)：
                        # 若祖先大抽屉是 backup，坚决赋权为历史快照实体，严禁被内部 package.json 夺权为活跃开发工程！
                        if curr_broad_cat == "backup" and collective_info:
                            collective_info["collective_type"] = "历史快照集体"
                            collective_info["suggested_category"] = "归档包与系统镜像 (Archives & Images)"
                            collective_info["reason"] = f"受顶级备份大抽屉 [{curr_umbrella}] 强行上位赋权，判定为历史快照原子资产"

                        # 宽容性集体兼容判定：只要非空且含有特征字段，均认定为集体资产
                        is_coll = bool(
                            collective_info and isinstance(collective_info, dict) and (
                                collective_info.get("is_collective")
                                or "type" in collective_info
                                or "suggested_category" in collective_info
                                or "app_name" in collective_info
                                or "software_name" in collective_info
                                or "project_name" in collective_info
                            )
                        )

                        if is_coll:
                            # 触发源头剪枝封包！严禁零散碎文件入栈！
                            # 极速聚合该目录的体积与文件数 (Edge 11,450 个文件秒级出库)
                            c_bytes, c_files, c_mtime = fast_aggregate_directory(d_path)

                            c_cat = normalize_unified_category(
                                collective_info.get("suggested_category", "软件安装与程序 (Apps & Installers)")
                            )
                            c_type = collective_info.get("collective_type") or collective_info.get("type") or "原子实体"

                            asset = AssetUnit(
                                id=f"COLL_{int(time.time()*1000)}_{len(results)}",
                                name=d_entry.name,
                                path=d_path,
                                size=c_bytes,
                                mtime=c_mtime,
                                file_count=c_files,
                                is_collective=True,
                                collective_type=c_type,
                                category=c_cat,
                                ext="",
                                scan_root=root,
                                umbrella_anchor=curr_umbrella,
                                umbrella_category=curr_broad_cat,
                                is_snapshot_backup=(curr_broad_cat == "backup"),
                                collective_info=collective_info,
                                tag=f"原子保全 ({c_type})",
                                reason=collective_info.get("reason", "不可拆分原子集体整体治理")
                            )
                            results.append(asset)
                            total_scanned_files += c_files
                            total_scanned_bytes += c_bytes

                            # 记录该集体真实路径已访问，绝对禁止其子目录被再次遍历
                            try:
                                visited_dirs.add(os.path.realpath(d_path).lower())
                            except Exception:
                                visited_dirs.add(os.path.normpath(d_path).lower())

                            # 剪枝完成：该子目录及其成千上万碎文件彻底不再入栈！
                            continue

                    # 未命中集体：常规子目录，安全推入扫描栈继续下钻 (层级+1)
                    stack.append((d_path, curr_umbrella, curr_broad_cat, curr_depth + 1))

                # 周期性节流汇报进度
                now = time.time()
                if progress_callback and (now - last_callback_time >= 0.08):
                    progress_callback(curr_dir, total_scanned_files, total_scanned_bytes)
                    last_callback_time = now

        if progress_callback:
            progress_callback("扫描完成", total_scanned_files, total_scanned_bytes)

        app_logger.info(
            f"统一扫描完成！共提炼资产单元: {len(results)} 项 (涵盖物理文件: {total_scanned_files} 项, 总容量: {format_size(total_scanned_bytes)})"
        )
        return results
