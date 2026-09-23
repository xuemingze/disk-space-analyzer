import os
import json
import requests
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from urllib.parse import urljoin

from app.utils.logger import app_logger
from app.utils.file_helper import is_system_critical_path, categorize_file_by_ext, format_size
from app.core.app_detector import AppDetector


class AIService:
    """
    负责对接 OpenAI 兼容规范的大模型服务接口：
    1. 动态拉取 /v1/models 模型列表
    2. 模型连通性与权限测试
    3. AI 辅助文件与目录整体分类方案生成 (以 App/工具/父目录为原子分组单元，拒绝单文件按格式拆分)
    4. 智能冗余文件安全甄别
    5. 磁盘健康度与全景深度分析报告生成
    """

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        url = base_url.strip().rstrip("/")
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        return url

    @classmethod
    def fetch_models(cls, base_url: str, api_key: str, timeout: int = 12) -> Tuple[bool, List[str], str]:
        normalized_url = cls._normalize_base_url(base_url)
        endpoint = f"{normalized_url}/models"
        
        headers = {"Content-Type": "application/json"}
        if api_key.strip():
            headers["Authorization"] = f"Bearer {api_key.strip()}"

        try:
            app_logger.info(f"正在拉取模型列表: {endpoint}")
            resp = requests.get(endpoint, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                return False, [], f"HTTP {resp.status_code}: {resp.text[:200]}"
                
            data = resp.json()
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
                        
            model_list = sorted(list(set(model_list)))
            if not model_list:
                return False, [], "响应中未发现有效模型列表"
            return True, model_list, "获取模型列表成功"
        except Exception as e:
            return False, [], f"请求异常: {str(e)}"

    @classmethod
    def test_connection(cls, base_url: str, api_key: str, model: str, timeout: int = 15) -> Tuple[bool, str]:
        normalized_url = cls._normalize_base_url(base_url)
        endpoint = f"{normalized_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key.strip()}"
        }
        payload = {
            "model": model.strip(),
            "messages": [{"role": "user", "content": "请回复 pong"}],
            "max_tokens": 10
        }
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 200:
                return True, "API 连通测试通过！"
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            return False, f"连通测试失败: {str(e)}"

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
            endpoint = f"{normalized_url}/chat/completions"
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

            system_prompt = (
                "你是一个专业的文件系统治理与软件生态识别专家。请分析待处理的目录与文件聚合单元：\n"
                "【核心原则】\n"
                "1. 必须以目录或工具链为整体单元（如 ~/npm, node_modules, ~/.cache, AppData 下具体工具），严禁拆分内部单个文件；\n"
                "2. 优先识别所属 App、软件或工具链（如 Node.js/npm, VS Code, Python/pip, 微信, Docker 等）；\n"
                "3. 若无法明确识别所属 App，必须归入 '未识别工具/待分类'，置信度设为 0.4 并标记 require_confirmation=true；\n"
                "4. 包含系统级受保护或关键配置文件时，风险等级必须设为 '需人工确认' 或 '高风险'。\n\n"
                "请严格以 JSON 格式输出: {\"groups\": [{\"original_root\": \"原根路径\", \"app_name\": \"软件名称\", \"suggested_category\": \"归档分类\", \"rationale\": \"依据\", \"confidence\": 0.95, \"risk_level\": \"低风险/中风险/需人工确认/高风险\", \"require_confirmation\": false}]}"
            )

            payload = {
                "model": model.strip(),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"待分类目录聚合单元:\n{json.dumps(group_summaries, ensure_ascii=False, indent=2)}"}
                ],
                "response_format": {"type": "json_object"} if "gpt" in model.lower() or "deepseek" in model.lower() else None,
                "temperature": 0.2
            }

            try:
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=35)
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    if "groups" in parsed and isinstance(parsed["groups"], list):
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
                                
                                # 更新目标根路径与子项目标路径
                                root_p = Path(orig_root)
                                if g["is_directory_group"]:
                                    new_target_base = dest_root_p / new_cat / root_p.name
                                else:
                                    new_target_base = dest_root_p / new_cat
                                g["target_root"] = str(new_target_base)

                                for sub in g["sub_items"]:
                                    sub["target_path"] = str(new_target_base / Path(sub["relative_path"]))
            except Exception as e:
                app_logger.error(f"AI 目录聚合分类请求失败，使用内置规则引擎: {e}")

        return grouped_units

    @classmethod
    def analyze_redundant_files_with_ai(
        cls,
        base_url: str,
        api_key: str,
        model: str,
        candidate_files: List[Dict[str, Any]]
    ) -> List[str]:
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
            "请以严格的 JSON 格式输出: {\"recommended_paths\": [\"路径1\", \"路径2\"]}"
        )

        normalized_url = cls._normalize_base_url(base_url)
        endpoint = f"{normalized_url}/chat/completions"
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
            "response_format": {"type": "json_object"} if "gpt" in model.lower() or "deepseek" in model.lower() else None,
            "temperature": 0.2
        }

        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=30)
            if resp.status_code == 200:
                result_json = resp.json()
                content = result_json["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                if "recommended_paths" in parsed and isinstance(parsed["recommended_paths"], list):
                    return parsed["recommended_paths"]
        except Exception as e:
            app_logger.error(f"AI 冗余文件分析调用失败: {e}")

        return []

    @classmethod
    def generate_health_report_with_ai(
        cls,
        base_url: str,
        api_key: str,
        model: str,
        scan_summary: Dict[str, Any]
    ) -> str:
        if api_key and base_url and model:
            normalized_url = cls._normalize_base_url(base_url)
            endpoint = f"{normalized_url}/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key.strip()}"
            }
            
            system_prompt = (
                "你是一位资深系统优化与存储架构专家。请根据提供的磁盘全景扫描统计数据，"
                "生成一份结构完整、数据详实、排版优美的 Markdown 格式《磁盘空间全景深度分析与治理报告》。"
                "包含：1.磁盘现状与健康度评估(0-100分与等级)；2.空间构成与类型特征；3.大文件与冗余分布；4.重复文件浪费分析；5.分级治理与清理优化建议。"
            )

            condensed = {
                "total_files": scan_summary.get("total_files"),
                "total_bytes": scan_summary.get("total_bytes"),
                "category_stats": scan_summary.get("category_stats"),
                "top_10_large_files": scan_summary.get("top_100_files", [])[:10],
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

            try:
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=40)
                if resp.status_code == 200:
                    res_json = resp.json()
                    return res_json["choices"][0]["message"]["content"]
            except Exception as e:
                app_logger.error(f"AI 生成报告失败，使用离线模板: {e}")

        return cls._generate_fallback_report(scan_summary)

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
