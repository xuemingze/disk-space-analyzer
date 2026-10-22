import os
import re
import json
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional, Set
from collections import defaultdict

from app.utils.file_helper import is_system_critical_path, format_size, categorize_file_by_ext
from app.utils.logger import app_logger
from app.core.organize_models import (
    OrganizeOptions, OrganizeMode, extract_file_content_sample, sanitize_subpath
)

# 已知软件、工具链及生态的特征规则库
KNOWN_APP_PATTERNS = [
    # 1. Node.js & 前端工具链
    {
        "app_name": "Node.js / npm",
        "category": "开发工具链/Node.js-npm",
        "patterns": [r"\.npm", r"\npm-cache", r"\npm", r"\AppData\Roaming\npm", r"\AppData\Local\npm-cache"],
        "marker_files": ["package.json", "npm-shrinkwrap.json", ".npmrc", "package-lock.json"],
        "default_risk": "低风险",
        "is_cache": True,
        "rationale_template": "命中 Node.js/npm 模块或包管理器缓存特征目录"
    },
    {
        "app_name": "pnpm / Yarn",
        "category": "开发工具链/pnpm-Yarn",
        "patterns": [r"\pnpm", r"\pnpm-store", r"\pnpm-cache", r"\.yarn", r"\yarn-cache", r"\yarn"],
        "marker_files": ["pnpm-lock.yaml", "yarn.lock", ".yarnrc"],
        "default_risk": "低风险",
        "is_cache": True,
        "rationale_template": "命中 pnpm/Yarn 依赖包全局存储或缓存目录"
    },
    {
        "app_name": "Node.js 依赖库 (node_modules)",
        "category": "开发工具链/node_modules",
        "patterns": [r"\node_modules"],
        "marker_files": ["package.json"],
        "default_risk": "低风险",
        "is_cache": True,
        "rationale_template": "命中项目级 node_modules 第三方依赖库"
    },
    
    # 2. Python 生态与虚拟环境
    {
        "app_name": "Python / pip / 虚拟环境",
        "category": "开发工具链/Python环境与缓存",
        "patterns": [
            r"\pip\cache", r"\.pip", r"\.virtualenvs", r"\.venv", r"\__pycache__", 
            r"\site-packages", r"\.conda", r"\miniconda", r"\anaconda"
        ],
        "marker_files": ["requirements.txt", "pyproject.toml", "Pipfile", "environment.yml", "setup.py"],
        "default_risk": "低风险",
        "is_cache": True,
        "rationale_template": "命中 Python pip 包缓存、字节码缓存或虚拟环境目录"
    },

    # 3. VS Code / 现代智能 IDE
    {
        "app_name": "Visual Studio Code",
        "category": "IDE与编辑器/VSCode",
        "patterns": [r"\.vscode", r"\Code\User\workspaceStorage", r"\Code\Cache", r"\Code\CachedData", r"\Code\Logs"],
        "marker_files": ["extensions.json", "settings.json"],
        "default_risk": "低风险",
        "is_cache": True,
        "rationale_template": "命中 VS Code 扩展、工作区存储或缓存目录"
    },
    {
        "app_name": "Cursor / Windsurf / JetBrains",
        "category": "IDE与编辑器/智能开发工具",
        "patterns": [r"\.cursor", r"\.windsurf", r"\.idea", r"\.atomcode", r"\.codex"],
        "marker_files": [],
        "default_risk": "低风险",
        "is_cache": True,
        "rationale_template": "命中 AI IDE 或 JetBrains 工程配置与缓存"
    },

    # 4. Git 版本控制
    {
        "app_name": "Git 版本控制",
        "category": "代码版本管理/Git",
        "patterns": [r"\.git", r"\.github", r"\.git-credential-cache"],
        "marker_files": ["config", "HEAD", ".gitignore"],
        "default_risk": "需人工确认",
        "is_cache": False,
        "rationale_template": "包含核心 Git 版本仓库，建议人工核实后归档"
    },

    # 5. Docker & 容器虚拟化
    {
        "app_name": "Docker / 容器引擎",
        "category": "虚拟化与容器/Docker",
        "patterns": [r"\.docker", r"\docker\data", r"\wsl", r"\minikube"],
        "marker_files": ["daemon.json", "Dockerfile", "docker-compose.yml"],
        "default_risk": "需人工确认",
        "is_cache": False,
        "rationale_template": "命中 Docker/WSL 镜像或容器运行配置"
    },

    # 6. Rust / Go / Java 编译生态
    {
        "app_name": "Rust / Cargo",
        "category": "开发工具链/Rust-Cargo",
        "patterns": [r"\.cargo", r"\.rustup", r"\target\debug", r"\target\release"],
        "marker_files": ["Cargo.toml", "Cargo.lock"],
        "default_risk": "低风险",
        "is_cache": True,
        "rationale_template": "命中 Rust Cargo 构建缓存或工具链"
    },
    {
        "app_name": "Java Maven / Gradle",
        "category": "开发工具链/Java构建工具",
        "patterns": [r"\.m2\repository", r"\.gradle\caches", r"\.gradle\wrapper"],
        "marker_files": ["pom.xml", "build.gradle", "settings.gradle"],
        "default_risk": "低风险",
        "is_cache": True,
        "rationale_template": "命中 Maven/Gradle 本地依赖仓库或缓存"
    },
    {
        "app_name": "Go 工具链",
        "category": "开发工具链/Go-Pkg",
        "patterns": [r"\go\pkg\mod", r"\go\pkg\sumdb"],
        "marker_files": ["go.mod", "go.sum"],
        "default_risk": "低风险",
        "is_cache": True,
        "rationale_template": "命中 Go 模块下载缓存"
    },

    # 7. 社交与通讯软件
    {
        "app_name": "微信 (WeChat)",
        "category": "通讯软件数据/微信",
        "patterns": [r"\WeChat Files", r"\Tencent\WeChat", r"\Tencent\MicroMsg"],
        "marker_files": ["AccInfo.dat", "Msg", "FileStorage"],
        "default_risk": "需人工确认",
        "is_cache": False,
        "rationale_template": "命中微信用户聊天记录、接收文件或缓存"
    },
    {
        "app_name": "腾讯 QQ / TIM",
        "category": "通讯软件数据/QQ",
        "patterns": [r"\Tencent\QQ", r"\Tencent\TIM", r"\QQPCMgr"],
        "marker_files": [],
        "default_risk": "需人工确认",
        "is_cache": False,
        "rationale_template": "命中 QQ/TIM 用户数据或接收文件目录"
    },
    {
        "app_name": "钉钉 (DingTalk)",
        "category": "办公协同软件/钉钉",
        "patterns": [r"\DingDing", r"\DingTalk"],
        "marker_files": [],
        "default_risk": "需人工确认",
        "is_cache": False,
        "rationale_template": "命中钉钉办公协同客户端缓存与文件"
    },
    {
        "app_name": "飞书 (Lark)",
        "category": "办公协同软件/飞书",
        "patterns": [r"\Lark", r"\Feishu"],
        "marker_files": [],
        "default_risk": "需人工确认",
        "is_cache": False,
        "rationale_template": "命中飞书协同客户端运行数据"
    },

    # 8. 浏览器应用
    {
        "app_name": "Google Chrome / Edge 浏览器",
        "category": "浏览器数据/Chrome-Edge",
        "patterns": [r"\Google\Chrome\User Data", r"\Microsoft\Edge\User Data", r"\BraveSoftware"],
        "marker_files": ["Bookmarks", "Preferences", "History"],
        "default_risk": "需人工确认",
        "is_cache": False,
        "rationale_template": "命中浏览器用户配置文件或扩展数据"
    },

    # 9. 设计与多媒体应用
    {
        "app_name": "Adobe 系列设计软件",
        "category": "设计与创作/Adobe",
        "patterns": [r"\Adobe\Photoshop", r"\Adobe\Premiere", r"\Adobe\Common", r"\Adobe\After Effects"],
        "marker_files": [],
        "default_risk": "中风险",
        "is_cache": False,
        "rationale_template": "命中 Adobe 创意套件工程缓存或媒体暂存"
    },
    {
        "app_name": "Blender / 3D 渲染工具",
        "category": "设计与创作/Blender",
        "patterns": [r"\Blender Foundation\Blender"],
        "marker_files": [],
        "default_risk": "低风险",
        "is_cache": False,
        "rationale_template": "命中 Blender 3D 建模配置与插件"
    },

    # 10. 系统级临时与日志
    {
        "app_name": "系统与应用临时缓存",
        "category": "系统临时与日志/Temp",
        "patterns": [r"\AppData\Local\Temp", r"\Windows\Temp", r"\repair-backups", r"\.cache\codex-runtimes"],
        "marker_files": [],
        "default_risk": "低风险",
        "is_cache": True,
        "rationale_template": "命中 Windows 或第三方应用标准临时文件目录"
    }
]


def _extract_pe_version_info(exe_path: str) -> Tuple[str, str]:
    """提取 Windows PE 可执行文件的 ProductName 和 FileDescription（外显软件铭牌信息）。"""
    prod_name = ""
    file_desc = ""
    try:
        import win32api
        trans = win32api.GetFileVersionInfo(exe_path, "\\VarFileInfo\\Translation")
        if trans:
            for lang, codepage in trans:
                str_path = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\"
                try:
                    p = win32api.GetFileVersionInfo(exe_path, str_path + "ProductName")
                    if p and not prod_name:
                        prod_name = str(p).strip()
                except Exception:
                    pass
                try:
                    d = win32api.GetFileVersionInfo(exe_path, str_path + "FileDescription")
                    if d and not file_desc:
                        file_desc = str(d).strip()
                except Exception:
                    pass
                if prod_name or file_desc:
                    break
    except Exception:
        pass

    if prod_name:
        prod_name = re.sub(r'[^\w\s\-.\(\)]', '', prod_name).strip()
    if file_desc:
        file_desc = re.sub(r'[^\w\s\-.\(\)]', '', file_desc).strip()
    return prod_name, file_desc


# 广义分类容器特征词典（大抽屉 / 顶层分类大区）
BROAD_CONTAINER_TAXONOMY: Dict[str, Dict[str, Any]] = {
    "project": {
        "keywords": {"项目", "工程", "开发", "代码", "源码", "workspace", "projects", "repos", "repositories", "code", "dev"},
        "suggested_category": "代码项目与依赖 (Dev & Code)",
        "subpath_prefix": "工程项目",
        "description": "开发工程、代码库与工作区容器"
    },
    "app": {
        "keywords": {
            "软件", "应用", "工具", "程序", "客户端", "绿色软件", "便携软件", "安装包", "软件安装包", "安装程序", "软件下载", "下载安装", "我的安装包",
            "apps", "software", "tools", "utilities", "applications", "programs", "movedapps", "softwares", "myapps", "portable", "app", "tool",
            "installer", "installers", "packages", "package", "setup", "setups"
        },
        "suggested_category": "软件安装与镜像 (Apps & Installers)",
        "subpath_prefix": "应用软件",
        "description": "独立应用、安装程序与绿色工具包"
    },
    "media": {
        "keywords": {"多媒体", "媒体", "视频", "影视", "电影", "电视剧", "动漫", "动画", "音乐", "音频", "录音", "videos", "movies", "tv", "media", "music", "audio"},
        "suggested_category": "音视频与多媒体 (Media & Videos)",
        "subpath_prefix": "影音媒体",
        "description": "影视剧集、音视频剪辑与录音素材"
    },
    "design": {
        "keywords": {"设计", "素材", "图片", "图像", "照片", "壁纸", "插画", "模型", "贴图", "资产", "live2d", "live2d模型", "ai模型", "checkpoint", "lora", "角色素材", "design", "assets", "images", "photos", "textures", "models"},
        "suggested_category": "图像设计与素材 (Design & Assets)",
        "subpath_prefix": "设计资产",
        "description": "平面美术、UI设计、三维模型与视觉素材"
    },
    "game": {
        "keywords": {"游戏", "单机游戏", "网络游戏", "模拟器", "手游", "端游", "games", "gaming", "game"},
        "suggested_category": "游戏娱乐与资产 (Games & Entertainment)",
        "subpath_prefix": "游戏项目",
        "description": "独立游戏、单机游戏与游戏本体资产"
    },
    "finance": {
        "keywords": {"财务", "合同", "商务", "订单", "薪酬", "工资", "税务", "经控", "发票", "报销", "账单", "送货单", "对账单", "finance", "contracts", "invoices", "bills", "accounting"},
        "suggested_category": "文档与电子书 (Documents & Books)",
        "subpath_prefix": "财务商务",
        "description": "商务合同、财务报表、发票凭证与税务单据"
    },
    "docs": {
        "keywords": {"文档", "资料", "文稿", "文章", "报告", "学习", "教程", "课件", "笔记", "书籍", "电子书", "论文", "学术", "docs", "documents", "books", "study", "learning"},
        "suggested_category": "文档与电子书 (Documents & Books)",
        "subpath_prefix": "知识文档",
        "description": "学术论文、知识文档、学习课件与业务报告"
    },
    "backup": {
        "keywords": {"备份", "归档", "历史", "快照", "backup", "backups", "archive", "archives", "snapshots", "snapshot", "bak"},
        "suggested_category": "归档包与系统镜像 (Archives & Images)",
        "subpath_prefix": "归档备份",
        "description": "历史备份包、系统快照与归档数据"
    }
}

NARROW_ENTITY_SUFFIX_PATTERN = re.compile(
    r"^(.+?)(项目|工程|系统|平台|助手|工具|客户端|设计|查重|初稿|终稿|报告|汇总|方案|复盘|模版|清单|明细|账套|对账|流水|合集|三部曲|全集|汉化版|免安装版|绿色版|特别版|完整版|正式版|发票|账单|送货单|经控|模型|素材|角色|\d+月.*|v\d+.*|\d{4}.*)$",
    re.IGNORECASE
)


class AppDetector:
    """
    负责智能识别文件/目录所属的 App、软件或工具链，
    并将文件集合按照父目录/工具根目录聚合为原子处理单元（Atomic Directory Groups）。
    """

    @classmethod
    def match_broad_container(cls, name: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        判断一个目录名是否属于“广义分类容器”（如：项目、多媒体、电影、游戏、设计、财务、学习）。
        返回: (分类标识, 分类配置字典) 或 None
        """
        if not name:
            return None
        n_clean = name.strip().lower()
        # 若带有明确日期、月份、版本（如 10月发票, 2026财务, v1.0, 7月），说明是具体业务账套或实例，绝非广义大抽屉容器
        if re.search(r"(\d+月|\d{4}|v\d+|_v\d+)", n_clean):
            return None

        for key, info in BROAD_CONTAINER_TAXONOMY.items():
            if n_clean in info["keywords"]:
                return key, info
            for kw in info["keywords"]:
                if len(kw) >= 2 and (n_clean == kw or n_clean.endswith(kw) or n_clean.startswith(kw)):
                    if len(n_clean) <= len(kw) + 3:
                        return key, info
        return None

    @classmethod
    def is_narrow_entity(cls, name: str, parent_broad_key: Optional[str] = None) -> bool:
        """
        判断一个子目录是否属于“狭义业务实体”（如：***项目、***设计、***查重、具体的软件名或影视名）。
        """
        if not name or len(name) < 2:
            return False
        # 如果子目录自身也是纯广义词（如 多媒体/视频），则不是狭义实体
        if cls.match_broad_container(name):
            return False
        # 1. 命中特定实体后缀（项目、工程、系统、平台、设计、查重、方案等）
        if NARROW_ENTITY_SUFFIX_PATTERN.match(name):
            return True
        # 2. 如果父级是已确认的广义容器，且子级名称具有实体命名长度
        if parent_broad_key and len(name) >= 2:
            return True
        return False

    @classmethod
    def detect_directory_collective(cls, dir_path: str | Path, cache: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        自顶向下防御式探测：检测指定目录是否属于不可拆分的“软件/工程/工具链原子集体”。
        若命中，返回提炼的外显身份卡片（Software Identity Card），供剪枝与高层归类使用。
        支持传入会话级轻量高速缓存 cache。
        """
        norm_dir = os.path.normpath(str(dir_path))
        if cache is not None and norm_dir in cache:
            return cache[norm_dir]

        res = cls._do_detect_directory_collective(norm_dir)
        if cache is not None:
            cache[norm_dir] = res
        return res

    @classmethod
    def _do_detect_directory_collective(cls, norm_dir: str) -> Optional[Dict[str, Any]]:
        try:
            p = Path(norm_dir)
        except Exception:
            return None

        if not os.path.isdir(norm_dir):
            return None

        # 0. 驱动器盘符根目录保护 (如 C:\, D:\)，绝不可作为单个软件/实体
        if len(p.parts) <= 1:
            return None

        # 0.1 保护系统核心受保护路径
        if is_system_critical_path(str(p)):
            return None

        dname = p.name
        dname_lower = dname.lower()

        # 0.2 Windows 注册表与自定义沉淀软件权威匹配 (物理事实第一优先，绝对优先于大抽屉与盘符启发式)
        try:
            from app.core.registry_detector import RegistryAppDetector
            matched_app, is_root = RegistryAppDetector.match_app_by_path(str(p))
            if matched_app and is_root:
                col_type = "用户自定义集体" if matched_app.source == "custom" else "已安装应用"
                reason_str = (
                    f"用户自定义沉淀集合 [{matched_app.name}]，原子保全封印"
                    if matched_app.source == "custom"
                    else f"Windows 注册表权威收录软件 [{matched_app.name}]，整包封印"
                )
                return {
                    "is_collective": True,
                    "collective_type": col_type,
                    "software_name": matched_app.name,
                    "directory_name": dname,
                    "primary_executable": "",
                    "product_title": matched_app.name,
                    "publisher": matched_app.publisher or ("用户自定义沉淀" if matched_app.source == "custom" else ""),
                    "manifest_project_name": matched_app.name,
                    "signature_type": "Custom User Collective" if matched_app.source == "custom" else "Windows Installed Software",
                    "suggested_category": "软件安装与程序 (Apps & Installers)",
                    "recommended_subpath": f"应用软件/{matched_app.name}",
                    "reason": reason_str,
                    "confidence": 1.0 if matched_app.source == "custom" else 0.99
                }
        except Exception as e:
            app_logger.debug("注册表应用匹配检测异常: %s", e)

# 0.3 系统核心保留大容器与已知顶层系统目录黑名单
        SYSTEM_CONTAINER_NAMES = {
            "downloads", "download", "下载", "我的下载", "下载内容", "安装包", "软件安装包", "安装程序", "软件下载", "临时下载",
            "desktop", "桌面", "documents", "文档", "user", "users", "administrator",
            "program files", "program files (x86)", "appdata", "local", "roaming",
            "$recycle.bin", "system volume information", "windows", "perflogs",
            "recovery", "boot"
        }
        if dname_lower in SYSTEM_CONTAINER_NAMES:
            return None

        # 若在 C 盘系统盘的一级根目录下 (如 C:\ProgramData)，保护不被误识别为单个实体
        if len(p.parts) == 2 and p.parts[0].lower().startswith("c:"):
            return None

        # 0.3 广义分类容器（如 "项目", "多媒体", "游戏", "电影", "设计", "财务", "学习", "backups", "MovedApps"）属于大抽屉，绝不可作为独立单个实体剪枝！
        if cls.match_broad_container(dname):
            return None

        # 附属/内部私有依赖目录（如 _internal, __pycache__）绝不可作为独立集体输出，必须溯源归属至主程序父目录
        if dname_lower in {"_internal", "internal", "__pycache__"}:
            return None

        # 1. 检测依赖生态与缓存工具链原子目录 (如 node_modules, .git, venv)
        if dname_lower == "node_modules":
            return {
                "is_collective": True,
                "collective_type": "生态工具链/依赖集体",
                "software_name": "Node.js 依赖库 (node_modules)",
                "directory_name": dname,
                "primary_executable": "",
                "product_title": "Node.js Package Modules",
                "manifest_project_name": "node_modules",
                "signature_type": "Node.js Dependencies",
                "suggested_category": "开发工具链/node_modules",
                "recommended_subpath": "开发依赖/node_modules",
                "reason": "包含项目级 node_modules 第三方依赖库",
                "confidence": 0.98,
                "risk_level": "低风险",
                "require_confirmation": False
            }

        if dname_lower == ".git":
            return {
                "is_collective": True,
                "collective_type": "代码版本管理集体",
                "software_name": "Git 版本仓库 (.git)",
                "directory_name": dname,
                "primary_executable": "",
                "product_title": "Git Repository",
                "manifest_project_name": ".git",
                "signature_type": "Git Version Control",
                "suggested_category": "代码版本管理/Git",
                "recommended_subpath": "版本管理/Git",
                "reason": "包含核心 Git 版本仓库，严禁拆分内部对象",
                "confidence": 0.98,
                "risk_level": "需人工确认",
                "require_confirmation": True
            }

        # 检查 Python 虚拟运行环境
        if (p / "pyvenv.cfg").exists() or dname_lower in {".venv", "venv", ".virtualenvs"}:
            return {
                "is_collective": True,
                "collective_type": "运行环境集体",
                "software_name": f"Python 虚拟环境 ({dname})",
                "directory_name": dname,
                "primary_executable": "python.exe",
                "product_title": "Python Virtualenv",
                "manifest_project_name": dname,
                "signature_type": "Python venv/pyvenv.cfg",
                "suggested_category": "开发工具链/Python环境与缓存",
                "recommended_subpath": f"运行环境/Python/{dname}",
                "reason": "检测到 pyvenv.cfg 配置文件，属于独立 Python 虚拟环境",
                "confidence": 0.96,
                "risk_level": "需人工确认",
                "require_confirmation": True
            }

        # 检查匹配 KNOWN_APP_PATTERNS
        for rule in KNOWN_APP_PATTERNS:
            for pat in rule["patterns"]:
                pat_clean = pat.lower().strip("\\/")
                if pat_clean == dname_lower:
                    return {
                        "is_collective": True,
                        "collective_type": "生态工具链/依赖集体",
                        "software_name": rule["app_name"],
                        "directory_name": dname,
                        "primary_executable": "",
                        "product_title": rule["app_name"],
                        "manifest_project_name": dname,
                        "signature_type": rule["app_name"],
                        "suggested_category": rule["category"],
                        "recommended_subpath": sanitize_subpath(rule["app_name"]),
                        "reason": rule["rationale_template"],
                        "confidence": 0.95,
                        "risk_level": rule["default_risk"],
                        "require_confirmation": (rule["default_risk"] != "低风险")
                    }

        # 1.5 检查 Live2D 虚拟角色模型与 AI 媒体实体资产 (.model3.json, .model.json, physics3.json)
        model_file = None
        try:
            with os.scandir(norm_dir) as it:
                for item_f in it:
                    if item_f.is_file():
                        low_f = item_f.name.lower()
                        if low_f.endswith(".model3.json") or low_f.endswith(".model.json") or low_f.endswith(".cdi3.json") or low_f.endswith(".physics3.json"):
                            model_file = item_f.name
                            break
        except Exception:
            pass

        if model_file:
            clean_m = sanitize_subpath(dname)
            return {
                "is_collective": True,
                "collective_type": "Live2D模型集体",
                "software_name": f"{dname} (Live2D模型)",
                "directory_name": dname,
                "primary_executable": "",
                "product_title": f"Live2D Model ({dname})",
                "manifest_project_name": dname,
                "signature_type": f"Live2D Model ({model_file})",
                "suggested_category": "图像设计与素材 (Design & Assets)",
                "recommended_subpath": f"Live2D模型/{clean_m}",
                "reason": f"检测到 Live2D 角色模型核心清单 {model_file}，属于不可拆分模型资产整体",
                "confidence": 0.98,
                "risk_level": "需人工确认",
                "require_confirmation": True
            }

        # 2. 核心泛型机制：父子语义广义-狭义落差拓扑佐证机制 (Semantic Granularity Hierarchy Corroboration)
        # 最高仲裁法则：若父级或上层属于明确的广义分类大抽屉 (如 app/MovedApps, backup/backups, finance/财务/经控, design/Live2D)：
        # 当前狭义业务实体必须优先继承其父级大类的上位语义！
        # 严禁将 backups 下的历史快照因包含 requirements.txt 误判为活跃开发工程；
        # 严禁将 MovedApps 下的应用软件因缺少主目录 exe 散落为碎片文件！
        try:
            parent_name = p.parent.name
            parent_broad = cls.match_broad_container(parent_name)
            # 若直接父级是版本/包装目录（如 soft-platform_v1.0），向上回溯一级寻找广义祖先
            if not parent_broad and len(p.parents) >= 2:
                grand_name = p.parents[1].name
                parent_broad = cls.match_broad_container(grand_name)
                if parent_broad:
                    parent_name = grand_name

            if parent_broad:
                broad_key, broad_info = parent_broad
                clean_name = sanitize_subpath(dname)
                prefix = broad_info.get("subpath_prefix", parent_name)

                # 2.1 归档与备份大抽屉 (backups, 归档备份, 历史备份) 下的实体：绝对强制上位赋权！
                # 严禁因内部包含 requirements.txt 或 package.json 反客为主误判为活跃开发工程！
                if broad_key == "backup":
                    return {
                        "is_collective": True,
                        "collective_type": "历史快照集体",
                        "software_name": f"{dname} (历史快照)",
                        "directory_name": dname,
                        "primary_executable": "",
                        "product_title": f"Snapshot Backup ({dname})",
                        "manifest_project_name": dname,
                        "signature_type": f"广义归档容器佐证 ({parent_name} -> {dname})",
                        "suggested_category": broad_info["suggested_category"],
                        "recommended_subpath": f"{prefix}/{clean_name}",
                        "reason": f"父级 [{parent_name}] 判定为归档备份容器，当前目录 [{dname}] 强行继承历史快照上位语义，整盘原子保全",
                        "confidence": 0.99,
                        "risk_level": "需人工确认",
                        "require_confirmation": True
                    }

                # 2.2 应用软件与工具大抽屉 (MovedApps, Apps, Tools, 软件, 工具) 下的实体
                if broad_key == "app":
                    return {
                        "is_collective": True,
                        "collective_type": "独立软件集体",
                        "software_name": f"{dname} (应用软件)",
                        "directory_name": dname,
                        "primary_executable": "",
                        "product_title": f"Application ({dname})",
                        "manifest_project_name": dname,
                        "signature_type": f"广义应用容器佐证 ({parent_name} -> {dname})",
                        "suggested_category": broad_info["suggested_category"],
                        "recommended_subpath": f"{prefix}/{clean_name}",
                        "reason": f"父级 [{parent_name}] 判定为应用软件容器，当前目录 [{dname}] 判定为独立应用实体，整盘原子保全",
                        "confidence": 0.98,
                        "risk_level": "需人工确认",
                        "require_confirmation": True
                    }

                # 2.3 财务商务大抽屉 (财务, 经控, 发票, 合同) 下的实体
                if broad_key == "finance":
                    return {
                        "is_collective": True,
                        "collective_type": "业务账套集体",
                        "software_name": f"{dname} (财务商务)",
                        "directory_name": dname,
                        "primary_executable": "",
                        "product_title": dname,
                        "manifest_project_name": dname,
                        "signature_type": f"广义财务容器佐证 ({parent_name} -> {dname})",
                        "suggested_category": broad_info["suggested_category"],
                        "recommended_subpath": f"{prefix}/{clean_name}",
                        "reason": f"父级 [{parent_name}] 判定为财务经控容器，当前目录 [{dname}] 判定为业务账套不可拆分集体，整盘原子保全",
                        "confidence": 0.98,
                        "risk_level": "需人工确认",
                        "require_confirmation": True
                    }

                # 2.4 图像设计与素材大抽屉 (设计, 素材, Live2D) 下的实体
                if broad_key == "design":
                    return {
                        "is_collective": True,
                        "collective_type": "业务实体集体",
                        "software_name": f"{dname} ({broad_info['subpath_prefix']})",
                        "directory_name": dname,
                        "primary_executable": "",
                        "product_title": dname,
                        "manifest_project_name": dname,
                        "signature_type": f"广义设计容器佐证 ({parent_name} -> {dname})",
                        "suggested_category": broad_info["suggested_category"],
                        "recommended_subpath": f"{prefix}/{clean_name}",
                        "reason": f"父级 [{parent_name}] 判定为设计资产容器，当前目录 [{dname}] 判定为狭义业务实体，整盘原子保全",
                        "confidence": 0.95,
                        "risk_level": "需人工确认",
                        "require_confirmation": True
                    }

                # 2.5 影视与多媒体大抽屉 (多媒体, 视频, 电影) 下的实体
                if broad_key == "media":
                    return {
                        "is_collective": True,
                        "collective_type": "业务实体集体",
                        "software_name": f"{dname} ({broad_info['subpath_prefix']})",
                        "directory_name": dname,
                        "primary_executable": "",
                        "product_title": dname,
                        "manifest_project_name": dname,
                        "signature_type": f"广义多媒体容器佐证 ({parent_name} -> {dname})",
                        "suggested_category": broad_info["suggested_category"],
                        "recommended_subpath": f"{prefix}/{clean_name}",
                        "reason": f"父级 [{parent_name}] 判定为影音媒体容器，当前目录 [{dname}] 判定为狭义业务实体，整盘原子保全",
                        "confidence": 0.95,
                        "risk_level": "需人工确认",
                        "require_confirmation": True
                    }
                # 2.6 知识文档大抽屉 (文档, 资料, 学习, 教程) 下的实体
                if broad_key == "docs":
                    return {
                        "is_collective": True,
                        "collective_type": "业务实体集体",
                        "software_name": f"{dname} ({broad_info['subpath_prefix']})",
                        "directory_name": dname,
                        "primary_executable": "",
                        "product_title": dname,
                        "manifest_project_name": dname,
                        "signature_type": f"广义文档容器佐证 ({parent_name} -> {dname})",
                        "suggested_category": broad_info["suggested_category"],
                        "recommended_subpath": f"{prefix}/{clean_name}",
                        "reason": f"父级 [{parent_name}] 判定为知识文档容器，当前目录 [{dname}] 判定为狭义业务实体，整盘原子保全",
                        "confidence": 0.95,
                        "risk_level": "需人工确认",
                        "require_confirmation": True
                    }

                # 2.7 游戏资产大抽屉 (游戏, 单机游戏, 网络游戏) 下的实体
                if broad_key == "game":
                    return {
                        "is_collective": True,
                        "collective_type": "业务实体集体",
                        "software_name": f"{dname} ({broad_info['subpath_prefix']})",
                        "directory_name": dname,
                        "primary_executable": "",
                        "product_title": dname,
                        "manifest_project_name": dname,
                        "signature_type": f"广义游戏容器佐证 ({parent_name} -> {dname})",
                        "suggested_category": broad_info["suggested_category"],
                        "recommended_subpath": f"{prefix}/{clean_name}",
                        "reason": f"父级 [{parent_name}] 判定为游戏资产容器，当前目录 [{dname}] 判定为狭义业务实体，整盘原子保全",
                        "confidence": 0.95,
                        "risk_level": "需人工确认",
                        "require_confirmation": True
                    }

                # 2.8 开发工程大抽屉 (项目, 工程, workspace, repos) 下具备狭义业务实体后缀
                if broad_key == "project" and NARROW_ENTITY_SUFFIX_PATTERN.match(dname):
                    return {
                        "is_collective": True,
                        "collective_type": "业务实体集体",
                        "software_name": f"{dname} ({broad_info['subpath_prefix']})",
                        "directory_name": dname,
                        "primary_executable": "",
                        "product_title": dname,
                        "manifest_project_name": dname,
                        "signature_type": f"广义工程容器佐证 ({parent_name} -> {dname})",
                        "suggested_category": broad_info["suggested_category"],
                        "recommended_subpath": f"{prefix}/{clean_name}",
                        "reason": f"父级 [{parent_name}] 判定为工程项目大抽屉，当前目录 [{dname}] 判定为狭义业务实体，整盘原子保全",
                        "confidence": 0.95,
                        "risk_level": "需人工确认",
                        "require_confirmation": True
                    }
        except Exception:
            pass

        # 3. 检查开发工程项目清单 (Project Manifests)
        # 3.1 Node.js / 前端项目 (package.json)
        pkg_json_path = p / "package.json"
        if pkg_json_path.exists() and pkg_json_path.is_file():
            proj_name = dname
            desc = ""
            framework_tag = "前端/Node"
            try:
                with open(pkg_json_path, "r", encoding="utf-8", errors="ignore") as f:
                    pj = json.load(f)
                    if isinstance(pj, dict):
                        proj_name = pj.get("name") or proj_name
                        desc = pj.get("description", "")
                        deps = {**pj.get("dependencies", {}), **pj.get("devDependencies", {})}
                        if "vue" in deps: framework_tag = "Vue 前端"
                        elif "react" in deps or "next" in deps: framework_tag = "React 前端"
                        elif "electron" in deps: framework_tag = "Electron 客户端"
                        elif "express" in deps or "koa" in deps or "nest" in deps: framework_tag = "Node 后端服务"
                        elif "vite" in deps: framework_tag = "Vite 前端"
            except Exception:
                pass
            clean_proj_name = sanitize_subpath(proj_name)
            return {
                "is_collective": True,
                "collective_type": "开发工程集体",
                "software_name": f"{proj_name} ({framework_tag})",
                "directory_name": dname,
                "primary_executable": "",
                "product_title": f"{proj_name} - {desc}" if desc else proj_name,
                "manifest_project_name": proj_name,
                "signature_type": f"Node.js ({framework_tag})",
                "suggested_category": "代码项目与依赖 (Dev & Code)",
                "recommended_subpath": f"前端工程/{clean_proj_name}",
                "reason": f"检测到 package.json 清单文件 (工程名: {proj_name})",
                "confidence": 0.95,
                "risk_level": "需人工确认",
                "require_confirmation": True
            }

        # 2.2 Java Maven 工程 (pom.xml)
        pom_path = p / "pom.xml"
        if pom_path.exists() and pom_path.is_file():
            artifact_id = dname
            try:
                content = pom_path.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r"<artifactId>(.*?)</artifactId>", content)
                if m: artifact_id = m.group(1).strip()
            except Exception:
                pass
            clean_art = sanitize_subpath(artifact_id)
            return {
                "is_collective": True,
                "collective_type": "开发工程集体",
                "software_name": f"{artifact_id} (Java/Maven)",
                "directory_name": dname,
                "primary_executable": "",
                "product_title": artifact_id,
                "manifest_project_name": artifact_id,
                "signature_type": "Java (Maven)",
                "suggested_category": "代码项目与依赖 (Dev & Code)",
                "recommended_subpath": f"Java工程/{clean_art}",
                "reason": f"检测到 pom.xml 构建配置 (构件: {artifact_id})",
                "confidence": 0.95,
                "risk_level": "需人工确认",
                "require_confirmation": True
            }

        # 2.3 Rust 工程 (Cargo.toml)
        cargo_path = p / "Cargo.toml"
        if cargo_path.exists() and cargo_path.is_file():
            pkg_name = dname
            try:
                content = cargo_path.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
                if m: pkg_name = m.group(1).strip()
            except Exception:
                pass
            clean_pkg = sanitize_subpath(pkg_name)
            return {
                "is_collective": True,
                "collective_type": "开发工程集体",
                "software_name": f"{pkg_name} (Rust/Cargo)",
                "directory_name": dname,
                "primary_executable": "",
                "product_title": pkg_name,
                "manifest_project_name": pkg_name,
                "signature_type": "Rust (Cargo)",
                "suggested_category": "代码项目与依赖 (Dev & Code)",
                "recommended_subpath": f"Rust工程/{clean_pkg}",
                "reason": f"检测到 Cargo.toml 清单 (包名: {pkg_name})",
                "confidence": 0.95,
                "risk_level": "需人工确认",
                "require_confirmation": True
            }

        # 2.4 Go 工程 (go.mod)
        gomod_path = p / "go.mod"
        if gomod_path.exists() and gomod_path.is_file():
            mod_name = dname
            try:
                content = gomod_path.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r'module\s+([^\s]+)', content)
                if m: mod_name = m.group(1).strip().split("/")[-1]
            except Exception:
                pass
            clean_mod = sanitize_subpath(mod_name)
            return {
                "is_collective": True,
                "collective_type": "开发工程集体",
                "software_name": f"{mod_name} (Go/Golang)",
                "directory_name": dname,
                "primary_executable": "",
                "product_title": mod_name,
                "manifest_project_name": mod_name,
                "signature_type": "Go (go.mod)",
                "suggested_category": "代码项目与依赖 (Dev & Code)",
                "recommended_subpath": f"Go工程/{clean_mod}",
                "reason": f"检测到 go.mod 模块配置 (模块名: {mod_name})",
                "confidence": 0.95,
                "risk_level": "需人工确认",
                "require_confirmation": True
            }

        # 2.5 Python 工程 (pyproject.toml 或 requirements.txt)
        if (p / "pyproject.toml").exists() or (p / "requirements.txt").exists():
            clean_py = sanitize_subpath(dname)
            return {
                "is_collective": True,
                "collective_type": "开发工程集体",
                "software_name": f"{dname} (Python 工程)",
                "directory_name": dname,
                "primary_executable": "",
                "product_title": dname,
                "manifest_project_name": dname,
                "signature_type": "Python (requirements/pyproject)",
                "suggested_category": "代码项目与依赖 (Dev & Code)",
                "recommended_subpath": f"Python工程/{clean_py}",
                "reason": "检测到 Python 工程依赖配置文件",
                "confidence": 0.92,
                "risk_level": "需人工确认",
                "require_confirmation": True
            }

        # 3. 检查独立绿色软件主程序与特征 (Standalone Executable / App Collectives)
        # 兼容 PyInstaller 6+ (_internal), Nuitka, Electron, Qt, JRE, 及常见中英文伴生资源子目录
        APP_COMPANION_DIRS = {
            "_internal", "internal", "runtime", "app", "resources", "res",
            "locales", "plugins", "platforms", "modules", "lib", "libs",
            "bin", "share", "assets", "translations", "data", "database",
            "组件", "插件", "模块", "部件", "数据", "配置", "资源"
        }

        exe_files: List[Path] = []
        has_accompanying_dll = False
        has_companion_folder = False
        has_sub_dll = False

        try:
            with os.scandir(str(p)) as it:
                for entry in it:
                    if entry.is_file():
                        low = entry.name.lower()
                        if low.endswith(".exe"):
                            exe_files.append(Path(entry.path))
                        elif low.endswith(".dll") or low.endswith(".pyd"):
                            has_accompanying_dll = True
                    elif entry.is_dir():
                        low = entry.name.lower()
                        if low in APP_COMPANION_DIRS:
                            has_companion_folder = True
                        if not has_sub_dll:
                            try:
                                with os.scandir(entry.path) as sub_it:
                                    for sub_e in sub_it:
                                        if sub_e.is_file():
                                            slow = sub_e.name.lower()
                                            if slow.endswith(".dll") or slow.endswith(".pyd") or slow.endswith(".so"):
                                                has_sub_dll = True
                                                break
                            except Exception:
                                pass

            # 若根目录没有 exe，探查 bin/ 子目录
            if not exe_files and (p / "bin").is_dir():
                with os.scandir(str(p / "bin")) as it_bin:
                    for entry in it_bin:
                        if entry.is_file() and entry.name.lower().endswith(".exe"):
                            exe_files.append(Path(entry.path))
                            has_companion_folder = True
        except Exception:
            pass

        if exe_files:
            helper_pattern = re.compile(r"^(unins\w*|uninstall|setup|install|update|crashpad\w*|elevate)\.exe$", re.I)
            main_exes = [e for e in exe_files if not helper_pattern.match(e.name)] or exe_files

            best_exe = main_exes[0]
            for e in main_exes:
                if e.stem.lower() in dname_lower or dname_lower in e.stem.lower():
                    best_exe = e
                    break

            prod_title, file_desc = _extract_pe_version_info(str(best_exe))
            sw_name = prod_title or file_desc or best_exe.stem

            has_pyinstaller = (p / "_internal").is_dir() or (p / "base_library.zip").exists()
            name_matches_dir = (best_exe.stem.lower() in dname_lower or dname_lower in best_exe.stem.lower())
            has_lnk_or_asar = (p / f"{best_exe.stem}.lnk").exists() or (p / "electron.asar").exists()

            # 独立软件与安装包集合池辨别守则 (Standalone App vs Installer Pool)：
            # 1. 若当前目录含有明显的下载/安装包词干，坚决判定为安装包池，绝不可作为单体软件剪枝！
            is_installer_pool_dir = any(k in dname_lower for k in [
                "安装包", "安装程序", "软件下载", "我的下载", "下载", "download", "downloads", "installer", "installers", "packages", "setup"
            ])
            if is_installer_pool_dir:
                return None

            # 2. 检查核心伴生运行时特征
            has_runtime_components = (
                has_accompanying_dll
                or has_companion_folder
                or has_sub_dll
                or has_pyinstaller
                or has_lnk_or_asar
            )

            # 3. 若存在 2 个以上 exe 且无伴生运行时（无 dll、无配套资源文件夹、无 pyinstaller、无 asar）且名称不匹配，
            # 判定为独立工具包散落或下载集合池，禁止作为单一软件实体整体封印！
            if len(exe_files) >= 2 and not has_runtime_components and not name_matches_dir:
                return None

            # 解禁数据盘根目录独立软件法则 (Broad vs Narrow Topology Law)：
            # 若位于非系统盘根目录下一级 (如 D:\Clash, D:\Everything)，要求主程序名与目录强匹配，或具备明确的伴生运行时
            is_data_drive_root_app = (
                (len(p.parts) == 2 and not p.parts[0].lower().startswith("c:"))
                and (name_matches_dir or has_runtime_components)
            )

            is_app_collective = (
                has_runtime_components
                or name_matches_dir
                or is_data_drive_root_app
            )

            if is_app_collective:
                clean_sw = sanitize_subpath(sw_name)
                sig = f"PyInstaller 独立应用 ({best_exe.name})" if has_pyinstaller else f"独立应用 ({best_exe.name})"
                return {
                    "is_collective": True,
                    "collective_type": "独立软件集体",
                    "software_name": sw_name,
                    "directory_name": dname,
                    "primary_executable": best_exe.name,
                    "product_title": prod_title or file_desc or best_exe.name,
                    "manifest_project_name": sw_name,
                    "signature_type": sig,
                    "suggested_category": "软件安装与镜像 (Apps & Installers)",
                    "recommended_subpath": f"应用软件/{clean_sw}",
                    "reason": f"检测到核心主程序 {best_exe.name} 及配套软件依赖/资源目录，判定为不可拆分独立软件整体",
                    "confidence": 0.98,
                    "risk_level": "需人工确认",
                    "require_confirmation": True
                }

        # 5. 补充兜底：若目录名自身直接包含明确业务单据特征（发票、经控、送货单、账单、明细、账套等）
        try:
            # 必须排除软件包装目录（如 发票明细软件-v2.3.4）与含有可执行程序的目录
            if any(k in dname for k in ["发票", "经控", "送货单", "对账单", "报销单", "明细", "账套", "对账", "流水", "清单"]):
                if not re.search(r"(软件|app|tool|v\d+|_v\d+)", dname, re.I) and not exe_files:
                    clean_name = sanitize_subpath(dname)
                    return {
                        "is_collective": True,
                        "collective_type": "业务账套集体",
                        "software_name": f"{dname} (财务商务)",
                        "directory_name": dname,
                        "primary_executable": "",
                        "product_title": dname,
                        "manifest_project_name": dname,
                        "signature_type": f"业务账套命名特征 ({dname})",
                        "suggested_category": "文档与电子书 (Documents & Books)",
                        "recommended_subpath": f"财务商务/{clean_name}",
                        "reason": f"目录名命中财务/经控单据关键特征，判定为业务账套不可拆分集体",
                        "confidence": 0.95,
                        "risk_level": "需人工确认",
                        "require_confirmation": True
                    }
        except Exception:
            pass

        return None

    @classmethod
    def detect_app_for_path(cls, path_str: str) -> Dict[str, Any]:
        """
        基于路径特征、父级目录名称及特征标记文件，精准识别所属 App 或工具。
        若无法识别，则归为 '未识别工具/待分类'。
        """
        norm_path = os.path.normpath(path_str).lower()
        p = Path(path_str)

        # 0. 优先检测系统受保护核心目录与安全敏感凭证
        if is_system_critical_path(path_str):
            return {
                "app_name": "Windows 系统核心",
                "suggested_category": "系统关键/需人工确认",
                "reason": "系统受保护关键目录或底层核心文件",
                "confidence": 0.20,
                "risk_level": "高风险",
                "require_confirmation": True,
                "is_recognized": True
            }

        from app.core.organize_models import SENSITIVE_FILENAME_PATTERNS
        fname_lower = p.name.lower()
        if any(pattern.search(fname_lower) for pattern in SENSITIVE_FILENAME_PATTERNS):
            return {
                "app_name": "安全凭证与私钥",
                "suggested_category": "安全凭证与私钥",
                "reason": f"文件名 {p.name} 匹配安全凭证与敏感私钥特征",
                "confidence": 0.30,
                "risk_level": "高风险",
                "require_confirmation": True,
                "is_recognized": True
            }

        if p.suffix.lower() == ".raw" and any(k in fname_lower for k in ["dump", "memory", "segment", "hex", "bin"]):
            return {
                "app_name": "内存/底层二进制转储",
                "suggested_category": "未分类/待人工确认",
                "reason": "包含内存转储关键字与底层 raw 二进制特征",
                "confidence": 0.35,
                "risk_level": "需人工确认",
                "require_confirmation": True,
                "is_recognized": False
            }

        # 1. 优先匹配已知 App 规则库
        for rule in KNOWN_APP_PATTERNS:
            for pattern in rule["patterns"]:
                pattern_norm = os.path.normpath(pattern).lower()
                if pattern_norm in norm_path:
                    # 检查是否为关键系统受保护路径
                    if is_system_critical_path(path_str):
                        return {
                            "app_name": rule["app_name"],
                            "suggested_category": rule["category"],
                            "reason": f"{rule['rationale_template']} (受保护系统目录)",
                            "confidence": 0.45,
                            "risk_level": "需人工确认",
                            "require_confirmation": True,
                            "is_recognized": True
                        }
                    
                    return {
                        "app_name": rule["app_name"],
                        "suggested_category": rule["category"],
                        "reason": f"{rule['rationale_template']} (匹配路径特征: {pattern})",
                        "confidence": 0.95,
                        "risk_level": rule["default_risk"],
                        "require_confirmation": (rule["default_risk"] != "低风险"),
                        "is_recognized": True
                    }

        # 2. 检查父目录中是否存在标志性配置文件 (e.g. package.json, Cargo.toml)
        try:
            curr = p if p.is_dir() else p.parent
            for _ in range(3): # 向上探查最多 3 层
                if not curr or str(curr) == str(curr.parent):
                    break
                if (curr / "package.json").exists():
                    return {
                        "app_name": "Node.js / npm 项目",
                        "suggested_category": "开发项目工程/Node.js",
                        "reason": f"在父级目录 {curr.name} 中检测到 package.json 工程文件",
                        "confidence": 0.92,
                        "risk_level": "需人工确认",
                        "require_confirmation": True,
                        "is_recognized": True
                    }
                if (curr / "Cargo.toml").exists():
                    return {
                        "app_name": "Rust / Cargo 项目",
                        "suggested_category": "开发项目工程/Rust",
                        "reason": f"在父级目录 {curr.name} 中检测到 Cargo.toml 工程文件",
                        "confidence": 0.92,
                        "risk_level": "需人工确认",
                        "require_confirmation": True,
                        "is_recognized": True
                    }
                if (curr / "requirements.txt").exists() or (curr / "pyproject.toml").exists():
                    return {
                        "app_name": "Python 项目工程",
                        "suggested_category": "开发项目工程/Python",
                        "reason": f"在父级目录 {curr.name} 中检测到 Python 依赖定义文件",
                        "confidence": 0.90,
                        "risk_level": "需人工确认",
                        "require_confirmation": True,
                        "is_recognized": True
                    }
                curr = curr.parent
        except Exception:
            pass

        # 3. 启发式父目录探测 (例如 Downloads, Desktop, Documents, Videos, Pictures)
        from app.utils.file_helper import EXTENSION_CATEGORIES
        is_known_ext = any(p.suffix.lower() in ext_set for ext_set in EXTENSION_CATEGORIES.values())
        if not is_known_ext and p.suffix:
            return {
                "app_name": "未识别格式/待人工确认",
                "suggested_category": "未分类/待人工确认",
                "reason": f"未识别的文件格式 ({p.suffix})，需人工核对",
                "confidence": 0.35,
                "risk_level": "需人工确认",
                "require_confirmation": True,
                "is_recognized": False
            }

        parts_lower = [part.lower() for part in p.parts]
        if "downloads" in parts_lower or "desktop" in parts_lower or "documents" in parts_lower:
            from app.utils.file_helper import EXTENSION_CATEGORIES
            safe_download_categories = {"视频与音频", "压缩包与镜像", "安装包与程序", "文档与办公", "图像与设计", "代码与工程"}
            ext_category = None
            for cat_name, ext_set in EXTENSION_CATEGORIES.items():
                if p.suffix.lower() in ext_set:
                    ext_category = cat_name
                    break

            if ext_category and ext_category in safe_download_categories:
                return {
                    "app_name": "系统下载中心" if "downloads" in parts_lower else ("桌面快捷暂存" if "desktop" in parts_lower else "个人文档库"),
                    "suggested_category": "个人与通用/下载暂存" if "downloads" in parts_lower else ("个人与通用/桌面文件" if "desktop" in parts_lower else "个人与通用/文档库"),
                    "reason": f"位于用户个人常用目录，格式属于 {ext_category}",
                    "confidence": 0.85,
                    "risk_level": "低风险",
                    "require_confirmation": False,
                    "is_recognized": True
                }
            else:
                return {
                    "app_name": "未识别格式/待人工确认",
                    "suggested_category": "未分类/待人工确认",
                    "reason": f"文件扩展名 ({p.suffix}) 无法作为常规个人文件自动确认，需人工审核",
                    "confidence": 0.35,
                    "risk_level": "需人工确认",
                    "require_confirmation": True,
                    "is_recognized": False
                }

        # 4. 无法可靠识别所属 App 或工具
        return {
            "app_name": "未识别工具/待分类",
            "suggested_category": "未识别工具/待分类",
            "reason": f"未能明确匹配已知 App 签名或工具链特征 (父目录: {p.parent.name})",
            "confidence": 0.40,
            "risk_level": "需人工确认",
            "require_confirmation": True,
            "is_recognized": False
        }

    @classmethod
    def is_symlink_or_junction(cls, path_str: str) -> Tuple[bool, Optional[str]]:
        """
        检查是否为符号链接 (Symlink) 或 Windows NTFS 挂载目录 (Junction)。
        返回: (是否为链接, 实际指向目标路径)
        """
        try:
            p = Path(path_str)
            if p.is_symlink():
                target = os.readlink(path_str)
                return True, target
            
            # Windows Junction 检查 (通过 stat attributes 或 reparse point)
            if os.name == "nt" and os.path.exists(path_str):
                import ctypes
                FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
                attrs = ctypes.windll.kernel32.GetFileAttributesW(str(p))
                if attrs != -1 and (attrs & FILE_ATTRIBUTE_REPARSE_POINT):
                    return True, "NTFS Junction 挂载点"
        except Exception:
            pass
        return False, None

    @classmethod
    def _detect_umbrella_from_name(cls, name: str, known_umbrellas: Optional[Set[str]] = None) -> Optional[str]:
        """从文件或目录名称中检测匹配的泛目录关键词（用于游离孤儿散件归巢吸引）"""
        low = name.lower()
        if "live2d" in low:
            return "live2D"
        if "经控" in name:
            return "经控"
        # 排除包含 setup, install, 软件, app 等应用安装程序关键字
        if "发票" in name and not any(k in low for k in ["setup", "install", "软件", "app", ".exe", "msi"]):
            return "发票"
        if "泰润" in name:
            return "泰润明细"
        if known_umbrellas:
            for k in sorted(known_umbrellas, key=len, reverse=True):
                if len(k) >= 2 and k.lower() in low:
                    return k
        return None

    @classmethod
    def _normalize_umbrella_name(cls, top_dir: str, sub_name: str = "") -> Optional[str]:
        """规整源泛目录名称，去除末尾日期/版本后缀并归聚子级语义"""
        if not top_dir:
            return None
        low = top_dir.lower()
        COMMON_CONTAINERS = {"downloads", "desktop", "documents", "temp", "tmp", "misc", "recycle.bin", "recycler"}
        if low in COMMON_CONTAINERS:
            if sub_name:
                return cls._detect_umbrella_from_name(sub_name)
            return None

        if "live2d" in low:
            return "live2D"
        if "经控" in top_dir or (sub_name and "经控" in sub_name):
            return "经控"
        if "发票" in top_dir:
            if sub_name and "经控" in sub_name:
                return "经控"
            return "发票"
        if "泰润" in top_dir:
            return "泰润明细"

        # 通用语义规整：去除末尾的日期、月份、版本号（如 '项目2025' -> '项目'，'经控9月' -> '经控'）
        base = re.sub(r'[\-_]?(?:20\d\d[-_]?\d*|v?\d+(?:\.\d+)*|\d+月).*$', '', top_dir, flags=re.I).strip()
        if base and len(base) >= 2:
            return base
        return top_dir

    @classmethod
    def extract_source_umbrella(
        cls,
        item_path: str,
        scan_roots: Optional[List[str]] = None,
        known_umbrellas: Optional[Set[str]] = None
    ) -> Optional[str]:
        """
        从文件/目录路径提取所属的源泛目录锚点 (Source Umbrella Anchor)。
        例如：E:\\共用文件\\live2D\\西域舞女 -> 'live2D'
              E:\\共用文件\\发票\\7月发票 -> '发票'
              E:\\共用文件\\发票\\经控8月 -> '经控'
              E:\\共用文件\\经控9月 -> '经控'
              E:\\共用文件\\08月经控送货单发票明细及汇总.xlsx -> '经控'
        """
        p = Path(item_path)
        norm_p_str = os.path.normpath(item_path)
        COMMON_CONTAINERS = {"downloads", "desktop", "documents", "temp", "tmp", "misc", "recycle.bin", "recycler"}

        # 1. 尝试匹配 scan_roots
        best_root = None
        if scan_roots:
            for r in scan_roots:
                if not r:
                    continue
                norm_r = os.path.normpath(r)
                if norm_p_str.lower().startswith(norm_r.lower()):
                    if best_root is None or len(norm_r) > len(best_root):
                        best_root = norm_r

        if best_root:
            try:
                rel = Path(norm_p_str).relative_to(Path(best_root))
                parts = rel.parts
                if len(parts) >= 2:
                    top_dir = parts[0]
                    sub_name = parts[1] if len(parts) > 1 else ""
                    return cls._normalize_umbrella_name(top_dir, sub_name)
                elif len(parts) == 1:
                    name = parts[0]
                    detected = cls._detect_umbrella_from_name(name, known_umbrellas)
                    if detected:
                        return detected
                    try:
                        if (Path(best_root) / name).is_dir():
                            return cls._normalize_umbrella_name(name)
                    except Exception:
                        pass
            except Exception:
                pass

        # 2. 若未匹配到明确的 scan_root，回溯父目录层级推测
        if len(p.parts) >= 2:
            detected = cls._detect_umbrella_from_name(p.name, known_umbrellas)
            if detected:
                return detected
            if p.parent and len(p.parent.parts) >= 1:
                if p.parent.name.lower() in COMMON_CONTAINERS:
                    return None
                detected_parent = cls._detect_umbrella_from_name(p.parent.name, known_umbrellas)
                if detected_parent:
                    return detected_parent
                if len(p.parents) >= 2:
                    if p.parents[1].name.lower() in COMMON_CONTAINERS:
                        return None
                    detected_grand = cls._detect_umbrella_from_name(p.parents[1].name, known_umbrellas)
                    if detected_grand:
                        return detected_grand
                    return cls._normalize_umbrella_name(p.parent.name)

        return None

    @classmethod
    def reconcile_umbrella_consensus(
        cls,
        grouped_units: List[Dict[str, Any]],
        destination_root: str,
        options: Optional[OrganizeOptions] = None
    ) -> List[Dict[str, Any]]:
        """
        源路径同源同宿收敛器 (Cluster Consensus Reconciler)：
        对同一 source_umbrella (源泛目录锚点) 下的所有聚合单元与文件进行多数表决与同构保全，
        确保同源泛目录不分裂、同源同宿收敛到同一一级分类，且 recommended_subpath 保持同源泛目录基准。
        """
        if not grouped_units:
            return grouped_units

        dest_root_p = Path(destination_root)

        # 1. 按 source_umbrella 分组单元
        umbrella_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for unit in grouped_units:
            umb = unit.get("source_umbrella")
            # 排除已识别的独立软件集体与开发工程集体，App 主体不参与业务泛目录平移收敛
            c_info = unit.get("collective_info") or {}
            c_type = c_info.get("collective_type", "")
            if c_type in ["独立软件集体", "开发工程集体"]:
                continue
            if umb:
                umbrella_groups[umb].append(unit)

        # 2. 对每个泛目录集合执行共识收敛
        for umb, units in umbrella_groups.items():
            if not units:
                continue

            # 多数表决一级分类 (suggested_category)
            # 排除未分类/待确认项，优先采用具体业务分类
            cat_scores: Dict[str, float] = defaultdict(float)
            for u in units:
                cat = u.get("suggested_category", "")
                conf = float(u.get("confidence", 0.5))
                if cat and cat not in ["未分类/待人工确认", "未识别工具/待分类", "系统关键/需人工确认"]:
                    cat_scores[cat] += conf + 1.0  # 票数权重 + 置信度加成

            if cat_scores:
                consensus_cat = max(cat_scores.items(), key=lambda x: x[1])[0]
            else:
                consensus_cat = units[0].get("suggested_category", "文档与多媒体资产 (Docs & Media)")

            clean_umb = sanitize_subpath(umb)

            # 3. 将共识分类与泛目录子路径应用到同源的所有单元
            for u in units:
                old_cat = u.get("suggested_category", "")
                u["suggested_category"] = consensus_cat
                u["source_umbrella"] = umb
                u["recommended_subpath"] = clean_umb

                # 若分类发生收敛修正，记录佐证依据
                if old_cat != consensus_cat and old_cat not in ["", "未分类/待人工确认"]:
                    u["rationale"] = (u.get("rationale", "") + f" [同源泛目录 '{umb}' 共识收敛至 '{consensus_cat}']").strip()

                # 重新计算目标路径
                root_p = Path(u["original_root"])
                is_dir = u.get("is_directory_group", False)
                sub_p = Path(clean_umb)

                if is_dir:
                    if root_p.name.lower() == sub_p.name.lower() or root_p.name.lower() in [part.lower() for part in sub_p.parts]:
                        new_target_base = dest_root_p / consensus_cat / sub_p
                    else:
                        new_target_base = dest_root_p / consensus_cat / sub_p / root_p.name
                else:
                    new_target_base = dest_root_p / consensus_cat / sub_p

                u["target_root"] = str(new_target_base)

                # 同步更新所有子项的目标路径
                for sub in u.get("sub_items", []):
                    sub_p_orig = sub.get("original_path", "")
                    if is_dir:
                        rel = sub.get("relative_path")
                        if not rel or rel == ".":
                            try:
                                rel = str(Path(sub_p_orig).relative_to(root_p))
                            except Exception:
                                rel = sub.get("name", Path(sub_p_orig).name)
                        sub["target_path"] = str(new_target_base / Path(rel))
                    else:
                        sub["target_path"] = str(new_target_base / Path(sub.get("name", Path(sub_p_orig).name)))

        return grouped_units

    @classmethod
    def generate_heuristic_subpath(
        cls,
        group_key: str,
        items: List[Dict[str, Any]],
        app_info: Dict[str, Any],
        is_dir_group: bool,
        mode: OrganizeMode = OrganizeMode.COMPREHENSIVE,
        lang: str = "zh",
        source_umbrella: Optional[str] = None
    ) -> str:
        """
        根据整理模式 (综合/按类型/按前缀/按日期/按应用) 与命名语言，
        生成高质量的离线推荐多级子目录层级 (recommended_subpath)。
        """
        is_en = (lang.lower() == "en")
        p = Path(group_key)
        
        # 1. 按修改日期模式
        if mode == OrganizeMode.BY_DATE:
            # 搜集时间戳
            mtimes = []
            for it in items:
                m = it.get("mtime")
                if m and isinstance(m, (int, float)) and m > 0:
                    mtimes.append(m)
                else:
                    try:
                        fpath = it.get("path") or it.get("original_path", "")
                        if fpath and os.path.exists(fpath):
                            mtimes.append(os.path.getmtime(fpath))
                    except Exception:
                        pass
            
            if mtimes:
                import datetime
                # 取中位数时间以防单个文件偏差
                median_mtime = sorted(mtimes)[len(mtimes) // 2]
                dt = datetime.datetime.fromtimestamp(median_mtime)
                return f"{dt.year}/{dt.strftime('%Y-%m')}"
            return "2026/2026-Q1" if not is_en else "2026/2026-Q1"

        # 2. 按前缀模式
        if mode == OrganizeMode.BY_PREFIX:
            names = [it.get("name", Path(it.get("path", "")).name) for it in items if it.get("name") or it.get("path")]
            if len(names) >= 2:
                # 寻找最长公共前缀
                prefix = os.path.commonprefix(names)
                # 清洗前缀末尾的下划线、减号、点
                prefix = re.sub(r'[\s_\-\.]+$', '', prefix).strip()
                if len(prefix) >= 3 and not prefix.isdigit():
                    return sanitize_subpath(prefix)
            elif len(names) == 1 and names[0]:
                stem = Path(names[0]).stem
                prefix_match = re.match(r'^([a-zA-Z\u4e00-\u9fa50-9]{3,})[_\-\s]', stem)
                if prefix_match:
                    return sanitize_subpath(prefix_match.group(1))

        # 3. 按文件类型模式
        if mode == OrganizeMode.BY_TYPE:
            ext_counts: Dict[str, int] = defaultdict(int)
            for it in items:
                fpath = it.get("path") or it.get("original_path", "")
                ext = Path(fpath).suffix.lower()
                if ext:
                    ext_counts[ext] += 1
            top_ext = max(ext_counts.items(), key=lambda x: x[1])[0] if ext_counts else ""
            
            # 扩展名到语义子目录映射
            if top_ext in [".pdf", ".doc", ".docx", ".wps", ".odt"]:
                return "Documents" if is_en else "文档资料"
            elif top_ext in [".xls", ".xlsx", ".csv", ".et"]:
                return "Spreadsheets" if is_en else "财务表格"
            elif top_ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".psd"]:
                return "Images" if is_en else "图像图片"
            elif top_ext in [".mp4", ".mkv", ".avi", ".mov", ".flv", ".mp3", ".wav"]:
                return "Media" if is_en else "音视频"
            elif top_ext in [".zip", ".rar", ".7z", ".tar", ".gz"]:
                return "Archives" if is_en else "压缩包"
            elif top_ext in [".exe", ".msi", ".iso", ".dmg"]:
                return "Installers" if is_en else "安装程序"
            elif top_ext in [".py", ".js", ".ts", ".html", ".css", ".java", ".cpp", ".rs", ".go"]:
                return "SourceCode" if is_en else "代码工程"

        # 4. 按应用工具链模式
        if mode == OrganizeMode.BY_APP:
            app_name = app_info.get("app_name", "")
            if app_name and "未识别" not in app_name:
                # 简化应用名称作为子路径
                clean_app = app_name.split("(")[0].strip().replace("/", "-")
                return sanitize_subpath(clean_app)

        # 5. 综合整理模式 (Comprehensive)
        # 优先锚定源泛目录 (Source Umbrella Preservation): 若明确属于源泛目录 (如 live2D, 经控, 发票)，整盘保全该主干
        if source_umbrella:
            clean_umb = sanitize_subpath(source_umbrella)
            if clean_umb:
                return clean_umb

        # 针对特定业务关键词智能细化（发票、合同、简历、日志等）
        p_name = Path(group_key).name.lower()
        names_text = (p_name + " " + " ".join([it.get("name", "") for it in items[:10]])).lower()

        # 父子语义广义容器佐证：若所在目录或父目录为广义容器（如 财务、设计、媒体、项目），结合上下文细分
        parent_broad = cls.match_broad_container(p.name if p.is_dir() else p.parent.name)
        if parent_broad:
            broad_key, broad_info = parent_broad
            prefix = broad_info["subpath_prefix"]
            if any(k in names_text for k in ["invoice", "发票", "receipt", "报销", "税"]):
                return "Finance/Invoices" if is_en else f"{prefix}/发票"
            if any(k in names_text for k in ["contract", "合同", "agreement", "协议"]):
                return "Business/Contracts" if is_en else f"{prefix}/合同"
            if any(k in names_text for k in ["poster", "海报", "banner", "kv", "视觉"]):
                return "Design/Posters" if is_en else f"{prefix}/海报"
            if any(k in names_text for k in ["icon", "图标", "logo"]):
                return "Design/Icons" if is_en else f"{prefix}/图标"
            if any(k in names_text for k in ["paper", "论文", "查重"]):
                return "Docs/Thesis" if is_en else f"{prefix}/论文查重"

        if any(k in names_text for k in ["invoice", "发票", "receipt", "报销", "税"]):
            return "Finance/Invoices" if is_en else "财务/发票"
        if any(k in names_text for k in ["contract", "合同", "agreement", "协议"]):
            return "Business/Contracts" if is_en else "商务/合同"
        if any(k in names_text for k in ["resume", "简历", "cv"]):
            return "HR/Resumes" if is_en else "人事/简历"
        if any(k in names_text for k in ["report", "汇报", "总结", "方案", "规划", "prd", "手册", "指南", "纪要"]):
            return "Office/Reports" if is_en else "办公/方案汇报"
        if any(k in names_text for k in ["screenshot", "截图", "snip"]):
            return "Screenshots" if is_en else "屏幕截图"
        if any(k in names_text for k in ["cache", "缓存", "dump", "temp", "临时", "scratch", "autosave"]):
            return "Caches/Temp" if is_en else "缓存与临时"
        if any(k in names_text for k in ["log", "日志", "crash", "trace"]):
            return "Logs" if is_en else "运行日志"
        if any(k in names_text for k in ["secret", "credential", "id_rsa", ".env", "token", "password", "key", "pem", "kdbx"]):
            return "Security/Credentials" if is_en else "安全凭证/密钥"
        if any(k in names_text for k in ["system32", "kernel32", "syswow64", "bootmgfw", "ntdll", "regedit", "cmd.exe", "hosts"]):
            return "System/Components" if is_en else "系统核心组件"

        # 若是已识别的应用工具链目录，给出应用级层级
        app_name = app_info.get("app_name", "")
        if app_name and "未识别" not in app_name:
            clean_app = app_name.split("(")[0].strip().replace("/", "-")
            return sanitize_subpath(clean_app)

        # 结合文件扩展名进行格式语义子目录划分 (兜底智能推断)
        ext_counts: Dict[str, int] = defaultdict(int)
        for it in items:
            fpath = it.get("path") or it.get("original_path", "")
            ext = Path(fpath).suffix.lower()
            if ext:
                ext_counts[ext] += 1
        top_ext = max(ext_counts.items(), key=lambda x: x[1])[0] if ext_counts else ""

        if top_ext in [".pdf", ".doc", ".docx", ".wps", ".odt", ".txt", ".md"]:
            return "Documents" if is_en else "文档资料"
        elif top_ext in [".xls", ".xlsx", ".csv", ".et"]:
            return "Spreadsheets" if is_en else "财务表格"
        elif top_ext in [".ppt", ".pptx", ".dps"]:
            return "Presentations" if is_en else "演示汇报"
        elif top_ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".psd", ".ai", ".cr2", ".arw"]:
            return "Media/Images" if is_en else "媒体/图像设计"
        elif top_ext in [".mp4", ".mkv", ".avi", ".mov", ".flv"]:
            return "Media/Videos" if is_en else "媒体/视频素材"
        elif top_ext in [".mp3", ".wav", ".flac", ".m4a"]:
            return "Media/Audio" if is_en else "媒体/音频录音"
        elif top_ext in [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"]:
            return "Archives" if is_en else "归档压缩包"
        elif top_ext in [".exe", ".msi", ".dmg", ".pkg"]:
            return "Installers" if is_en else "安装程序"
        elif top_ext in [".iso", ".img"]:
            return "OS_Images" if is_en else "系统镜像"
        elif top_ext in [".py", ".js", ".ts", ".html", ".css", ".java", ".cpp", ".rs", ".go"]:
            return "SourceCode" if is_en else "代码工程"
        elif top_ext in [".log", ".tmp", ".dmp", ".dump"]:
            return "Logs_Temp" if is_en else "日志与临时"

        return ""

    @classmethod
    def group_files_by_parent_or_tool(
        cls,
        file_items: List[Dict[str, Any]],
        destination_root: str,
        options: Optional[OrganizeOptions] = None
    ) -> List[Dict[str, Any]]:
        """
        将散装文件列表按照“所属 App / 工具根目录”或“父目录树”聚合为整体处理单元。
        支持 OrganizeOptions（模式选择、中英文命名、内容抽样与细粒度子目录推荐）。
        """
        if options is None:
            options = OrganizeOptions()

        dest_root_path = Path(destination_root)
        
        # 解析扫描根集合 (scan_roots) 与已知泛目录索引
        scan_roots_set = set()
        for it in file_items:
            sr = it.get("scan_root")
            if sr:
                scan_roots_set.add(os.path.normpath(sr))
        if not scan_roots_set and file_items:
            all_valid_paths = [it.get("path") or it.get("original_path", "") for it in file_items if it.get("path") or it.get("original_path")]
            if all_valid_paths:
                try:
                    common_p = os.path.commonpath(all_valid_paths)
                    if common_p and len(Path(common_p).parts) > 1:
                        scan_roots_set.add(os.path.normpath(common_p))
                except Exception:
                    pass
        scan_roots_list = list(scan_roots_set)

        # 预先扫描发掘已存在的源泛目录集合 (known_umbrellas)
        known_umbrellas: Set[str] = set()
        for it in file_items:
            fpath = it.get("path") or it.get("original_path", "")
            if not fpath:
                continue
            umb = cls.extract_source_umbrella(fpath, scan_roots_list)
            if umb:
                known_umbrellas.add(umb)

        # 构建扫描文件集合内的项目工程根目录快速索引
        project_marker_names = {
            "package.json": ("Node.js", "代码项目与依赖 (Dev & Code)"),
            "cargo.toml": ("Rust / Cargo", "代码项目与依赖 (Dev & Code)"),
            "pyproject.toml": ("Python", "代码项目与依赖 (Dev & Code)"),
            "requirements.txt": ("Python", "代码项目与依赖 (Dev & Code)"),
            "pom.xml": ("Java / Maven", "代码项目与依赖 (Dev & Code)"),
            "build.gradle": ("Java / Gradle", "代码项目与依赖 (Dev & Code)"),
            "build.gradle.kts": ("Java / Gradle", "代码项目与依赖 (Dev & Code)"),
            "go.mod": ("Go / Golang", "代码项目与依赖 (Dev & Code)"),
            "cmakelists.txt": ("C++ / CMake", "代码项目与依赖 (Dev & Code)"),
            "dockerfile": ("Docker", "代码项目与依赖 (Dev & Code)"),
            "docker-compose.yml": ("Docker", "代码项目与依赖 (Dev & Code)"),
        }

        discovered_project_roots: Dict[str, Tuple[str, Tuple[str, str]]] = {}
        for it in file_items:
            fpath = it.get("path") or it.get("original_path", "")
            fname = (it.get("name") or Path(fpath).name).lower()
            if fname in project_marker_names:
                p = Path(fpath)
                p_parent = p.parent
                if p_parent and str(p_parent) != str(p_parent.parent):
                    discovered_project_roots[str(p_parent).lower()] = (str(p_parent), project_marker_names[fname])

        # 1. 查找每个文件所属的“最佳聚合根目录”
        file_to_group_root: Dict[str, str] = {}
        group_root_info: Dict[str, Dict[str, Any]] = {}

        common_container_names = {
            "downloads", "desktop", "documents", "misc", "finance", "contracts",
            "office", "videos", "audio", "assets", "installers", "design"
        }

        for item in file_items:
            fpath = item.get("path") or item.get("original_path", "")
            p = Path(fpath)

            # 0. 优先识别已被扫描层剪枝标记的“软件/工程/工具链原子集体”
            if item.get("is_directory_collective"):
                c_info = item.get("collective_info") or {}
                group_key = fpath
                file_to_group_root[fpath] = group_key
                group_root_info[group_key] = {
                    "root_path": group_key,
                    "is_directory_group": True,
                    "app_info": {
                        "app_name": c_info.get("software_name", item.get("name")),
                        "suggested_category": c_info.get("suggested_category", item.get("category", "代码项目与依赖 (Dev & Code)")),
                        "reason": c_info.get("reason", "识别为不可拆分独立软件/工程集体"),
                        "confidence": c_info.get("confidence", 0.95),
                        "risk_level": c_info.get("risk_level", "需人工确认"),
                        "require_confirmation": c_info.get("require_confirmation", True),
                        "is_recognized": True,
                        "recommended_subpath": c_info.get("recommended_subpath", ""),
                        "collective_info": c_info
                    },
                    "items": [item]
                }
                continue

            detected = cls.detect_app_for_path(fpath)
            
            # 尝试在祖先路径中定位工具根目录或工程根目录
            matched_tool_root = None
            matched_collective_info = None

            item_scan_root = item.get("scan_root")
            if not item_scan_root and scan_roots_list:
                for sr in scan_roots_list:
                    if fpath.lower().startswith(sr.lower()):
                        item_scan_root = sr
                        break

            # 1. 优先自顶向下检查祖先路径中最外层的“软件/工程集体”特征探测器 (detect_directory_collective)
            # 优先锚定最外层项目工程根，防止嵌套子工具(如 it-tool)被从父项目集体中撕裂 (严格限定在 scan_root 边界之内)
            for parent in reversed(list(p.parents)):
                if str(parent) == str(parent.parent) or len(parent.parts) <= 2:
                    continue
                if item_scan_root:
                    try:
                        parent.relative_to(Path(item_scan_root))
                    except ValueError:
                        continue
                c_cand = cls.detect_directory_collective(parent)
                if c_cand:
                    matched_tool_root = str(parent)
                    matched_collective_info = c_cand
                    detected = {
                        "app_name": c_cand.get("software_name", parent.name),
                        "suggested_category": c_cand.get("suggested_category", "代码项目与依赖 (Dev & Code)"),
                        "reason": c_cand.get("reason", f"在项目根目录 {parent.name} 中检测到软件/工程集体"),
                        "confidence": c_cand.get("confidence", 0.95),
                        "risk_level": c_cand.get("risk_level", "需人工确认"),
                        "require_confirmation": c_cand.get("require_confirmation", True),
                        "is_recognized": True,
                        "recommended_subpath": c_cand.get("recommended_subpath", ""),
                        "collective_info": c_cand
                    }
                    break

            # 2. 其次匹配已知 App 规则库 (例如 ~/.npm, ~/AppData/Local/pip/cache 等全局工具生态目录)
            if not matched_tool_root and detected["is_recognized"] and detected["app_name"] != "未识别工具/待分类":
                for parent in [p] + list(p.parents):
                    parent_str = str(parent)
                    for rule in KNOWN_APP_PATTERNS:
                        if rule["app_name"] == detected["app_name"]:
                            for pat in rule["patterns"]:
                                if pat.lower().strip("\\/") == parent.name.lower().strip("\\/"):
                                    matched_tool_root = parent_str
                                    break
                        if matched_tool_root:
                            break
                    if matched_tool_root:
                        break

            # 3. 再次匹配独立项目工程根目录索引
            if not matched_tool_root:
                for parent in [p] + list(p.parents):
                    if item_scan_root:
                        try:
                            parent.relative_to(Path(item_scan_root))
                        except ValueError:
                            continue
                    parent_str_lower = str(parent).lower()
                    if parent_str_lower in discovered_project_roots:
                        matched_proj_path, (proj_app, proj_cat) = discovered_project_roots[parent_str_lower]
                        matched_tool_root = matched_proj_path
                        if not detected["is_recognized"] or "未识别" in detected["app_name"]:
                            detected = {
                                "app_name": f"{proj_app}",
                                "suggested_category": proj_cat,
                                "reason": f"在父目录 {parent.name} 中检测到工程配置",
                                "confidence": 0.92,
                                "risk_level": "需人工确认",
                                "require_confirmation": True,
                                "is_recognized": True
                            }
                        break

            # 如果没有匹配到专门的工具根
            if matched_tool_root:
                group_key = matched_tool_root
                is_dir_group = True
            else:
                is_in_common_container = (
                    p.parent.name.lower() in common_container_names or
                    len(p.parent.parts) <= 2 or
                    (item_scan_root and str(p.parent).lower() == item_scan_root.lower())
                )
                if not is_in_common_container and p.parent and len(p.parent.parts) > 1:
                    group_key = str(p.parent)
                    is_dir_group = True
                else:
                    group_key = fpath
                    is_dir_group = False

            file_to_group_root[fpath] = group_key
            if group_key not in group_root_info:
                group_root_info[group_key] = {
                    "root_path": group_key,
                    "is_directory_group": is_dir_group,
                    "app_info": detected,
                    "items": []
                }
            group_root_info[group_key]["items"].append(item)

        # 为每个聚合单元计算源泛目录锚点 (source_umbrella) 并进行向心孤儿归巢 (Orphan Attraction)
        for group_key, gdata in group_root_info.items():
            c_info = gdata["app_info"].get("collective_info") or {}
            # 独立软件集体与开发工程集体作为独立App主体，不归入普通文件泛目录
            if c_info.get("collective_type") in ["独立软件集体", "开发工程集体"]:
                gdata["source_umbrella"] = None
                continue
            umb = cls.extract_source_umbrella(group_key, scan_roots_list, known_umbrellas)
            if not umb and not gdata["is_directory_group"] and gdata["items"]:
                first_name = gdata["items"][0].get("name", Path(group_key).name)
                umb = cls._detect_umbrella_from_name(first_name, known_umbrellas)
            gdata["source_umbrella"] = umb

        # 2. 生成结构化分组单元列表
        grouped_results: List[Dict[str, Any]] = []

        # 先按总大小从大到小排序，确保稳定编号
        sorted_keys = sorted(
            group_root_info.keys(),
            key=lambda k: sum(int(it.get("size", 0)) for it in group_root_info[k]["items"]),
            reverse=True
        )

        for idx, group_key in enumerate(sorted_keys):
            gdata = group_root_info[group_key]
            items_in_group = gdata["items"]
            root_p = Path(gdata["root_path"])
            app_info = gdata["app_info"]
            
            total_size = sum(int(it.get("size", 0)) for it in items_in_group)
            file_count = len(items_in_group)
            
            # 检查是否有符号链接
            is_link, link_target = cls.is_symlink_or_junction(gdata["root_path"])
            
            # 检查该组内是否有高风险文件或系统受保护文件
            has_critical = any(is_system_critical_path(it.get("path", "")) for it in items_in_group)
            
            if is_link:
                risk_level = "需人工确认"
                require_conf = True
                app_info["reason"] += f" (检测到挂载点/软链接: {link_target})"
                confidence = 0.50
            elif has_critical:
                risk_level = "高风险"
                require_conf = True
                app_info["reason"] += " (包含核心系统受保护路径)"
                confidence = 0.30
            else:
                risk_level = app_info["risk_level"]
                require_conf = app_info["require_confirmation"]
                confidence = app_info["confidence"]

            # 如果置信度低于阈值，强制要求人工确认
            if confidence < options.min_confidence:
                require_conf = True

            # 优先采用集体/软件已识别的推荐子路径 (如 应用软件/xxx)
            c_info = app_info.get("collective_info") or {}
            if c_info.get("recommended_subpath"):
                recommended_subpath = c_info["recommended_subpath"]
            else:
                # 生成高质量的推荐子路径 (注入源泛目录锚点)
                recommended_subpath = cls.generate_heuristic_subpath(
                    group_key=group_key,
                    items=items_in_group,
                    app_info=app_info,
                    is_dir_group=gdata["is_directory_group"],
                    mode=options.mode,
                    lang=options.naming_language,
                    source_umbrella=gdata.get("source_umbrella")
                )

            # 建议目标路径 (防止重名重复嵌套)
            cat_name = app_info["suggested_category"]
            if gdata["is_directory_group"]:
                if recommended_subpath:
                    sub_p = Path(recommended_subpath)
                    if root_p.name.lower() == sub_p.name.lower() or root_p.name.lower() in [part.lower() for part in sub_p.parts]:
                        target_base_dir = dest_root_path / cat_name / sub_p
                    else:
                        target_base_dir = dest_root_path / cat_name / sub_p / root_p.name
                else:
                    target_base_dir = dest_root_path / cat_name / root_p.name
            else:
                if recommended_subpath:
                    target_base_dir = dest_root_path / cat_name / Path(recommended_subpath)
                else:
                    target_base_dir = dest_root_path / cat_name

            # 内容样本抽取 (仅当明确开启时)
            content_samples = []
            if options.sample_content_enabled:
                for it in items_in_group[:2]:
                    fpath = it.get("path") or it.get("original_path", "")
                    sample = extract_file_content_sample(fpath, options.sample_content_max_bytes)
                    if sample:
                        content_samples.append({
                            "name": it.get("name", Path(fpath).name),
                            "sample": sample
                        })

            # 构建每个子项的原路径与目标相对路径
            sub_items_detail = []
            for it in items_in_group:
                it_path = it.get("path") or it.get("original_path", "")
                it_p = Path(it_path)
                try:
                    rel_to_root = it_p.relative_to(root_p) if gdata["is_directory_group"] else Path(it_p.name)
                except Exception:
                    rel_to_root = Path(it_p.name)
                
                target_file_path = target_base_dir / rel_to_root if gdata["is_directory_group"] else (target_base_dir / it_p.name)
                
                sub_items_detail.append({
                    "original_path": it_path,
                    "name": it.get("name", it_p.name),
                    "size": int(it.get("size", 0)),
                    "relative_path": str(rel_to_root),
                    "target_path": str(target_file_path),
                    "scan_root": it.get("scan_root", "")
                })

            file_count = sum(int(it.get("file_count", 1)) for it in items_in_group)
            group_unit = {
                "group_id": f"grp_{idx+1:04d}",
                "name": root_p.name or group_key,
                "original_root": gdata["root_path"],
                "scan_root": items_in_group[0].get("scan_root", "") if items_in_group else "",
                "source_umbrella": gdata.get("source_umbrella") or "",
                "target_root": str(target_base_dir),
                "is_directory_group": gdata["is_directory_group"],
                "is_symlink": is_link,
                "symlink_target": link_target or "",
                "app_name": app_info["app_name"],
                "suggested_category": cat_name,
                "recommended_subpath": recommended_subpath,
                "rationale": app_info["reason"],
                "confidence": confidence,
                "risk_level": risk_level,
                "require_confirmation": require_conf,
                "action": "归档" if not require_conf else "需确认",
                "file_count": file_count,
                "total_size": total_size,
                "content_samples": content_samples,
                "sub_items": sub_items_detail,
                "collective_info": app_info.get("collective_info"),
                "source": "离线规则"
            }
            grouped_results.append(group_unit)

        # 执行源路径同源同宿收敛与源路径同构保全
        grouped_results = cls.reconcile_umbrella_consensus(grouped_results, destination_root, options)
        return grouped_results
