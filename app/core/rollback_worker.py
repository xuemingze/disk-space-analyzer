import os
import json
import time
import shutil
from pathlib import Path
from typing import List, Dict, Any, Tuple

from PySide6.QtCore import QThread, Signal
from app.utils.logger import app_logger

class RollbackWorker(QThread):
    """异步多文件/目录选择性回滚引擎"""
    progress_signal = Signal(object, object, str, int, object, object)
    file_processed_signal = Signal(str, str, bool, str)
    log_signal = Signal(str, str)
    finished_signal = Signal(bool, dict)

    def __init__(self, manifest_path: str, selected_entry_ids: List[str] = None, parent=None):
        super().__init__(parent)
        self.manifest_path = manifest_path
        self.selected_entry_ids = selected_entry_ids  # None means all rollbackable
        self._is_running = True
        self._pause_event = __import__('threading').Event()
        self._pause_event.set()

    def pause(self):
        self._pause_event.clear()
        self.log_signal.emit("⏸️ 回滚任务已暂停", "warn")

    def resume(self):
        self._pause_event.set()
        self.log_signal.emit("▶️ 回滚任务已恢复", "info")

    def cancel(self):
        self._is_running = False
        self._pause_event.set()
        self.log_signal.emit("⏹️ 正在中止回滚任务...", "warn")

    def run(self):
        start_time = time.time()
        m_file = Path(self.manifest_path)
        if not m_file.exists():
            self.log_signal.emit("❌ 清单文件不存在", "error")
            self.finished_signal.emit(False, {"error": "清单文件不存在"})
            return

        try:
            with open(m_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self.log_signal.emit(f"❌ 解析清单文件失败: {e}", "error")
            self.finished_signal.emit(False, {"error": str(e)})
            return

        items = data.get("items", [])
        
        # 筛选需要回滚的项
        target_items = []
        for it in items:
            if self.selected_entry_ids is not None:
                if it.get("entry_id") not in self.selected_entry_ids:
                    continue
            
            if it.get("operation_status") != "success" or it.get("rollback_status") == "success":
                continue
            
            target_items.append(it)

        total_count = len(target_items)
        if total_count == 0:
            self.log_signal.emit("⚠️ 没有需要回滚的项目", "warn")
            self.finished_signal.emit(True, {"success_count": 0, "failed_count": 0, "skipped_count": 0})
            return

        success_paths = []
        summary = {
            "success_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "total_bytes": sum(it.get("size", 0) for it in target_items),
            "restored_bytes": 0,
            "errors": []
        }

        self.log_signal.emit(f"🚀 启动回滚任务，目标恢复项目数: {total_count}", "info")
        
        processed_bytes = 0
        speed_timer = time.time()
        bytes_since_last = 0

        for idx, item in enumerate(target_items, 1):
            if not self._is_running:
                break
            self._pause_event.wait()

            orig = item.get("original_path")
            targ = item.get("archived_path") or item.get("target_path")
            f_size = item.get("size", 0)

            if not targ or not os.path.exists(targ):
                summary["failed_count"] += 1
                item["rollback_status"] = "failed"
                item["error_message"] = "归档文件不存在或已删除"
                self.file_processed_signal.emit(targ, orig, False, item["error_message"])
                continue

            if os.path.exists(orig):
                summary["skipped_count"] += 1
                item["rollback_status"] = "conflict"
                item["error_message"] = "原路径已存在文件，为安全已跳过"
                self.file_processed_signal.emit(targ, orig, False, item["error_message"])
                continue

            try:
                os.makedirs(os.path.dirname(orig), exist_ok=True)
                shutil.move(targ, orig)
                summary["success_count"] += 1
                success_paths.append(orig)
                summary["restored_bytes"] += f_size
                processed_bytes += f_size
                bytes_since_last += f_size
                
                item["rollback_status"] = "success"
                item["error_message"] = ""
                self.file_processed_signal.emit(targ, orig, True, "回滚成功")

                now = time.time()
                if now - speed_timer >= 0.4 or idx == total_count:
                    duration = max(0.001, now - speed_timer)
                    speed_bps = bytes_since_last / duration
                    from app.utils.file_helper import format_size
                    speed_str = f"{format_size(int(speed_bps))}/s"
                    rem_bytes = max(0, summary["total_bytes"] - processed_bytes)
                    eta_sec = int(rem_bytes / speed_bps) if speed_bps > 0 else 0

                    self.progress_signal.emit(
                        idx, total_count, speed_str, eta_sec, processed_bytes, summary["total_bytes"]
                    )
                    speed_timer = now
                    bytes_since_last = 0
                    
            except Exception as err:
                summary["failed_count"] += 1
                item["rollback_status"] = "failed"
                item["error_message"] = str(err)
                self.file_processed_signal.emit(targ, orig, False, str(err))

        # 更新清单
        has_failed = summary["failed_count"] > 0
        has_success = summary["success_count"] > 0
        all_success = all(it.get("rollback_status") == "success" for it in items if it.get("operation_status") == "success")
        
        if all_success:
            data["rollback_status"] = "FULL_ROLLEDBACK"
        elif has_success:
            data["rollback_status"] = "PARTIAL_ROLLEDBACK"

        try:
            with open(m_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            app_logger.error(f"保存回滚清单失败: {e}")

        elapsed = round(time.time() - start_time, 2)
        summary["elapsed_seconds"] = elapsed
        self.log_signal.emit(
            f"🎉 回滚任务完成！成功: {summary['success_count']} | 失败: {summary['failed_count']} | 跳过: {summary['skipped_count']} (耗时 {elapsed}s)",
            "success" if not has_failed else "warn"
        )
        
        from app.core.events import event_bus
        if success_paths:
            event_bus.publish_files_changed("rollbacked", success_paths, "ROLLBACK_TASK", {"restored_bytes": summary["restored_bytes"]})
            
        self.finished_signal.emit(not has_failed, summary)
