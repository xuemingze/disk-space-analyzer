"""
自动化安全归档执行器 (Automation Safe Archive Executor)
负责在自动化监控 (RuleWatcher) 或计划任务 (TaskScheduler) 处于自动归档模式时，
执行安全、带保底、防回环、可回滚的文件平移操作。
"""

import os
import json
import time
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable, Tuple

from app.core.app_detector import AppDetector
from app.core.organize_models import OrganizeOptions, OrganizeMode
from app.core.cleaner import ARCHIVE_MANIFEST_DIR
from app.utils.file_helper import is_system_critical_path, format_size
from app.utils.lock_detector import is_file_locked_or_in_use, is_destination_valid
from app.utils.logger import app_logger


def execute_safe_auto_archive(
    files: List[Dict[str, Any]],
    target_root: str,
    source_dir: str,
    organize_mode: str = "comprehensive",
    source_name: str = "自动化归档",
    conflict_policy: str = "auto_rename",
    min_cooldown_seconds: float = 0.0,
    log_callback: Optional[Callable[[str, str], None]] = None,
    proposed_groups: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    执行高安全保底的自动归档平移：
    1. 目标目录与源目录防死循环校验；
    2. 对每个文件执行运行中/独占锁/Office伴生锁探测，被占用的文件坚决不移动；
    3. 系统受保护核心目录严禁移动；
    4. 采用 auto_rename 防冲突落位；
    5. 生成标准 Manifest 凭据支持随时一键回滚。
    """
    def _log(msg: str, level: str = "info"):
        if log_callback:
            try:
                log_callback(msg, level)
            except Exception:
                pass
        app_logger.info(f"[{level.upper()}] {msg}")

    # 1. 验证目标目录有效性与防死循环
    valid, err_msg = is_destination_valid(source_dir, target_root)
    if not valid:
        _log(f"❌ 自动归档终止: {err_msg}", "error")
        return {"success": False, "error": err_msg, "success_count": 0, "manifest_path": ""}

    ARCHIVE_MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    backup_id = f"AUTO_{int(time.time()*1000000)}"
    manifest_file = ARCHIVE_MANIFEST_DIR / f"manifest_{backup_id}.json"

    manifest = {
        "backup_id": backup_id,
        "task_id": f"AUTO_TASK_{int(time.time()*1000)}",
        "scan_task_id": "",
        "report_id": source_name,
        "created_at": time.time(),
        "status": "RUNNING",
        "conflict_policy": conflict_policy,
        "destination_root": os.path.normpath(target_root),
        "items": [],
        "results": {"success": 0, "failed": 0, "skipped": 0, "conflict": 0, "locked": 0},
        "manifest_path": str(manifest_file),
        "rollback_status": "NONE",
        "error_reason": ""
    }

    try:
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
    except Exception as e:
        _log(f"❌ 写入归档清单失败: {e}", "error")
        return {"success": False, "error": str(e), "success_count": 0, "manifest_path": ""}

    # 2. 规划组织拓扑结构（优先直接采用上游 AI 编排与主路由表仲裁后的 proposed_groups）
    if proposed_groups is not None:
        groups = proposed_groups
    else:
        try:
            mode_enum = OrganizeMode(organize_mode)
        except Exception:
            mode_enum = OrganizeMode.COMPREHENSIVE

        options = OrganizeOptions(mode=mode_enum)
        groups = AppDetector.group_files_by_parent_or_tool(files, target_root, options)

    # 扁平化映射: source_file_path -> dest_dir
    file_target_map: Dict[str, str] = {}
    for g in groups:
        cat_name = (
            g.get("effective_category")
            or g.get("suggested_category")
            or g.get("target_folder")
            or g.get("category")
            or "未分类"
        )
        rec_sub = str(g.get("recommended_subpath") or g.get("target_subpath") or "").strip("/\\")
        if g.get("target_root") and not g.get("is_directory_group", False):
            # 单文件组 target_root 可能是建议目标目录或文件完整路径
            tr_p = Path(g["target_root"])
            cat_dir = str(tr_p.parent) if tr_p.suffix else str(tr_p)
        elif g.get("target_root") and g.get("is_directory_group", False):
            cat_dir = str(g["target_root"])
        elif rec_sub:
            cat_dir = os.path.join(target_root, cat_name, rec_sub)
        else:
            cat_dir = os.path.join(target_root, cat_name)

        for f in g.get("files", []):
            fpath_val = f.get("path") or f.get("original_path") or ""
            if fpath_val:
                file_target_map[os.path.normpath(fpath_val)] = cat_dir

        for sub in g.get("sub_items", []):
            orig_p_str = sub.get("original_path") or sub.get("path") or ""
            if orig_p_str:
                if sub.get("target_path"):
                    file_target_map[os.path.normpath(orig_p_str)] = str(Path(sub["target_path"]).parent)
                else:
                    file_target_map[os.path.normpath(orig_p_str)] = cat_dir

        if g.get("original_root"):
            orig_root_norm = os.path.normpath(g["original_root"])
            if orig_root_norm not in file_target_map:
                file_target_map[orig_root_norm] = cat_dir

    success_count = 0
    locked_count = 0
    skipped_count = 0
    failed_count = 0
    archived_bytes = 0
    success_paths: List[str] = []

    os.makedirs(target_root, exist_ok=True)

    for idx, f_info in enumerate(files, 1):
        fpath = f_info.get("path", "")
        norm_f = os.path.normpath(fpath)

        if not os.path.exists(fpath):
            skipped_count += 1
            manifest["results"]["skipped"] += 1
            continue

        # 保底防御 1: 检查是否为 Windows 核心保护路径
        if is_system_critical_path(fpath):
            failed_count += 1
            manifest["results"]["failed"] += 1
            _log(f"🛡️ 安全拦截：禁止移动核心保护路径: {fpath}", "warn")
            continue

        # 保底防御 2: 严格检查独占占用、运行中、Office/WPS 伴生锁
        is_locked, lock_reason = is_file_locked_or_in_use(fpath, min_cooldown_seconds=min_cooldown_seconds)
        if is_locked:
            locked_count += 1
            manifest["results"]["locked"] += 1
            _log(f"🔒 保底拦截 [{os.path.basename(fpath)}]: {lock_reason} (已跳过)", "warn")
            continue

        dest_dir = file_target_map.get(norm_f, os.path.join(target_root, "其他文件"))
        try:
            os.makedirs(dest_dir, exist_ok=True)
            orig_p = Path(fpath)
            f_size = orig_p.stat().st_size if orig_p.is_file() else 0
            target_p = Path(dest_dir) / orig_p.name

            # 冲突处理
            if target_p.exists():
                manifest["results"]["conflict"] += 1
                if conflict_policy == "skip":
                    skipped_count += 1
                    manifest["results"]["skipped"] += 1
                    continue
                elif conflict_policy == "auto_rename":
                    counter = 1
                    while target_p.exists():
                        target_p = target_p.parent / f"{orig_p.stem}_{counter}{orig_p.suffix}"
                        counter += 1

            # 执行安全移动
            shutil.move(str(orig_p), str(target_p))

            success_count += 1
            archived_bytes += f_size
            success_paths.append(str(target_p))

            manifest["items"].append({
                "entry_id": f"AUTO_{idx}",
                "node_type": "file",
                "original_path": fpath,
                "archived_path": str(target_p),
                "parent_path": str(orig_p.parent),
                "operation": "move",
                "operation_status": "success",
                "rollback_status": "none",
                "size": f_size
            })

            _log(f"📦 自动归档成功: {orig_p.name} ➔ {target_p.parent.name}/{target_p.name}", "info")

        except Exception as e:
            failed_count += 1
            manifest["results"]["failed"] += 1
            _log(f"❌ 移动失败 [{fpath}]: {e}", "error")

    # 更新并写入最终 Manifest 凭证
    manifest["status"] = "COMPLETED" if failed_count == 0 else "PARTIAL_SUCCESS"
    manifest["results"]["success"] = success_count
    try:
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        _log(f"📑 已生成归档回滚凭据: {manifest_file.name}", "info")
    except Exception as e:
        app_logger.error(f"保存清单异常: {e}")

    # 发布领域事件
    if success_paths:
        try:
            from app.core.events import event_bus
            orig_success = [it["original_path"] for it in manifest["items"] if it.get("operation_status") == "success"]
            event_bus.publish_files_changed("archived", orig_success, backup_id, {"archived_bytes": archived_bytes})
        except Exception as e:
            app_logger.debug(f"领域事件广播异常: {e}")

    summary_msg = (
        f"⚡ 自动归档完成！成功: {success_count} | 占用/锁定跳过: {locked_count} | "
        f"失败: {failed_count} | 容量: {format_size(archived_bytes)}"
    )
    _log(summary_msg, "success" if success_count > 0 else "info")

    return {
        "success": True,
        "backup_id": backup_id,
        "manifest_path": str(manifest_file),
        "success_count": success_count,
        "locked_count": locked_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "archived_bytes": archived_bytes,
        "success_paths": success_paths
    }
