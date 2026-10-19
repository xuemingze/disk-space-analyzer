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
    r"c:\windows",
    r"c:\programdata\microsoft\windows",
    r"c:\program files\common files",
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


def normalize_unified_category(cat: str) -> str:
    """将底层扩展名分类与业务高阶分类归一化收敛为统一高阶全景资产分类"""
    c = (cat or "").strip()
    if not c:
        return "其他与通用文件 (Misc & General)"
    if any(k in c for k in ["代码", "工程", "依赖", "Dev", "Code"]):
        return "代码项目与依赖 (Dev & Code)"
    if any(k in c for k in ["软件", "安装", "程序", "Apps", "Installers"]):
        return "软件安装与程序 (Apps & Installers)"
    if any(k in c for k in ["设计", "图像", "图片", "素材", "Design", "Assets", "Live2D", "模型"]):
        return "图像设计与模型 (Design & Models)"
    if any(k in c for k in ["文档", "办公", "财务", "发票", "经控", "商务", "电子书", "Books", "Documents", "Finance"]):
        return "文档报表与账套 (Docs & Business)"
    if any(k in c for k in ["视频", "音频", "影音", "媒体", "Media", "Videos"]):
        return "音视频与多媒体 (Media & Videos)"
    if any(k in c for k in ["压缩", "镜像", "归档", "Archives", "OS_Images"]):
        return "归档包与系统镜像 (Archives & Images)"
    if any(k in c for k in ["游戏", "Games"]):
        return "游戏娱乐与资产 (Games & Entertainment)"
    if any(k in c for k in ["临时", "日志", "缓存", "Temp", "Logs", "Caches"]):
        return "系统运行与临时缓存 (System & Temp)"
    if any(k in c for k in ["系统", "核心", "System"]):
        return "系统核心运行数据 (System Core)"
    return "其他与通用文件 (Misc & General)"


def is_system_critical_path(file_path: str) -> bool:
    """判断路径是否属于 Windows 关键受保护系统目录"""
    if not file_path:
        return False
    normalized = os.path.normpath(file_path).lower()
    # 临时目录除外
    if r"\windows\temp" in normalized or r"\appdata\local\temp" in normalized:
        return False
    for protected in PROTECTED_SYSTEM_PATHS:
        if normalized.startswith(protected.lower()) or protected.lower() in normalized:
            return True
    return False


import re

INSTALLER_PATTERN = re.compile(r'(setup|installer|install|安装包|_setup|-setup|\.msi$)', re.IGNORECASE)
CONFLICT_PATTERN = re.compile(r'(\.sync-conflict-|\s*-\s*副本|_\s*副本|\(\d+\)|_copy)', re.IGNORECASE)


def get_heuristic_redundant_tag(file_path: str, file_name: Optional[str] = None, file_size: int = 0) -> Optional[Tuple[str, str, bool]]:
    """启发式分析文件是否属于高冗余/可清理推荐文件，返回 (标签, 理由, 是否推荐治理)"""
    if is_system_critical_path(file_path):
        return None
    
    path_lower = file_path.lower()
    name = file_name or Path(file_path).name
    ext = Path(name).suffix.lower()

    # 1. 同步冲突与带编号的冗余副本 (如 .sync-conflict-xxx, 集团、循环电脑(1).xls)
    if CONFLICT_PATTERN.search(name):
        return ("同步与历史副本", "检测为云同步冲突或多次保存的带编号冗余副本，建议比对确认后处理", True)

    # 2. 软件独立安装包与安装程序残留 (如 SteamSetup.exe, windowscleaner...setup.exe, Everything-Setup.exe)
    if ext in {".exe", ".msi", ".pkg", ".dmg", ".deb", ".rpm"}:
        if INSTALLER_PATTERN.search(name) or ext == ".msi":
            return ("软件安装程序", "检测为独立软件离线安装程序或安装引导包，软件安装后该安装包可归档或清理", True)

    # 3. 冗余归档包与已解压镜像
    if ext in {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"}:
        parent_p = Path(file_path).parent
        parent_low = parent_p.name.lower()
        # 原则三：同源同宿与归档资产保全。若已处于正规的备份/归档大抽屉目录下，属于用户主动存放的核心备份资产，严禁标记为“冗余”！
        if any(b in parent_low for b in ["backup", "backups", "归档", "备份", "archive", "archives", "snapshot", "snapshots"]):
            return None

        stem = Path(name).stem.lower()
        # 检查同目录下是否存在同名解压目录
        try:
            for sibling in parent_p.iterdir():
                if sibling.is_dir():
                    sib_name = sibling.name.lower()
                    if sib_name == stem or stem.startswith(sib_name) or sib_name.startswith(stem):
                        return ("已解压冗余归档包", f"同目录下已存在解压后的对应实体目录 [{sibling.name}]，压缩包为冗余副本", True)
        except Exception:
            pass
        if "appdata" in path_lower or "users" in path_lower or file_size > 50 * 1024 * 1024:
            return ("冗余归档包", "大型历史压缩归档包，建议确认后移入长期冷备份", False)

    # 4. 路径特征匹配 (系统临时目录、开发包缓存等)
    for pattern, desc in KNOWN_REDUNDANT_PATTERNS:
        if pattern.lower() in path_lower:
            return ("安全可清理", desc, True)
            
    # 5. 后缀特征匹配 (临时文件、日志等)
    if ext in {".tmp", ".temp", ".log", ".dmp", ".bak", ".old", ".part", ".crdownload"}:
        return ("临时与日志", f"属于 {ext} 临时或诊断日志文件，通常可直接释放", True)
        
    return None


def calculate_file_hash(file_path: str, algorithm: str = "md5", chunk_size: int = 1024 * 1024) -> Optional[str]:
    """
    分块读取文件并计算完整哈希值 (若为目录集体，计算所有内部相对路径、大小与首部采样的深度指纹)，防止大文件溢出内存
    """
    if os.path.isdir(file_path):
        hasher = hashlib.md5() if algorithm.lower() == "md5" else hashlib.sha256()
        try:
            for root, dirs, files in os.walk(file_path):
                dirs.sort()
                for f in sorted(files):
                    fp = os.path.join(root, f)
                    rel = os.path.relpath(fp, file_path)
                    try:
                        st = os.stat(fp)
                        sz = st.st_size
                    except OSError:
                        sz = 0
                    hasher.update(f"{rel}:{sz}".encode("utf-8", errors="ignore"))
                    try:
                        with open(fp, "rb") as sub_f:
                            hasher.update(sub_f.read(4096))
                    except Exception:
                        pass
            return hasher.hexdigest()
        except Exception:
            return None

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
    快速读取文件头部 8KB 样本哈希 (若为目录集体，采样前 20 个子文件的相对路径与大小)，用于初步过滤相同大小的文件
    """
    if os.path.isdir(file_path):
        hasher = hashlib.md5()
        try:
            entries = []
            for root, dirs, files in os.walk(file_path):
                dirs.sort()
                for f in sorted(files):
                    fp = os.path.join(root, f)
                    rel = os.path.relpath(fp, file_path)
                    try:
                        sz = os.path.getsize(fp)
                    except OSError:
                        sz = 0
                    entries.append(f"{rel}:{sz}")
                    if len(entries) >= 20:
                        break
                if len(entries) >= 20:
                    break
            hasher.update("|".join(entries).encode("utf-8", errors="ignore"))
            return hasher.hexdigest()
        except Exception:
            return None

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
