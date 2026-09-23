import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional, Tuple

CACHE_DB_PATH = Path.home() / ".disk_space_analyzer" / "hash_cache.db"


class HashCache:
    """
    SQLite 持久化哈希缓存引擎
    缓存键: (path, size, mtime, algo)
    避免对未修改文件重复进行耗时磁盘 I/O 哈希计算
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path: Path = CACHE_DB_PATH):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(HashCache, cls).__new__(cls)
                cls._instance._init_db(db_path)
            return cls._instance

    def _init_db(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.local_thread = threading.local()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self.local_thread, "conn") or self.local_thread.conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_hashes (
                    file_path TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    algorithm TEXT NOT NULL,
                    sample_hash TEXT,
                    full_hash TEXT,
                    cached_at REAL NOT NULL,
                    PRIMARY KEY (file_path, algorithm)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_lookup ON file_hashes(file_path, file_size, mtime, algorithm);")
            conn.commit()
            self.local_thread.conn = conn
        return self.local_thread.conn

    def get_hashes(self, file_path: str, file_size: int, mtime: float, algorithm: str) -> Tuple[Optional[str], Optional[str]]:
        """
        获取缓存的 (sample_hash, full_hash)，若文件大小或 mtime 不一致则视为失效并返回 (None, None)
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT sample_hash, full_hash FROM file_hashes WHERE file_path = ? AND file_size = ? AND mtime = ? AND algorithm = ?",
                (os.path.normpath(file_path), file_size, mtime, algorithm.lower())
            )
            row = cursor.fetchone()
            if row:
                return row[0], row[1]
        except Exception:
            pass
        return None, None

    def put_hashes(self, file_path: str, file_size: int, mtime: float, algorithm: str, sample_hash: Optional[str], full_hash: Optional[str]):
        """写入或更新哈希缓存"""
        import time
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO file_hashes (file_path, file_size, mtime, algorithm, sample_hash, full_hash, cached_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path, algorithm) DO UPDATE SET
                    file_size = excluded.file_size,
                    mtime = excluded.mtime,
                    sample_hash = coalesce(excluded.sample_hash, file_hashes.sample_hash),
                    full_hash = coalesce(excluded.full_hash, file_hashes.full_hash),
                    cached_at = excluded.cached_at;
                """,
                (os.path.normpath(file_path), file_size, mtime, algorithm.lower(), sample_hash, full_hash, time.time())
            )
            conn.commit()
        except Exception:
            pass

    def clear_cache(self):
        """清空哈希缓存"""
        try:
            conn = self._get_connection()
            conn.execute("DELETE FROM file_hashes;")
            conn.commit()
        except Exception:
            pass


hash_cache = HashCache()
