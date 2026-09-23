import os
import json
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional, Set
from collections import defaultdict

from app.utils.file_helper import is_system_critical_path, format_size, categorize_file_by_ext
from app.utils.logger import app_logger

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


class AppDetector:
    """
    负责智能识别文件/目录所属的 App、软件或工具链，
    并将文件集合按照父目录/工具根目录聚合为原子处理单元（Atomic Directory Groups）。
    """

    @classmethod
    def detect_app_for_path(cls, path_str: str) -> Dict[str, Any]:
        """
        基于路径特征、父级目录名称及特征标记文件，精准识别所属 App 或工具。
        若无法识别，则归为 '未识别工具/待分类'。
        """
        norm_path = os.path.normpath(path_str).lower()
        p = Path(path_str)

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
        parts_lower = [part.lower() for part in p.parts]
        if "downloads" in parts_lower:
            return {
                "app_name": "系统下载中心",
                "suggested_category": "个人与通用/下载暂存",
                "reason": "位于用户个人 Downloads 目录",
                "confidence": 0.85,
                "risk_level": "低风险",
                "require_confirmation": False,
                "is_recognized": True
            }
        elif "desktop" in parts_lower:
            return {
                "app_name": "桌面快捷暂存",
                "suggested_category": "个人与通用/桌面文件",
                "reason": "位于用户桌面 Desktop 目录",
                "confidence": 0.75,
                "risk_level": "中风险",
                "require_confirmation": True,
                "is_recognized": True
            }
        elif "documents" in parts_lower:
            return {
                "app_name": "个人文档库",
                "suggested_category": "个人与通用/文档库",
                "reason": "位于用户 Documents 目录",
                "confidence": 0.80,
                "risk_level": "低风险",
                "require_confirmation": False,
                "is_recognized": True
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
    def group_files_by_parent_or_tool(
        cls,
        file_items: List[Dict[str, Any]],
        destination_root: str
    ) -> List[Dict[str, Any]]:
        """
        将散装文件列表按照“所属 App / 工具根目录”或“父目录树”聚合为整体处理单元。
        
        例如：
        - ~/npm 下的 1000 个 .js/.json 聚合为一个名为 "~/npm (Node.js / npm)" 的目录单元；
        - node_modules 目录作为一个整体；
        - 散装单文件（若处于普通目录）独立保留为单文件单元。
        """
        dest_root_path = Path(destination_root)
        
        # 1. 查找每个文件所属的“最佳聚合根目录”
        # 规则：如果一个文件处于已知工具规则目录（如 .npm, .cache, node_modules, pip\cache）下，
        # 则将该工具目录作为聚合根（Group Root）。
        file_to_group_root: Dict[str, str] = {}
        group_root_info: Dict[str, Dict[str, Any]] = {}

        for item in file_items:
            fpath = item.get("path") or item.get("original_path", "")
            p = Path(fpath)
            
            detected = cls.detect_app_for_path(fpath)
            
            # 尝试在祖先路径中定位工具根目录
            matched_tool_root = None
            if detected["is_recognized"] and detected["app_name"] != "未识别工具/待分类":
                # 向上查找哪一级匹配了 pattern
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

            # 如果没有匹配到专门的工具根，但文件在同一个直接父目录下
            if matched_tool_root:
                group_key = matched_tool_root
                is_dir_group = True
            else:
                # 若文件处于独立文件夹中，以直接父目录作为聚合键
                if p.parent and len(p.parent.parts) > 1:
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

        # 2. 生成结构化分组单元列表
        grouped_results: List[Dict[str, Any]] = []

        for group_key, gdata in group_root_info.items():
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

            # 建议目标路径
            cat_name = app_info["suggested_category"]
            if gdata["is_directory_group"]:
                target_base_dir = dest_root_path / cat_name / root_p.name
            else:
                target_base_dir = dest_root_path / cat_name

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
                    "target_path": str(target_file_path)
                })

            group_unit = {
                "group_id": f"GRP_{abs(hash(group_key)) % 1000000:06d}",
                "name": root_p.name or group_key,
                "original_root": gdata["root_path"],
                "target_root": str(target_base_dir),
                "is_directory_group": gdata["is_directory_group"],
                "is_symlink": is_link,
                "symlink_target": link_target or "",
                "app_name": app_info["app_name"],
                "suggested_category": cat_name,
                "rationale": app_info["reason"],
                "confidence": confidence,
                "risk_level": risk_level,
                "require_confirmation": require_conf,
                "file_count": file_count,
                "total_size": total_size,
                "sub_items": sub_items_detail
            }
            grouped_results.append(group_unit)

        # 按总占用容量降序排序
        grouped_results.sort(key=lambda x: x["total_size"], reverse=True)
        return grouped_results
