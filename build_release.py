"""一键构建 Windows 发布制品（PyInstaller）。

用法::

    python build_release.py                 # 目录版 + 便携 zip（默认）
    python build_release.py --onefile       # 追加单文件 exe
    python build_release.py --version 1.2.0 # 覆盖版本号

产出（release/ 目录）::

    DiskSpaceAnalyzer-<version>-win64-portable.zip   目录版便携包（推荐）
    DiskSpaceAnalyzer-<version>-win64.exe            单文件版（--onefile）

构建全过程同时写入 ``logs/build_release.log``；任何异常连同完整堆栈
写入 ``logs/build_release_error.log``，符合「异常必须落盘可追溯」的交付规约。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
RELEASE_DIR = ROOT / "release"
LOG_DIR = ROOT / "logs"
ICON_PATH = ROOT / "assets" / "app.ico"

APP_EXE_NAME = "DiskSpaceAnalyzer"
MAIN_SCRIPT = ROOT / "main.py"

# app 包的完整顶层导入集合（静态盘点 + 运行时实测）为：
#   stdlib + PySide6 / matplotlib / numpy / requests / send2trash / winreg
# 以下模块在 PyInstaller 的 hook 依赖推导中会被过度收集（实测会拖入
# torch / onnxruntime / pandas / scipy 等 GB 级无关依赖），必须显式剔除。
# 剔除后由 exe 冒烟测试 + 日志核对来验证运行期无 ImportError。
EXCLUDED_MODULES = (
    # 其它 GUI 绑定
    "tkinter",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.Qt3DCore",
    # 深度学习 / 推理 / 视觉（本项目完全未使用）
    "torch",
    "torchvision",
    "torchaudio",
    "tensorflow",
    "keras",
    "sklearn",
    "skimage",
    "onnxruntime",
    "onnx",
    "cv2",
    "paddle",
    "paddleocr",
    "paddlex",
    "modelscope",
    "easyocr",
    "rapidocr_onnxruntime",
    "imgaug",
    "pyclipper",
    "shapely",
    # 数据分析 / 办公文档（matplotlib 不依赖它们，仅 pandas 生态需要）
    "pandas",
    "scipy",
    "pyarrow",
    "sqlalchemy",
    "lxml",
    "openpyxl",
    "xlrd",
    "xlwt",
    "xlsxwriter",
    # 符号计算 / 科学计算附加件（torch 的传递依赖）
    "sympy",
    "mpmath",
    "networkx",
    # 测试与终端美化
    "pytest",
    "_pytest",
    "pluggy",
    "iniconfig",
    "py",
    "rich",
    "pygments",
    # Web / 交互式分析栈
    "streamlit",
    "altair",
    "pydeck",
    "IPython",
    "jupyter",
    "notebook",
    "nbformat",
    "tornado",
)

BUILD_LOG = LOG_DIR / "build_release.log"
BUILD_ERROR_LOG = LOG_DIR / "build_release_error.log"


class _Tee:
    """把 stdout 同时写入控制台与构建日志文件。"""

    def __init__(self, stream, file_obj) -> None:
        self._stream = stream
        self._file = file_obj

    def write(self, data: str) -> int:
        try:
            self._file.write(data)
            self._file.flush()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._stream is not None:
                self._stream.write(data)
        except Exception:  # noqa: BLE001
            pass
        return len(data)

    def flush(self) -> None:
        for target in (self._file, self._stream):
            try:
                if target is not None:
                    target.flush()
            except Exception:  # noqa: BLE001
                pass


def read_version() -> str:
    """从 main.py 读取 APP_VERSION，保证制品版本与代码一致。"""
    match = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', MAIN_SCRIPT.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError("main.py 中未找到 APP_VERSION 定义")
    return match.group(1)


def ensure_icon() -> Path | None:
    if ICON_PATH.exists():
        return ICON_PATH
    try:
        sys.path.insert(0, str(ROOT / "assets"))
        import make_icon  # type: ignore

        make_icon.build_icon(ICON_PATH)
    except Exception:  # noqa: BLE001
        print("[build] 图标生成失败，改用默认图标\n" + traceback.format_exc())
    return ICON_PATH if ICON_PATH.exists() else None


def clean_previous() -> None:
    for path in (DIST_DIR, BUILD_DIR):
        if path.exists():
            print(f"[build] 清理 {path}")
            shutil.rmtree(path, ignore_errors=True)


def _pyinstaller_args(onefile: bool, icon: Path | None) -> list[str]:
    args = [
        str(MAIN_SCRIPT),
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        APP_EXE_NAME,
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--specpath",
        str(BUILD_DIR),
    ]
    for module in EXCLUDED_MODULES:
        args += ["--exclude-module", module]
    args.append("--onefile" if onefile else "--onedir")
    if icon is not None:
        args += ["--icon", str(icon)]
    return args


def run_pyinstaller(onefile: bool, icon: Path | None) -> None:
    import PyInstaller.__main__ as pyi_main

    mode = "单文件" if onefile else "目录版"
    print(f"[build] PyInstaller 开始构建（{mode}模式）...")
    try:
        pyi_main.run(_pyinstaller_args(onefile, icon))
    except SystemExit as exc:  # PyInstaller 内部以 SystemExit 传递退出码
        if exc.code not in (0, None):
            raise RuntimeError(f"PyInstaller 构建失败，退出码 {exc.code}") from exc


def make_portable_zip(version: str) -> Path | None:
    """把目录版打包为便携 zip。"""
    source = DIST_DIR / APP_EXE_NAME
    if not source.is_dir():
        print("[build] 未找到目录版产物，跳过打包")
        return None

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    archive_base = RELEASE_DIR / f"{APP_EXE_NAME}-{version}-win64-portable"
    if archive_base.with_suffix(".zip").exists():
        archive_base.with_suffix(".zip").unlink()

    print("[build] 打包便携 zip ...")
    produced = shutil.make_archive(
        str(archive_base), "zip", root_dir=str(DIST_DIR), base_dir=APP_EXE_NAME
    )
    return Path(produced)


def collect_single_file(version: str) -> Path | None:
    """把单文件 exe 复制为带版本号的发布名。"""
    source = DIST_DIR / f"{APP_EXE_NAME}.exe"
    if not source.is_file():
        print("[build] 未找到单文件产物，跳过")
        return None
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    target = RELEASE_DIR / f"{APP_EXE_NAME}-{version}-win64.exe"
    shutil.copy2(source, target)
    return target


def _human(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} GB"


def _dir_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 Windows 发布制品")
    parser.add_argument("--onefile", action="store_true", help="同时构建单文件 exe")
    parser.add_argument("--version", default=None, help="覆盖版本号")
    parser.add_argument("--skip-zip", action="store_true", help="跳过便携 zip 打包")
    options = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = BUILD_LOG.open("a", encoding="utf-8")
    original_stdout = sys.stdout
    sys.stdout = _Tee(original_stdout, log_file)  # type: ignore[assignment]
    try:
        version = options.version or read_version()
        print("=" * 70)
        print(f"[build] 构建开始 {datetime.now():%Y-%m-%d %H:%M:%S} | 版本 {version}")

        icon = ensure_icon()
        clean_previous()

        run_pyinstaller(onefile=False, icon=icon)
        artifacts: list[Path] = []

        if not options.skip_zip:
            zipped = make_portable_zip(version)
            if zipped:
                artifacts.append(zipped)

        if options.onefile:
            run_pyinstaller(onefile=True, icon=icon)
            single = collect_single_file(version)
            if single:
                artifacts.append(single)

        print("-" * 70)
        if not artifacts:
            print("[build] 未产生任何制品，请检查上方 PyInstaller 输出")
            return 1
        print("[build] 制品清单:")
        for item in artifacts:
            print(f"  - {item.name}  ({_human(item.stat().st_size)})")
        dist_folder = DIST_DIR / APP_EXE_NAME
        if dist_folder.is_dir():
            print(f"  - 目录版体积: {_human(_dir_size(dist_folder))}")
        print(f"[build] 构建成功 {datetime.now():%Y-%m-%d %H:%M:%S}")
        return 0
    except BaseException as exc:  # noqa: BLE001 - 构建脚本必须留痕
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        try:
            with BUILD_ERROR_LOG.open("a", encoding="utf-8") as fh:
                fh.write(f"\n{'=' * 70}\n[{datetime.now():%Y-%m-%d %H:%M:%S}] 构建失败\n{detail}")
        except Exception:  # noqa: BLE001
            pass
        print(f"[build] 构建失败: {exc}\n{detail}")
        return 1
    finally:
        sys.stdout = original_stdout  # type: ignore[assignment]
        log_file.close()


if __name__ == "__main__":
    os.chdir(ROOT)
    sys.exit(main())
