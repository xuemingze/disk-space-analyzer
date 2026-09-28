"""「空间全景深度分析与冗余文件扫描」桌面客户端入口。

启动流程遵循交付规约：先装配全局异常拦截与文件日志，再创建 GUI，
确保任何阶段的崩溃都能留下完整堆栈（error.log / crash-*.log）。
"""

import os
import sys
import traceback

# 将项目根目录添加至 sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

APP_NAME = "空间全景深度分析与冗余文件扫描"
APP_VERSION = "1.2.0"

from app.utils.logger import (  # noqa: E402
    LOG_DIR,
    app_logger,
    install_exception_hooks,
    install_qt_message_handler,
    log_runtime_environment,
)


def _report_fatal_startup_error(exc: BaseException) -> None:
    """启动阶段致命错误：落盘 + 尽力弹窗告知用户日志位置。"""
    app_logger.critical(
        "应用程序启动失败: %s\n%s",
        exc,
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    )
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is None:
            QApplication(sys.argv)
        QMessageBox.critical(
            None,
            "启动失败",
            f"程序启动时发生未处理的错误：\n\n{exc}\n\n"
            f"完整错误堆栈已写入日志文件：\n{LOG_DIR}",
        )
    except Exception:  # noqa: BLE001 - 弹窗失败绝不能掩盖原始异常
        app_logger.error("错误提示弹窗展示失败（不影响日志落盘）")


def main() -> int:
    install_exception_hooks()
    log_runtime_environment(APP_NAME, APP_VERSION)

    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    from app.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    install_qt_message_handler()

    app_logger.info("启动「%s」客户端 (v%s)...", APP_NAME, APP_VERSION)

    window = MainWindow()
    window.show()

    exit_code = app.exec()
    app_logger.info("客户端正常退出，退出码: %s", exit_code)
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as fatal:  # noqa: BLE001 - 最后一道兜底，必须落盘
        _report_fatal_startup_error(fatal)
        sys.exit(1)
