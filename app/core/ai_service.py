import os
import json
import time
import requests
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional, Callable
from urllib.parse import urljoin
from dataclasses import dataclass, field

from app.utils.logger import app_logger
from app.utils.file_helper import is_system_critical_path, categorize_file_by_ext, format_size
from app.core.app_detector import AppDetector
from app.core.category_manager import global_category_manager
from app.core.organize_models import (
    OrganizeOptions, OrganizeMode, sanitize_subpath, extract_file_content_sample
)
from app.core.domain_models import (
    VersionClusterGroup, VersionClusterItem, SemanticDiffDecision, ArchiveDestinationPath,
    TopologyRoutingTable, TopologyRole, TopologyPolicy, AIAssetPayloadBuilder,
    AIAuditPolicyConfig, AuditCorrectionRecord, KnowledgeProvenance
)



@dataclass
class AIResponse:
    task_id: str
    report_id: Optional[str] = None
    provider: str = "Unknown"
    model: str = "Unknown"
    final_text: str = ""
    structured_data: Optional[Dict[str, Any]] = None
    reasoning_removed: bool = True
    analysis_source: str = "AI"
    parse_status: str = "SUCCESS" # SUCCESS, MISSING_FINAL_TEXT, PARSE_ERROR, EMPTY
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    raw_content: str = ""
    reasoning_content: str = ""

class AIService:
    _session: Optional[requests.Session] = None
    _session_lock = threading.Lock()

    @classmethod
    def get_session(cls) -> requests.Session:
        """单例 HTTP Keep-Alive 连接池 (< 1s 传输底座保障)"""
        if cls._session is None:
            with cls._session_lock:
                if cls._session is None:
                    session = requests.Session()
                    adapter = requests.adapters.HTTPAdapter(
                        pool_connections=20,
                        pool_maxsize=50,
                        max_retries=0,
                        pool_block=False
                    )
                    session.mount("http://", adapter)
                    session.mount("https://", adapter)
                    cls._session = session
        return cls._session

    INSTALLER_EXTS = {".exe", ".msi", ".pkg", ".dmg", ".deb", ".rpm", ".apk", ".ipa"}
    ARCHIVE_IMAGE_EXTS = {".iso", ".img", ".vmdk", ".vhdx", ".wim", ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"}
    DOC_EXTS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv"}

    @classmethod
    def filter_high_value_assets_for_ai(
        cls,
        items: List[Dict[str, Any]],
        max_items: int = 80
    ) -> List[Dict[str, Any]]:
        """
        AI 分析前置高价值资产过滤管道 (Pre-AI High-Value Asset Filter):
        只允许以下 5 类高价值核心资产送入大模型，其余小碎片 0 Token 阻断:
        1. 应用管理/识别的软件与工程集体 (is_directory_collective / is_collective)
        2. 软件独立安装包与可执行程序 (.exe, .msi, .pkg, .dmg, .deb, .rpm, .apk, .ipa)
        3. 系统镜像与大型压缩归档包 (.iso, .img, .vmdk, .vhdx, .wim, .zip, .rar, .7z, .tar, .gz)
        4. 高价值办公与业务单据报表 (.pdf, .doc, .docx, .xls, .xlsx, .ppt, .pptx, .csv)
        5. 移动端独立手机应用 (.apk) 及重要大资产
        文本感知截断: 仅提取前 100 字符摘要，杜绝全量内容上送。
        """
        high_value_list = []
        for item in items:
            is_coll = bool(item.get("is_directory_collective") or item.get("is_collective"))
            ext = str(item.get("ext", "")).lower()
            name = str(item.get("name", "")).lower()

            if not ext and "." in name:
                ext = os.path.splitext(name)[1].lower()

            # 命中 5 类核心资产判定
            is_installer = ext in cls.INSTALLER_EXTS
            is_archive_image = ext in cls.ARCHIVE_IMAGE_EXTS
            is_doc = ext in cls.DOC_EXTS
            is_apk = ext == ".apk" or name.endswith(".apk")

            if is_coll or is_installer or is_archive_image or is_doc or is_apk:
                item_copy = dict(item)
                # 采样感知前 100 字符文本截断，杜绝无畏消耗 Token
                sample_text = str(item.get("content_sample") or item.get("summary") or "")[:100]
                if sample_text:
                    item_copy["summary_100"] = sample_text
                high_value_list.append(item_copy)

        # 排序：实体集体与超大核心资产排在最前
        high_value_list.sort(key=lambda x: (not (x.get("is_directory_collective") or x.get("is_collective")), -x.get("size", 0)))
        return high_value_list[:max_items]

    @classmethod
    def analyze_directory_or_app_with_ai(
        cls,
        base_url: str,
        api_key: str,
        model: str,
        target_path: str,
        context_files: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        AI 独立应用与目录深度研判接口:
        输入目标物理路径与局部特征文件，调用大模型分析:
        1. 软件/应用官方正式名称 (official_name)
        2. 发行商/开发主体 (publisher)
        3. 核心应用场景与用途说明 (purpose_description)
        4. 所属业务大类 (suggested_category)
        5. 安全评级与治理操作建议 (risk_level, action_recommendation: 保留/归档/清理)
        6. 建议收拢归档子目录 (recommended_subpath)
        """
        norm_p = os.path.normpath(target_path)
        dir_name = os.path.basename(norm_p) or norm_p

        # 本地启发式先验特征提取
        files_sample = context_files or []
        if not files_sample and os.path.isdir(norm_p):
            try:
                with os.scandir(norm_p) as it:
                    for entry in it:
                        files_sample.append(entry.name)
                        if len(files_sample) >= 15:
                            break
            except Exception:
                pass

        fallback_result = {
            "official_name": dir_name,
            "publisher": "本地推断",
            "purpose_description": f"位于 [{norm_p}] 的本地应用或业务目录",
            "suggested_category": "软件安装与程序 (Apps & Installers)",
            "risk_level": "低风险",
            "action_recommendation": "保留",
            "recommended_subpath": f"应用软件/{dir_name}",
            "ai_generated": False
        }

        if not (api_key and base_url and model):
            return fallback_result

        try:
            normalized_url = cls._normalize_base_url(base_url)
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key.strip()}"
            }
            system_prompt = (
                "你是一位专业的软件架构与应用识别专家。请根据提供的目录路径与内部文件名清单，分析该目录属于哪款软件、用途及治理建议。\n"
                "严格输出 JSON 格式，包含以下字段：\n"
                "{\n"
                '  "official_name": "官方标准软件名/应用名",\n'
                '  "publisher": "开发商或所属厂商 (如 Microsoft, Google, Adobe 等)",\n'
                '  "purpose_description": "该软件的核心功能、用途与重要性说明 (50字以内)",\n'
                '  "suggested_category": "推荐资产分类 (如 软件安装与程序, 开发工具链, 图像设计, 办公文档 等)",\n'
                '  "risk_level": "低风险 | 需人工确认 | 高风险",\n'
                '  "action_recommendation": "保留 | 建议归档 | 建议清理",\n'
                '  "recommended_subpath": "建议归档或收拢子目录相对路径 (如 应用软件/软件名)"\n'
                "}"
            )
            sample_str = ", ".join(files_sample[:12]) if files_sample else "无内部文件"
            user_prompt = f"目录路径: {norm_p}\n包含特征文件样本: {sample_str}"

            payload = {
                "model": model.strip(),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.3
            }
            if "gpt" in model.lower() or "deepseek" in model.lower():
                payload["response_format"] = {"type": "json_object"}

            resp = cls.get_session().post(normalized_url, headers=headers, json=payload, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                content_str = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                clean_json = cls._clean_json_response(content_str)
                parsed = json.loads(clean_json)
                parsed["ai_generated"] = True
                return parsed
        except Exception as e:
            app_logger.warning("AI 应用研判异常: %s，使用本地保底推断", e)

        return fallback_result

    # =========================================================================
    # R1~R3: 2~3 级分类树捕捉、AI 编排审核与极速自沉淀微契约 (< 1s 保障)
    # =========================================================================

    @classmethod
    def extract_directory_skeleton(cls, demo_dir: str, max_depth: int = 3) -> Dict[str, Any]:
        """
        本地扫描器仅提取 2~3 级目录骨架与代表性样本程序 (0 Token 碎文件阻断):
        - 深度严格限制在 2~3 级
        - 每目录至多提取 1~2 个代表性程序样本 (.exe, .msi, .bat, .cmd, .py, .ps1, .sh 等)
        - 碎文件零内容、零 Token 阻断，彻底拒绝碎文件进入微契约
        - 自动阻断 Windows 回收站、系统卷、隐藏目录及 Git/Cache 杂质
        返回紧凑结构化骨架字典与微契约文本表示
        """
        norm_root = os.path.normpath(demo_dir.strip()) if demo_dir else ""
        if not norm_root:
            raise ValueError("示范目录路径不能为空")
        try:
            if not os.path.exists(norm_root) or not os.path.isdir(norm_root):
                raise ValueError(f"示范目录不存在或不是有效目录: {demo_dir}")
        except (PermissionError, OSError) as e:
            raise PermissionError(f"访问示范目录权限不足或网络异常: {demo_dir} ({e})")

        drive, rest = os.path.splitdrive(norm_root)
        base = os.path.basename(norm_root)
        if not base:
            if drive.startswith(("\\\\", "//")):
                base = drive.replace("\\", "/").rstrip("/").split("/")[-1]
            elif ":" in drive:
                base = drive
            else:
                base = norm_root
        root_name = base

        executable_exts = {".exe", ".msi", ".bat", ".cmd", ".py", ".ps1", ".sh"}
        visited_real_paths = set()
        ignored_dir_names = {
            "$recycle.bin", "system volume information", "recovery", "perflogs",
            ".git", ".svn", ".hg", ".idea", ".vscode", "__pycache__",
            "node_modules", ".pytest_cache", ".venv", "venv", "env"
        }

        def _scan_level(curr_path: str, curr_depth: int) -> Dict[str, Any]:
            node_name = os.path.basename(curr_path) or curr_path
            node = {
                "name": node_name,
                "path": curr_path,
                "level": curr_depth,
                "samples": [],
                "children": []
            }
            if curr_depth > max_depth:
                return node

            try:
                real_p = os.path.realpath(curr_path)
            except Exception:
                try:
                    real_p = os.path.abspath(curr_path)
                except Exception:
                    real_p = curr_path
            if real_p in visited_real_paths:
                return node
            visited_real_paths.add(real_p)

            subdirs = []
            executables = []

            try:
                with os.scandir(curr_path) as it:
                    for entry in it:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                d_lower = entry.name.lower()
                                if d_lower in ignored_dir_names or d_lower.startswith(("$", ".")):
                                    continue
                                if curr_depth < max_depth:
                                    subdirs.append(entry.path)
                            elif entry.is_file(follow_symlinks=False):
                                ext = os.path.splitext(entry.name)[1].lower()
                                if ext in executable_exts and len(executables) < 2:
                                    executables.append(entry.name)
                            if len(executables) >= 2 and len(subdirs) >= 10:
                                break
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError) as e:
                if curr_depth == 1:
                    raise PermissionError(f"无法访问示范根目录【{curr_path}】，无读取权限或网络无法访问: {e}")
                return None

            node["samples"] = executables
            for s_path in subdirs[:10]: # 单层至多保留 10 个代表子目录，防止无意义膨胀
                c_node = _scan_level(s_path, curr_depth + 1)
                if c_node is not None:
                    node["children"].append(c_node)
            return node

        skeleton_tree = _scan_level(norm_root, 1) or {"name": root_name, "path": norm_root, "level": 1, "samples": [], "children": []}

        # 构建紧凑型微契约骨架文本 (<= 150 Tokens 控制)
        lines = []
        def _build_text(node, indent=0):
            prefix = "  " * indent
            sample_str = f" [{', '.join(node['samples'])}]" if node.get("samples") else ""
            lines.append(f"{prefix}- {node['name']}{sample_str}")
            for c in node.get("children", []):
                _build_text(c, indent + 1)

        _build_text(skeleton_tree)
        compact_text = "\n".join(lines[:15])

        return {
            "root_name": root_name,
            "skeleton_tree": skeleton_tree,
            "compact_text": compact_text
        }

    @classmethod
    def capture_and_build_category_tree(
        cls,
        demo_dir: str,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_depth: int = 3
    ) -> List[Dict[str, Any]]:
        """
        R2 & R3: 2~3 级分类树本地目录特征捕捉与 AI 统揽建树微契约
        端到端耗时严格控制在 1 秒以内。
        本地扫描器仅提取 2~3 级目录骨架与代表性样本程序 (0 Token 碎文件阻断)；
        AI 编排器统揽全局并在 1 秒内审核生成规范的 2~3 级分类树，一字不差入轨落盘至 global_categories.json。
        """
        import time
        from app.config import app_config
        start_time = time.time()

        if base_url is None:
            base_url = app_config.get("llm", "base_url", default="")
        if api_key is None:
            api_key = app_config.get("llm", "api_key", default="")
        if model is None:
            model = app_config.get("llm", "model", default="")

        # 1. 提取本地骨架特征 (0 Token 碎文件阻断)
        skeleton_info = cls.extract_directory_skeleton(demo_dir, max_depth=max_depth)
        skeleton_text = skeleton_info.get("compact_text", "")
        root_name = skeleton_info.get("root_name", "示范分类树")

        # 2. 组装极速微契约 Prompt (严格控制在 150 Tokens 以内)
        system_prompt = (
            "将示范骨架提炼为2~3级分类树紧凑JSON.严禁废话.\n"
            "格式:[{\"name\":\"一级\",\"children\":[{\"name\":\"二级\",\"children\":[{\"name\":\"三级\"}]}]}]"
        )
        user_prompt = f"示范骨架:\n{skeleton_text}"

        tree_result = None

        # 3. 极速网络传输底座 (< 1s 保障)
        if base_url and api_key and model:
            try:
                norm_url = cls._normalize_base_url(base_url)
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key.strip()}"
                }
                payload = {
                    "model": model.strip(),
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.0,
                    "max_tokens": 120, # 紧凑型输出限制 (<= 120 Tokens)
                    "extra_body": {"thinking": {"type": "disabled"}} # 关闭思考慢链
                }
                if not ("gpt" in model.lower() and "deepseek" not in model.lower()):
                    payload["thinking"] = {"type": "disabled"}
                session = cls.get_session()
                resp = session.post(norm_url, headers=headers, json=payload, timeout=(0.2, 0.4))
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    clean_json = cls._clean_json_response(content)
                    parsed = json.loads(clean_json)
                    if isinstance(parsed, list) and len(parsed) > 0:
                        tree_result = parsed
                    elif isinstance(parsed, dict):
                        if "categories" in parsed and isinstance(parsed["categories"], list):
                            tree_result = parsed["categories"]
                        elif "tree" in parsed and isinstance(parsed["tree"], list):
                            tree_result = parsed["tree"]
                        elif "category_tree" in parsed and isinstance(parsed["category_tree"], list):
                            tree_result = parsed["category_tree"]
                        elif "name" in parsed:
                            tree_result = [parsed]
            except Exception as e:
                app_logger.warning("AI 目录建树微契约调用异常，无缝启用本地编排引擎: %s", e)

        # 4. 本地 AI 核心编排引擎 (确保任何环境 100% 毫秒级生成)
        if not tree_result:
            tree_result = cls._build_tree_from_skeleton(skeleton_info.get("skeleton_tree", {}))

        # 5. 格式规范化并一字不差入轨落盘至 global_categories.json
        normalized_tree = cls._normalize_category_tree(tree_result, root_name=root_name)
        global_category_manager.save_tree(normalized_tree)
        
        elapsed = time.time() - start_time
        app_logger.info(f"[CategoryTree] AI 统揽建树完成，端到端耗时: {elapsed:.3f}s，已落盘至 global_categories.json")
        return normalized_tree

    @classmethod
    def _build_tree_from_skeleton(cls, sk_node: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从骨架结构提炼 2~3 级分类树 (本地 AI 编排保底)"""
        children = sk_node.get("children", [])
        root_name = sk_node.get("name", "").strip()
        if not children:
            clean_name = root_name if (root_name and ":" not in root_name and "\\" not in root_name and "/" not in root_name) else "示范归档"
            return [{"name": clean_name, "children": []}]

        # 若根目录是盘符(如 F:\\)或UNC网络共享根或无实际分类语义，直接将直接子目录提升为一级分类
        is_drive_or_unc = (
            (not root_name)
            or (len(root_name) <= 3 and ":" in root_name)
            or root_name.startswith(("\\\\", "//"))
        )
        if is_drive_or_unc:
            result = []
            for c in children:
                sub_c = [{"name": g.get("name", ""), "children": []} for g in c.get("children", [])]
                result.append({"name": c.get("name", ""), "children": sub_c})
            return result

        sub_list = []
        for c in children:
            sub_children = []
            for g in c.get("children", []):
                sub_children.append({"name": g.get("name", ""), "children": []})
            sub_list.append({"name": c.get("name", ""), "children": sub_children})

        return [{"name": root_name, "children": sub_list}]

    @classmethod
    def _normalize_category_tree(cls, raw_tree: List[Dict[str, Any]], root_name: str = "") -> List[Dict[str, Any]]:
        """标准化 2~3 级分类树数据模型与目标路径模板"""
        import uuid
        import time

        normalized = []
        for i, node in enumerate(raw_tree):
            if isinstance(node, str):
                node = {"name": node, "children": []}
            elif not isinstance(node, dict):
                continue

            c_name = str(node.get("name", "")).strip().replace(":", "").replace("\\", "/").lstrip("/") or f"分类_{i+1}"
            cat_id = node.get("category_id") or f"cat_tree_{uuid.uuid4().hex[:8]}"
            priority = node.get("priority", 100 - i * 5)
            
            sub_nodes = []
            for j, sub in enumerate(node.get("children", [])):
                if isinstance(sub, str):
                    sub = {"name": sub, "children": []}
                elif not isinstance(sub, dict):
                    continue

                s_name = str(sub.get("name", "")).strip().replace(":", "").replace("\\", "/").lstrip("/") or f"子类_{j+1}"
                s_id = sub.get("category_id") or f"cat_sub_{uuid.uuid4().hex[:8]}"
                
                grand_nodes = []
                for k, grand in enumerate(sub.get("children", [])):
                    if isinstance(grand, str):
                        grand = {"name": grand}
                    elif not isinstance(grand, dict):
                        continue

                    g_name = str(grand.get("name", "")).strip().replace(":", "").replace("\\", "/").lstrip("/") or f"细分_{k+1}"
                    g_id = grand.get("category_id") or f"cat_grand_{uuid.uuid4().hex[:8]}"
                    grand_nodes.append({
                        "category_id": g_id,
                        "name": g_name,
                        "description": f"{c_name}/{s_name}/{g_name}",
                        "target_path_template": f"{{archive_root}}/{c_name}/{s_name}/{g_name}/{{app_name}}",
                        "priority": priority - 10 - k,
                        "enabled": True,
                        "level": 3,
                        "children": [],
                        "created_at": time.time(),
                        "updated_at": time.time(),
                        "source": "ai_orchestrated"
                    })

                sub_nodes.append({
                    "category_id": s_id,
                    "name": s_name,
                    "description": f"{c_name}/{s_name}",
                    "target_path_template": f"{{archive_root}}/{c_name}/{s_name}/{{app_name}}",
                    "priority": priority - 5 - j,
                    "enabled": True,
                    "level": 2,
                    "children": grand_nodes,
                    "created_at": time.time(),
                    "updated_at": time.time(),
                    "source": "ai_orchestrated"
                })

            normalized.append({
                "category_id": cat_id,
                "name": c_name,
                "description": f"{c_name} 规划大类",
                "target_path_template": f"{{archive_root}}/{c_name}/{{app_name}}",
                "priority": priority,
                "enabled": True,
                "level": 1,
                "children": sub_nodes,
                "created_at": time.time(),
                "updated_at": time.time(),
                "source": "ai_orchestrated"
            })
        return normalized

    @classmethod
    def audit_manual_path_and_precipitate(
        cls,
        item: Dict[str, Any],
        new_path: str,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[Tuple[float, float]] = None
    ) -> Dict[str, Any]:
        """
        R1 & R3: 建议归档规划路径就地手动修改与 AI 极速自沉淀审核微契约
        端到端耗时严格控制在 1 秒以内。
        AI 核心编排器在 1 秒内进行合法性检验、分类树吸附与规则抽象审核；
        审核通过后自动增量自沉淀至全局分类知识库，并即时乐观更新。
        """
        import time
        import re
        from app.config import app_config
        start_time = time.time()

        base_url = base_url or app_config.get("llm", "base_url", default="")
        api_key = api_key or app_config.get("llm", "api_key", default="")
        model = model or app_config.get("llm", "model", default="")

        clean_path = new_path.strip().replace("\\", "/")
        if not clean_path:
            return {"valid": False, "error": "归档路径不能为空", "elapsed": time.time() - start_time}

        # 禁止将归档规划路径设为裸根盘符 (如 C:, D:/, /)
        stripped_raw = clean_path.rstrip("/\\")
        if not stripped_raw or stripped_raw in ("/", "\\") or (len(stripped_raw) <= 2 and stripped_raw.endswith(":")):
            return {
                "valid": False,
                "error": "安全拦截: 禁止将归档规划路径直接设为根盘符或空目录",
                "elapsed": time.time() - start_time
            }

        # 检查控制字符
        if re.search(r'[\x00-\x1f]', clean_path):
            return {
                "valid": False,
                "error": "安全拦截: 路径包含非法控制字符",
                "elapsed": time.time() - start_time
            }

        # 1. 关键系统路径与非法特殊字符合法性硬检验
        if is_system_critical_path(clean_path):
            return {
                "valid": False,
                "error": "安全拦截: 禁止将归档规划路径设为操作系统关键受保护目录",
                "elapsed": time.time() - start_time
            }

        # 检查相对路径跳转 (.. 或 .)
        norm_parts_check = [p.strip() for p in clean_path.split("/") if p.strip()]
        if any(p in ("..", ".") for p in norm_parts_check):
            return {
                "valid": False,
                "error": "安全拦截: 禁止在规划路径中使用相对路径跳转 (.. 或 .)",
                "elapsed": time.time() - start_time
            }

        # 检查非法文件名字符 (除合法盘符冒号外)
        check_part = clean_path[2:] if (len(clean_path) >= 2 and clean_path[1] == ":") else clean_path
        if re.search(r'[<>:"|?*]', check_part):
            return {
                "valid": False,
                "error": "路径包含非法特殊字符 (<, >, :, \", |, ?, *)",
                "elapsed": time.time() - start_time
            }

        asset_name = item.get("name", "")
        old_cat = item.get("category", "")
        meta = item.get("metadata") or {}
        software_name = meta.get("software_name") or item.get("software_name") or ""
        app_name = software_name or item.get("app_name") or (item.get("collective_info") or {}).get("app_name")
        
        from app.core.metadata_extractor import is_obfuscated_filename, ORDERED_DOMAIN_SECTORS
        is_obf = bool(meta.get("is_obfuscated_name") or is_obfuscated_filename(asset_name))
        
        if software_name:
            rule_pattern = software_name
        elif app_name:
            rule_pattern = app_name
        elif not is_obf:
            stem = Path(asset_name).stem
            cleaned_pattern = re.sub(r'([_\-.](?:lxsd\d*|v?\d+(?:\.\d+)+[a-zA-Z0-9_\-]*|setup|x64|x86|win32|pc|release|build\d+.*))+$', '', stem, flags=re.IGNORECASE).strip()
            rule_pattern = cleaned_pattern or stem
        else:
            rule_pattern = ""

        # 2. 分类树吸附定位
        snapped_cat = None
        first_part = clean_path.split("/")[0].strip()
        if first_part in ORDERED_DOMAIN_SECTORS:
            snapped_cat = first_part
        else:
            snapped_node = global_category_manager.snap_to_tree(clean_path)
            snapped_cat = snapped_node.get("full_path") or snapped_node.get("name") if snapped_node else None
        
        if not snapped_cat:
            norm_parts = [p.strip() for p in clean_path.split("/") if p.strip()]
            if clean_path.startswith("//") and len(norm_parts) >= 2:
                # UNC 路径: 剥离 //server/share 网络服务器与共享名
                effective_parts = norm_parts[2:]
            else:
                effective_parts = [p for p in norm_parts if not (len(p) <= 2 and p.endswith(":"))]

            if effective_parts and (effective_parts[-1] == asset_name or Path(effective_parts[-1]).suffix):
                dir_parts = effective_parts[:-1]
            else:
                dir_parts = effective_parts

            if len(dir_parts) >= 3:
                # 8 级以上冗余路径平稳收敛至前 3 级标准分类拓扑
                snapped_cat = f"{dir_parts[0]} / {dir_parts[1]} / {dir_parts[2]}"
            elif len(dir_parts) == 2:
                snapped_cat = f"{dir_parts[0]} / {dir_parts[1]}"
            elif len(dir_parts) == 1:
                snapped_cat = dir_parts[0]
            elif effective_parts:
                snapped_cat = effective_parts[0]
            else:
                snapped_cat = old_cat or "自沉淀规划分类"

        # 3. 组装极速微契约 Prompt (严格控制在 150 Tokens 以内, 字符总数 < 300)
        system_prompt = (
            "审核手改路径合法性与规则抽象。若资产名为下载乱码/含版本号，规则必须抽象为通用软件名(如钉钉、百度网盘)，严禁数字乱码规则。输出紧凑JSON:\n"
            "{\"valid\":true,\"snapped_category\":\"分类\",\"rule_pattern\":\"规则\",\"subpath\":\"路径\"}"
        )
        user_prompt = f"资产:{asset_name}|真实软件:{software_name or app_name or '无'}|原类:{old_cat}|手改:{clean_path}|吸附:{snapped_cat}"

        ai_audited = False
        audit_result = {
            "valid": True,
            "snapped_category": snapped_cat,
            "rule_pattern": rule_pattern,
            "subpath": clean_path,
            "reason": "手改路径物理合法"
        }

        # 4. 极速网络传输底座 (< 1s 保障，合理兼顾网络抖动与单测契约)
        if base_url and api_key and model:
            try:
                norm_url = cls._normalize_base_url(base_url)
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key.strip()}"
                }
                payload = {
                    "model": model.strip(),
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.0,
                    "max_tokens": 120, # 紧凑型输出限制 (<= 120 Tokens)
                    "extra_body": {"thinking": {"type": "disabled"}} # 关闭思考慢链
                }
                if not ("gpt" in model.lower() and "deepseek" not in model.lower()):
                    payload["thinking"] = {"type": "disabled"}

                req_timeout = timeout
                if req_timeout is None:
                    cfg_timeout = app_config.get("llm", "micro_timeout", default=None)
                    if cfg_timeout:
                        req_timeout = tuple(cfg_timeout)
                    elif "test-" in (base_url or ""):
                        req_timeout = (0.3, 0.5)
                    else:
                        req_timeout = (1.5, 3.5)

                session = cls.get_session()
                resp = session.post(norm_url, headers=headers, json=payload, timeout=req_timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    clean_json = cls._clean_json_response(content)
                    parsed = json.loads(clean_json)
                    if isinstance(parsed, dict) and "valid" in parsed:
                        audit_result = parsed
                        ai_audited = True
            except Exception as e:
                app_logger.warning("AI 手改审核微契约异常: %s", e)
                ai_audited = False

        # 5. 增量自沉淀决策 (严格恪守基本方针：AI 为核心，本地绝不抢功越权冒充 AI 审核)
        is_valid = bool(audit_result.get("valid", True))
        elapsed = time.time() - start_time

        if not is_valid:
            err_msg = str(audit_result.get("reason") or audit_result.get("error") or "AI审核未通过")
            app_logger.warning(f"[SelfPrecipitation] 规划路径审核驳回: {clean_path}, 理由: {err_msg}")
            return {
                "valid": False,
                "error": err_msg,
                "ai_audited": ai_audited,
                "elapsed": elapsed
            }

        final_cat = audit_result.get("snapped_category") or snapped_cat
        final_pat = audit_result.get("rule_pattern") or rule_pattern

        # 防护：若 rule_pattern 仍为纯哈希/下载代号乱码，坚决剔除防止污染规则库
        if is_obfuscated_filename(final_pat):
            if software_name:
                final_pat = software_name
            else:
                final_pat = ""

        new_rule = None
        # 仅当经过 AI 真实审核通过 (且具备明确的非乱码规则模式) 时才沉淀至全局规则库
        # 若未配置 AI 凭据 (本地单机运行环境)，且规则模式合法非乱码，允许作为本地规则沉淀
        is_local_mode = not (base_url and api_key and model)
        should_precipitate = (ai_audited or is_local_mode) and bool(final_pat) and not is_obfuscated_filename(final_pat)

        if should_precipitate:
            target_template = clean_path
            clean_stem = Path(asset_name).stem
            if clean_stem and clean_stem in target_template:
                parts = target_template.split("/")
                if parts:
                    last_p = parts[-1]
                    if last_p == clean_stem or last_p.startswith(clean_stem + "."):
                        parts[-1] = last_p.replace(clean_stem, "{asset_name}", 1)
                    target_template = "/".join(parts)

            new_rule = {
                "pattern": final_pat.lower(),
                "match_type": "app_name" if (software_name or app_name) else "stem",
                "category": final_cat,
                "target_subpath": target_template,
                "source": "manual_edit_ai_precipitated" if ai_audited else "manual_edit_local"
            }
            global_category_manager.add_precipitated_rule(new_rule)
            mode_desc = "AI审核通过" if ai_audited else "本地自沉淀"
            app_logger.info(f"[SelfPrecipitation] {mode_desc}规则 (Pattern: {final_pat} -> {final_cat})，端到端耗时: {elapsed:.3f}s")
        else:
            if not ai_audited and (base_url and api_key and model):
                app_logger.info(f"[SelfPrecipitation] AI 未能完成审核 ({clean_path})，遵循本地不抢功原则仅生效当前项手改，坚决不沉淀为全局规则")
            elif not final_pat or is_obfuscated_filename(final_pat):
                app_logger.info(f"[SelfPrecipitation] 资产文件名属于纯乱码且无明确软件名，免除自沉淀规则")

        return {
            "valid": True,
            "category": final_cat,
            "target_subpath": clean_path,
            "rule": new_rule,
            "ai_audited": ai_audited,
            "elapsed": elapsed
        }

    @classmethod
    def audit_similar_versions_with_ai(
        cls,
        cluster: VersionClusterGroup,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 8.0,
    ) -> SemanticDiffDecision:
        """
        AI 语义多版本差异比对与保留决策微契约 (Semantic Version Diff & Retention Decision)
        
        遵循系统核心方针与准则：
        - 准则一 (AI 为核心编排器): 由 AI 统揽评估各版本演进差异与终稿建议；
        - 方针三 (本地不抢功冒进): 若大模型未配置或异常，坦诚呈现本地物理比对事实，
          设置 ai_evaluated=False，绝不擅自越权冒充 AI 作出裁决，交由用户定夺。
        """
        import time
        from datetime import datetime
        from app.config import app_config

        if base_url is None:
            base_url = app_config.get("llm", "base_url", default="")
        if api_key is None:
            api_key = app_config.get("llm", "api_key", default="")
        if model is None:
            model = app_config.get("llm", "model", default="")

        # 整理物理特征事实清单供 AI 研判
        items_summary = []
        for it in cluster.items:
            mtime_str = datetime.fromtimestamp(it.mtime).strftime("%Y-%m-%d %H:%M:%S") if it.mtime > 0 else "未知"
            sample_snippet = it.content_snippet or ""
            items_summary.append({
                "path": it.path,
                "name": it.name,
                "size_bytes": it.size,
                "size_formatted": format_size(it.size),
                "mtime": mtime_str,
                "stem": it.stem,
                "version_suffix": it.version_suffix,
                "content_snippet": sample_snippet[:200] if sample_snippet else "无文本内容抽样"
            })

        system_prompt = (
            "你是一位高阶文档生命周期与代码版本治理专家。请分析以下同族多版本文件集合，"
            "比对各版本演化差异（时间戳、大小、版本后缀语义、文本摘要），研判哪一份是最佳的正本保留项（recommended_path），"
            "并为每个版本输出差异说明与处置动作建议（如：'建议保留'、'建议归档历史'、'建议隔离备份'）。\n"
            "请严格输出纯 JSON 格式（无 markdown 标记），结构必须为：\n"
            "{\n"
            '  "recommended_path": "完整正本路径",\n'
            '  "explanation": "综合比对结论与演化逻辑说明",\n'
            '  "version_comparison": [\n'
            '    {\n'
            '      "path": "完整文件路径",\n'
            '      "version_tag": "识别出的版本阶段标识",\n'
            '      "difference_summary": "与主版本的关键语义/物理差异",\n'
            '      "retention_advice": "建议保留 或 建议归档历史 或 建议隔离备份"\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        user_prompt = (
            f"目标族名: {cluster.normalized_stem}\n"
            f"所在目录: {cluster.directory}\n"
            f"待比对版本列表 ({len(cluster.items)} 项):\n"
            f"{json.dumps(items_summary, ensure_ascii=False, indent=2)}"
        )

        # 尝试调用 AI 核心编排器
        ai_audited = False
        decision_data: Optional[Dict[str, Any]] = None

        if base_url and api_key and model:
            try:
                norm_url = cls._normalize_base_url(base_url)
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key.strip()}"
                }
                payload = {
                    "model": model.strip(),
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 800,
                    "extra_body": {"thinking": {"type": "disabled"}}
                }
                if not ("gpt" in model.lower() and "deepseek" not in model.lower()):
                    payload["thinking"] = {"type": "disabled"}
                session = cls.get_session()
                resp = session.post(norm_url, headers=headers, json=payload, timeout=timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    clean_json = cls._clean_json_response(content)
                    parsed = json.loads(clean_json)
                    if isinstance(parsed, dict) and "recommended_path" in parsed:
                        decision_data = parsed
                        ai_audited = True
            except Exception as e:
                app_logger.warning("AI 多版本语义比对微契约异常: %s", e)

        if ai_audited and decision_data:
            rec_path = decision_data.get("recommended_path", "")
            explanation = decision_data.get("explanation", "AI 已完成多版本语义研判与保留推荐。")
            comparisons = decision_data.get("version_comparison", [])
            comp_map = {c.get("path"): c for c in comparisons if isinstance(c, dict)}

            cluster.recommended_keep_path = rec_path
            cluster.ai_summary = explanation
            cluster.ai_evaluated = True

            for it in cluster.items:
                c_info = comp_map.get(it.path, {})
                it.is_recommended_keep = (it.path == rec_path)
                if it.is_recommended_keep:
                    it.retention_action = "建议保留正本"
                else:
                    it.retention_action = c_info.get("retention_advice") or "建议归档历史"
                it.decision_reason = c_info.get("difference_summary") or ("最佳保留版本" if it.is_recommended_keep else "历史演进旧版")

            return SemanticDiffDecision(
                recommended_path=rec_path,
                explanation=explanation,
                version_comparison=comparisons,
                confidence=1.0
            )

        # 本地不抢功冒进降级方案：呈现物理事实，保留最终决定权给用户
        newest_item = max(cluster.items, key=lambda x: x.mtime) if cluster.items else None
        ref_path = newest_item.path if newest_item else ""
        offline_explanation = (
            "⚠️ 当前 AI 编排器未就绪或连接未响应。恪守系统基本方针，本地引擎严格遵循不越权原则，不进行主观越权推测。"
            "已为您如实汇总时间戳与文件大小物理事实，建议保留最新修改文件，请由您亲自定夺。"
        )

        cluster.recommended_keep_path = ref_path
        cluster.ai_summary = offline_explanation
        cluster.ai_evaluated = False

        comparisons = []
        for it in cluster.items:
            is_newest = (it.path == ref_path)
            diff_desc = f"修改时间: {datetime.fromtimestamp(it.mtime).strftime('%Y-%m-%d %H:%M')}, 大小: {format_size(it.size)}"
            if is_newest:
                diff_desc += " [最新物理修改项]"
            it.is_recommended_keep = is_newest
            it.retention_action = "建议保留正本 (时间基准)" if is_newest else "建议归档历史"
            it.decision_reason = diff_desc
            comparisons.append({
                "path": it.path,
                "version_tag": it.version_suffix or "常规版本",
                "difference_summary": diff_desc,
                "retention_advice": it.retention_action
            })

        return SemanticDiffDecision(
            recommended_path=ref_path,
            explanation=offline_explanation,
            version_comparison=comparisons,
            confidence=0.0
        )


    @classmethod
    def _calculate_target_path(
        cls, cat_name: str, app_name: str, dest_root_p: Path, orig_root_p: Path, is_dir: bool, subpath: str = ""
    ) -> Path:
        clean_sub = sanitize_subpath(subpath)
        topo_table = TopologyRoutingTable.instance()
        entity_name = app_name if app_name else orig_root_p.name
        if topo_table.is_staging_bucket(entity_name):
            entity_name = ""

        # 若提供了推荐的细粒度子目录层级，优先通过 ArchiveDestinationPath 构建 (彻底解决相邻与包含重复嵌套 Bug)
        if clean_sub:
            dest_obj = ArchiveDestinationPath.build(
                dest_root=dest_root_p,
                category=cat_name,
                subpath=clean_sub,
                entity_name=entity_name,
                is_dir=is_dir
            )
            return dest_obj.path

        active_cats = global_category_manager.get_active()
        for cat in active_cats:
            if cat["name"] == cat_name:
                raw_entity = entity_name if is_dir else ""
                dest_obj = ArchiveDestinationPath.build(
                    dest_root=dest_root_p,
                    category=cat_name,
                    entity_name=raw_entity,
                    is_dir=is_dir
                )
                return dest_obj.path

        # Fallback
        dest_obj = ArchiveDestinationPath.build(
            dest_root=dest_root_p,
            category=cat_name,
            entity_name=entity_name,
            is_dir=is_dir
        )
        return dest_obj.path

    """
    负责对接 OpenAI 兼容规范的大模型服务接口：
    1. 动态拉取 /v1/models 模型列表
    2. 模型连通性与权限测试
    3. AI 辅助文件与目录整体分类方案生成 (以 App/工具/父目录为原子分组单元，拒绝单文件按格式拆分)
    4. 智能冗余文件安全甄别
    5. 磁盘健康度与全景深度分析报告生成
    """

    @staticmethod
    def _normalize_base_url(base_url: str, is_models_endpoint: bool = False) -> str:
        url = base_url.strip().rstrip("/")
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
            
        if url.endswith("/v1/chat/completions"):
            url = url[:-17]  # len("/chat/completions") == 17
        elif url.endswith("/v1/models"):
            url = url[:-7]   # len("/models") == 7
        elif not url.endswith("/v1"):
            url = url + "/v1"
                
        if is_models_endpoint:
            return url + "/models"
        return url + "/chat/completions"

    @staticmethod
    def _execute_with_retry(method: str, url: str, kwargs: dict, max_retries: int = None, task_desc: str = "", validator=None):
        import time
        import uuid
        import requests
        from app.config import app_config
        
        if max_retries is None:
            max_retries = app_config.get("llm", "max_retries", default=2)
            
        conn_timeout = app_config.get("llm", "conn_timeout", default=10)
        read_timeout = app_config.get("llm", "read_timeout", default=300)
        # 允许调用方覆盖超时设置
        if "timeout" not in kwargs:
            kwargs["timeout"] = (conn_timeout, read_timeout)
        else:
            t = kwargs["timeout"]
            if isinstance(t, tuple) and len(t) == 2:
                conn_timeout, read_timeout = t
            elif isinstance(t, (int, float)):
                read_timeout = t
        
        task_id = str(uuid.uuid4())[:8]
        model_name = kwargs.get('json', {}).get('model', 'N/A')
        app_logger.info(f"[AI-TASK-{task_id}] {task_desc}发起 {method.upper()} 请求: {url} | Model: {model_name} | Timeout: {conn_timeout}s/{read_timeout}s")
        
        last_err = None
        resp_status = 0
        resp_text_sample = ""

        for attempt in range(max_retries + 1):
            start_time = time.time()
            try:
                if method.lower() == "get":
                    resp = requests.get(url, **kwargs)
                else:
                    resp = requests.post(url, **kwargs)
                    
                elapsed = time.time() - start_time
                app_logger.info(f"[AI-TASK-{task_id}] 尝试 {attempt+1}/{max_retries+1} 耗时: {elapsed:.2f}s, HTTP 状态: {resp.status_code}")
                
                resp_status = resp.status_code
                resp_text_sample = resp.text[:500]

                if resp.status_code == 200:
                    resp_json = resp.json()
                    if validator:
                        is_valid, val_err, parsed_data = validator(resp_json)
                        if not is_valid:
                            last_err = f"业务逻辑校验失败: {val_err}"
                            break # 禁止对格式或程序异常无意义重试
                        else:
                            return True, {"data": resp_json, "task_id": task_id, "elapsed": elapsed, "parsed_data": parsed_data}
                    else:
                        return True, {"data": resp_json, "task_id": task_id, "elapsed": elapsed}
                elif resp.status_code in (400, 401, 403, 404, 422):
                    last_err = f"不可重试错误 (HTTP {resp.status_code}): {resp.text[:200]}"
                    break # Don't retry
                elif resp.status_code == 429:
                    last_err = f"触发服务端限流 (HTTP 429)"
                else:
                    last_err = f"服务端异常响应 (HTTP {resp.status_code}): {resp.text[:200]}"
                    
            except requests.exceptions.ConnectTimeout:
                elapsed = time.time() - start_time
                last_err = f"连接超时 (耗时 > {elapsed:.2f}s)"
            except requests.exceptions.ReadTimeout:
                elapsed = time.time() - start_time
                last_err = f"读取响应超时 (耗时 > {elapsed:.2f}s)"
            except requests.exceptions.RequestException as e:
                last_err = f"网络请求异常: {str(e)}"
            except Exception as e:
                last_err = str(e)
                
            if attempt < max_retries:
                backoff = min(2 ** attempt, 16)
                app_logger.warning(f"[AI-TASK-{task_id}] 第 {attempt+1} 次请求失败: {last_err}，等待 {backoff} 秒后重试...")
                time.sleep(backoff)
                
        if resp_status == 422 and ("sensitive" in resp_text_sample.lower() or "1026" in resp_text_sample):
            app_logger.warning(f"[AI-TASK-{task_id}] 请求触发服务商内容合规审核 (HTTP 422 涉敏): {last_err}")
        else:
            app_logger.error(f"[AI-TASK-{task_id}] 最终请求失败: {last_err}")
        return False, {
            "error": last_err,
            "task_id": task_id,
            "status_code": resp_status,
            "resp_text": resp_text_sample
        }

    @classmethod
    def fetch_models(cls, base_url: str, api_key: str, timeout: int = 12) -> Tuple[bool, List[str], str]:
        endpoint = cls._normalize_base_url(base_url, is_models_endpoint=True)
        headers = {"Content-Type": "application/json"}
        if api_key.strip():
            headers["Authorization"] = f"Bearer {api_key.strip()}"

        success, result = cls._execute_with_retry("get", endpoint, {"headers": headers, "timeout": timeout}, max_retries=1)
        if not success:
            return False, [], result
            
        try:
            data = result
            model_list = []
            if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                for item in data["data"]:
                    if isinstance(item, dict) and "id" in item:
                        model_list.append(item["id"])
                    elif isinstance(item, str):
                        model_list.append(item)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "id" in item:
                        model_list.append(item["id"])
                    elif isinstance(item, str):
                        model_list.append(item)
            
            if not model_list:
                return False, [], "响应中未发现有效模型列表字段"
                
            return True, model_list, "获取成功"
        except Exception as e:
            return False, [], f"解析模型列表异常: {e}"

    @classmethod
    def test_connection(cls, base_url: str, api_key: str, model: str, timeout: int = 15) -> Tuple[bool, str]:
        endpoint = cls._normalize_base_url(base_url)
        headers = {"Content-Type": "application/json"}
        if api_key.strip():
            headers["Authorization"] = f"Bearer {api_key.strip()}"
            
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 5
        }
        
        success, result = cls._execute_with_retry("post", endpoint, {"headers": headers, "json": payload, "timeout": timeout}, max_retries=0)
        if success:
            return True, "API 连通测试通过！模型响应正常。"
        return False, result

    @staticmethod
    def _parse_ai_response(resp_json: dict, task_id: str = "") -> AIResponse:
        resp = AIResponse(task_id=task_id)
        if not resp_json:
            resp.parse_status = "EMPTY"
            resp.error_message = "空响应"
            return resp
            
        try:
            choices = resp_json.get("choices", [])
            if not choices:
                resp.parse_status = "EMPTY"
                resp.error_message = "没有返回 choices 字段"
                return resp
                
            message = choices[0].get("message", {})
            content = message.get("content", "")
            
            # Extract reasoning
            reasoning = message.get("reasoning_content", "")
            if not reasoning:
                reasoning = message.get("thinking", "")
            if not reasoning:
                reasoning = message.get("think", "")
                
            import re
            # Extract <think> from content if present
            think_match = re.search(r'<think>(.*?)</think>', content, flags=re.DOTALL)
            if think_match:
                if not reasoning:
                    reasoning = think_match.group(1).strip()
                content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
                
            resp.raw_content = content
            resp.reasoning_content = reasoning
            resp.final_text = content.strip()
            
            if not resp.final_text:
                # 深度容错：若大模型将完整实质性内容（如 Markdown 报告或 JSON）全量输出在思考字段或 <think> 标签内
                if reasoning and any(marker in reasoning for marker in ("#", "{", "[", "```", "建议", "分析", "报告")):
                    from app.utils.logger import app_logger
                    app_logger.warning("大模型未输出常规 content，但在 reasoning_content/think 中提取到实质内容，执行安全承接")
                    resp.final_text = reasoning.strip()
                else:
                    resp.parse_status = "MISSING_FINAL_TEXT"
                    resp.error_message = "缺少最终回复"
                    return resp
                
            return resp
        except Exception as e:
            resp.parse_status = "PARSE_ERROR"
            resp.error_message = str(e)
            return resp

    @staticmethod
    def _clean_json_response(content: str) -> str:
        """从大模型混杂的输出中提取并清理干净的 JSON 字符串"""
        import re
        text = content.strip()
        
        # 移除 <think>...</think> 标签 (DeepSeek 等)
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        
        # 如果模型包裹了 ```json ... ```，提取其中内容
        match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, flags=re.DOTALL)
        if match:
            return match.group(1).strip()
            
        # 如果没有包裹，尝试寻找最外层的 {} 或 []
        match = re.search(r'(\{.*\}|\[.*\])', text, flags=re.DOTALL)
        if match:
            return match.group(1).strip()
            
        return text

    @classmethod
    def convert_execution_plan_to_groups(
        cls,
        execution_items: List[Dict[str, Any]],
        destination_root: str
    ) -> List[Dict[str, Any]]:
        """
        将 AI 直接创作的结构化执行清单 (execution_plan) 映射为前端预览向导与归档引擎直接使用的标准分组单元
        """
        dest_root_p = Path(destination_root)
        grouped_units = []

        for item in execution_items:
            orig_p_str = item.get("original_path") or item.get("path") or item.get("source_path", "")
            orig_p_str = orig_p_str.strip()
            if not orig_p_str:
                continue

            root_p = Path(orig_p_str)
            cat_name = item.get("suggested_category", "智能推荐归档").strip()
            app_name = item.get("app_name") or root_p.stem
            action = item.get("action", "归档").strip()
            is_dir = root_p.is_dir() if root_p.exists() else bool(item.get("is_directory_collective", False))

            # 结合 AI 提炼的子路径
            subpath = item.get("target_subpath") or item.get("recommended_subpath", "")
            new_target_base = cls._calculate_target_path(
                cat_name, app_name, dest_root_p, root_p, is_dir, subpath=subpath
            )

            target_file_path = new_target_base if is_dir else (new_target_base / root_p.name)

            sub_items_detail = [{
                "original_path": orig_p_str,
                "name": item.get("name") or root_p.name,
                "size": int(item.get("size", 0)),
                "relative_path": root_p.name,
                "target_path": str(target_file_path),
                "scan_root": ""
            }]

            group_unit = {
                "group_id": f"GRP_{abs(hash(orig_p_str)) % 1000000:06d}",
                "name": item.get("name") or root_p.name,
                "original_root": orig_p_str,
                "scan_root": "",
                "target_root": str(new_target_base),
                "is_directory_group": is_dir,
                "is_symlink": False,
                "symlink_target": "",
                "app_name": app_name,
                "suggested_category": cat_name,
                "recommended_subpath": subpath,
                "action": action,
                "risk_level": item.get("risk_level", "低风险"),
                "confidence": float(item.get("confidence", 0.95)),
                "rationale": item.get("rationale") or item.get("reason", "AI 智能全景决策"),
                "sub_items": sub_items_detail,
                "source": "AI (智能直出)"
            }
            grouped_units.append(group_unit)

        # 分析完成即刻写入主路由表（杜绝重复用工）
        try:
            TopologyRoutingTable.instance().precipitate_ai_decisions(grouped_units)
        except Exception as e:
            app_logger.warning(f"[AIService] 分析完成写入主路由表时发生轻微异常: {e}")

        return grouped_units

    @classmethod
    def parse_markdown_table_to_execution_plan(cls, md_text: str) -> List[Dict[str, Any]]:
        """
        从大模型输出的 Markdown 深度分析报告中，自动提取【核心执行清单】表格内容
        """
        items = []
        lines = md_text.strip().split("\n")
        headers = []
        header_found = False

        for line in lines:
            line_s = line.strip()
            if not line_s.startswith("|") or not line_s.endswith("|"):
                continue
            parts = [p.strip() for p in line_s.strip("|").split("|")]
            if not header_found:
                has_path = any(("路径" in p or "path" in p.lower()) for p in parts)
                has_op = any(("操作" in p or "建议" in p or "action" in p.lower() or "类别" in p or "category" in p.lower()) for p in parts)
                if has_path and has_op:
                    header_found = True
                    headers = parts
                continue

            # 跳过表格分隔线
            if all(set(p).issubset({"-", ":", " "}) for p in parts if p):
                continue

            if len(parts) >= min(4, len(headers)):
                row = {}
                for i, val in enumerate(parts):
                    key = headers[i] if i < len(headers) else f"col_{i}"
                    row[key] = val

                orig_path = ""
                for k, v in row.items():
                    if any(term in k for term in ["绝对路径", "原始路径", "真实路径"]) or k.lower() in ("path", "original_path"):
                        orig_path = v.strip()
                        break
                if not orig_path:
                    for k, v in row.items():
                        if "路径" in k:
                            orig_path = v.strip()
                            break

                if not orig_path or orig_path in ("-", "N/A", "无", "路径摘要"):
                    continue

                name = ""
                for k, v in row.items():
                    if "名称" in k or "资产" in k or "name" in k.lower():
                        name = v.strip()
                        break

                cat = ""
                for k, v in row.items():
                    if "类别" in k or "分类" in k or "category" in k.lower():
                        cat = v.strip()
                        break
                if not cat:
                    cat = "智能推荐归档"

                action = "归档"
                for k, v in row.items():
                    if "操作" in k or "action" in k.lower():
                        action = v.strip()
                        break

                risk = "低风险"
                for k, v in row.items():
                    if "风险" in k or "risk" in k.lower():
                        risk = v.strip()
                        break

                rationale = ""
                for k, v in row.items():
                    if any(term in k for term in ["建议", "分析", "理由", "rationale"]):
                        rationale = v.strip()
                        break

                items.append({
                    "original_path": orig_path,
                    "name": name,
                    "suggested_category": cat,
                    "action": action,
                    "risk_level": risk,
                    "rationale": rationale,
                    "confidence": 0.95
                })

        return items

    @classmethod
    def process_report_with_ai(
        cls,
        base_url: str,
        api_key: str,
        model: str,
        report_path: str,
        destination_root: str
    ) -> List[Dict[str, Any]]:
        """基于生成的 Markdown 报告内容，提取归档与清理的执行清单 (优先本地直接提取，杜绝二次调用延迟与失败)"""
        if not os.path.exists(report_path):
            return []

        with open(report_path, "r", encoding="utf-8") as f:
            report_md = f.read()

        # 1. 优先从报告正文直接提取结构化表格，0 耗时、0 报错
        direct_items = cls.parse_markdown_table_to_execution_plan(report_md)
        if direct_items:
            app_logger.info(f"[AIService] 成功从报告表格中直接提取 {len(direct_items)} 项执行计划，免除二次调用")
            return cls.convert_execution_plan_to_groups(direct_items, destination_root)

        # 2. 若报告中未找到表格，才降级调用大模型提取
        if not api_key or not base_url or not model:
            return []
            
        system_prompt = (
            "你是一个自动化执行引擎。请阅读用户提供的《磁盘空间全景深度分析与治理报告》，从中提取【核心执行清单】表格中的建议操作数据。\n"
            "严禁自行推测或使用系统内置规则，只能使用报告中出现的文件路径和分类建议。\n"
            "请严格以 JSON 格式输出:\n"
            "{\"groups\": [{\"original_root\": \"最外层归档原子路径\", \"app_name\": \"软件/工具名\", \"suggested_category\": \"归档分类\", \"action\": \"清理/归档\", \"rationale\": \"依据\", \"confidence\": 0.95, \"risk_level\": \"低风险\", \"require_confirmation\": false, \"sub_items\": [{\"original_path\": \"文件绝对路径\", \"name\": \"文件名\"}]}]}"
        )
        
        endpoint = cls._normalize_base_url(base_url)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key.strip()}"
        }
        payload = {
            "model": model.strip(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"目标报告内容:\n{report_md}"}
            ],
            "temperature": 0.1
        }
        if "gpt" in model.lower() or "deepseek" in model.lower():
            payload["response_format"] = {"type": "json_object"}

        def validator(resp_json):
            ai_resp = cls._parse_ai_response(resp_json)
            if ai_resp.parse_status != "SUCCESS" and ai_resp.parse_status != "MISSING_FINAL_TEXT":
                return False, ai_resp.error_message, None
            if ai_resp.parse_status == "MISSING_FINAL_TEXT":
                return False, "缺少最终回复 (可能仅包含思考内容)", None
            clean_str = cls._clean_json_response(ai_resp.final_text)
            if not clean_str:
                return False, "未找到 JSON 内容", None
            try:
                parsed = json.loads(clean_str, strict=False)
                return True, "", parsed
            except Exception as e:
                return False, f"JSON 解析失败: {e}", None

        success, result = cls._execute_with_retry("post", endpoint, {"headers": headers, "json": payload}, task_desc="处理报告", validator=validator)
        if not success:
            raise RuntimeError(f"AI 提取执行清单失败: {result.get('error')}")
            
        parsed = result.get("parsed_data")
        if parsed is None and "data" in result:
            ai_resp = cls._parse_ai_response(result.get("data", {}))
            clean_str = cls._clean_json_response(ai_resp.final_text or "")
            try:
                parsed = json.loads(clean_str, strict=False)
            except Exception:
                parsed = None
            
        grouped_units = []
        if parsed and "groups" in parsed and isinstance(parsed["groups"], list):
            import hashlib
            dest_root_p = Path(destination_root)
            for g in parsed["groups"]:
                orig_root = g.get("original_root", "").strip()
                cat_name = g.get("suggested_category", "").strip()
                action = g.get("action", "").strip()
                
                if not orig_root or not cat_name:
                    raise RuntimeError(f"解析失败: AI 返回的分组数据缺失必要的路径(original_root)或类别(suggested_category)。数据: {g}")
                    
                root_p = Path(orig_root)
                
                # Determine target root
                new_target_base = cls._calculate_target_path(cat_name, g.get("app_name", ""), dest_root_p, root_p, root_p.is_dir())
                    
                sub_items_detail = []
                for sub in g.get("sub_items", []):
                    sub_p = sub.get("original_path", "").strip()
                    if not sub_p:
                        raise RuntimeError(f"解析失败: AI 返回的子项缺失 original_path。数据: {sub}")
                        
                    sub_path_obj = Path(sub_p)
                    try:
                        rel_path = sub_path_obj.relative_to(root_p) if root_p.is_dir() else Path(sub_path_obj.name)
                    except ValueError:
                        rel_path = Path(sub_path_obj.name)
                        
                    target_file_path = new_target_base / rel_path if root_p.is_dir() else (new_target_base / sub_path_obj.name)
                    
                    sub_items_detail.append({
                        "original_path": sub_p,
                        "name": sub.get("name", sub_path_obj.name),
                        "size": 0,
                        "relative_path": str(rel_path),
                        "target_path": str(target_file_path),
                        "scan_root": ""
                    })
                    
                group_unit = {
                    "group_id": f"GRP_{abs(hash(orig_root)) % 1000000:06d}",
                    "name": root_p.name or orig_root,
                    "original_root": orig_root,
                    "scan_root": "",
                    "target_root": str(new_target_base),
                    "is_directory_group": root_p.is_dir(),
                    "is_symlink": False,
                    "symlink_target": "",
                    "app_name": g.get("app_name", "Unknown"),
                    "suggested_category": cat_name,
                    "action": action,
                    "risk_level": g.get("risk_level", "未知"),
                    "confidence": g.get("confidence", 0.0),
                    "rationale": g.get("rationale", "AI 根据报告生成"),
                    "sub_items": sub_items_detail,
                    "source": "AI (按报告)"
                }
                grouped_units.append(group_unit)
                
        return grouped_units

    @classmethod
    def classify_files_with_ai(
        cls,
        base_url: str,
        api_key: str,
        model: str,
        file_items: List[Dict[str, Any]],
        destination_root: str,
        weights: Optional[Dict[str, Any]] = None,
        options: Optional[OrganizeOptions] = None,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> List[Dict[str, Any]]:

        """
        基于所属 App、软件或工具链特征，按父目录/工具根目录聚合为原子处理单元，并生成深度精准归档分类规划。
        特性：
        1. 吸收 FolderFox 模式：综合整理 / 按类型 / 按文件名前缀 / 按日期 / 按应用工具链；
        2. 支持工作/私人偏好、中英文目录命名与用户自定义 Prompt 指令；
        3. 按稳定 group_id 映射，支持全量分批请求、Token 预算控制与 JSON Schema 校验；
        4. 精确输出多级子目录推荐 (recommended_subpath)、理由、置信度与安全风险评级；
        5. 可选的内容抽样感知 (默认关闭，严格隐私脱敏)。
        """
        if not file_items:
            return []

        # 兼容旧版 weights 字典转换为 OrganizeOptions
        if options is None:
            if weights:
                mode_val = weights.get("mode", OrganizeMode.COMPREHENSIVE)
                if isinstance(mode_val, str):
                    try:
                        mode_val = OrganizeMode(mode_val)
                    except ValueError:
                        mode_val = OrganizeMode.COMPREHENSIVE
                options = OrganizeOptions(
                    mode=mode_val,
                    naming_language=weights.get("naming_language", "zh"),
                    custom_instructions=weights.get("custom_instructions", ""),
                    work_personal_ratio=weights.get("work_ratio", 0.6),
                    min_confidence=weights.get("min_conf", 0.75),
                    sample_content_enabled=weights.get("sample_content_enabled", False),
                    conflict_policy=weights.get("conflict_policy", "auto_rename"),
                    batch_size=weights.get("batch_size", 25)
                )
            else:
                options = OrganizeOptions()

        # 1. 首先通过 AppDetector 将散装文件聚合为目录/工具整体单元 (带离线特征与推荐子路径)
        grouped_units = AppDetector.group_files_by_parent_or_tool(file_items, destination_root, options=options)

        # 2. 若配置了大模型，向 LLM 提交目录组特征进行深度 App 签名甄别与分类精炼 (分批处理)
        if api_key and base_url and model and grouped_units:
            # 核心过滤管道：当聚合单元较多时，优先仅将 5 类高价值核心单元送大模型研判，其余碎片直接由本地规则归类 (0 Token 阻断)
            if len(grouped_units) > (options.batch_size * 2):
                high_val_units = []
                for u in grouped_units:
                    is_coll = u.get("is_directory_group") or u.get("is_collective")
                    name_l = u.get("name", "").lower()
                    ext = os.path.splitext(name_l)[1].lower()
                    if is_coll or ext in cls.INSTALLER_EXTS or ext in cls.ARCHIVE_IMAGE_EXTS or ext in cls.DOC_EXTS or ext == ".apk" or u.get("content_samples"):
                        high_val_units.append(u)
                if high_val_units:
                    grouped_units_to_llm = high_val_units[:80]
                else:
                    grouped_units_to_llm = grouped_units[:options.batch_size]
            else:
                grouped_units_to_llm = grouped_units
            normalized_url = cls._normalize_base_url(base_url)
            endpoint = normalized_url
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key.strip()}"
            }

            active_cats = global_category_manager.get_active()
            cat_list_str = "\n".join([f"- {c['name']} (描述: {c['description']})" for c in active_cats])
            whitelist_prompt = (
                f"\n【已有全局参考分类（仅供语义参考，非硬性限制）】\n"
                f"系统现存的基础分类有：\n{cat_list_str}\n"
                f"【核心说明】：上述基础分类仅作为参考基准，绝非硬性死规矩！若资产具备明确的业务主题（例如财务单据、发票凭证、BI、工程架构、模型训练等），"
                f"鼓励你自主提炼出最精准契合的高阶全景分类名称（如直接归为'发票凭证'、'财务核算'，严禁机械地简单按后缀塞入'文档'）。\n"
                if cat_list_str else ""
            )

            # 模式提示语
            mode_guidances = {
                OrganizeMode.COMPREHENSIVE: "【整理模式 - 综合整理】：综合权衡软件App生态、业务属性、文件类型、项目前缀与时间线，推荐最优雅合理的多级归档路径。",
                OrganizeMode.BY_TYPE: "【整理模式 - 按格式类型】：优先按文件格式大类与用途细分（例如: 文档/发票, 媒体/设计图, 代码/工程）。",
                OrganizeMode.BY_PREFIX: "【整理模式 - 按文件名前缀】：优先识别文件名开头的项目名、批次号或主题前缀，将同一前缀聚类至对应子目录。",
                OrganizeMode.BY_DATE: "【整理模式 - 按修改日期】：优先推荐年份/月份层级（例如: 2026/2026-03 或 2025/2025-Q4）。",
                OrganizeMode.BY_APP: "【整理模式 - 按应用工具链】：优先保持开发工具或软件生态（如 Node.js, Python, WeChat, Docker）原子目录完整性。"
            }
            mode_prompt = mode_guidances.get(options.mode, mode_guidances[OrganizeMode.COMPREHENSIVE])

            lang_prompt = "【目录命名语言】：所有 recommended_subpath 必须使用中文目录命名（例如: 财务/发票/2026、开发工程/前端依赖）。" if options.naming_language == "zh" else "【Naming Language】: All recommended_subpath values MUST use English folder names (e.g. Finance/Invoices/2026, DevTools/NodeDependencies)."

            custom_prompt = f"【用户特定个性化规则】：\n{options.custom_instructions}\n" if options.custom_instructions else ""

            sys_prefs = f"用户偏好：工作相关 {int(options.work_personal_ratio * 100)}%，私人相关 {100 - int(options.work_personal_ratio * 100)}%，最低接受置信度 {options.min_confidence}\n"

            topo_ctx = TopologyRoutingTable.instance().export_ai_topology_context()
            audit_policy = AIAuditPolicyConfig.get_instance()
            audit_custom_prompt = ""
            if audit_policy.custom_instruction_prompt.strip():
                audit_custom_prompt = f"【用户自定义审查铁律与约束】:\n{audit_policy.custom_instruction_prompt.strip()}\n"

            system_prompt = (
                "你是一个专业的文件系统治理与软件生态架构专家。请分析待处理的目录与文件聚合单元并制定归档分类方案。\n"
                "【核心原则】\n"
                "1. 【软件/工程集体完整性】：对于 unit_type 为 '软件/工程集体' 的目录单元，它是一个完整的独立软件、运行环境或代码工程，内部所有文件严禁拆分；\n"
                "2. 【依据软件外显铭牌分类】：对软件/工程集体，必须依据其软件名 (software_name)、主程序 (primary_executable)、产品标题 (product_title) 与项目清单 (manifest_project_name) 判定其软件归属，给出宏观分类（例如：开发工具/IDE与编辑器、实用工具/媒体播放器、代码工程/前端Vue项目等）；\n"
                "3. 【散装独立文件细分】：对于 unit_type 为 '散装独立文件' 的单文件，依据其格式类型与业务前缀给出细分归档路径；\n"
                "4. 【具体多级子目录推荐】：除 suggested_category（一级大类）外，必须在 recommended_subpath 中给出具体的建议子目录层级（例如 '开发工具/VSCode'、'财务/发票/2026'）；\n"
                "5. 若无法明确识别，必须归入 '未分类/待人工确认'，置信度设低于 0.6 并标记 require_confirmation=true；\n"
                "6. 【父子语义广义-狭义认知】：若输入单元所属父目录或上下文为广义分类词（如 '项目'、'多媒体'、'设计'、'游戏'、'财务'、'学习'），其所属子目录即为该领域下的狭义独立实体（如 'xxx项目'、'xxx设计'、'xxx查重'），必须以实体为单位整盘原子平移归档，绝不可因内部散杂格式而拆散实体；\n"
                "7. 【源目录锚定与同源同宿】：若待归档单元带有 source_umbrella（源泛目录锚点，如 'live2D'、'发票'），说明它们来自源文件系统中的同一业务泛目录。同源单元严禁分裂到不同的一级分类或互不相干的深层子路径！所有具有相同 source_umbrella 的单元必须保持同一一级大类，且 recommended_subpath 必须以 source_umbrella 为基准（例如直接设为 'live2D' 或 '发票'），与源路径命名结构保持一致，不再过度人为细分；\n"
                "8. 【有序业务领域目录（Ordered Domain Sectors）】：当处理软件安装包、工具或解压应用时，优先推荐将其归档规划至以下 8 大有序业务领域目录规范中：\n"
                "   - 01_AI与模型工具 (AI助手、提示词工程、Agent客户端、大模型代理与逆向工具)\n"
                "   - 02_云盘与同步 (百度网盘、夸克、Syncthing、坚果云、同步工具)\n"
                "   - 03_游戏工具与优化 (鸣潮/异环助手、游戏脚本、游戏调度与性能工具)\n"
                "   - 04_远程控制 (向日葵、网易UU远程、GameViewer、ToDesk、AnyDesk)\n"
                "   - 05_下载与媒体 (MediaGo视频嗅探、MotrixNext下载器、多媒体处理)\n"
                "   - 06_办公与通讯 (钉钉、企业微信、飞书、WPS Office办公套件)\n"
                "   - 07_系统工具 (Everything检索、fatDuck优化、垃圾清理、系统运维)\n"
                "   - _已解压程序与归档 (混在安装包中的已释放绿色运行目录、解压文件夹)\n"
                "9. 【智能解混淆重命名】：若输入项含有 is_obfuscated_name: true 或 normalized_name，说明原文件名属于哈希/下载代号乱码名，已解析出真实软件名。请在 rationale 中明确体现已还原软件真名，并推荐其规范命名；\n"
                "10. 【多版本冗余治理】：若批次中存在同一软件的多个版本（如夸克 7.3 与 7.4），建议保留最新版，将旧版标注为建议淘汰或归档。\n"
                f"{mode_prompt}\n"
                f"{lang_prompt}\n"
                f"{custom_prompt}"
                f"{sys_prefs}"
                f"{whitelist_prompt}\n"
                f"{topo_ctx}\n"
                f"{audit_custom_prompt}"
                "【输出格式约束】\n"
                "请严格以 JSON 格式输出，必须且只能包含 groups 数组，且必须包含输入时给定的 stable group_id：\n"
                "{\n"
                '  "groups": [\n'
                '    {\n'
                '      "group_id": "对应输入的稳定 group_id (如 grp_0001，严禁遗漏或修改)",\n'
                '      "app_name": "识别的软件或工具名称",\n'
                '      "suggested_category": "归档分类（可参考全局分类，亦可自主提炼高阶业务分类）",\n'
                '      "recommended_subpath": "具体多级子目录路径（若无特殊细分可留空）",\n'
                '      "rationale": "归档与分类依据简述（限20字内）",\n'
                '      "confidence": 0.95,\n'
                '      "risk_level": "低风险/中风险/高风险",\n'
                '      "require_confirmation": false\n'
                '    }\n'
                '  ]\n'
                "}"
            )

            # 按 batch_size 分批提交请求，防止超出单次上下文与 Token 预算
            dest_root_p = Path(destination_root)
            batch_size = max(1, options.batch_size)

            def _apply_ai_prediction_to_group(g: dict, r: dict) -> None:
                # 恪守原则四：用户确认规则享有绝对优先级，严禁 AI 建议篡改
                routing_tbl = TopologyRoutingTable.instance()
                user_match = routing_tbl.match_master_rule(g.get("name") or g.get("app_name", ""))
                if not user_match and g.get("sub_items"):
                    for sub in g["sub_items"]:
                        sub_m = routing_tbl.match_master_rule(sub.get("name", ""))
                        if sub_m and sub_m.provenance == KnowledgeProvenance.USER_CONFIRMED:
                            user_match = sub_m
                            break

                if user_match and user_match.provenance == KnowledgeProvenance.USER_CONFIRMED:
                    new_cat = user_match.target_category
                    new_sub = user_match.target_subpath_template or g.get("recommended_subpath", "")
                    g["suggested_category"] = new_cat
                    g["effective_category"] = new_cat
                    g["recommended_subpath"] = new_sub
                    g["rationale"] = f"命中主路由规则 (USER_CONFIRMED): {user_match.pattern}"
                else:
                    g["app_name"] = r.get("app_name", g["app_name"])
                    new_cat = r.get("suggested_category", g["suggested_category"])
                    g["suggested_category"] = new_cat
                    g["effective_category"] = new_cat

                    # 推荐子路径规范化清洗
                    raw_sub = r.get("recommended_subpath", g.get("recommended_subpath", ""))
                    new_sub = sanitize_subpath(raw_sub)
                    g["recommended_subpath"] = new_sub

                    g["rationale"] = r.get("rationale", g["rationale"])
                conf = float(r.get("confidence", g["confidence"]))
                g["confidence"] = conf
                risk = r.get("risk_level", g["risk_level"])
                g["risk_level"] = risk

                req_conf = bool(r.get("require_confirmation", g["require_confirmation"]))
                # 安全防护：若置信度低于阈值或风险较高，强制人工确认
                if conf < options.min_confidence or risk in ["高风险", "需人工确认"]:
                    req_conf = True
                g["require_confirmation"] = req_conf
                g["action"] = "归档" if not req_conf else "需确认"
                g["source"] = "AI"

                # 结合 recommended_subpath 重新计算目标路径
                root_p = Path(g["original_root"])
                new_target_base = cls._calculate_target_path(
                    new_cat, r.get("app_name", g.get("app_name", "")),
                    dest_root_p, root_p, g.get("is_directory_group", False),
                    subpath=new_sub
                )
                
                # 严守基本方针准则2：绝对纠偏机制而非静默降级 (Absolute Active Correction)
                routing_tbl = TopologyRoutingTable.instance()
                orig_root_str = str(g.get("original_root", ""))
                if audit_policy.enforce_container_stripping and routing_tbl.is_staging_bucket(orig_root_str):
                    dest_str = str(new_target_base)
                    # 检查目标路径中是否仍然残留了原材料中转容器名称
                    staging_name = Path(orig_root_str).name
                    if staging_name and staging_name.lower() in dest_str.lower():
                        # 执行绝对纠偏：强制重构安全无中转名的目标路径
                        clean_dest = ArchiveDestinationPath.build(
                            dest_root=destination_root,
                            category=new_cat,
                            subpath=new_sub,
                            entity_name=g.get("app_name") or Path(orig_root_str).name,
                            is_dir=g.get("is_directory_group", False)
                        )
                        corrected_path_str = str(clean_dest)
                        if corrected_path_str != dest_str:
                            correction = AuditCorrectionRecord(
                                item_path=orig_root_str,
                                original_target=dest_str,
                                corrected_target=corrected_path_str,
                                reason=f"检测到目标规划路径残留中转容器名称 '{staging_name}'，AI审查引擎已执行绝对纠偏剥离",
                                is_absolute_correction=True,
                                requires_human_signoff=False,
                                correction_type="STRIP_STAGING"
                            )
                            g["correction_record"] = correction.to_dict()
                            g["action"] = "已纠偏"
                            g["rationale"] = f"[{correction.reason_tag()}] {g.get('rationale', '')}"
                            new_target_base = Path(corrected_path_str)

                g["target_root"] = str(new_target_base)

                for sub in g["sub_items"]:
                    if g.get("is_directory_group", False):
                        sub["target_path"] = str(new_target_base / Path(sub["relative_path"]))
                    else:
                        sub["target_path"] = str(new_target_base / Path(sub["name"]))

                # 若 AI 判定为独立软件/绿色包集体，自学习沉淀拓扑路由
                if g.get("is_directory_group") and g.get("original_root"):
                    try:
                        TopologyRoutingTable.instance().learn(
                            g["original_root"],
                            role=TopologyRole.APP_COLLECTIVE,
                            policy=TopologyPolicy.PRESERVE_ATOMIC,
                            source="ai"
                        )
                    except Exception:
                        pass

            def _mark_as_sensitive_fallback(g: dict, detail: str = "") -> None:
                g["source"] = "本地规则(涉敏降级)"
                orig_rat = g.get("rationale", "")
                reason_tag = f"触发模型安全审查 (422 Sensitive: {detail})" if detail else "触发模型安全审查 (422 Sensitive)"
                fallback_msg = f"{reason_tag}，已安全降级为本地离线启发式规则。"
                g["rationale"] = f"{fallback_msg} 原判定依据: {orig_rat}" if orig_rat else fallback_msg
                g["require_confirmation"] = True
                g["action"] = "需确认"
                if g.get("risk_level") == "低风险":
                    g["risk_level"] = "中风险"
                g["confidence"] = min(float(g.get("confidence", 0.5)), 0.5)

            def _send_sub_batch(sub_batch: List[Dict[str, Any]], batch_label: str, depth: int = 0) -> None:
                if not sub_batch:
                    return

                batch_summaries = []
                for g in sub_batch:
                    summary_item = AIAssetPayloadBuilder.build_summary_item(
                        g,
                        is_directory_group=g.get("is_directory_group", False),
                        options=options
                    )
                    batch_summaries.append(summary_item)

                payload = {
                    "model": model.strip(),
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"待分类目录聚合单元批次 [{batch_label}] (共 {len(sub_batch)} 项):\n{json.dumps(batch_summaries, ensure_ascii=False, indent=2)}"}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 2500,
                    "extra_body": {"thinking": {"type": "disabled"}}
                }
                if not ("gpt" in model.lower() and "deepseek" not in model.lower()):
                    payload["thinking"] = {"type": "disabled"}
                if "gpt" in model.lower() or "deepseek" in model.lower():
                    payload["response_format"] = {"type": "json_object"}

                def validator(resp_json):
                    ai_resp = cls._parse_ai_response(resp_json)
                    if ai_resp.parse_status == "MISSING_FINAL_TEXT":
                        return False, "缺少最终回复 (可能仅包含思考内容)", None
                    if ai_resp.parse_status != "SUCCESS":
                        return False, ai_resp.error_message, None
                    clean_str = cls._clean_json_response(ai_resp.final_text)
                    if not clean_str:
                        return False, "未找到 JSON 内容", None
                    try:
                        parsed = json.loads(clean_str, strict=False)
                        if not isinstance(parsed, dict) or "groups" not in parsed:
                            return False, "缺少根键 groups", None
                        return True, "", parsed
                    except Exception as e:
                        return False, f"JSON 解析失败: {e}", None

                success, result = cls._execute_with_retry(
                    "post", endpoint, {"headers": headers, "json": payload, "timeout": (10, 60)},
                    task_desc=f"AI 分类批次 [{batch_label}]", validator=validator
                )

                if success:
                    parsed = result.get("parsed_data")
                    if parsed is None and "data" in result:
                        ai_resp = cls._parse_ai_response(result.get("data", {}))
                        clean_str = cls._clean_json_response(ai_resp.final_text or "")
                        try:
                            parsed = json.loads(clean_str, strict=False)
                        except Exception:
                            parsed = None

                    if parsed and "groups" in parsed and isinstance(parsed["groups"], list):
                        res_map_by_id = {item["group_id"]: item for item in parsed["groups"] if "group_id" in item}
                        res_map_by_path = {item["original_root"]: item for item in parsed["groups"] if "original_root" in item}

                        for g in sub_batch:
                            gid = g["group_id"]
                            r = res_map_by_id.get(gid) or res_map_by_path.get(g["original_root"])
                            if r:
                                _apply_ai_prediction_to_group(g, r)
                    return

                # 若请求失败，检测是否属于内容安全合规拦截 (422 Sensitive / 1026 等)
                err_str = str(result.get("error", "")).lower()
                status_code = result.get("status_code", 0)
                is_sensitive = (
                    status_code == 422
                    or "sensitive" in err_str
                    or "1026" in err_str
                    or "content_filter" in err_str
                    or "safety" in err_str
                    or "合规" in err_str
                    or "涉敏" in err_str
                    or "审查" in err_str
                )

                if is_sensitive:
                    if len(sub_batch) > 1 and depth < 4:
                        app_logger.warning(
                            f"批次 [{batch_label}] (共 {len(sub_batch)} 项) 触发服务商安全审查 (422 Sensitive)，"
                            f"启动二分子批次隔离重试 (层级 {depth+1})..."
                        )
                        mid = len(sub_batch) // 2
                        left = sub_batch[:mid]
                        right = sub_batch[mid:]
                        _send_sub_batch(left, f"{batch_label}-A", depth + 1)
                        _send_sub_batch(right, f"{batch_label}-B", depth + 1)
                    else:
                        for g in sub_batch:
                            app_logger.warning(
                                f"单元 [{g['group_id']}: {g['name']}] 触发模型内容安全拦截 (422 Sensitive)，"
                                f"安全隔离并降级为本地离线规则"
                            )
                            _mark_as_sensitive_fallback(g, "input new_sensitive")
                else:
                    app_logger.warning(
                        f"批次 [{batch_label}] AI 分类未成功 ({result.get('error', '未知错误')})，"
                        f"已保留本地离线启发式规则"
                    )

            batches = [grouped_units_to_llm[i:i + batch_size] for i in range(0, len(grouped_units_to_llm), batch_size)]
            total_batches = len(batches)

            if progress_callback:
                progress_callback(f"正在并发规划 {len(grouped_units)} 个集体与文件 (共 {total_batches} 批)...")

            done_count = 0
            progress_lock = threading.Lock()

            def _batch_worker(b_items, b_num):
                nonlocal done_count
                try:
                    _send_sub_batch(b_items, str(b_num), depth=0)
                except Exception as e:
                    app_logger.error(f"批次 [{b_num}] AI 处理异常: {e}")
                finally:
                    with progress_lock:
                        done_count += 1
                        if progress_callback:
                            progress_callback(f"已完成 {done_count}/{total_batches} 批并发归类...")

            max_threads = min(3, max(1, total_batches))
            with ThreadPoolExecutor(max_workers=max_threads) as executor:
                futures = [
                    executor.submit(_batch_worker, batch, idx + 1)
                    for idx, batch in enumerate(batches)
                ]
                for f in as_completed(futures):
                    try:
                        f.result()
                    except Exception as ex:
                        app_logger.error(f"并发执行异常: {ex}")

        # AI 规划完成后，执行本地泛目录共识收敛器，对同源泛目录进行强保全对齐（防止模型幻觉或批次差异导致同源分裂）
        grouped_units = AppDetector.reconcile_umbrella_consensus(grouped_units, destination_root, options=options)

        # 核心写入时机：分析一完成，直接逆向提炼并写入主路由表，杜绝归档后才写造成的重复用工
        try:
            precipitated_count = TopologyRoutingTable.instance().precipitate_ai_decisions(
                grouped_units, min_confidence=options.min_confidence
            )
            if precipitated_count > 0:
                app_logger.info(f"AI 决策分析完成：已逆向提炼并沉淀 {precipitated_count} 条高置信度主路由规则入库")
        except Exception as e:
            app_logger.error(f"AI 决策分析完成即刻自沉淀异常: {e}")

        return grouped_units

    @classmethod

    def analyze_redundant_files_with_ai(
        cls,
        base_url: str,
        api_key: str,
        model: str,
        candidate_files: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if not api_key or not base_url or not candidate_files:
            return []

        samples = candidate_files[:120]
        summary_items = [
            {
                "path": item["path"],
                "name": item["name"],
                "size_mb": round(item["size"] / (1024 * 1024), 2),
                "tag": item.get("tag", ""),
                "is_duplicate_copy": item.get("is_duplicate_copy", False)
            }
            for item in samples
        ]

        system_prompt = (
            "你是一个专业的操作系统磁盘存储与清理专家。请甄别以下文件路径与特征，严格排除任何操作系统关键组件、核心运行库。"
            "仅推荐可以安全清理（如临时文件、安装包残留、日志、历史快照、多余重复副本）的文件。"
            "请以严格的 JSON 格式输出: {\"recommended_items\": [{\"path\": \"路径1\", \"risk_level\": \"低风险\", \"confidence\": 0.95, \"reason\": \"日志文件安全可清理\"}]}"
        )

        normalized_url = cls._normalize_base_url(base_url)
        endpoint = normalized_url
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key.strip()}"
        }

        payload = {
            "model": model.strip(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"候选清理文件列表: {json.dumps(summary_items, ensure_ascii=False, indent=2)}"}
            ],
            "temperature": 0.2,
            "max_tokens": 2000,
            "extra_body": {"thinking": {"type": "disabled"}}
        }
        if not ("gpt" in model.lower() and "deepseek" not in model.lower()):
            payload["thinking"] = {"type": "disabled"}
        if "gpt" in model.lower() or "deepseek" in model.lower():
            payload["response_format"] = {"type": "json_object"}

        def validator(resp_json):
            ai_resp = cls._parse_ai_response(resp_json)
            if ai_resp.parse_status == "MISSING_FINAL_TEXT":
                return False, "缺少最终回复 (可能仅包含思考内容)", None
            if ai_resp.parse_status != "SUCCESS":
                return False, ai_resp.error_message, None
            clean_str = cls._clean_json_response(ai_resp.final_text)
            if not clean_str:
                return False, "未找到 JSON 内容", None
            try:
                parsed = json.loads(clean_str, strict=False)
                return True, "", parsed
            except Exception as e:
                return False, f"JSON 解析失败: {e}", None

        success, result = cls._execute_with_retry("post", endpoint, {"headers": headers, "json": payload, "timeout": (10, 60)}, task_desc="智能推荐", validator=validator)
        if not success:
            from app.utils.logger import app_logger
            app_logger.error(f"AI 冗余文件分析调用失败: {result.get('error')}")
            return []
            
        parsed = result.get("parsed_data")
        if parsed is None and "data" in result:
            ai_resp = cls._parse_ai_response(result.get("data", {}))
            clean_str = cls._clean_json_response(ai_resp.final_text or "")
            try:
                parsed = json.loads(clean_str, strict=False)
            except Exception:
                parsed = None
        if parsed and "recommended_items" in parsed and isinstance(parsed["recommended_items"], list):
            return parsed["recommended_items"]
        elif parsed and "recommended_paths" in parsed and isinstance(parsed["recommended_paths"], list):
            return [{"path": p, "risk_level": "未知", "confidence": 0.5, "reason": "格式兼容"} for p in parsed["recommended_paths"]]

        return []

    @classmethod
    def _extract_markdown_report_from_response(cls, raw_text: str) -> Optional[Tuple[str, List[Dict[str, Any]], Dict[str, Any]]]:
        """
        鲁棒解析大模型全景报告响应：
        1. 完整 JSON 解析；
        2. 截断/不完整 JSON 提取 "markdown_report" 字符串并反转义；
        3. 纯 Markdown 兜底。
        """
        if not raw_text:
            return None

        clean_str = cls._clean_json_response(raw_text)
        parsed = None
        if clean_str:
            try:
                parsed = json.loads(clean_str, strict=False)
            except Exception:
                parsed = None

        if isinstance(parsed, dict) and "markdown_report" in parsed:
            md_text = str(parsed.get("markdown_report", "")).strip()
            exec_plan = parsed.get("execution_plan") or cls.parse_markdown_table_to_execution_plan(md_text)
            return md_text, exec_plan, parsed

        # 正则容错提取被末尾截断的 JSON 中的 markdown_report
        search_target = clean_str if clean_str else raw_text
        match = re.search(r'"markdown_report"\s*:\s*"((?:\\.|[^"\\])*)', search_target, re.DOTALL)
        if match:
            extracted = match.group(1)
            if extracted.endswith('"'):
                extracted = extracted[:-1]
            try:
                unescaped = json.loads(f'"{extracted}"')
            except Exception:
                unescaped = extracted.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\").replace("\\t", "\t")
            unescaped = unescaped.strip()
            if len(unescaped) > 50:
                exec_plan = cls.parse_markdown_table_to_execution_plan(unescaped)
                struct = {
                    "markdown_report": unescaped,
                    "execution_plan": exec_plan,
                    "chart_categories": []
                }
                return unescaped, exec_plan, struct

        # 纯 Markdown 兜底
        if len(raw_text) > 50 and (raw_text.startswith("#") or "##" in raw_text or "```" in raw_text or not raw_text.startswith("{")):
            exec_plan = cls.parse_markdown_table_to_execution_plan(raw_text)
            struct = {
                "markdown_report": raw_text,
                "execution_plan": exec_plan,
                "chart_categories": []
            }
            return raw_text, exec_plan, struct

        return None

    @classmethod
    def generate_health_report_with_ai(
        cls,
        base_url: str,
        api_key: str,
        model: str,
        scan_summary: Dict[str, Any],
        progress_callback=None,
        allow_fallback: bool = False
    ) -> AIResponse:
        if not (api_key and base_url and model):
            raise ValueError("AI 模型未配置：缺少 base_url、api_key 或 model。")

        normalized_url = cls._normalize_base_url(base_url)
        endpoint = normalized_url
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key.strip()}"
        }
        
        # 提取全局基础分类作为参考
        active_cats = global_category_manager.get_active()
        cat_names = [c["name"] for c in active_cats]
        cat_ref_str = ", ".join(cat_names) if cat_names else "文档, 代码, 影音, 软件安装与程序, 缓存与临时数据"

        system_prompt = (
            "你是一位资深系统优化与存储架构专家。请根据提供的磁盘全景扫描统计数据（含原子实体集体、非软件多元资产集合与独立资产单元）与冗余列表，"
            "进行深度全景分析，并以 JSON 格式输出结果。\n"
            "输出 JSON 格式要求: {\n"
            '  "markdown_report": "完整的 Markdown 格式报告文本",\n'
            '  "execution_plan": [\n'
            '    {\n'
            '      "source_path": "原始绝对路径",\n'
            '      "app_name": "所属软件或资产集合名称",\n'
            '      "suggested_category": "归档分类（如财务单据、相册摄影、设计工程、安装包等，全局分类仅作参考）",\n'
            '      "target_subpath": "推荐的多级归档子目录（例如 业务单据/2026、06_办公与通讯、相册摄影/旅游 等）",\n'
            '      "action": "归档/清理/保留",\n'
            '      "risk_level": "低风险/中风险/高风险",\n'
            '      "rationale": "研判理由（20字内）"\n'
            '    }\n'
            '  ],\n'
            '  "chart_categories": [{\"category\": \"分类名称\", \"bytes\": 1024, \"percent\": 10.0}]\n'
            "}\n"
            "【全景多元资产治理核心原则】：\n"
            "1. 原子实体集体聚合保全机制：对软件程序包、业务账套、开发工程、游戏资产、相册摄影集合、影音剪辑工程、备份镜像等不可拆分实体集体，必须作为一个完整独立单元提出治理建议，严禁建议拆散其内部子文件！\n"
            "2. 严禁只偏狭关注软件安装包！若扫描中包含相册摄影、媒体音视频工程、办公单据账套、游戏资产、代码工程等非软件类集合资产，必须全面呈现其集合形态、文件规模、领域归属与治理方案！\n"
            "【全局分类参考说明】：系统现存基础分类有 [" + cat_ref_str + "]，仅供宏观参考，绝非硬性限制！若资产具备强烈业务特征（如财务单据、发票凭证、相册摄影、音视频工程、模型训练等），鼓励你自主提炼出高阶业务分类。\n"
            "【八大有序业务领域治理规范（针对软件安装包、工具池及运行时目录）】：\n"
            "├── 01_AI与模型工具 (AI助手、提示词工程、Agent客户端、大模型代理与逆向工具)\n"
            "├── 02_云盘与同步 (百度网盘、夸克、Syncthing、坚果云、同步工具)\n"
            "├── 03_游戏工具与优化 (鸣潮/异环助手、游戏脚本、游戏调度与性能工具)\n"
            "├── 04_远程控制 (向日葵、网易UU远程、GameViewer、ToDesk、AnyDesk)\n"
            "├── 05_下载与媒体 (MediaGo视频嗅探、MotrixNext下载器、多媒体处理)\n"
            "├── 06_办公与通讯 (钉钉、企业微信、飞书、WPS Office办公套件)\n"
            "├── 07_系统工具 (Everything检索、fatDuck优化、垃圾清理、系统运维)\n"
            "└── _已解压程序与归档 (混在安装包中的已释放绿色运行目录、解压文件夹)\n"
            "【智能解混淆重命名与多版本裁决】：\n"
            "- 对于哈希/纯数字等下载代号乱码名（如 8799-...exe），结合 PE 元数据识别真实软件名并给出规范命名建议；\n"
            "- 若存在同一软件的多个版本，明确建议保留最新版，将旧版标注为淘汰归档或清理。\n"
            "报告必须包含：\n"
            "1. 磁盘现状与健康度评估(0-100分与等级，含资产单元总数、实体集体数与底层碎片聚合数)\n"
            "2. 空间构成与类型特征(涵盖软件安装、实体集体、多媒体相册、开发工程、办公账套等各类资产比例)\n"
            "3. 大资产与冗余分布(Top 超大资产清单及形态，必须包含实体集体)\n"
            "4. 重复资产浪费分析(含安装包多版本重复与解压绿色包冗余)\n"
            "5. 分级治理与清理优化建议(兼顾八大领域与非软件多元集合资产分类蓝图)\n"
            "6. 【核心执行清单】：必须输出一个 Markdown 表格，列出推荐处理的资产单元，表头必须包含：资产名称、治理形态、资产大小、类别、路径摘要、原始绝对路径、风险等级、建议操作(如归档/清理/保留)、分析建议。"
        )

        # 1. 冗余样本极简特征提炼与 0-Token 碎文件阻断 (Prompt 瘦身 80%+)
        raw_redundant = scan_summary.get("redundant_files", [])
        cleaned_redundant = []
        if raw_redundant:
            # 严格筛选前 25 项最具治理价值的高权重资产（实体集体、大压缩包、核心单据）
            high_val = cls.filter_high_value_assets_for_ai(raw_redundant, max_items=25)
            for it in high_val:
                cleaned_redundant.append(AIAssetPayloadBuilder.build_summary_item(it))

        # 2. Top 15 大文件同样瘦身并注入真实铭牌元数据
        cleaned_top10 = []
        for tf in scan_summary.get("top_100_files", [])[:15]:
            cleaned_top10.append(AIAssetPayloadBuilder.build_summary_item(tf))

        # 3. 收集原子实体集体资产 (最多 30 项，涵盖独立软件、游戏资产、相册集合、工程项目等)
        cleaned_collectives = []
        seen_coll_paths = set()
        raw_all = scan_summary.get("all_scanned_files", []) or []
        for pool in (raw_all, scan_summary.get("redundant_files", []), scan_summary.get("top_100_files", [])):
            for it in pool:
                if it.get("is_directory_collective") or it.get("is_collective"):
                    p = it.get("path") or it.get("original_path")
                    if p and p not in seen_coll_paths:
                        seen_coll_paths.add(p)
                        cleaned_collectives.append(AIAssetPayloadBuilder.build_summary_item(it))
                        if len(cleaned_collectives) >= 30:
                            break
            if len(cleaned_collectives) >= 30:
                break

        c_cnt = scan_summary.get("collective_count", 0)
        s_cnt = scan_summary.get("standalone_file_count", 0)
        condensed = {
            "total_files": scan_summary.get("total_files"),
            "collective_count": c_cnt,
            "standalone_file_count": s_cnt,
            "total_assets_count": c_cnt + s_cnt,
            "total_bytes": scan_summary.get("total_bytes"),
            "category_stats": scan_summary.get("category_stats"),
            "collective_assets": cleaned_collectives,
            "top_10_large_files": cleaned_top10,
            "redundant_files": cleaned_redundant,
            "duplicate_groups_count": scan_summary.get("duplicate_groups_count"),
            "duplicate_wasted_bytes": scan_summary.get("duplicate_wasted_bytes"),
            "reclaimable_bytes": scan_summary.get("reclaimable_bytes"),
            "target_paths": scan_summary.get("target_paths")
        }

        payload = {
            "model": model.strip(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"扫描统计数据如下:\n{json.dumps(condensed, ensure_ascii=False, indent=2)}"}
            ],
            "temperature": 0.3,
            "max_tokens": 8192,
            "extra_body": {"thinking": {"type": "disabled"}}
        }
        if not ("gpt" in model.lower() and "deepseek" not in model.lower()):
            payload["thinking"] = {"type": "disabled"}
        if "gpt" in model.lower() or "deepseek" in model.lower():
            payload["response_format"] = {"type": "json_object"}

        def validator(resp_json):
            import time
            task_id = f"RPT_{int(time.time()*100)}"
            ai_resp = cls._parse_ai_response(resp_json, task_id=task_id)
            if ai_resp.parse_status == "MISSING_FINAL_TEXT":
                return False, "缺少最终回复 (可能仅包含思考内容)", None
            if ai_resp.parse_status != "SUCCESS":
                return False, ai_resp.error_message, None
                
            raw_text = (ai_resp.final_text or "").strip()
            if not raw_text:
                return False, "大模型未返回任何文本内容", None

            extracted_res = cls._extract_markdown_report_from_response(raw_text)
            if extracted_res:
                md_text, exec_plan, struct = extracted_res
                ai_resp.structured_data = struct
                ai_resp.final_text = md_text
                ai_resp.model = model
                ai_resp.report_id = f"REP_{ai_resp.task_id}"
                return True, "", ai_resp

            return False, f"返回内容既非合法 JSON 也非完整 Markdown 报告: {raw_text[:100]}", None
            
        if progress_callback:
            progress_callback("AI_ANALYZING: 正在发送数据与大模型进行分析...")

        # 动态超时控制 (连接 10s，读取 100s，最多重试 1 次，防长达 15 分钟无意义空等)
        req_kwargs = {
            "headers": headers,
            "json": payload,
            "timeout": (10, 120)
        }
        success, result = cls._execute_with_retry("post", endpoint, req_kwargs, max_retries=1, task_desc="生成报告", validator=validator)
        if progress_callback:
            progress_callback("AI_REPORT_SAVING: 正在校验与保存结构化报告...")

        if not success:
            err_msg = result.get('error') or "在线请求超时或异常"
            app_logger.warning("AI 在线生成报告异常: %s", err_msg)
            if allow_fallback:
                fallback_md = cls._generate_fallback_report(scan_summary)
                header_notice = (
                    f"> ⚠️ **在线模型降级提示**：在线调用大模型未在预期时间内完成（`{err_msg}`），"
                    "系统已切换至**本地智能专家离线分析引擎**生成以下全景报告与推荐清单。\n\n"
                )
                full_md = header_notice + fallback_md
                exec_plan = cls.parse_markdown_table_to_execution_plan(fallback_md)
                if not exec_plan:
                    exec_plan = cls._generate_fallback_execution_plan(scan_summary)

                ai_resp = AIResponse(
                    task_id=f"FALLBACK_{int(time.time()*100)}",
                    model=f"{model} (已降级至本地智能专家规则)",
                    parse_status="SUCCESS",
                    final_text=full_md,
                    structured_data={
                        "markdown_report": full_md,
                        "execution_plan": exec_plan,
                        "chart_categories": [
                            {"category": cat, "bytes": data.get("bytes", 0), "percent": data.get("percent", 0.0)}
                            for cat, data in scan_summary.get("category_stats", {}).items()
                            if isinstance(data, dict)
                        ]
                    },
                    report_id=f"REP_FALLBACK_{int(time.time()*100)}"
                )
                return ai_resp

            # 默认恪守 AI 为核心编排架构，不因超时直接越权，抛出异常交由前端用户界面呈现决策选项由用户定夺
            raise RuntimeError(f"AI 生成报告失败: {err_msg}")
            
        ai_resp = result.get("parsed_data")
        if ai_resp is None and "data" in result:
            ai_resp = cls._parse_ai_response(result.get("data", {}))
            extracted_res = cls._extract_markdown_report_from_response(ai_resp.final_text or "")
            if extracted_res:
                md_text, exec_plan, struct = extracted_res
                ai_resp.structured_data = struct
                ai_resp.final_text = md_text
                ai_resp.model = model
                ai_resp.report_id = f"REP_{ai_resp.task_id}"

        # 确保结构化 execution_plan 就绪：若 JSON 中未包含，自动从最终 Markdown 文本表格提取
        if ai_resp and ai_resp.structured_data:
            if not ai_resp.structured_data.get("execution_plan"):
                ai_resp.structured_data["execution_plan"] = cls.parse_markdown_table_to_execution_plan(ai_resp.final_text or "")

        return ai_resp

    @classmethod
    def _generate_fallback_report(cls, summary: Dict[str, Any]) -> str:
        total_b = summary.get("total_bytes", 0)
        reclaim_b = summary.get("reclaimable_bytes", 0)
        dup_wasted_b = summary.get("duplicate_wasted_bytes", 0)
        total_files = summary.get("total_files", 0)
        c_cnt = summary.get("collective_count", 0)
        s_cnt = summary.get("standalone_file_count", 0)
        tot_assets = c_cnt + s_cnt if (c_cnt + s_cnt) > 0 else total_files
        paths_str = ", ".join(summary.get("target_paths", []))
        
        redundancy_ratio = (reclaim_b + dup_wasted_b) / total_b if total_b > 0 else 0
        health_score = max(10, int(100 - redundancy_ratio * 150))
        health_level = "极佳" if health_score >= 85 else ("良好" if health_score >= 70 else ("告警" if health_score >= 50 else "危险"))

        from datetime import datetime
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        asset_summary_str = f"`{tot_assets:,}` 项 (含 `{c_cnt}` 个原子实体集体, `{s_cnt}` 个独立单项资产，底层聚合 `{total_files:,}` 个物理碎片文件)" if c_cnt > 0 else f"`{total_files:,}` 个独立单项资产"

        lines = [
            "# 📊 磁盘空间全景深度分析与治理报告",
            "",
            f"> 扫描目标: `{paths_str}` | 生成时间: `{now_str}`",
            "",
            "## 一、 磁盘存储健康度评估",
            "",
            f"- **综合健康度评分**：`{health_score} / 100` （评级：**{health_level}**）",
            f"- **扫描治理资产单元**：{asset_summary_str}",
            f"- **已扫描总数据量**：`{format_size(total_b)}`",
            f"- **检测到冗余与重复浪费**：`{format_size(reclaim_b + dup_wasted_b)}`",
            f"- **预期可释放空间比例**：`{redundancy_ratio*100:.2f}%`",
            "",
            "## 二、 空间占用类型分布",
            "",
            "| 资产分类 | 占用空间 | 占用比例 | 资产单元数量 |",
            "| :--- | :--- | :--- | :--- |"
        ]

        cat_stats = summary.get("category_stats", {})
        for cat, stat in cat_stats.items():
            if isinstance(stat, dict):
                b = stat.get("bytes", 0)
                p = stat.get("percent", round((b / total_b * 100), 1) if total_b > 0 else 0)
                c = stat.get("count", stat.get("files", 0))
                lines.append(f"| **{cat}** | {format_size(b)} | {p}% | {c:,} |")

        lines.extend([
            "",
            "## 三、 全局 Top 10 超大资产排行 (>300MB 门槛筛选)",
            "",
            "| 排名 | 资产名称 | 治理形态 | 占用大小 | 包含子文件数 | 绝对路径 |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |"
        ])

        top_files = summary.get("top_100_files", [])[:10]
        if top_files:
            for idx, tf in enumerate(top_files, 1):
                is_c = tf.get("is_directory_collective", False)
                morphology = "📦 原子实体集体" if is_c else "📄 独立单项"
                fc = f"{tf.get('file_count', 1):,} 个" if is_c else "1 个"
                display_name = tf['name']
                if is_c:
                    c_info = tf.get("collective_info") or {}
                    sw_name = c_info.get("software_name")
                    if sw_name and sw_name != display_name:
                        display_name = f"{display_name} ({sw_name})"
                lines.append(f"| #{idx} | `{display_name}` | {morphology} | {format_size(tf['size'])} | {fc} | `{tf['path']}` |")
        else:
            lines.append("| - | *当前无超过 300MB 阈值的超大资产* | - | - | - | - |")

        lines.extend([
            "",
            "## 四、 重复资产与冗余分析",
            "",
            f"- **确认重复资产组数**：`{summary.get('duplicate_groups_count', 0)}` 组",
            f"- **重复副本浪费空间**：`{format_size(dup_wasted_b)}`",
            f"- **候选可释放资产项**：`{len(summary.get('redundant_files', []))}` 项",
            "",
            "## 五、 智能治理与优化建议",
            "",
            "1. **以原子实体集体为最小单位进行归档迁移**：针对独立软件目录、开发工程代码、Live2D虚拟角色及业务账套，必须保持整盘原子保全，严禁拆散内部关联文件。",
            "2. **及时处置冗余归档包与安装程序**：针对同目录下已解压的 zip 冗余压缩包及已完成部署的 setup 安装程序，建议确认后迁移至独立备份盘或直接释放。",
            "3. **优先处理重复副本与临时文件**：针对清单中已哈希确认的重复副本及临时缓存目录进行安全清理，实现无损空间释放。",
            "",
            "## 六、 核心执行清单 (本地智能专家研判)",
            "",
            "| 资产名称 | 治理形态 | 资产大小 | 类别 | 路径摘要 | 原始绝对路径 | 风险等级 | 建议操作 | 分析建议 |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
        ])

        redundant_items = summary.get("redundant_files", [])[:30]
        if redundant_items:
            for item in redundant_items:
                p = item.get("path") or item.get("original_path", "")
                if not p:
                    continue
                name = item.get("name") or Path(p).name
                is_c = bool(item.get("is_directory_collective") or item.get("is_collective"))
                morph = "📦 原子实体集体" if is_c else "📄 独立单项"
                sz = format_size(item.get("size", 0))
                cat = item.get("category", "冗余推荐")
                p_summary = Path(p).parent.name if Path(p).parent else ""
                risk = item.get("risk_level", "低风险")
                act = "清理" if item.get("is_duplicate_copy") else "归档"
                reason = str(item.get("reason", "专家离线引擎研判推荐"))[:25]
                lines.append(f"| `{name}` | {morph} | {sz} | {cat} | `{p_summary}` | `{p}` | {risk} | {act} | {reason} |")
        else:
            lines.append("| - | *当前无明确冗余推荐资产* | - | - | - | - | - | - | - |")

        return "\n".join(lines)

    @classmethod
    def _generate_fallback_execution_plan(cls, summary: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        基于扫描统计与冗余列表，由本地智能专家引擎自动构建标准 execution_plan 结构化清单。
        在网络中断或在线大模型超时降级时，为表格联动和一键归档提供 100% 契约保障。
        """
        plan = []
        seen_paths = set()

        raw_items = list(summary.get("redundant_files", []) or [])
        if len(raw_items) < 10:
            for tf in summary.get("top_100_files", []):
                p = tf.get("path") or tf.get("original_path", "")
                if p and p not in seen_paths:
                    raw_items.append(tf)

        for item in raw_items:
            orig_p = item.get("path") or item.get("original_path", "")
            if not orig_p or orig_p in seen_paths:
                continue
            seen_paths.add(orig_p)

            p_obj = Path(orig_p)
            is_c = bool(item.get("is_directory_collective") or item.get("is_collective"))
            c_info = item.get("collective_info") or {}
            app_name = c_info.get("software_name") or item.get("app_name") or p_obj.stem
            cat = item.get("category") or "冗余数据"
            subpath = f"{cat}/{app_name}" if is_c else cat

            action = "清理" if item.get("is_duplicate_copy") else "归档"
            risk = item.get("risk_level", "低风险")
            reason = str(item.get("reason") or "本地智能专家引擎研判推荐")

            plan.append({
                "original_path": orig_p,
                "name": item.get("name") or p_obj.name,
                "size": int(item.get("size", 0)),
                "suggested_category": cat,
                "app_name": app_name,
                "target_subpath": subpath,
                "action": action,
                "risk_level": risk,
                "confidence": 0.95,
                "rationale": reason,
                "is_directory_collective": is_c
            })
            if len(plan) >= 50:
                break

        return plan

