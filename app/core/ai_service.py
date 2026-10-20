import os
import json
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

            import requests
            resp = requests.post(normalized_url, headers=headers, json=payload, timeout=20)
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

    @classmethod
    def _calculate_target_path(
        cls, cat_name: str, app_name: str, dest_root_p: Path, orig_root_p: Path, is_dir: bool, subpath: str = ""
    ) -> Path:
        active_cats = global_category_manager.get_active()
        clean_sub = sanitize_subpath(subpath)
        
        # 若提供了推荐的细粒度子目录层级，优先在主分类下构建该层级 (防止重名重复嵌套)
        if clean_sub:
            sub_p = Path(clean_sub)
            if is_dir:
                sub_parts_lower = [part.lower() for part in sub_p.parts]
                if orig_root_p.name.lower() == sub_p.name.lower() or (orig_root_p.name.lower() in sub_parts_lower):
                    return dest_root_p / cat_name / sub_p
                return dest_root_p / cat_name / sub_p / orig_root_p.name
            else:
                return dest_root_p / cat_name / sub_p

        for cat in active_cats:
            if cat["name"] == cat_name:
                template = cat.get("target_path_template", "{archive_root}/{category_name}/{app_name}")
                res = template.replace("{archive_root}", str(dest_root_p))
                res = res.replace("{category_name}", cat_name)
                res = res.replace("{app_name}", app_name if app_name else orig_root_p.name)
                return Path(res)
        # Fallback
        if is_dir:
            return dest_root_p / cat_name / orig_root_p.name
        else:
            return dest_root_p / cat_name

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
    def process_report_with_ai(
        cls,
        base_url: str,
        api_key: str,
        model: str,
        report_path: str,
        destination_root: str
    ) -> List[Dict[str, Any]]:
        """基于生成的 Markdown 报告内容，提取归档与清理的执行清单"""
        if not api_key or not base_url or not model:
            raise ValueError("AI 模型未配置。")
            
        with open(report_path, "r", encoding="utf-8") as f:
            report_md = f.read()
            
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
            whitelist_prompt = f"\n【必须使用的有效分类白名单】\n你必须且只能从以下列表中选择最合适的一级分类名称（如果都不匹配，请使用 '未分类/待人工确认'）：\n{cat_list_str}\n" if cat_list_str else ""

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

            system_prompt = (
                "你是一个专业的文件系统治理与软件生态架构专家。请分析待处理的目录与文件聚合单元并制定归档分类方案。\n"
                "【核心原则】\n"
                "1. 【软件/工程集体完整性】：对于 unit_type 为 '软件/工程集体' 的目录单元，它是一个完整的独立软件、运行环境或代码工程，内部所有文件严禁拆分；\n"
                "2. 【依据软件外显铭牌分类】：对软件/工程集体，必须依据其软件名 (software_name)、主程序 (primary_executable)、产品标题 (product_title) 与项目清单 (manifest_project_name) 判定其软件归属，给出宏观分类（例如：开发工具/IDE与编辑器、实用工具/媒体播放器、代码工程/前端Vue项目等）；\n"
                "3. 【散装独立文件细分】：对于 unit_type 为 '散装独立文件' 的单文件，依据其格式类型与业务前缀给出细分归档路径；\n"
                "4. 【具体多级子目录推荐】：除 suggested_category（一级大类）外，必须在 recommended_subpath 中给出具体的建议子目录层级（例如 '开发工具/VSCode'、'财务/发票/2026'）；\n"
                "5. 若无法明确识别，必须归入 '未分类/待人工确认'，置信度设低于 0.6 并标记 require_confirmation=true；\n"
                "6. 【父子语义广义-狭义认知】：若输入单元所属父目录或上下文为广义分类词（如 '项目'、'多媒体'、'设计'、'游戏'、'财务'、'学习'），其所属子目录即为该领域下的狭义独立实体（如 'xxx项目'、'xxx设计'、'xxx查重'），必须以实体为单位整盘原子平移归档，绝不可因内部散杂格式而拆散实体；\n"
                "7. 【源目录锚定与同源同宿】：若待归档单元带有 source_umbrella（源泛目录锚点，如 'live2D'、'经控'、'发票'），说明它们来自源文件系统中的同一业务泛目录。同源单元严禁分裂到不同的一级分类或互不相干的深层子路径！所有具有相同 source_umbrella 的单元必须保持同一一级大类，且 recommended_subpath 必须以 source_umbrella 为基准（例如直接设为 'live2D' 或 '经控'），与源路径命名结构保持一致，不再过度人为细分；\n"
                f"{mode_prompt}\n"
                f"{lang_prompt}\n"
                f"{custom_prompt}"
                f"{sys_prefs}"
                f"{whitelist_prompt}\n"
                "【输出格式约束】\n"
                "请严格以 JSON 格式输出，必须且只能包含 groups 数组，且必须包含输入时给定的 stable group_id：\n"
                "{\n"
                '  "groups": [\n'
                '    {\n'
                '      "group_id": "对应输入的稳定 group_id (如 grp_0001，严禁遗漏或修改)",\n'
                '      "app_name": "识别的软件或工具名称",\n'
                '      "suggested_category": "归档一级分类（必须选自白名单）",\n'
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
                g["app_name"] = r.get("app_name", g["app_name"])
                new_cat = r.get("suggested_category", g["suggested_category"])
                g["suggested_category"] = new_cat

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
                g["target_root"] = str(new_target_base)

                for sub in g["sub_items"]:
                    if g.get("is_directory_group", False):
                        sub["target_path"] = str(new_target_base / Path(sub["relative_path"]))
                    else:
                        sub["target_path"] = str(new_target_base / Path(sub["name"]))

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
                    c_info = g.get("collective_info") or {}
                    summary_item = {
                        "group_id": g["group_id"],
                        "total_size_mb": round(g["total_size"] / (1024 * 1024), 2),
                        "initial_suggested_category": g["suggested_category"],
                        "initial_subpath": g.get("recommended_subpath", ""),
                    }
                    if g.get("source_umbrella"):
                        summary_item["source_umbrella"] = g["source_umbrella"]
                    if g.get("is_directory_group"):
                        summary_item["unit_type"] = "软件/工程集体 (Directory Collective)"
                        summary_item["directory_name"] = g["name"]
                        summary_item["software_name"] = c_info.get("software_name") or g.get("app_name") or g["name"]
                        if c_info.get("primary_executable"):
                            summary_item["primary_executable"] = c_info["primary_executable"]
                        if c_info.get("product_title"):
                            summary_item["product_title"] = c_info["product_title"]
                        if c_info.get("manifest_project_name"):
                            summary_item["manifest_project_name"] = c_info["manifest_project_name"]
                        if c_info.get("signature_type"):
                            summary_item["signature_type"] = c_info["signature_type"]
                    else:
                        summary_item["unit_type"] = "散装独立文件 (Single File)"
                        summary_item["file_name"] = g["name"]
                        summary_item["extension"] = Path(g["name"]).suffix.lower()
                        summary_item["initial_detected_app"] = g.get("app_name", "")
                        if options.sample_content_enabled and g.get("content_samples"):
                            summary_item["content_samples"] = g["content_samples"]
                    batch_summaries.append(summary_item)

                payload = {
                    "model": model.strip(),
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"待分类目录聚合单元批次 [{batch_label}] (共 {len(sub_batch)} 项):\n{json.dumps(batch_summaries, ensure_ascii=False, indent=2)}"}
                    ],
                    "temperature": 0.2
                }
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
                    "post", endpoint, {"headers": headers, "json": payload},
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
            "temperature": 0.2
        }
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

        success, result = cls._execute_with_retry("post", endpoint, {"headers": headers, "json": payload}, task_desc="智能推荐", validator=validator)
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
    def generate_health_report_with_ai(
        cls,
        base_url: str,
        api_key: str,
        model: str,
        scan_summary: Dict[str, Any],
        progress_callback=None
    ) -> AIResponse:
        if not (api_key and base_url and model):
            raise ValueError("AI 模型未配置：缺少 base_url、api_key 或 model。")

        normalized_url = cls._normalize_base_url(base_url)
        endpoint = normalized_url
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key.strip()}"
        }
        
        system_prompt = (
            "你是一位资深系统优化与存储架构专家。请根据提供的磁盘全景扫描统计数据（含原子实体集体与独立资产单元）与冗余列表，"
            "进行深度全景分析，并严格以 JSON 格式输出结果。\n"
            "输出 JSON 格式要求: {\"markdown_report\": \"完整的 Markdown 格式报告文本\", \"chart_categories\": [{\"category\": \"分类名称\", \"bytes\": \"占用字节数(整数)\", \"percent\": \"占比(浮点数)\"}]}\n"
            "注意：在 JSON 中，markdown_report 字符串中的所有换行符必须严格转义为 \\n，严禁出现真实换行符。不能使用未转义的多行字符串。\n"
            "【核心原则】：系统采用原子实体集体（软件/工程/模型/账套/缓存）防撕裂与聚合保全机制，对于目录集体资产必须作为一个整体提出治理建议，严禁建议拆散其内部子文件。\n"
            "报告必须包含：\n"
            "1. 磁盘现状与健康度评估(0-100分与等级，含资产单元总数、实体集体数与底层碎片聚合数)\n"
            "2. 空间构成与类型特征\n"
            "3. 大资产与冗余分布(Top 超大资产清单及形态)\n"
            "4. 重复资产浪费分析\n"
            "5. 分级治理与清理优化建议\n"
            "6. 【核心执行清单】：必须输出一个 Markdown 表格，列出推荐处理的资产单元，表头必须包含：资产名称、治理形态、资产大小、类别、路径摘要、原始绝对路径、风险等级、建议操作(如归档/清理/保留)、分析建议。"
        )

        redundant_samples = scan_summary.get("redundant_files", [])
        if len(redundant_samples) > 100:
            redundant_samples = [f for f in redundant_samples if f.get("is_recommended")] or redundant_samples[:100]

        c_cnt = scan_summary.get("collective_count", 0)
        s_cnt = scan_summary.get("standalone_file_count", 0)
        condensed = {
            "total_files": scan_summary.get("total_files"),
            "collective_count": c_cnt,
            "standalone_file_count": s_cnt,
            "total_assets_count": c_cnt + s_cnt,
            "total_bytes": scan_summary.get("total_bytes"),
            "category_stats": scan_summary.get("category_stats"),
            "top_10_large_files": scan_summary.get("top_100_files", [])[:10],
            "redundant_files": redundant_samples,
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
            "temperature": 0.5
        }
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

            # 1. 优先尝试按照 JSON 进行清洗与解析
            clean_str = cls._clean_json_response(raw_text)
            parsed = None
            if clean_str:
                try:
                    parsed = json.loads(clean_str, strict=False)
                except Exception:
                    parsed = None
                    
            if isinstance(parsed, dict) and "markdown_report" in parsed:
                ai_resp.structured_data = parsed
                ai_resp.final_text = str(parsed.get("markdown_report", ""))
                ai_resp.model = model
                ai_resp.report_id = f"REP_{ai_resp.task_id}"
                return True, "", ai_resp

            # 2. 强力容错兜底：如果模型（如 MiniMax-M3, Qwen 等）直接输出了 Markdown 报告
            # 只要文本包含 Markdown 标记或长度足够（说明是完整报告，而非报错），直接认定为有效 Markdown 报告
            if len(raw_text) > 50 or raw_text.startswith("#") or "##" in raw_text or "```" in raw_text:
                ai_resp.structured_data = {
                    "markdown_report": raw_text,
                    "chart_categories": []
                }
                ai_resp.final_text = raw_text
                ai_resp.model = model
                ai_resp.report_id = f"REP_{ai_resp.task_id}"
                return True, "", ai_resp

            return False, f"返回内容既非合法 JSON 也非完整 Markdown 报告: {raw_text[:100]}", None
            
        if progress_callback:
            progress_callback("AI_ANALYZING: 正在发送数据与大模型进行分析...")
        success, result = cls._execute_with_retry("post", endpoint, {"headers": headers, "json": payload}, task_desc="生成报告", validator=validator)
        if progress_callback:
            progress_callback("AI_REPORT_SAVING: 正在校验与保存结构化报告...")
        if not success:
            err_msg = result.get('error')
            app_logger.error(f"AI 生成报告失败: {err_msg}")
            raise RuntimeError(f"AI 生成报告失败: {err_msg}")
            
        ai_resp = result.get("parsed_data")
        if ai_resp is None and "data" in result:
            ai_resp = cls._parse_ai_response(result.get("data", {}))
            clean_str = cls._clean_json_response(ai_resp.final_text or "")
            try:
                parsed = json.loads(clean_str, strict=False)
                if isinstance(parsed, dict) and "markdown_report" in parsed:
                    ai_resp.structured_data = parsed
                    ai_resp.final_text = parsed.get("markdown_report", "")
                    ai_resp.model = model
                    ai_resp.report_id = f"REP_{ai_resp.task_id}"
            except Exception:
                pass
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
            "3. **优先处理重复副本与临时文件**：针对清单中已哈希确认的重复副本及临时缓存目录进行安全清理，实现无损空间释放。"
        ])

        return "\n".join(lines)
