import os
import hashlib
from pathlib import Path
from typing import Optional, Tuple

# 文件类型分类映射表
EXTENSION_CATEGORIES = {
    "视频与音频": {
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".rmvb", ".m4v",
        ".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"
    },
    "压缩包与镜像": {
        ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso", ".img", ".vmdk", ".vhdx", ".qcow2", ".wim"
    },
    "安装包与程序": {
        ".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".apk", ".ipa"
    },
    "开发依赖与包缓存": {
        ".whl", ".egg", ".jar", ".war", ".nuget", ".gem"
    },
    "文档与办公": {
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".txt", ".md", ".epub"
    },
    "图像与设计": {
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".psd", ".ai", ".raw", ".tiff", ".ico"
    },
    "代码与工程": {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".php",
        ".html", ".css", ".json", ".xml", ".yaml", ".yml", ".sql", ".sh", ".bat", ".ps1"
    },
    "临时与日志": {
        ".tmp", ".temp", ".log", ".dmp", ".bak", ".old", ".cache", ".chk", ".swp", ".swo", ".part", ".crdownload"
    },
    "系统与核心数据": {
        ".sys", ".dll", ".so", ".dylib", ".cab", ".dat"
    }
}

# 严格保护的系统关键路径白名单（绝对不可由 AI 或用户一键推荐误删）
PROTECTED_SYSTEM_PATHS = [
    r"c:\windows\system32",
    r"c:\windows\syswow64",
    r"c:\windows\winsxs",
    r"c:\windows\boot",
    r"c:\windows\system",
    r"c:\recovery",
    r"c:\system volume information",
    r"c:\boot",
    r"c:\bootmgr"
]

# 常见可以直接清理或推荐归档的高价值模式
KNOWN_REDUNDANT_PATTERNS = [
    (r"\appdata\local\temp", "系统应用临时文件"),
    (r"\windows\temp", "Windows 系统临时文件"),
    (r"\repair-backups", "应用历史自动修复备份"),
    (r"-updater", "软件升级下载残留包"),
    (r"\pip\cache", "Python pip 包缓存"),
    (r"\npm-cache", "Node npm 下载缓存"),
    (r"\appdata\local\pnpm", "pnpm 全局缓存"),
    (r"\.cache\codex-runtimes", "开发运行时缓存"),
    (r"\$recycle.bin", "回收站已废弃文件"),
    (r"\.tmp-", "临时过程文件"),
    (r"\downloads", "下载目录文件")
]


def format_size(size_bytes: int) -> str:
    """格式化字节大小为可读字符串 (B, KB, MB, GB, TB)"""
    if size_bytes < 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(size_bytes)
    unit_index = 0
    while size >= 1024.0 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1
    return f"{size:.2f} {units[unit_index]}"


def categorize_file_by_ext(file_path: Path) -> str:
    """根据文件扩展名归类文件类别"""
    ext = file_path.suffix.lower()
    for category, ext_set in EXTENSION_CATEGORIES.items():
        if ext in ext_set:
            return category
    return "其他文件"


def is_system_critical_path(file_path: str) -> bool:
    """判断路径是否属于 Windows 关键受保护系统目录"""
    normalized = os.path.abspath(file_path).lower()
    for protected in PROTECTED_SYSTEM_PATHS:
        if normalized.startswith(protected.lower()):
            return True
    return False


def get_heuristic_redundant_tag(file_path: str) -> Optional[Tuple[str, str]]:
    """启发式分析文件是否属于高冗余/可清理推荐文件，返回 (标签, 理由)"""
    if is_system_critical_path(file_path):
        return None
    
    path_lower = file_path.lower()
    
    # 特殊大 zip 归档包
    if path_lower.endswith(".zip") or path_lower.endswith(".tar.gz"):
        if "appdata" in path_lower or "users" in path_lower:
            return ("冗余归档包", "位于用户或应用数据目录下的独立大型压缩包，建议确认后清理或移入归档")

    # 路径匹配
    for pattern, desc in KNOWN_REDUNDANT_PATTERNS:
        if pattern.lower() in path_lower:
            return ("安全可清理", desc)
            
    # 后缀匹配
    ext = Path(file_path).suffix.lower()
    if ext in {".tmp", ".temp", ".log", ".dmp", ".bak", ".old", ".part", ".crdownload"}:
        return ("临时与日志", f"属于 {ext} 临时或诊断日志文件，通常可直接释放")
        
    return None


def calculate_file_hash(file_path: str, algorithm: str = "md5", chunk_size: int = 1024 * 1024) -> Optional[str]:
    """
    分块读取文件并计算完整哈希值，防止大文件溢出内存 (严格控制在 chunk_size 内存)
    """
    hasher = hashlib.md5() if algorithm.lower() == "md5" else hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()
    except (PermissionError, FileNotFoundError, OSError):
        return None


def calculate_partial_hash(file_path: str, sample_size: int = 8192) -> Optional[str]:
    """
    快速读取文件头部 8KB 样本哈希，用于初步过滤相同大小的文件
    """
    hasher = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(sample_size)
            if not chunk:
                return "empty"
            hasher.update(chunk)
        return hasher.hexdigest()
    except (PermissionError, FileNotFoundError, OSError):
        return None
