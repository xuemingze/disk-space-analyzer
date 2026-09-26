import json
import time
import threading
import os
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any
from PySide6.QtCore import QObject, Signal

class TaskType(str, Enum):
    SCAN = "磁盘空间扫描"
    HASH_CHECK = "深度哈希查重"
    MIGRATION = "文件智能迁移"
    CLEANUP = "冗余文件清理"
    AI_ANALYSIS = "AI 智能分析"

class TaskStatus(str, Enum):
    CREATED = "已创建"
    QUEUED = "排队中"
    RUNNING = "运行中"
    PAUSING = "暂停中"
    PAUSED = "已暂停"
    CANCELLING = "取消中"
    CANCELED = "已取消"
    COMPLETED = "已完成"
    FAILED = "失败"

class TaskItem:
    def __init__(self, task_id: str, name: str, task_type: TaskType, worker: Any = None):
        self.task_id = task_id
        self.name = name
        self.task_type = task_type
        self.status = TaskStatus.CREATED
        self.current_phase = "准备就绪"
        self.progress_percent = 0.0
        self.processed_count = 0
        self.total_count = 0
        self.processed_bytes = 0
        self.total_bytes = 0
        self.current_speed = "0 B/s"
        self.eta_seconds = 0
        self.start_time = time.time()
        self.end_time = None
        self.error_message = None
        self.logs = []
        self.worker = worker

    def add_log(self, message: str, level: str = "info"):
        timestamp = time.strftime("%H:%M:%S")
        self.logs.append({"time": timestamp, "message": message, "level": level})
        if len(self.logs) > 500:
            self.logs.pop(0)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "task_type": self.task_type.value,
            "status": self.status.value,
            "current_phase": self.current_phase,
            "progress_percent": self.progress_percent,
            "processed_count": self.processed_count,
            "total_count": self.total_count,
            "processed_bytes": self.processed_bytes,
            "total_bytes": self.total_bytes,
            "current_speed": self.current_speed,
            "eta_seconds": self.eta_seconds,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "error_message": self.error_message,
            "logs": self.logs
        }

    @classmethod
    def from_dict(cls, data: dict):
        try:
            t_type = TaskType(data.get("task_type", TaskType.SCAN.value))
        except ValueError:
            t_type = TaskType.SCAN
        item = cls(data.get("task_id", ""), data.get("name", "Unknown"), t_type)
        try:
            item.status = TaskStatus(data.get("status", TaskStatus.FAILED.value))
        except ValueError:
            item.status = TaskStatus.FAILED
        
        if item.status in (TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.PAUSING, TaskStatus.PAUSED, TaskStatus.CANCELLING):
            item.status = TaskStatus.FAILED
            item.error_message = "任务异常中断 (程序关闭或崩溃)"
            
        item.current_phase = data.get("current_phase", "")
        item.progress_percent = data.get("progress_percent", 0.0)
        item.processed_count = data.get("processed_count", 0)
        item.total_count = data.get("total_count", 0)
        item.processed_bytes = data.get("processed_bytes", 0)
        item.total_bytes = data.get("total_bytes", 0)
        item.current_speed = data.get("current_speed", "0 B/s")
        item.eta_seconds = data.get("eta_seconds", 0)
        item.start_time = data.get("start_time", time.time())
        item.end_time = data.get("end_time")
        item.error_message = data.get("error_message")
        item.logs = data.get("logs", [])
        return item

class TaskManager(QObject):
    task_added = Signal(TaskItem)
    task_updated = Signal(TaskItem)
    task_finished = Signal(TaskItem)
    task_log_appended = Signal(str, str, str)

    _instance = None
    _lock = threading.Lock()
    _HISTORY_FILE = Path.home() / ".disk_space_analyzer" / "task_history.json"

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(TaskManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        super().__init__()
        self._tasks: Dict[str, TaskItem] = {}
        self._task_lock = threading.Lock()
        self._initialized = True
        self._HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._load_history()

    def _load_history(self):
        if not self._HISTORY_FILE.exists():
            return
        try:
            with open(self._HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in data.items():
                    self._tasks[k] = TaskItem.from_dict(v)
        except Exception:
            pass

    def _save_history(self):
        try:
            data = {k: v.to_dict() for k, v in self._tasks.items()}
            with open(self._HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def create_task(self, name: str, task_type: TaskType, worker: Any = None) -> TaskItem:
        task_id = f"TASK_{int(time.time()*1000)}"
        item = TaskItem(task_id, name, task_type, worker)
        item.status = TaskStatus.QUEUED
        with self._task_lock:
            self._tasks[task_id] = item
            self._save_history()
        self.task_added.emit(item)
        return item

    def get_task(self, task_id: str) -> Optional[TaskItem]:
        with self._task_lock:
            return self._tasks.get(task_id)

    def list_tasks(self) -> List[TaskItem]:
        with self._task_lock:
            return list(self._tasks.values())

    def update_task_progress(self, task_id: str, phase: str = None, progress_pct: float = None,
                             processed_count: int = None, total_count: int = None,
                             processed_bytes: int = None, total_bytes: int = None,
                             speed: str = None, eta: int = None):
        with self._task_lock:
            item = self._tasks.get(task_id)
            if not item: return
            if phase is not None: item.current_phase = phase
            if progress_pct is not None: item.progress_percent = max(0.0, min(100.0, progress_pct))
            if processed_count is not None: item.processed_count = processed_count
            if total_count is not None: item.total_count = total_count
            if processed_bytes is not None: item.processed_bytes = processed_bytes
            if total_bytes is not None: item.total_bytes = total_bytes
            if speed is not None: item.current_speed = speed
            if eta is not None: item.eta_seconds = eta
            
            if item.status in (TaskStatus.CREATED, TaskStatus.QUEUED):
                item.status = TaskStatus.RUNNING

        self.task_updated.emit(item)

    def append_log(self, task_id: str, message: str, level: str = "info"):
        with self._task_lock:
            item = self._tasks.get(task_id)
            if item: item.add_log(message, level)
        self.task_log_appended.emit(task_id, message, level)

    def set_task_status(self, task_id: str, status: TaskStatus, error_msg: str = None):
        with self._task_lock:
            item = self._tasks.get(task_id)
            if not item: return
            if item.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED):
                return
            item.status = status
            if error_msg: item.error_message = error_msg
            if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED):
                item.end_time = time.time()
                item.worker = None
            self._save_history()

        self.task_updated.emit(item)
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED):
            self.task_finished.emit(item)

    def pause_task(self, task_id: str):
        with self._task_lock:
            item = self._tasks.get(task_id)
            if not item or item.status not in (TaskStatus.RUNNING, TaskStatus.QUEUED):
                return
            item.status = TaskStatus.PAUSING
            if item.worker and hasattr(item.worker, "pause"):
                item.worker.pause()
            item.status = TaskStatus.PAUSED
            self._save_history()
            self.task_updated.emit(item)

    def resume_task(self, task_id: str):
        with self._task_lock:
            item = self._tasks.get(task_id)
            if not item or item.status != TaskStatus.PAUSED:
                return
            item.status = TaskStatus.RUNNING
            if item.worker and hasattr(item.worker, "resume"):
                item.worker.resume()
            self._save_history()
            self.task_updated.emit(item)

    def cancel_task(self, task_id: str):
        with self._task_lock:
            item = self._tasks.get(task_id)
            if not item or item.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED):
                return
            item.status = TaskStatus.CANCELLING
            if item.worker and hasattr(item.worker, "cancel"):
                item.worker.cancel()
            item.status = TaskStatus.CANCELED
            item.end_time = time.time()
            item.worker = None
            self._save_history()
            
        self.task_updated.emit(item)
        self.task_finished.emit(item)

    def clear_history(self):
        with self._task_lock:
            active_tasks = {
                k: v for k, v in self._tasks.items()
                if v.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED)
            }
            self._tasks = active_tasks
            self._save_history()

    def has_active_tasks(self) -> bool:
        with self._task_lock:
            for t in self._tasks.values():
                if t.status in (TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.QUEUED, TaskStatus.PAUSING, TaskStatus.CANCELLING):
                    return True
        return False


from PySide6.QtCore import QThread

class TaskHistoryCleanupTask(QThread):
    cleanup_started = Signal(str, int)
    cleanup_progress = Signal(str, int, int)
    cleanup_item_result = Signal(str, str, str, str)
    cleanup_finished = Signal(str, int, int, int)
    cleanup_failed = Signal(str, str, str)

    def __init__(self, task_manager, parent=None):
        super().__init__(parent)
        self.task_manager = task_manager
        self.cleanup_task_id = "CLEANUP_" + str(int(time.time()))

    def run(self):
        try:
            tasks_to_remove = []
            with self.task_manager._task_lock:
                all_tasks = list(self.task_manager._tasks.values())
            
            for t in all_tasks:
                if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED):
                    tasks_to_remove.append(t.task_id)
            
            total = len(tasks_to_remove)
            self.cleanup_started.emit(self.cleanup_task_id, total)
            
            success = 0
            skipped = 0
            
            for i, tid in enumerate(tasks_to_remove):
                with self.task_manager._task_lock:
                    t = self.task_manager._tasks.get(tid)
                    if t and t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED):
                        del self.task_manager._tasks[tid]
                        success += 1
                        self.cleanup_item_result.emit(self.cleanup_task_id, tid, "SUCCESS", "")
                    else:
                        skipped += 1
                        self.cleanup_item_result.emit(self.cleanup_task_id, tid, "SKIPPED", "状态已改变")
                
                self.cleanup_progress.emit(self.cleanup_task_id, i + 1, total)
                time.sleep(0.01)
                
            self.task_manager._save_history()
            self.cleanup_finished.emit(self.cleanup_task_id, success, 0, skipped)
        except Exception as e:
            self.cleanup_failed.emit(self.cleanup_task_id, "Exception", str(e))


global_task_manager = TaskManager()
