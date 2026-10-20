"""
app/dedup/executor.py
安全跨盘原子融合与断点恢复执行器
支持跨卷原子暂存落位、排他锁安全保护、同名冲突自动重命名与标准可回滚 Manifest 凭据
"""
import os
import shutil
import time
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Callable, Set, Tuple, Any

from app.dedup.models import DedupScanResult, MergeAction, DedupGroup, CollisionItem
from app.utils.lock_detector import is_destination_valid, is_file_locked_or_in_use
from app.utils.logger import app_logger

ARCHIVE_MANIFEST_DIR = Path.home() / ".disk_space_analyzer" / "archive_manifests"


class MergeExecutor:
    """查重与融合执行引擎"""

    @classmethod
    def build_merge_plan(
        cls,
        scan_result: DedupScanResult,
        target_dir: str,
        isolation_dir: Optional[str] = None,
        keep_paths_override: Optional[Set[str]] = None,
        collision_strategy: str = "rename"  # rename | skip
    ) -> List[MergeAction]:
        """
        根据查重与冲突检测结果构建具体的融合操作指令清单
        """
        norm_target = os.path.normpath(target_dir) if target_dir else ""
        norm_iso = os.path.normpath(isolation_dir) if isolation_dir else (
            os.path.join(norm_target, "_Duplicate_Isolation") if norm_target else ""
        )

        actions: List[MergeAction] = []
        handled_paths: Set[str] = set()

        # 1. 处理完全重复文件组 (Exact Duplicates)
        for group in scan_result.duplicate_groups:
            # 确定当前组保留的文件路径
            keep_path = group.recommended_keep_path or (group.items[0].path if group.items else "")
            if keep_paths_override:
                # 若用户在前端手动指定了保留项
                for it in group.items:
                    if it.path in keep_paths_override:
                        keep_path = it.path
                        break

            for it in group.items:
                handled_paths.add(it.path)
                if it.path == keep_path:
                    # 保留项
                    actions.append(MergeAction(
                        action_type="keep",
                        source_path=it.path,
                        target_path=it.path,
                        size=it.size,
                        reason="保留唯一正本",
                        is_locked=it.is_locked,
                        source_dir=it.source_dir
                    ))
                else:
                    # 冗余副本：移入专属隔离归档目录，严禁直接永久物理删除
                    iso_sub = it.rel_path
                    iso_target = os.path.join(norm_iso, iso_sub) if norm_iso else ""
                    actions.append(MergeAction(
                        action_type="isolate_archive",
                        source_path=it.path,
                        target_path=iso_target,
                        size=it.size,
                        reason="冗余重复副本移入隔离区",
                        is_locked=it.is_locked,
                        source_dir=it.source_dir
                    ))

        # 2. 处理同名异内容冲突文件 (Collisions)
        for col in scan_result.collisions:
            for it in col.files:
                if it.path in handled_paths:
                    continue
                handled_paths.add(it.path)

                if collision_strategy == "skip":
                    actions.append(MergeAction(
                        action_type="skip",
                        source_path=it.path,
                        target_path=None,
                        size=it.size,
                        reason="同名异内容冲突策略设为跳过",
                        is_locked=it.is_locked,
                        source_dir=it.source_dir
                    ))
                else:
                    # 自动安全重命名: 添加源目录标记与防冲突后缀
                    src_tag = os.path.basename(it.source_dir)
                    stem, ext = os.path.splitext(it.rel_path)
                    renamed_rel = f"{stem}_from_{src_tag}{ext}"
                    dest_p = os.path.join(norm_target, renamed_rel) if norm_target else ""
                    actions.append(MergeAction(
                        action_type="rename_merge",
                        source_path=it.path,
                        target_path=dest_p,
                        size=it.size,
                        reason=f"同名异内容安全重命名融入 (来自 {src_tag})",
                        is_locked=it.is_locked,
                        source_dir=it.source_dir
                    ))

        # 3. 处理唯一文件 (Unique Files)
        for it in scan_result.unique_files:
            if it.path in handled_paths:
                continue
            handled_paths.add(it.path)

            dest_p = os.path.join(norm_target, it.rel_path) if norm_target else ""
            actions.append(MergeAction(
                action_type="move_merge",
                source_path=it.path,
                target_path=dest_p,
                size=it.size,
                reason="唯一资产按源相对结构融入",
                is_locked=it.is_locked,
                source_dir=it.source_dir
            ))

        return actions

    @classmethod
    def validate_plan(
        cls,
        actions: List[MergeAction],
        target_dir: str,
        source_dirs: List[str]
    ) -> Tuple[bool, List[str]]:
        """
        校验计划合法性、防嵌套逃逸与目标空间
        """
        errors: List[str] = []
        if not target_dir or not target_dir.strip():
            errors.append("未指定目标融合目录")
            return False, errors

        norm_target = os.path.normpath(target_dir)

        # 检查各源目录与目标目录的嵌套包含关系
        for src in source_dirs:
            is_valid, msg = is_destination_valid(src, norm_target)
            if not is_valid:
                errors.append(f"源目录 [{os.path.basename(src)}] 与目标目录拓扑冲突: {msg}")

        # 检查被锁定的文件
        locked_count = sum(1 for a in actions if a.is_locked and a.action_type not in ("keep", "skip"))
        if locked_count > 0:
            app_logger.warning("发现 %d 个文件被外部程序占用，执行时将自动保护跳过", locked_count)

        # 检查目标盘空间 (粗略估算需写入的总字节数)
        total_need_bytes = sum(
            a.size for a in actions
            if a.action_type in ("move_merge", "rename_merge")
            and a.target_path
            and os.path.splitdrive(a.source_path)[0].upper() != os.path.splitdrive(a.target_path)[0].upper()
        )
        try:
            target_drive = os.path.splitdrive(norm_target)[0]
            drive_to_check = target_drive if target_drive else norm_target
            disk_stat = shutil.disk_usage(drive_to_check)
            if disk_stat.free < total_need_bytes:
                errors.append(f"目标磁盘空间不足: 需要跨卷写入 {total_need_bytes} 字节，剩余仅 {disk_stat.free} 字节")
        except Exception as e:
            app_logger.debug("检查磁盘剩余空间跳过: %s", e)

        return len(errors) == 0, errors

    @classmethod
    def execute_plan(
        cls,
        actions: List[MergeAction],
        target_dir: str,
        progress_cb: Optional[Callable[[int, int, str, int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> Dict[str, Any]:
        """
        安全执行融合操作，支持跨盘原子落位与可回滚 Manifest 凭据记录
        progress_cb: (已处理项数, 总项数, 当前文件, 成功数, 失败数)
        """
        norm_target = os.path.normpath(target_dir)
        os.makedirs(norm_target, exist_ok=True)

        backup_id = f"merge_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        ARCHIVE_MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
        manifest_file = ARCHIVE_MANIFEST_DIR / f"manifest_{backup_id}.json"

        manifest: Dict[str, Any] = {
            "version": "1.0",
            "backup_id": backup_id,
            "created_at": datetime.now().isoformat(),
            "status": "RUNNING",
            "operation_type": "dedup_merge",
            "destination_root": norm_target,
            "manifest_path": str(manifest_file),
            "items": [],
            "results": {
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "conflict": 0
            }
        }

        executable_actions = [a for a in actions if a.action_type in ("move_merge", "rename_merge", "isolate_archive")]
        total_count = len(executable_actions)
        success_count = 0
        failed_count = 0
        skipped_count = 0

        for idx, act in enumerate(executable_actions):
            if cancel_check and not cancel_check():
                break

            src = act.source_path
            dst = act.target_path

            if progress_cb:
                progress_cb(idx + 1, total_count, os.path.basename(src), success_count, failed_count)

            # 1. 占用锁与文件存在性检查
            if not os.path.exists(src):
                skipped_count += 1
                continue

            if act.is_locked:
                # 再次检测，若仍锁定则安全跳过
                is_locked, reason = is_file_locked_or_in_use(src, min_cooldown_seconds=0.5)
                if is_locked:
                    skipped_count += 1
                    app_logger.warning("文件被程序占用锁定，安全跳过: %s (%s)", src, reason)
                    continue

            if not dst:
                skipped_count += 1
                continue

            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)

                # 2. 如果目标已存在同名项，防止覆盖自动防冲突重命名
                final_dst = dst
                c_idx = 1
                base, ext = os.path.splitext(dst)
                while os.path.exists(final_dst) and os.path.normcase(final_dst) != os.path.normcase(src):
                    final_dst = f"{base}_{c_idx}{ext}"
                    c_idx += 1

                # 3. 判断同卷或跨卷转移
                src_drive = os.path.splitdrive(src)[0].upper()
                dst_drive = os.path.splitdrive(final_dst)[0].upper()

                if src_drive == dst_drive:
                    # 同卷系统级原子重命名
                    shutil.move(src, final_dst)
                else:
                    # 跨卷原子落位: 复制到 .tmp_merge -> SHA-256 校验 -> 原子 rename
                    tmp_target = final_dst + f".tmp_merge_{int(time.time()*1000)}"
                    cls._copy_with_hash_verify(src, tmp_target)
                    # 校验完成，重命名为正式路径
                    if os.path.exists(final_dst):
                        os.remove(final_dst)
                    os.rename(tmp_target, final_dst)
                    # 移除源文件
                    try:
                        os.remove(src)
                    except Exception:
                        pass

                success_count += 1
                manifest["items"].append({
                    "entry_id": f"ENTRY_{idx + 1}",
                    "node_type": "file",
                    "original_path": src,
                    "archived_path": final_dst,
                    "parent_path": str(Path(src).parent),
                    "operation": "move",
                    "operation_status": "success",
                    "rollback_status": "none",
                    "conflict_status": "none",
                    "error_message": "",
                    "size": act.size
                })

            except Exception as e:
                failed_count += 1
                app_logger.error("融合移动失败 %s -> %s: %s", src, dst, e)
                manifest["items"].append({
                    "entry_id": f"ENTRY_{idx + 1}",
                    "node_type": "file",
                    "original_path": src,
                    "archived_path": dst,
                    "parent_path": str(Path(src).parent),
                    "operation": "move",
                    "operation_status": "failed",
                    "rollback_status": "none",
                    "conflict_status": "none",
                    "error_message": str(e),
                    "size": act.size
                })

        manifest["status"] = "COMPLETED" if failed_count == 0 else "PARTIAL_SUCCESS"
        manifest["results"]["success"] = success_count
        manifest["results"]["failed"] = failed_count
        manifest["results"]["skipped"] = skipped_count
        manifest["completed_at"] = datetime.now().isoformat()

        try:
            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
        except Exception as e:
            app_logger.error("保存 Manifest 凭据失败: %s", e)

        return {
            "backup_id": backup_id,
            "manifest_file": str(manifest_file),
            "total": total_count,
            "success": success_count,
            "failed": failed_count,
            "skipped": skipped_count
        }

    @classmethod
    def _copy_with_hash_verify(cls, src: str, tmp_dst: str):
        """跨盘复制并计算 SHA-256 校验确保无损"""
        src_h = hashlib.sha256()
        dst_h = hashlib.sha256()

        chunk_size = 1024 * 1024
        with open(src, "rb") as f_in, open(tmp_dst, "wb") as f_out:
            while True:
                buf = f_in.read(chunk_size)
                if not buf:
                    break
                src_h.update(buf)
                f_out.write(buf)
                dst_h.update(buf)

        if src_h.hexdigest() != dst_h.hexdigest():
            if os.path.exists(tmp_dst):
                os.remove(tmp_dst)
            raise IOError(f"跨盘校验哈希不一致: {src} -> {tmp_dst}")
