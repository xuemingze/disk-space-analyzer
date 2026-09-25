from typing import Any, Callable, Dict, List
from PySide6.QtCore import QObject, Signal, QThread

class _EventBus(QObject):
    """全局领域事件总线 (线程安全)"""
    # 当文件状态被修改(如被归档、迁移、清理、回滚)时触发
    # args: (event_type: str, processed_paths: List[str], task_id: str, payload: dict)
    # event_type 可以是 "archived", "deleted", "migrated", "rollbacked"
    files_state_changed = Signal(str, list, str, dict)
    
    # 报告失效或重新生成时触发
    report_updated = Signal(str, str) # report_id, scan_task_id

    # 专门用于处理跨线程执行主线程函数的辅助信号
    _execute_in_main_thread = Signal(object, tuple, dict)

    def __init__(self):
        super().__init__()
        self._execute_in_main_thread.connect(self._do_execute)

    def publish_files_changed(self, event_type: str, paths: List[str], task_id: str = "", payload: dict = None):
        if not payload:
            payload = {}
        self.files_state_changed.emit(event_type, paths, task_id, payload)

    def publish_report_updated(self, report_id: str, scan_task_id: str):
        self.report_updated.emit(report_id, scan_task_id)
        
    def run_in_main(self, func: Callable, *args, **kwargs):
        """确保在 Qt 主线程执行函数，避免跨线程直接操作 UI 导致崩溃"""
        if QThread.currentThread() is self.thread():
            func(*args, **kwargs)
        else:
            self._execute_in_main_thread.emit(func, args, kwargs)
            
    def _do_execute(self, func, args, kwargs):
        func(*args, **kwargs)


# 全局单例
event_bus = _EventBus()
