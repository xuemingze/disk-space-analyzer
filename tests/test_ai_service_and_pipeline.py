import os
import sys
from pathlib import Path
import pytest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.ai_service import AIService


def test_clean_json_response_with_think_and_markdown():
    raw_response = """
<think>
Evaluating disk storage and formatting JSON response...
</think>
Here is the recommended organize plan:
```json
{
  "groups": [
    {
      "original_root": "C:/Users/Admin/.cache",
      "app_name": "User Cache",
      "suggested_category": "缓存文件",
      "action": "清理",
      "rationale": "临时缓存",
      "risk_level": "低",
      "sub_items": [
        {"original_path": "C:/Users/Admin/.cache/temp.log", "size_bytes": 1024, "target_relative_path": "temp.log"}
      ]
    }
  ]
}
```
Hope this helps!
    """
    cleaned = AIService._clean_json_response(raw_response)
    assert cleaned.startswith("{")
    assert "<think>" not in cleaned
    assert "```" not in cleaned
    import json
    data = json.loads(cleaned)
    assert "groups" in data
    assert len(data["groups"]) == 1
    assert data["groups"][0]["app_name"] == "User Cache"


def test_clean_json_response_raw_json():
    raw_json = '{"groups": [{"original_root": "D:/temp", "suggested_category": "Temp", "action": "清理", "sub_items": []}]}'
    cleaned = AIService._clean_json_response(raw_json)
    assert cleaned == raw_json


def test_process_report_validation_rejects_missing_fields(tmp_path):
    report_file = tmp_path / "test_report.md"
    report_file.write_text("# Test Report\nSome summary", encoding="utf-8")

    # Mock response missing suggested_category and action
    mock_resp_data = {
        "groups": [
            {
                "original_root": "C:/some/path"
                # Missing suggested_category, action, sub_items
            }
        ]
    }

    import json
    with patch.object(AIService, "_execute_with_retry") as mock_exec:
        mock_exec.return_value = (True, {
            "data": {
                "choices": [{"message": {"content": f"```json\n{json.dumps(mock_resp_data)}\n```"}}]
            }
        })
        with pytest.raises(RuntimeError, match="缺失必要的路径"):
            AIService.process_report_with_ai("http://dummy", "key", "model", str(report_file), "D:/dest")


def test_generate_health_report_timeout_graceful_degradation():
    """
    准则一核心编排架构契约测试：
    验证在线大模型请求超时 (如 300s) 时，系统必须 100% 优雅降级至本地智能专家治理报告，
    严禁向前端抛出阻断性崩溃异常，且执行清单与全景结构化数据必须完整输出。
    """
    summary = {
        "total_files": 500,
        "total_bytes": 1024 * 1024 * 100,
        "redundant_files": [
            {"path": f"D:/test/file_{i}.zip", "name": f"file_{i}.zip", "size": 1024 * 1024, "category": "归档包"}
            for i in range(20)
        ],
        "category_stats": {"归档包": {"bytes": 1024 * 1024 * 20, "percent": 20.0}},
        "top_100_files": [],
        "duplicate_groups_count": 2,
        "duplicate_wasted_bytes": 1024 * 1024 * 5,
        "reclaimable_bytes": 1024 * 1024 * 20,
        "target_paths": ["D:/test"]
    }

    with patch.object(AIService, "_execute_with_retry", return_value=(False, {"error": "读取响应超时 (耗时 > 300.38s)"})):
        # 1. 默认准则一契约：严禁越权替代 AI，抛出异常交由前端用户界面呈现选项由用户定夺
        with pytest.raises(RuntimeError, match="读取响应超时"):
            AIService.generate_health_report_with_ai(
                base_url="https://api.minimaxi.com/v1",
                api_key="mock_key",
                model="MiniMax-Text-01",
                scan_summary=summary,
                allow_fallback=False
            )

        # 2. 授权兜底模式：生成本地智能专家应急治理报告
        resp = AIService.generate_health_report_with_ai(
            base_url="https://api.minimaxi.com/v1",
            api_key="mock_key",
            model="MiniMax-Text-01",
            scan_summary=summary,
            allow_fallback=True
        )
        assert resp is not None
        assert resp.parse_status == "SUCCESS"
        assert "已降级至本地智能专家规则" in resp.model
        assert "在线模型降级提示" in resp.final_text
        assert resp.structured_data is not None
        assert "execution_plan" in resp.structured_data
        assert len(resp.structured_data["execution_plan"]) > 0
        first_item = resp.structured_data["execution_plan"][0]
        assert "original_path" in first_item
        assert "suggested_category" in first_item


def test_extract_markdown_report_from_response():
    """测试从完整或截断的 JSON 响应中提取 markdown 报告（含反转义与正则抽取）"""
    # 1. 模拟被截断的 JSON（结尾缺失闭合大括号）
    truncated_json = '{"markdown_report": "# 治理报告\\n\\n## 资产分析\\n- 测试项\\n", "execution_plan": ['
    result = AIService._extract_markdown_report_from_response(truncated_json)
    assert result is not None
    md_text, exec_plan, struct = result
    assert md_text.startswith("# 治理报告")
    assert "## 资产分析" in md_text
    assert "\\n" not in md_text  # 验证反转义成功
    assert isinstance(struct, dict)

    # 2. 模拟普通 Markdown 文本
    plain_md = "# 普通报告\n内容"
    res_plain = AIService._extract_markdown_report_from_response(plain_md)
    assert res_plain is not None
    assert res_plain[0] == plain_md

    # 3. 模拟未闭合 JSON 内部包含 Markdown 方括号语法（原正则曾被错误截断匹配 [804 个底层文件]）
    truncated_with_brackets = (
        '{\n  "markdown_report": "# 磁盘全景分析与治理报告\\n\\n## 一、扫描范围\\n\\n'
        '本次扫描范围为 `D:\\\\安装包`，共识别 [804 个底层文件]、23 个顶层资产。'
    )
    res_brackets = AIService._extract_markdown_report_from_response(truncated_with_brackets)
    assert res_brackets is not None
    assert "磁盘全景分析与治理报告" in res_brackets[0]
    assert "[804 个底层文件]" in res_brackets[0]

    # 4. 模拟 JSON 外壳破损但包含 Markdown 标题的容错提取
    broken_envelope = '{\n  # 磁盘全景深度报告\n\n## 章节一\n这里是测试内容，空间分析正常。'
    res_broken = AIService._extract_markdown_report_from_response(broken_envelope)
    assert res_broken is not None
    assert res_broken[0].startswith("# 磁盘全景深度报告")


