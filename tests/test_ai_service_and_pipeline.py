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
