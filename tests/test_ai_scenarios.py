import sys
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from app.core.ai_service import AIService
from app.core.ai_service import AIResponse

def test_ai_response_parsing():
    print("--- 场景 1: HTTP 200 且返回有效目录级规划 ---")
    valid_json = {
        "choices": [{
            "message": {
                "content": '{"groups": [{"original_root": "C:/test", "suggested_category": "Test"}]}'
            }
        }]
    }
    resp1 = AIService._parse_ai_response(valid_json)
    print("解析状态:", resp1.parse_status)

    print("\n--- 场景 2: HTTP 200 但 content 为空 ---")
    empty_json = {
        "choices": [{
            "message": {
                "content": ''
            }
        }]
    }
    resp2 = AIService._parse_ai_response(empty_json)
    print("解析状态:", resp2.parse_status, "错误信息:", resp2.error_message)

    print("\n--- 场景 3: HTTP 200 但仅返回思考内容 ---")
    think_json = {
        "choices": [{
            "message": {
                "content": '<think>思考中...</think>'
            }
        }]
    }
    resp3 = AIService._parse_ai_response(think_json)
    print("解析状态:", resp3.parse_status, "错误信息:", resp3.error_message)

if __name__ == '__main__':
    app = QApplication.instance() or QApplication(sys.argv)
    test_ai_response_parsing()
    print("\n✅ 测试脚本执行完毕。")
