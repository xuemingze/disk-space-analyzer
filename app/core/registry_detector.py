"""
app/core/registry_detector.py
Windows 注册表已安装软件拓扑索引与前缀匹配引擎
通过毫秒级解析 HKLM/HKCU 注册表，构建权威软件根目录索引树，
从源头终结多层嵌套应用 (如 EdgeWebView) 内部碎片文件泄露问题。
"""
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Set
from app.utils.logger import app_logger

GENERIC_SUBDIRS = {
    "application", "app", "bin", "core", "programs",
    "x64", "x86", "win64", "win32", "release", "client"
}

COMMON_PARENTS = {
    "program files", "program files (x86)", "appdata", "local",
    "roaming", "microsoft", "programs", "windows", "common files",
    "system32", "syswow64", "users"
}

WINDOWS_INBOX_COMPONENTS = [
    {
        "name": "WindowsPowerShell (x86)",
        "paths": [r"C:\Program Files (x86)\WindowsPowerShell"],
        "publisher": "Microsoft Corporation"
    },
    {
        "name": "WindowsPowerShell",
        "paths": [r"C:\Program Files\WindowsPowerShell"],
        "publisher": "Microsoft Corporation"
    },
    {
        "name": "Windows Defender",
        "paths": [r"C:\Program Files\Windows Defender", r"C:\Program Files (x86)\Windows Defender"],
        "publisher": "Microsoft Corporation"
    },
    {
        "name": "Windows Media Player",
        "paths": [r"C:\Program Files\Windows Media Player", r"C:\Program Files (x86)\Windows Media Player"],
        "publisher": "Microsoft Corporation"
    },
    {
        "name": "Windows Mail",
        "paths": [r"C:\Program Files\Windows Mail"],
        "publisher": "Microsoft Corporation"
    },
    {
        "name": ".NET Runtime",
        "paths": [r"C:\Program Files\dotnet"],
        "publisher": "Microsoft Corporation"
    }
]


@dataclass
class InstalledAppInfo:
    """已安装软件元数据"""
    name: str
    install_root: str
    publisher: str = ""
    version: str = ""
    source: str = "registry"  # registry | custom | ai_catalog
    icon_path: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "install_root": self.install_root,
            "publisher": self.publisher,
            "version": self.version,
            "source": self.source,
            "icon_path": self.icon_path
        }


class RegistryAppDetector:
    """Windows 注册表与自定义软件库检测引擎"""

    _cached_apps: Optional[Dict[str, InstalledAppInfo]] = None
    _cached_roots_sorted: Optional[List[Tuple[str, InstalledAppInfo]]] = None
    _custom_dirs: Dict[str, str] = {}

    @classmethod
    def set_custom_apps(cls, custom_dirs: List[str]):
        """设置用户手动添加的独立应用目录"""
        cls._custom_dirs = {
            os.path.normcase(os.path.normpath(d)): os.path.normpath(d)
            for d in custom_dirs if d and d.strip()
        }
        # 重置缓存以重新合并
        cls._cached_apps = None
        cls._cached_roots_sorted = None

    @classmethod
    def get_installed_apps(cls, force_reload: bool = False) -> Dict[str, InstalledAppInfo]:
        """
        获取全部已知已安装应用映射字典：
        Key: 标准化小写路径 (normcase)
        Value: InstalledAppInfo
        """
        if cls._cached_apps is not None and not force_reload:
            return cls._cached_apps
        cls._cached_roots_sorted = None

        apps: Dict[str, InstalledAppInfo] = {}

        if sys.platform == "win32":
            try:
                import winreg
                keys = [
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")
                ]

                for root, subkey in keys:
                    try:
                        with winreg.OpenKey(root, subkey) as k:
                            num_subkeys = winreg.QueryInfoKey(k)[0]
                            for i in range(num_subkeys):
                                try:
                                    sub_name = winreg.EnumKey(k, i)
                                    with winreg.OpenKey(k, sub_name) as ak:
                                        cls._extract_app_from_reg_key(winreg, ak, apps)
                                except Exception:
                                    pass
                    except Exception as e:
                        app_logger.debug("读取注册表项失败 %s: %s", subkey, e)

            except ImportError:
                pass

        # 注入 Windows 原生系统预置组件库
        for comp in WINDOWS_INBOX_COMPONENTS:
            for p_str in comp["paths"]:
                if os.path.exists(p_str):
                    norm_k = os.path.normcase(os.path.normpath(p_str))
                    if norm_k not in apps:
                        apps[norm_k] = InstalledAppInfo(
                            name=comp["name"],
                            install_root=os.path.normpath(p_str),
                            publisher=comp["publisher"],
                            source="system_builtin"
                        )

        # 合并用户自定义独立软件目录 (优先级高于注册表)
        try:
            from app.config import app_config
            cfg_dirs = app_config.get("custom_app_dirs", default=[])
            if cfg_dirs:
                for d in cfg_dirs:
                    if d and d.strip():
                        norm_d = os.path.normpath(d)
                        cls._custom_dirs[os.path.normcase(norm_d)] = norm_d
        except Exception:
            pass

        for norm_c_dir, orig_p in cls._custom_dirs.items():
            if os.path.exists(orig_p):
                dir_name = os.path.basename(orig_p)
                apps[norm_c_dir] = InstalledAppInfo(
                    name=dir_name,
                    install_root=orig_p,
                    publisher="用户自定义",
                    source="custom"
                )

        cls._cached_apps = apps
        app_logger.info("已加载已安装软件拓扑索引: 共 %d 款软件", len(apps))
        return apps

    @classmethod
    def _extract_app_from_reg_key(cls, winreg, ak, apps_dict: Dict[str, InstalledAppInfo]):
        def _val(val_name: str):
            try:
                v, _ = winreg.QueryValueEx(ak, val_name)
                return v
            except Exception:
                return None

        dname = _val("DisplayName")
        if not dname or not str(dname).strip():
            return

        loc = _val("InstallLocation")
        icon = _val("DisplayIcon")
        uninst = _val("UninstallString")
        pub = _val("Publisher") or ""
        ver = _val("DisplayVersion") or ""

        app_dir = None
        if loc and os.path.isdir(str(loc)):
            app_dir = str(loc)
        elif icon:
            p = str(icon).split(",")[0].strip("\"' ")
            if os.path.isfile(p):
                app_dir = os.path.dirname(p)
        elif uninst:
            p = str(uninst).split(",")[0].strip("\"' ")
            if os.path.isfile(p):
                app_dir = os.path.dirname(p)

        if not app_dir:
            return

        norm = os.path.normpath(app_dir)
        base_sub = os.path.basename(norm).lower()
        parent_p = os.path.dirname(norm)
        parent_base = os.path.basename(parent_p).lower()

        # 智能收拢通用子目录：若处于 Application/bin 等通用子目录，且父目录不是公共大抽屉，收拢至父级作为软件根
        if base_sub in GENERIC_SUBDIRS and parent_base not in COMMON_PARENTS:
            final_root = parent_p
        else:
            final_root = norm

        norm_final = os.path.normcase(os.path.normpath(final_root))
        # 排除盘符根目录 (如 C:\) 或只有驱动器的非法路径
        if len(norm_final) > 3 and os.path.splitdrive(norm_final)[1].strip(os.sep):
            apps_dict[norm_final] = InstalledAppInfo(
                name=str(dname).strip(),
                install_root=final_root,
                publisher=str(pub).strip(),
                version=str(ver).strip(),
                source="registry"
            )

    @classmethod
    def match_app_by_path(cls, dir_path: str) -> Optional[Tuple[InstalledAppInfo, bool]]:
        """
        根据物理目录路径匹配已安装应用：
        返回: (InstalledAppInfo, is_exact_root)
        - is_exact_root=True: 当前目录恰好就是该软件的安装根目录 (应在此处直接封包剪枝)
        - is_exact_root=False: 当前目录属于该软件的子目录 (说明此前扫描漏入或直接扫描了子目录)
        - 若当前目录是该软件的祖先大抽屉 (例如 C:\\Program Files (x86)\\Microsoft 是 EdgeWebView 的父目录)，
          则返回 None，允许扫描栈继续深入到具体的软件根目录！
        """
        apps = cls.get_installed_apps()
        norm_target = os.path.normcase(os.path.normpath(dir_path))

        # 1. 精确匹配当前目录是否为软件根
        if norm_target in apps:
            return apps[norm_target], True

        # 2. 预排序最长前缀优先，加速前缀快速匹配
        if cls._cached_roots_sorted is None:
            cls._cached_roots_sorted = sorted(apps.items(), key=lambda x: len(x[0]), reverse=True)

        for app_root_norm, info in cls._cached_roots_sorted:
            if norm_target.startswith(app_root_norm + os.sep):
                return info, False

        return None
