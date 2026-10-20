"""
app/core/asset_promoter.py
资产向上收拢、智能父级推断与全局知识沉淀控制器
遵循「一改俱改、特性同构」铁律，作为所有表格执行“转为集合”的核心领域服务。
"""
import os
import time
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

from PySide6.QtCore import QObject, Signal

from app.core.unified_scanner import fast_aggregate_directory
from app.core.registry_detector import RegistryAppDetector, COMMON_PARENTS
from app.config import app_config
from app.utils.logger import app_logger


class AssetPromoterService(QObject):
    """
    单例领域事件与收拢服务
    广播信号: collective_promoted(target_dir: str, new_asset: dict)
    """
    collective_promoted = Signal(str, dict)

    _instance = None

    @classmethod
    def instance(cls) -> "AssetPromoterService":
        if cls._instance is None:
            cls._instance = AssetPromoterService()
        return cls._instance

    @classmethod
    def infer_parent_candidates(cls, file_or_dir_path: str) -> List[Dict[str, Any]]:
        """
        对给定路径自底向上智能解析候选父目录，并给出推荐权重。
        过滤盘符根目录 (如 C:\\) 与 Windows 系统级顶层保留大抽屉 (如 Program Files)。
        """
        norm = os.path.normpath(file_or_dir_path)
        p = Path(norm).resolve()

        # 如果输入的是文件，从其直接父目录开始推断；若是目录，从自身开始
        curr = p.parent if p.is_file() else p
        candidates: List[Dict[str, Any]] = []

        visited = set()
        while len(curr.parts) > 1:
            curr_str = str(curr)
            norm_c = os.path.normcase(os.path.normpath(curr_str))

            if norm_c in visited:
                break
            visited.add(norm_c)

            dname = curr.name
            dname_lower = dname.lower()

            # 过滤盘符或盘符根目录
            if len(curr.parts) <= 1 or not dname:
                break

            # 过滤系统顶层大抽屉
            if dname_lower in COMMON_PARENTS:
                break

            # 计算推荐度权重
            parent_of_curr = curr.parent
            parent_name_lower = parent_of_curr.name.lower() if len(parent_of_curr.parts) > 1 else ""

            is_rec = False
            rec_reason = "候选父目录"

            # 1. 若当前目录匹配到了已安装软件或系统组件
            match_info = RegistryAppDetector.match_app_by_path(curr_str)
            if match_info and match_info[1] is True:
                is_rec = True
                rec_reason = f"⭐ 权威匹配: {match_info[0].name} 软件物理根目录"
            elif parent_name_lower in COMMON_PARENTS:
                # 2. 如果其父目录恰好是 Program Files、Program Files (x86)、AppData 等，说明本层就是软件主根目录！
                is_rec = True
                rec_reason = f"⭐ 推荐: 位于 [{parent_of_curr.name}] 下的一级软件根目录"
            elif len(parent_of_curr.parts) <= 1:
                # 3. 数据盘根目录的一级目录 (如 D:\Clash)
                is_rec = True
                rec_reason = "⭐ 推荐: 数据盘根目录独立软件"

            candidates.append({
                "path": curr_str,
                "name": dname,
                "is_recommended": is_rec,
                "reason": rec_reason,
                "depth": len(curr.parts)
            })

            curr = curr.parent

        # 排序：推荐项优先，其次按路径深度从浅到深（优先保留更高层级实体）
        candidates.sort(key=lambda c: (not c["is_recommended"], c["depth"]))
        return candidates

    @classmethod
    def execute_promotion(
        cls,
        target_dir: str,
        app_name: str,
        current_assets: List[Dict[str, Any]],
        persist: bool = True
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        在内存数据模型层执行极速收割与合并：
        1. 找出当前列表中所有属于 target_dir 下的散碎条目并移除；
        2. 极速聚合 target_dir 的总体积与文件数；
        3. 组装单一 AssetUnit/Dict 集合资产并插入；
        4. 持久化沉淀至配置与注册表匹配树；
        5. 发射全局广播信号，通知所有关联视图更新。
        """
        norm_target = os.path.normcase(os.path.normpath(target_dir))
        prefix_with_sep = norm_target + os.sep

        retained_assets: List[Dict[str, Any]] = []
        removed_count = 0
        removed_bytes = 0

        for item in current_assets:
            p = os.path.normcase(os.path.normpath(item.get("path", "")))
            if p == norm_target or p.startswith(prefix_with_sep):
                removed_count += item.get("file_count", 1)
                removed_bytes += item.get("size", 0)
            else:
                retained_assets.append(item)

        # 物理聚合该目录的准确大小与文件数
        c_bytes, c_files, c_mtime = fast_aggregate_directory(target_dir)
        c_bytes = max(c_bytes, removed_bytes)
        c_files = max(c_files, removed_count)

        new_asset = {
            "name": app_name,
            "path": target_dir,
            "size": c_bytes,
            "mtime": c_mtime,
            "ext": "",
            "file_count": c_files,
            "category": "软件安装与程序 (Apps & Installers)",
            "is_directory_collective": True,
            "collective_info": {
                "is_collective": True,
                "collective_type": "已安装应用",
                "app_name": app_name,
                "software_name": app_name,
                "suggested_category": "软件安装与程序 (Apps & Installers)",
                "reason": f"用户在扫描结果中手动收拢为独立软件集合 [{app_name}] 并沉淀"
            },
            "phase_status": "阶段一已归类 (原子保全)",
            "tag": f"用户收拢集体 ({app_name})",
            "is_recommended": False
        }

        # 插入到最前面以醒目呈现
        retained_assets.insert(0, new_asset)

        # 知识库沉淀
        if persist:
            cls.persist_collective(target_dir)

        # 发射全局广播通知所有页面联动更新
        cls.instance().collective_promoted.emit(target_dir, new_asset)
        app_logger.info("动态收拢资产成功: %s -> %s (收割碎文件 %d 个, 聚合容量: %d 字节)",
                        target_dir, app_name, removed_count, c_bytes)

        return retained_assets, new_asset

    @classmethod
    def persist_collective(cls, target_dir: str):
        """沉淀至全局配置与注册表匹配树"""
        try:
            norm_d = os.path.normpath(target_dir)
            cfg_dirs = list(app_config.get("custom_app_dirs", default=[]))
            if norm_d not in cfg_dirs:
                cfg_dirs.append(norm_d)
                app_config.set("custom_app_dirs", cfg_dirs, level="global")

            RegistryAppDetector.set_custom_apps(cfg_dirs)
        except Exception as e:
            app_logger.error("沉淀自定义集合规则失败: %s", e)
