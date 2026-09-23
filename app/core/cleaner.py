import os
import json
import time
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

import send2trash
from PySide6.QtCore import QThread, Signal

from app.utils.file_helper import is_system_critical_path, format_size
from app.utils.logger import app_logger

ARCHIVE_MANIFEST_DIR = Path.home() / ".disk_space_analyzer" / "archive_manifests"


class ArchiveWorker(QThread):
    """
    异步多文件/目录后台归档迁移引擎
    具备：
    1. 实时吞吐速度 (MB/s) 与剩余预估时间 (ETA) 计算
    2. 毫秒级 Pause (暂停) / Resume (恢复) / Cancel (取消) 支持
    3. 冲突策略处理 (auto_rename, skip, overwrite)
    4. 单文件异常非阻塞容错
    5. 自动生成可回滚 Manifest 凭证
    """
    progress_signal = Signal(object, object, str, int, object, object) # (已处理数, 总数, 速度, ETA, 已处理字节, 总字节)
    file_processed_signal = Signal(str, str, bool, str)                 # (原路径, 目标路径, 成功, 信息)
    log_signal = Signal(str, str)                                       # (日志消息, 级别: info/success/warn/error)
    finished_signal = Signal(bool, dict)                                # (是否全部成功, 汇总报告)

    def __init__(
        self,
        file_items: List[Dict[str, Any]],  # [{"path": "...", "target_category": "...", "custom_target": "..."}, ...]
        destination_root: str,
        conflict_policy: str = "auto_rename", # auto_rename | skip | overwrite
        preserve_structure: bool = True,
        task_id: Optional[str] = None,
        parent=None
    ):
        super().__init__(parent)
        self.file_items = file_items
        self.destination_root = os.path.normpath(destination_root)
        self.conflict_policy = conflict_policy
        self.preserve_structure = preserve_structure
        self.task_id = task_id or f"ARCHIVE_{int(time.time()*1000)}"

        self._is_running = True
        self._pause_event = threading.Event()
        self._pause_event.set()

    def pause(self):
        self._pause_event.clear()
        self.log_signal.emit("⏸️ 归档任务已暂停", "warn")

    def resume(self):
        self._pause_event.set()
        self.log_signal.emit("▶️ 归档任务已恢复", "info")

    def cancel(self):
        self._is_running = False
        self._pause_event.set()
        self.log_signal.emit("⏹️ 正在中止归档任务...", "warn")

    def run(self):
        start_time = time.time()
        ARCHIVE_MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
        manifest_file = ARCHIVE_MANIFEST_DIR / f"manifest_{self.task_id}.json"

        manifest = {
            "task_id": self.task_id,
            "created_at": start_time,
            "destination_root": self.destination_root,
            "items": []
        }

        summary = {
            "task_id": self.task_id,
            "manifest_path": str(manifest_file),
            "total_count": len(self.file_items),
            "success_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "conflict_count": 0,
            "archived_bytes": 0,
            "total_bytes": 0,
            "errors": []
        }

        # 计算总字节数
        for item in self.file_items:
            fpath = item.get("path", "")
            if os.path.exists(fpath):
                try:
                    summary["total_bytes"] += os.path.getsize(fpath) if os.path.isfile(fpath) else 0
                except Exception:
                    pass

        self.log_signal.emit(f"🚀 启动后台归档任务 [{self.task_id}]，目标: {self.destination_root} (共 {len(self.file_items)} 项)", "info")
        os.makedirs(self.destination_root, exist_ok=True)

        dest_root_path = Path(self.destination_root)
        timestamp_folder = datetime.now().strftime("Archive_%Y%m%d_%H%M%S")
        base_dir = dest_root_path / timestamp_folder if self.preserve_structure else dest_root_path
        base_dir.mkdir(parents=True, exist_ok=True)

        processed_bytes = 0
        speed_timer = time.time()
        bytes_since_last_calc = 0
        total_items_count = len(self.file_items)

        for idx, item in enumerate(self.file_items, 1):
            if not self._is_running:
                break
            self._pause_event.wait()

            fpath = item.get("path", "")
            if not os.path.exists(fpath):
                summary["skipped_count"] += 1
                self.file_processed_signal.emit(fpath, "", False, "文件不存在，已跳过")
                continue

            # 安全拦截系统目录
            if is_system_critical_path(fpath):
                summary["failed_count"] += 1
                summary["errors"].append({"path": fpath, "error": "安全拦截：禁止移动 Windows 核心受保护系统文件"})
                self.log_signal.emit(f"❌ 安全拦截：禁止归档核心系统目录: {fpath}", "error")
                self.file_processed_signal.emit(fpath, "", False, "安全拦截")
                continue

            try:
                p = Path(fpath)
                f_size = p.stat().st_size if p.is_file() else 0
                
                # 计算目标归档路径
                custom_target = item.get("custom_target")
                custom_cat = item.get("target_category")
                if custom_target:
                    target_file = Path(custom_target)
                elif custom_cat:
                    # 自定义分类目录
                    target_dir = dest_root_path / custom_cat
                    target_file = target_dir / p.name
                elif self.preserve_structure:
                    drive = p.drive.replace(":", "") if p.drive else "Root"
                    relative_parts = p.parts[1:] if p.drive else p.parts
                    target_file = base_dir / f"Drive_{drive}" / Path(*relative_parts)
                else:
                    target_file = base_dir / p.name

                target_file.parent.mkdir(parents=True, exist_ok=True)

                # 冲突处理
                if target_file.exists():
                    summary["conflict_count"] += 1
                    if self.conflict_policy == "skip":
                        summary["skipped_count"] += 1
                        self.log_signal.emit(f"⚠️ 目标已存在同名文件，跳过: {target_file}", "warn")
                        self.file_processed_signal.emit(fpath, str(target_file), False, "同名冲突跳过")
                        continue
                    elif self.conflict_policy == "overwrite":
                        # 覆盖模式
                        if target_file.is_file():
                            os.remove(str(target_file))
                        elif target_file.is_dir():
                            shutil.rmtree(str(target_file))
                    else:
                        # 自动递增重命名 (auto_rename)
                        counter = 1
                        while target_file.exists():
                            target_file = target_file.parent / f"{target_file.stem}_{counter}{target_file.suffix}"
                            counter += 1

                # 执行物理移动
                shutil.move(str(p), str(target_file))
                
                summary["success_count"] += 1
                summary["archived_bytes"] += f_size
                processed_bytes += f_size
                bytes_since_last_calc += f_size

                manifest["items"].append({
                    "original_path": fpath,
                    "target_path": str(target_file),
                    "size": f_size
                })

                self.file_processed_signal.emit(fpath, str(target_file), True, "归档成功")

                # 速度与 ETA 计算
                now = time.time()
                if now - speed_timer >= 0.4 or idx == total_items_count:
                    duration = max(0.001, now - speed_timer)
                    speed_bps = bytes_since_last_calc / duration
                    speed_str = f"{format_size(int(speed_bps))}/s"
                    rem_bytes = max(0, summary["total_bytes"] - processed_bytes)
                    eta_sec = int(rem_bytes / speed_bps) if speed_bps > 0 else 0

                    self.progress_signal.emit(
                        idx, total_items_count, speed_str, eta_sec, processed_bytes, summary["total_bytes"]
                    )
                    speed_timer = now
                    bytes_since_last_calc = 0

            except Exception as e:
                app_logger.error(f"归档失败 {fpath}: {e}")
                summary["failed_count"] += 1
                summary["errors"].append({"path": fpath, "error": str(e)})
                self.log_signal.emit(f"❌ 归档失败: {fpath} -> {str(e)}", "error")
                self.file_processed_signal.emit(fpath, "", False, str(e))

        # 保存 Manifest 凭据
        try:
            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            self.log_signal.emit(f"📑 已生成归档回滚清单: {manifest_file.name}", "info")
        except Exception as e:
            app_logger.error(f"保存归档清单异常: {e}")

        elapsed = round(time.time() - start_time, 2)
        summary["elapsed_seconds"] = elapsed
        self.log_signal.emit(
            f"🎉 归档任务执行完成！成功: {summary['success_count']} | 失败: {summary['failed_count']} | 跳过: {summary['skipped_count']} | 容量: {format_size(summary['archived_bytes'])} (耗时 {elapsed}s)",
            "success" if summary["failed_count"] == 0 else "warn"
        )
        self.finished_signal.emit(summary["failed_count"] == 0, summary)

    @classmethod
    def rollback_archive(cls, manifest_path: str) -> Tuple[bool, str]:
        """根据 Manifest 清单将已归档文件还原回原路径"""
        m_file = Path(manifest_path)
        if not m_file.exists():
            return False, "清单文件不存在"

        try:
            with open(m_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            restored = 0
            errors = []
            for item in data.get("items", []):
                orig = item.get("original_path")
                targ = item.get("target_path")
                if targ and os.path.exists(targ):
                    try:
                        os.makedirs(os.path.dirname(orig), exist_ok=True)
                        shutil.move(targ, orig)
                        restored += 1
                    except Exception as err:
                        errors.append(str(err))

            return True, f"成功回滚还原 {restored} 个文件！" + (f" ({len(errors)} 个失败)" if errors else "")
        except Exception as e:
            return False, f"回滚过程发生异常: {e}"


class DeleteWorker(QThread):
    """异步后台安全删除/回收站引擎"""
    progress_signal = Signal(object, object)      # (已删除数, 总数)
    finished_signal = Signal(bool, dict)

    def __init__(self, file_paths: List[str], to_recycle_bin: bool = True, parent=None):
        super().__init__(parent)
        self.file_paths = file_paths
        self.to_recycle_bin = to_recycle_bin
        self._is_canceled = False

    def cancel(self):
        self._is_canceled = True

    def run(self):
        summary = {
            "success_count": 0,
            "failed_count": 0,
            "freed_bytes": 0,
            "errors": []
        }
        total = len(self.file_paths)

        for idx, fpath in enumerate(self.file_paths, 1):
            if self._is_canceled:
                break

            if not os.path.exists(fpath):
                continue

            if is_system_critical_path(fpath):
                summary["failed_count"] += 1
                summary["errors"].append({"path": fpath, "error": "安全拦截：禁止删除受保护系统核心文件"})
                continue

            try:
                file_size = os.path.getsize(fpath) if os.path.isfile(fpath) else 0
                if self.to_recycle_bin:
                    send2trash.send2trash(os.path.normpath(fpath))
                else:
                    if os.path.isfile(fpath) or os.path.islink(fpath):
                        os.remove(fpath)
                    elif os.path.isdir(fpath):
                        shutil.rmtree(fpath)
                summary["success_count"] += 1
                summary["freed_bytes"] += file_size
            except Exception as e:
                summary["failed_count"] += 1
                summary["errors"].append({"path": fpath, "error": str(e)})

            self.progress_signal.emit(idx, total)

        self.finished_signal.emit(summary["failed_count"] == 0, summary)


class FileCleaner:
    """提供统一接口与辅助方法的 Cleaner 门面类"""
    @staticmethod
    def delete_files(file_paths: List[str], to_recycle_bin: bool = True) -> Tuple[int, int, int, List[Dict[str, str]]]:
        worker = DeleteWorker(file_paths, to_recycle_bin)
        worker.run() # 同步调用备用
        res = worker.finished_signal
        return worker.file_paths
