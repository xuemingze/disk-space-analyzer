"""应用日志系统：控制台输出 + 独立文件持久化 + 全局异常拦截。

交付规约（AGENTS.md）要求：

1. **全局错误拦截**：未捕获异常（主线程 / 子线程 / Qt 事件循环 / 解释器退出）
   必须被拦截并记录，避免程序因未捕获异常而静默崩溃。
2. **独立文件持久化**：所有抛出的异常、报错信息及完整堆栈追踪，
   必须完整、静默地写入独立日志文件，保障问题排查的可追溯性。

日志目录解析优先级：

1. 环境变量 ``DISK_ANALYZER_LOG_DIR``
2. 打包运行（PyInstaller ``sys.frozen``）：可执行文件同级 ``logs`` 目录（便携）
3. 源码运行：项目根目录 ``logs``
4. 以上均不可写时回退 ``~/.disk_space_analyzer/logs``

产出文件：

* ``app.log``    —— INFO 及以上全量运行日志（2MB x 3 轮转）
* ``error.log``  —— ERROR 及以上错误日志（1MB x 5 轮转，含完整堆栈）
* ``crash-*.log``—— 未捕获异常的独立崩溃快照（完整 traceback）
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

_LOG_FORMAT = "[%(asctime)s] [%(levelname)-8s] [%(threadName)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_GLOBAL_LOGGER_NAME = "DiskAnalyzer"
_APP_LOG_NAME = "app.log"
_ERROR_LOG_NAME = "error.log"


# --------------------------------------------------------------------------- #
# 日志目录解析
# --------------------------------------------------------------------------- #
def _candidate_log_dirs() -> list[Path]:
    """按优先级返回候选日志目录列表。"""
    candidates: list[Path] = []

    env_dir = os.environ.get("DISK_ANALYZER_LOG_DIR", "").strip()
    if env_dir:
        candidates.append(Path(env_dir))

    if getattr(sys, "frozen", False):
        # 打包运行：与 exe 同级，保证便携版日志随手可取
        candidates.append(Path(sys.executable).resolve().parent / "logs")
    else:
        candidates.append(Path(__file__).resolve().parents[2] / "logs")

    # 兜底：用户目录，避免只读介质 / 无权限路径导致日志丢失
    candidates.append(Path.home() / ".disk_space_analyzer" / "logs")
    return candidates


def _resolve_log_dir() -> Path:
    """返回第一个可写的日志目录；全部失败时仍返回首选目录而不抛异常。"""
    candidates = _candidate_log_dirs()
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except Exception:  # noqa: BLE001 - 日志系统自身绝不允许抛出
            continue
    return candidates[0]


LOG_DIR: Path = _resolve_log_dir()
LOG_FILE: Path = LOG_DIR / _APP_LOG_NAME
ERROR_LOG_FILE: Path = LOG_DIR / _ERROR_LOG_NAME


# --------------------------------------------------------------------------- #
# Handler 构建
# --------------------------------------------------------------------------- #
class _LevelFilter(logging.Filter):
    """按最低级别过滤，用于把 ERROR 及以上单独落到 error.log。"""

    def __init__(self, min_level: int) -> None:
        super().__init__()
        self.min_level = min_level

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        return record.levelno >= self.min_level


def _build_console_handler() -> logging.Handler | None:
    """构造控制台 handler。

    打包为无控制台的窗口程序（``--noconsole``）时 ``sys.stdout`` /
    ``sys.stderr`` 均为 ``None``，此时必须跳过，否则每次写日志都会
    抛出 ``AttributeError`` 并被 logging 静默吞掉。
    """
    stream = getattr(sys, "stdout", None) or getattr(sys, "stderr", None)
    if stream is None:
        return None
    try:
        handler = logging.StreamHandler(stream)
    except Exception:  # noqa: BLE001
        return None
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
    return handler


def _build_rotating_handler(filename: Path, max_bytes: int, backups: int) -> logging.Handler | None:
    try:
        handler = logging.handlers.RotatingFileHandler(
            filename=str(filename),
            maxBytes=max_bytes,
            backupCount=backups,
            encoding="utf-8",
            delay=True,
        )
    except Exception:  # noqa: BLE001 - 磁盘满 / 权限不足时降级为仅控制台
        return None
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
    return handler


# --------------------------------------------------------------------------- #
# Logger 装配
# --------------------------------------------------------------------------- #
def setup_logger(name: str = _GLOBAL_LOGGER_NAME) -> logging.Logger:
    """装配并返回全局 logger（幂等：重复调用不会叠加 handler）。"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    console = _build_console_handler()
    if console is not None:
        logger.addHandler(console)

    app_file = _build_rotating_handler(LOG_FILE, 2 * 1024 * 1024, 3)
    if app_file is not None:
        logger.addHandler(app_file)

    error_file = _build_rotating_handler(ERROR_LOG_FILE, 1024 * 1024, 5)
    if error_file is not None:
        error_file.addFilter(_LevelFilter(logging.ERROR))
        logger.addHandler(error_file)

    # 把 warnings 模块的输出也纳入持久化，避免告警消失
    try:
        logging.captureWarnings(True)
        warnings_logger = logging.getLogger("py.warnings")
        if not warnings_logger.handlers:
            warnings_logger.setLevel(logging.WARNING)
            if app_file is not None:
                warnings_logger.addHandler(app_file)
    except Exception:  # noqa: BLE001
        pass

    return logger


app_logger = setup_logger()


# --------------------------------------------------------------------------- #
# 全局错误拦截
# --------------------------------------------------------------------------- #
def _write_crash_snapshot(exc_type, exc_value, exc_tb, source: str) -> None:
    """把未捕获异常完整写入独立崩溃快照与 error.log。"""
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    header = (
        f"{'=' * 78}\n"
        f"[CRASH] 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"[CRASH] 来源: {source}\n"
        f"[CRASH] 线程: {threading.current_thread().name}\n"
        f"[CRASH] 进程: pid={os.getpid()} frozen={getattr(sys, 'frozen', False)}\n"
        f"[CRASH] 工作目录: {os.getcwd()}\n"
        f"{'-' * 78}\n{text}{'=' * 78}\n"
    )

    try:
        snapshot = LOG_DIR / f"crash-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        snapshot.write_text(header, encoding="utf-8")
    except Exception:  # noqa: BLE001
        snapshot = None

    try:
        app_logger.critical("未捕获异常（%s）%s", source, header)
        if snapshot is not None:
            app_logger.critical("崩溃快照已保存: %s", snapshot)
    except Exception:  # noqa: BLE001
        pass


def install_exception_hooks(logger: logging.Logger | None = None) -> None:
    """安装主线程 / 子线程 / 解释器退出三处全局异常拦截。"""
    target = logger or app_logger

    previous_hook = sys.excepthook

    def _handle_uncaught(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            previous_hook(exc_type, exc_value, exc_tb)
            return
        _write_crash_snapshot(exc_type, exc_value, exc_tb, "sys.excepthook")

    sys.excepthook = _handle_uncaught

    def _handle_thread_uncaught(args: "threading.ExceptHookArgs") -> None:
        if issubclass(args.exc_type, SystemExit):
            return
        _write_crash_snapshot(
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
            f"threading.excepthook[{getattr(args.thread, 'name', 'unknown')}]",
        )

    if hasattr(threading, "excepthook"):
        threading.excepthook = _handle_thread_uncaught

    def _handle_unraisable(args) -> None:
        try:
            target.error(
                "未捕获的可忽略异常（unraisable）: %s",
                "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
            )
        except Exception:  # noqa: BLE001
            pass

    try:
        sys.unraisablehook = _handle_unraisable
    except Exception:  # noqa: BLE001
        pass


def install_qt_message_handler() -> None:
    """把 Qt 自身的警告/致命消息接入日志系统（Qt 默认会吞掉这些信息）。"""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
        from PySide6.QtCore import Qt as _Qt  # noqa: F401
    except Exception:  # noqa: BLE001 - 非 GUI 场景（如 pytest）直接跳过
        return

    level_map = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def _handler(mode, context, message: str) -> None:
        try:
            app_logger.log(level_map.get(mode, logging.INFO), "[Qt] %s", message)
        except Exception:  # noqa: BLE001
            pass

    try:
        qInstallMessageHandler(_handler)
    except Exception:  # noqa: BLE001
        pass


def log_runtime_environment(app_name: str, app_version: str) -> None:
    """记录一次运行环境快照，便于问题回溯。"""
    try:
        app_logger.info("-" * 70)
        app_logger.info("程序: %s v%s", app_name, app_version)
        app_logger.info("Python: %s", sys.version.replace("\n", " "))
        app_logger.info("日志目录: %s", LOG_DIR)
        app_logger.info("可执行文件: %s", sys.executable)
        app_logger.info("模糊打包(frozen): %s", getattr(sys, "frozen", False))
    except Exception:  # noqa: BLE001
        pass
