"""
目录指纹探针与变化探测引擎 (Directory Fingerprint Probe)

职责：
1. 建立轻量级目录特征指纹 (DirectoryFingerprint)，采用极速非递归 top-level scandir；
2. 捕获目录自身的 mtime、直属子项条目数 (entry_count)、直属子项的最大 mtime 与直属总字节；
3. 在调度重量级 UnifiedScanner 之前以微秒级探针进行变化比对，杜绝空转 I/O 与日志风暴；
4. 线程安全，支持增量基线更新与重置。
"""

import os
import threading
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from app.utils.logger import app_logger


@dataclass(frozen=True)
class DirectoryFingerprint:
    """轻量级目录指纹快照 (Value Object)"""
    dir_path: str
    dir_mtime: float
    entry_count: int
    max_child_mtime: float
    total_immediate_size: int

    def matches(self, other: "DirectoryFingerprint") -> bool:
        """比较两份指纹是否完全一致 (无物理文件新增、删除或直属修改)"""
        if other is None:
            return False
        return (
            self.entry_count == other.entry_count
            and abs(self.dir_mtime - other.dir_mtime) < 1e-4
            and abs(self.max_child_mtime - other.max_child_mtime) < 1e-4
            and self.total_immediate_size == other.total_immediate_size
        )


class DirectoryFingerprintProbe:
    """
    轻量级目录变化探针 (Directory Fingerprint Probe)
    """

    def __init__(self):
        self._baselines: Dict[str, DirectoryFingerprint] = {}
        self._lock = threading.Lock()

    def capture_fingerprint(self, dir_path: str) -> Optional[DirectoryFingerprint]:
        """
        极速非递归提取目录顶层指纹 (微秒级完成)
        """
        norm_dir = os.path.normpath(dir_path)
        if not os.path.isdir(norm_dir):
            return None

        try:
            st = os.stat(norm_dir)
            dir_mtime = st.st_mtime
            entry_count = 0
            max_child_mtime = dir_mtime
            total_size = 0

            with os.scandir(norm_dir) as it:
                for entry in it:
                    entry_count += 1
                    try:
                        c_stat = entry.stat(follow_symlinks=False)
                        if c_stat.st_mtime > max_child_mtime:
                            max_child_mtime = c_stat.st_mtime
                        if entry.is_file(follow_symlinks=False):
                            total_size += c_stat.st_size
                    except (OSError, PermissionError):
                        continue

            return DirectoryFingerprint(
                dir_path=norm_dir,
                dir_mtime=dir_mtime,
                entry_count=entry_count,
                max_child_mtime=max_child_mtime,
                total_immediate_size=total_size
            )
        except (OSError, PermissionError) as e:
            app_logger.debug("指纹探针读取失败 [%s]: %s", norm_dir, e)
            return None

    def has_changed(self, dir_path: str) -> bool:
        """
        探测目录自上次基线以来是否发生物理变更。
        首次调用时自动登记基线并返回 True，便于触发首次扫描构建初始快照；
        后续调用若指纹一致返回 False；若变更则更新基线并返回 True。
        """
        curr = self.capture_fingerprint(dir_path)
        if curr is None:
            return False

        norm_dir = curr.dir_path
        with self._lock:
            prev = self._baselines.get(norm_dir)
            if prev is None:
                self._baselines[norm_dir] = curr
                return True

            if curr.matches(prev):
                return False

            # 指纹发生物理变化，更新基线
            self._baselines[norm_dir] = curr
            return True

    def reset_baseline(self, dir_path: Optional[str] = None):
        """重置指定目录或全量探针基线"""
        with self._lock:
            if dir_path:
                self._baselines.pop(os.path.normpath(dir_path), None)
            else:
                self._baselines.clear()
