import os
import json
import requests
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from urllib.parse import urljoin
from dataclasses import dataclass, field

from app.utils.logger import app_logger
from app.utils.file_helper import is_system_critical_path, categorize_file_by_ext, format_size
from app.core.app_detector import AppDetector
from app.core.category_manager import global_category_manager



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
    @classmethod
    def _calculate_target_path(cls, cat_name: str, app_name: str, dest_root_p: Path, orig_root_p: Path, is_dir: bool) -> Path:
        active_cats = global_category_manager.get_active()
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
        for attempt in range(max_retries + 1):
            start_time = time.time()
            try:
                if method.lower() == "get":
                    resp = requests.get(url, **kwargs)
                else:
                    resp = requests.post(url, **kwargs)
                    
                elapsed = time.time() - start_time
                app_logger.info(f"[AI-TASK-{task_id}] 尝试 {attempt+1}/{max_retries+1} 耗时: {elapsed:.2f}s, HTTP 状态: {resp.status_code}")
                
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
                
        app_logger.error(f"[AI-TASK-{task_id}] 最终请求失败: {last_err}")
        return False, {"error": last_err, "task_id": task_id}

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
        weights: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        基于所属 App、软件或工具链特征，按父目录/工具根目录聚合为原子处理单元，并生成归档分类规划。
        返回的是目录/工具级聚合单元列表（每个单元内包含完整子文件树）。
        """
        if not file_items:
            return []

        # 1. 首先通过 AppDetector 将散装文件聚合为目录/工具整体单元
        grouped_units = AppDetector.group_files_by_parent_or_tool(file_items, destination_root)

        # 2. 若配置了大模型，向 LLM 提交目录组特征进行深度 App 签名甄别与分类精炼
        if api_key and base_url and model and grouped_units:
            normalized_url = cls._normalize_base_url(base_url)
            endpoint = normalized_url
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key.strip()}"
            }

            # 抽取前 40 个目录单元摘要送入大模型
            group_summaries = []
            for g in grouped_units[:40]:
                sample_files = [sub["name"] for sub in g["sub_items"][:6]]
                group_summaries.append({
                    "original_root": g["original_root"],
                    "is_directory": g["is_directory_group"],
                    "file_count": g["file_count"],
                    "total_size_mb": round(g["total_size"] / (1024 * 1024), 2),
                    "initial_detected_app": g["app_name"],
                    "sample_files": sample_files
                })

            sys_prefs = ""
            if weights:
                w = weights.get("work_ratio", 0.5)
                sys_prefs = f"用户偏好：工作相关 {int(w*100)}%，私人相关 {100-int(w*100)}%，最低接受置信度 {weights.get('min_conf', 0.8)}\n"
            
            active_cats = global_category_manager.get_active()
            cat_list_str = "\n".join([f"- {c['name']} (描述: {c['description']})" for c in active_cats])
            if cat_list_str:
                sys_prefs += f"\n【必须使用的有效分类白名单】\n你必须且只能从以下列表中选择最合适的分类名称（如果都不匹配，请使用 '未分类/待人工确认'）：\n{cat_list_str}\n"

            system_prompt = (
                "你是一个专业的文件系统治理与软件生态识别专家。请分析待处理的目录与文件聚合单元：\n"
                "【核心原则】\n"
                "1. 必须以目录或工具链为整体单元（如 ~/npm, node_modules, ~/.cache, AppData 下具体工具），严禁拆分内部单个文件；\n"
                "2. 优先识别所属 App、软件或工具链（如 Node.js/npm, VS Code, Python/pip, 微信, Docker 等）；\n"
                "3. 若无法明确识别所属 App，必须归入 '未分类杂项'，置信度设低并标记 require_confirmation=true；\n"
                "4. 包含系统级受保护或关键配置文件时，风险等级必须设为 '高风险'。\n"
                + sys_prefs +
                "\n请严格以 JSON 格式输出: {\"groups\": [{\"original_root\": \"原根路径\", \"app_name\": \"软件名称\", \"suggested_category\": \"归档分类\", \"rationale\": \"依据\", \"confidence\": 0.95, \"risk_level\": \"低风险/中风险/高风险\", \"require_confirmation\": false}]}"
            )

            payload = {
                "model": model.strip(),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"待分类目录聚合单元:\n{json.dumps(group_summaries, ensure_ascii=False, indent=2)}"}
                ],
                "temperature": 0.2
            }
            if "gpt" in model.lower() or "deepseek" in model.lower():
                payload["response_format"] = {"type": "json_object"}

            try:
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
                
                success, result = cls._execute_with_retry("post", endpoint, {"headers": headers, "json": payload}, validator=validator)
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
                        res_map = {item["original_root"]: item for item in parsed["groups"] if "original_root" in item}
                        
                        # 用大模型的精炼识别结果更新目录单元
                        dest_root_p = Path(destination_root)
                        for g in grouped_units:
                            orig_root = g["original_root"]
                            if orig_root in res_map:
                                r = res_map[orig_root]
                                g["app_name"] = r.get("app_name", g["app_name"])
                                new_cat = r.get("suggested_category", g["suggested_category"])
                                g["suggested_category"] = new_cat
                                g["rationale"] = r.get("rationale", g["rationale"])
                                g["confidence"] = float(r.get("confidence", g["confidence"]))
                                g["risk_level"] = r.get("risk_level", g["risk_level"])
                                g["require_confirmation"] = bool(r.get("require_confirmation", g["require_confirmation"]))
                                g["source"] = "AI"
                                
                                # 更新目标根路径与子项目标路径
                                root_p = Path(orig_root)
                                new_target_base = cls._calculate_target_path(new_cat, r.get("app_name", g.get("app_name", "")), dest_root_p, root_p, g.get("is_directory_group", False))
                                g["target_root"] = str(new_target_base)

                                for sub in g["sub_items"]:
                                    sub["target_path"] = str(new_target_base / Path(sub["relative_path"]))
            except Exception as e:
                app_logger.error(f"AI 目录聚合分类请求失败，使用内置规则引擎: {e}")
                for g in grouped_units:
                    g["source"] = "offline_rule"
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
            # Fallback for older formats
            return [{"path": p, "risk_level": "未知", "confidence": 0.5, "reason": "格式兼容"} for p in parsed["recommended_paths"]]

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
            "请以严格的 JSON 格式输出: {\"recommended_paths\": [\"路径1\", \"路径2\"]}"
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
                {"role": "user", "content": f"待分析文件清单:\n{json.dumps(summary_items, ensure_ascii=False, indent=2)}"}
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
        if parsed and "recommended_paths" in parsed and isinstance(parsed["recommended_paths"], list):
            return parsed["recommended_paths"]

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
            "你是一位资深系统优化与存储架构专家。请根据提供的磁盘全景扫描统计数据与冗余文件列表，"
            "进行深度分析，并严格以 JSON 格式输出结果。\n"
            "输出 JSON 格式要求: {\"markdown_report\": \"完整的 Markdown 格式报告文本\", \"chart_categories\": [{\"category\": \"分类名称\", \"bytes\": \"占用字节数(整数)\", \"percent\": \"占比(浮点数)\"}]}\n"
            "注意：在 JSON 中，markdown_report 字符串中的所有换行符必须严格转义为 \\n，严禁出现真实换行符。不能使用未转义的多行字符串。\n"
            "报告必须包含：\n"
            "1. 磁盘现状与健康度评估(0-100分与等级)\n"
            "2. 空间构成与类型特征\n"
            "3. 大文件与冗余分布\n"
            "4. 重复文件浪费分析\n"
            "5. 分级治理与清理优化建议\n"
            "6. 【核心执行清单】：必须输出一个 Markdown 表格，列出推荐处理的文件，表头必须包含：文件名、文件大小(GiB)、类别、路径摘要、原始绝对路径、风险等级、建议操作(如归档/清理/保留)、分析建议。"
        )

        redundant_samples = scan_summary.get("redundant_files", [])
        if len(redundant_samples) > 100:
            redundant_samples = [f for f in redundant_samples if f.get("is_recommended")] or redundant_samples[:100]

        condensed = {
            "total_files": scan_summary.get("total_files"),
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
                
            clean_str = cls._clean_json_response(ai_resp.final_text)
            if not clean_str:
                return False, "未找到 JSON 内容", None
                
            try:
                parsed = json.loads(clean_str, strict=False)
                if "markdown_report" not in parsed:
                    return False, "缺少 markdown_report 字段", None
                
                ai_resp.structured_data = parsed
                ai_resp.final_text = parsed.get("markdown_report", "")
                ai_resp.model = model
                ai_resp.report_id = f"REP_{ai_resp.task_id}"
                
                return True, "", ai_resp
            except Exception as e:
                return False, f"JSON 解析失败: {e}", None
            
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
        paths_str = ", ".join(summary.get("target_paths", []))
        
        redundancy_ratio = (reclaim_b + dup_wasted_b) / total_b if total_b > 0 else 0
        health_score = max(10, int(100 - redundancy_ratio * 150))
        health_level = "极佳" if health_score >= 85 else ("良好" if health_score >= 70 else ("告警" if health_score >= 50 else "危险"))

        from datetime import datetime
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            "# 📊 磁盘空间全景深度分析与治理报告",
            "",
            f"> 扫描目标: `{paths_str}` | 生成时间: `{now_str}`",
            "",
            "## 一、 磁盘存储健康度评估",
            "",
            f"- **综合健康度评分**：`{health_score} / 100` （评级：**{health_level}**）",
            f"- **已扫描总文件数**：`{total_files:,}` 个",
            f"- **已扫描总数据量**：`{format_size(total_b)}`",
            f"- **检测到冗余与重复浪费**：`{format_size(reclaim_b + dup_wasted_b)}`",
            f"- **预期可释放空间比例**：`{redundancy_ratio*100:.2f}%`",
            "",
            "## 二、 空间占用类型分布",
            "",
            "| 文件分类 | 占用空间 | 占用比例 | 文件数量 |",
            "| :--- | :--- | :--- | :--- |"
        ]

        cat_stats = summary.get("category_stats", {})
        for cat, stat in cat_stats.items():
            lines.append(f"| **{cat}** | {format_size(stat['bytes'])} | {stat['percent']}% | {stat['count']:,} |")

        lines.extend([
            "",
            "## 三、 全局 Top 10 超大文件排行",
            "",
            "| 排名 | 文件名 | 类别 | 文件大小 | 绝对路径 |",
            "| :--- | :--- | :--- | :--- | :--- |"
        ])

        top_files = summary.get("top_100_files", [])[:10]
        for idx, tf in enumerate(top_files, 1):
            lines.append(f"| #{idx} | `{tf['name']}` | {tf['category']} | {format_size(tf['size'])} | `{tf['path']}` |")

        lines.extend([
            "",
            "## 四、 重复文件与冗余分析",
            "",
            f"- **重复文件分组数**：`{summary.get('duplicate_groups_count', 0)}` 组",
            f"- **重复副本浪费空间**：`{format_size(dup_wasted_b)}`",
            f"- **候选冗余文件清单数**：`{len(summary.get('redundant_files', []))}` 个",
            "",
            "## 五、 智能治理与优化建议",
            "",
            "1. **以工具链与目录为整体进行归档**：针对 Node.js / npm、pnpm、pip、Docker 等大型工具缓存，建议以目录为单位统一归档或清理，避免拆散文件破坏工具链完整性。",
            "2. **优先处理重复副本与临时文件**：针对清单中已确认的重复副本进行安全清理或归档，可实现无损空间释放。",
            "3. **超大归档包与媒体迁移**：针对 Top 大文件中的视频与安装包，建议利用「智能迁移」转移到空间充裕的独立磁盘。"
        ])

        return "\n".join(lines)
