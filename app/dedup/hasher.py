"""
app/dedup/hasher.py
三阶递进式无损哈希计算引擎
对接 SQLite 哈希缓存，流式分块读取，防止大文件爆内存
"""
import os
import hashlib
from typing import Optional, Callable, Tuple
from app.core.hash_cache import hash_cache
from app.utils.logger import app_logger

SAMPLE_THRESHOLD = 64 * 1024  # 64 KB
SAMPLE_CHUNK_SIZE = 8 * 1024  # 8 KB
STREAM_CHUNK_SIZE = 1024 * 1024  # 1 MB


class DedupHasher:
    """递进式哈希计算器"""

    @classmethod
    def get_hash_func(cls, algorithm: str = "sha256"):
        algo = (algorithm or "sha256").lower()
        if algo == "md5":
            return hashlib.md5
        elif algo == "sha1":
            return hashlib.sha1
        return hashlib.sha256

    @classmethod
    def compute_sample_hash(
        cls,
        file_path: str,
        file_size: int,
        mtime: float,
        algorithm: str = "sha256",
        use_cache: bool = True
    ) -> Optional[str]:
        """
        计算文件的稀疏采样哈希 (二阶漏斗)
        < 64KB: 全量内容哈希
        >= 64KB: 头部 8KB + 中部 8KB + 尾部 8KB 混合摘要
        """
        algo_name = (algorithm or "sha256").lower()
        if use_cache:
            s_cached, _ = hash_cache.get_hashes(file_path, file_size, mtime, algo_name)
            if s_cached:
                return s_cached

        h = cls.get_hash_func(algo_name)()
        try:
            with open(file_path, "rb") as f:
                if file_size < SAMPLE_THRESHOLD:
                    content = f.read()
                    h.update(content)
                else:
                    # 头部 8KB
                    h.update(f.read(SAMPLE_CHUNK_SIZE))
                    # 中部 8KB
                    mid_offset = (file_size - SAMPLE_CHUNK_SIZE) // 2
                    f.seek(mid_offset)
                    h.update(f.read(SAMPLE_CHUNK_SIZE))
                    # 尾部 8KB
                    f.seek(file_size - SAMPLE_CHUNK_SIZE)
                    h.update(f.read(SAMPLE_CHUNK_SIZE))

            sample_digest = h.hexdigest()
            if use_cache:
                hash_cache.put_hashes(file_path, file_size, mtime, algo_name, sample_digest, None)
            return sample_digest
        except (OSError, PermissionError) as e:
            app_logger.debug("读取文件采样哈希失败 %s: %s", file_path, e)
            return None

    @classmethod
    def compute_full_hash(
        cls,
        file_path: str,
        file_size: int,
        mtime: float,
        algorithm: str = "sha256",
        use_cache: bool = True,
        cancel_check: Optional[Callable[[], bool]] = None,
        bytes_progress_cb: Optional[Callable[[int], None]] = None
    ) -> Optional[str]:
        """
        流式计算文件的完整哈希校验码 (三阶校验)
        采用 1MB Chunk 流式读取，支持取消中断与字节级进度通知
        """
        algo_name = (algorithm or "sha256").lower()
        if use_cache:
            _, f_cached = hash_cache.get_hashes(file_path, file_size, mtime, algo_name)
            if f_cached:
                if bytes_progress_cb:
                    bytes_progress_cb(file_size)
                return f_cached

        h = cls.get_hash_func(algo_name)()
        try:
            with open(file_path, "rb") as f:
                while True:
                    if cancel_check and not cancel_check():
                        return None
                    chunk = f.read(STREAM_CHUNK_SIZE)
                    if not chunk:
                        break
                    h.update(chunk)
                    if bytes_progress_cb:
                        bytes_progress_cb(len(chunk))

            full_digest = h.hexdigest()
            if use_cache:
                # 保留原有 sample_hash，更新 full_hash
                s_cached, _ = hash_cache.get_hashes(file_path, file_size, mtime, algo_name)
                hash_cache.put_hashes(file_path, file_size, mtime, algo_name, s_cached, full_digest)
            return full_digest
        except (OSError, PermissionError) as e:
            app_logger.debug("计算文件完整哈希失败 %s: %s", file_path, e)
            return None
