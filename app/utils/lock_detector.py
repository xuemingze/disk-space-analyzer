"""
文件锁定与占用探测器 (File Lock & In-Use Detector)
用于在自动化监控、定时归档、文件整理执行前提供保底防御：
1. 排他性独占探针 (Exclusive Lock Probe)：检测文件是否被其他进程打开占用 (如运行中程序、独占编辑等)；
2. 办公与编辑器伴生锁检测 (Office / WPS / Editor Lock Files)：检测 ~$ 锁文件、.~lock 等；
3. 闲置冷却窗口检查 (Cool-down Settling Window)：防止移动刚刚写入完毕、编辑器尚未完全刷盘的文件；
4. 防回环目标路径安全检查 (Anti-Cycle / Directory Containment Check)。
"""

import os
import time
from pathlib import Path
from typing import Tuple, Optional


def check_office_companion_lock(file_path: str) -> Tuple[bool, str]:
    """
    检查同目录下是否存在 Office 或 WPS 编辑时生成的隐藏伴生锁文件。
    例如:
    - 针对 '文档.docx'，Office 打开时会创建同级隐藏文件 '~$文档.docx'
    - 针对 '表格.xlsx'，WPS 打开时会创建同级 '.~lock.表格.xlsx#' 或 '~$表格.xlsx'
    
    返回: (is_locked, reason)
    """
    try:
        p = Path(file_path)
        parent = p.parent
        name = p.name

        # 检查是否本身就是伴生锁文件
        if name.startswith("~$") or name.startswith(".~lock."):
            return True, f"文件本身是伴生锁或临时标记: {name}"

        # 1. 检测 Office 伴生锁: ~$filename
        office_lock = parent / f"~${name}"
        if office_lock.exists():
            return True, f"检测到 Office 正在编辑伴生锁: {office_lock.name}"

        # 2. 检测 WPS 伴生锁: .~lock.filename#
        wps_lock = parent / f".~lock.{name}#"
        if wps_lock.exists():
            return True, f"检测到 WPS 正在编辑伴生锁: {wps_lock.name}"

    except Exception as e:
        return False, f"伴生锁检测异常: {e}"

    return False, ""


def check_file_exclusive_lock(file_path: str) -> Tuple[bool, str]:
    """
    通过非破坏性排他探针检测文件是否被其他进程占用或正在运行。
    在 Windows 下，若其他程序正在对文件进行独占写、或者 exe/dll 正在运行，
    尝试以读写追加模式获取文件句柄将立即抛出 PermissionError (WinError 32)。
    
    返回: (is_locked, reason)
    """
    if not os.path.isfile(file_path):
        return False, "文件不存在或为目录"

    # 若文件本身是只读属性，以只读探针打开
    try:
        # 首先尝试只读探测基础可访问性
        with open(file_path, "rb"):
            pass
    except PermissionError as e:
        return True, f"文件无法读取，被系统或其他进程排他独占 (WinError/PermissionDenied): {e}"
    except OSError as e:
        return True, f"文件访问异常 (可能被独占): {e}"

    # 尝试无损探针：如果文件可写，尝试追加打开排他探测
    # 注意：使用 a+b 打开但绝不写入任何字节，并在退出后立即释放
    try:
        # 如果是只读文件，跳过排他写探测
        if os.access(file_path, os.W_OK):
            with open(file_path, "r+b"):
                pass
    except PermissionError as e:
        return True, f"文件正被其他程序写入或独占编辑中 (WinError 32 独占锁): {e}"
    except OSError as e:
        # 在 Windows 上很多正被打开编辑的文件会报 OSError
        return True, f"文件句柄被占用，无法获取排他权限: {e}"

    return False, ""


def check_settling_cooldown(file_path: str, min_cooldown_seconds: float = 3.0) -> Tuple[bool, str]:
    """
    检查文件最后修改时间是否超过冷却静默期。
    若最近修改时间距今不足 min_cooldown_seconds，视为仍可能处于半写入状态。
    
    返回: (is_cooling, reason)
    """
    try:
        stat = os.stat(file_path)
        elapsed = time.time() - stat.st_mtime
        if elapsed < min_cooldown_seconds:
            return True, f"文件最近 {elapsed:.1f} 秒内刚被修改，未度过安全冷却期 ({min_cooldown_seconds}s)"
    except Exception as e:
        return True, f"获取文件状态失败: {e}"

    return False, ""


def is_file_locked_or_in_use(file_path: str, min_cooldown_seconds: float = 3.0) -> Tuple[bool, str]:
    """
    综合全景保底探针：
    1. 检查伴生锁 (Office / WPS)；
    2. 检查排他独占 (运行中 / 被其他软件打开)；
    3. 检查冷却静默期。
    
    返回: (is_busy, reason)
    只要任一项命中，即判定为忙碌/受保护，严禁移动。
    """
    # 1. 伴生锁
    locked, reason = check_office_companion_lock(file_path)
    if locked:
        return True, reason

    # 2. 独占句柄探针
    locked, reason = check_file_exclusive_lock(file_path)
    if locked:
        return True, reason

    # 3. 冷却静默期
    if min_cooldown_seconds > 0:
        cooling, reason = check_settling_cooldown(file_path, min_cooldown_seconds)
        if cooling:
            return True, reason

    return False, "就绪 (未被占用)"


def is_destination_valid(source_path: str, target_dir: str) -> Tuple[bool, str]:
    """
    验证归档目标目录与源监控目录的关系，杜绝回环与无限套娃：
    1. 目标目录不能为空；
    2. 目标目录与源目录不能相同；
    3. 目标目录不能是源目录的子目录 (否则移入目标目录会再次触发源目录的监控，导致死循环)；
    4. 源目录不能是目标目录的子目录。
    
    返回: (is_valid, error_message)
    """
    if not source_path or not source_path.strip():
        return False, "源监控目录不能为空"
    if not target_dir or not target_dir.strip():
        return False, "归档目标目录不能为空"

    norm_src = os.path.abspath(os.path.normpath(source_path)).lower()
    norm_dest = os.path.abspath(os.path.normpath(target_dir)).lower()

    if norm_src == norm_dest:
        return False, "归档目标目录不能与源监控目录完全相同，否则会导致重复归档死循环。"

    # 检查父子嵌套关系
    try:
        src_p = Path(norm_src)
        dest_p = Path(norm_dest)

        if dest_p in src_p.parents:
            return False, "源监控目录不能位于归档目标目录的子路径中。"

        if src_p in dest_p.parents:
            return False, "归档目标目录不能位于源监控目录内部，否则移动文件会触发重复监控死循环！"
    except Exception as e:
        # 兼容普通前缀判断
        sep = os.sep.lower()
        if norm_dest.startswith(norm_src + sep):
            return False, "归档目标目录不能位于源监控目录内部，否则移动文件会触发重复监控死循环！"
        if norm_src.startswith(norm_dest + sep):
            return False, "源监控目录不能位于归档目标目录的子路径中。"

    return True, ""
