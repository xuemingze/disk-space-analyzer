import time
import threading
from enum import Enum
from typing import Dict, List, Optional, Any
from PySide6.QtCore import QObject, Signal


class TaskType(str, Enum):
    SCAN = "磁盘空间扫描"
    HASH_CHECK = "深度哈希查重"
    MIGRATION = "文件智能迁移"
    CLEANUP = "冗余文件清理"
    AI_ANALYSIS = "AI 智能分析"


class TaskStatus(str, Enum):
    PENDING = "排队中"
    RUNNING = "运行中"
    PAUSED = "已暂停"
    CANCELED = "已取消"
    COMPLETED = "已完成"
    FAILED = "失败"


class TaskItem:
    """单个后台任务数据实体"""
    def __init__(self, task_id: str, name: str, task_type: TaskType, worker: Any = None):
        self.task_id = task_id
        self.name = name
        self.task_type = task_type
        self.status = TaskStatus.PENDING
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


class TaskManager(QObject):
    """
    统一后台任务协调与生命周期管理中心
    """
    task_added = Signal(TaskItem)
    task_updated = Signal(TaskItem)
    task_finished = Signal(TaskItem)
    task_log_appended = Signal(str, str, str)  # (task_id, message, level)

    _instance = None
    _lock = threading.Lock()

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

    def create_task(self, name: str, task_type: TaskType, worker: Any = None) -> TaskItem:
        task_id = f"TASK_{int(time.time()*1000)}"
        item = TaskItem(task_id, name, task_type, worker)
        with self._task_lock:
            self._tasks[task_id] = item
        self.task_added.emit(item)
        return item

    def get_task(self, task_id: str) -> Optional[TaskItem]:
        with self._task_lock:
            return self._tasks.get(task_id)

    def list_tasks(self) -> List[TaskItem]:
        with self._task_lock:
            return list(self._tasks.values())

    def update_task_progress(
        self,
        task_id: str,
        phase: str = None,
        progress_pct: float = None,
        processed_count: int = None,
        total_count: int = None,
        processed_bytes: int = None,
        total_bytes: int = None,
        speed: str = None,
        eta: int = None
    ):
        with self._task_lock:
            item = self._tasks.get(task_id)
            if not item:
                return
            if phase is not None:
                item.current_phase = phase
            if progress_pct is not None:
                item.progress_percent = max(0.0, min(100.0, progress_pct))
            if processed_count is not None:
                item.processed_count = processed_count
            if total_count is not None:
                item.total_count = total_count
            if processed_bytes is not None:
                item.processed_bytes = processed_bytes
            if total_bytes is not None:
                item.total_bytes = total_bytes
            if speed is not None:
                item.current_speed = speed
            if eta is not None:
                item.eta_seconds = eta
            if item.status == TaskStatus.PENDING:
                item.status = TaskStatus.RUNNING

        self.task_updated.emit(item)

    def append_log(self, task_id: str, message: str, level: str = "info"):
        with self._task_lock:
            item = self._tasks.get(task_id)
            if item:
                item.add_log(message, level)
        self.task_log_appended.emit(task_id, message, level)

    def set_task_status(self, task_id: str, status: TaskStatus, error_msg: str = None):
        with self._task_lock:
            item = self._tasks.get(task_id)
            if not item:
                return
            item.status = status
            if error_msg:
                item.error_message = error_msg
            if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED):
                item.end_time = time.time()

        self.task_updated.emit(item)
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED):
            self.task_finished.emit(item)

    def pause_task(self, task_id: str):
        with self._task_lock:
            item = self._tasks.get(task_id)
            if item and item.worker and hasattr(item.worker, "pause"):
                item.worker.pause()
                item.status = TaskStatus.PAUSED
                self.task_updated.emit(item)

    def resume_task(self, task_id: str):
        with self._task_lock:
            item = self._tasks.get(task_id)
            if item and item.worker and hasattr(item.worker, "resume"):
                item.worker.resume()
                item.status = TaskStatus.RUNNING
                self.task_updated.emit(item)

    def cancel_task(self, task_id: str):
        with self._task_lock:
            item = self._tasks.get(task_id)
            if item and item.worker and hasattr(item.worker, "cancel"):
                item.worker.cancel()
                item.status = TaskStatus.CANCELED
                item.end_time = time.time()
                self.task_updated.emit(item)
                self.task_finished.emit(item)

    def clear_history(self):
        with self._task_lock:
            active_tasks = {
                k: v for k, v in self._tasks.items()
                if v.status in (TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.PENDING)
            }
            self._tasks = active_tasks

    def has_active_tasks(self) -> bool:
        with self._task_lock:
            for t in self._tasks.values():
                if t.status in (TaskStatus.RUNNING, TaskStatus.PAUSED):
                    return True
        return False


global_task_manager = TaskManager()
