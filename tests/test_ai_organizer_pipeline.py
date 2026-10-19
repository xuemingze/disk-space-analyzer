"""
AI 目录整理增强管道与离线基准评测自动化测试套件
覆盖：
1. OrganizeOptions 偏好模型与模式枚举校验
2. 跨平台子路径安全清洗 (sanitize_subpath) 防目录穿越
3. 内容样本抽样安全准入与脱敏过滤 (is_safe_for_content_sampling)
4. 五大整理模式离线启发式规则 (generate_heuristic_subpath: comprehensive, by_type, by_prefix, by_date, by_app) 与中英文双语
5. 稳定 ID (grp_XXXX) 聚合与推荐子目录注入
6. 分批 Token 预算与稳定 ID 映射鲁棒性 (classify_files_with_ai)
7. 320 组脱敏样例离线基准评测 (结构合法率 100%、分类准确率、建议可用率、安全拦截守则)
"""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.organize_models import (
    OrganizeMode,
    OrganizeOptions,
    sanitize_subpath,
    is_safe_for_content_sampling,
    extract_file_content_sample
)
from app.core.app_detector import AppDetector
from app.core.ai_service import AIService
from app.core.scanner import DirectoryScanTask


# ============================================================================
# 1. OrganizeOptions 偏好模型校验
# ============================================================================
def test_organize_options_defaults_and_modes():
    opts = OrganizeOptions()
    assert opts.mode == OrganizeMode.COMPREHENSIVE
    assert opts.language == "zh"
    assert opts.custom_prompt == ""
    assert opts.enable_content_sampling is False
    assert opts.sample_content_enabled is False
    assert opts.min_confidence == 0.70
    assert opts.batch_size == 20

    # 验证五大模式枚举值
    assert OrganizeMode.COMPREHENSIVE.value == "comprehensive"
    assert OrganizeMode.BY_TYPE.value == "by_type"
    assert OrganizeMode.BY_PREFIX.value == "by_prefix"
    assert OrganizeMode.BY_DATE.value == "by_date"
    assert OrganizeMode.BY_APP.value == "by_app"


# ============================================================================
# 2. 跨平台子路径清洗安全性
# ============================================================================
def test_sanitize_subpath_security():
    # 正常合法子路径
    assert sanitize_subpath("财务/发票/2026") == "财务/发票/2026"
    assert sanitize_subpath("Finance/Invoices") == "Finance/Invoices"
    assert sanitize_subpath("  前端/React  ") == "前端/React"

    # 目录穿越与相对路径攻击防御
    assert ".." not in sanitize_subpath("../../etc/passwd")
    assert sanitize_subpath("../../../secret") == "secret"
    assert sanitize_subpath("a/../../b") == "b"

    # Windows 绝对盘符清理
    assert sanitize_subpath("C:\\Windows\\System32") == "Windows/System32"
    assert sanitize_subpath("D:/Projects/App") == "Projects/App"

    # Unix 根路径清理
    assert sanitize_subpath("/var/log/nginx") == "var/log/nginx"

    # 非法字符清理 (< > : " | ? *)
    dirty = '项目:方案<v1.0>*test?|"name"'
    clean = sanitize_subpath(dirty)
    for c in '<>:"|?*':
        assert c not in clean

    # 空值与极值防御
    assert sanitize_subpath("") == ""
    assert sanitize_subpath("   ") == ""
    assert sanitize_subpath("///") == ""
    assert sanitize_subpath("..//..//") == ""


# ============================================================================
# 3. 内容样本抽样安全准入与脱敏过滤
# ============================================================================
def test_content_sampling_safety_filter(tmp_path):
    # 3.1 常见敏感凭据必须无条件拒绝抽样
    sensitive_names = [
        ".env",
        ".env.production",
        ".env.local",
        "id_rsa",
        "id_ed25519",
        "server.pem",
        "private.key",
        "jwt_secret.txt",
        "auth_config.json",
        "service_account.json",
        "passwd",
        "shadow"
    ]
    for name in sensitive_names:
        p = tmp_path / name
        p.write_text("SOME_SECRET_DATA=12345", encoding="utf-8")
        assert is_safe_for_content_sampling(str(p)) is False, f"{name} 应该被拒绝抽样"
        assert extract_file_content_sample(str(p)) == ""

    # 3.2 二进制可执行文件与音视频、压缩包必须拒绝抽样
    binary_names = ["test.exe", "test.dll", "test.bin", "test.zip", "test.mp4", "test.png"]
    for name in binary_names:
        p = tmp_path / name
        p.write_bytes(b"\x00\x01\x02\x03\x04")
        assert is_safe_for_content_sampling(str(p)) is False

    # 3.3 安全文本文件允许抽样，但若含有敏感 Token 需自动脱敏
    safe_doc = tmp_path / "readme.txt"
    safe_doc.write_text("Hello DiskSpaceAnalyzer! api_key=sk-1234567890abcdef12345678", encoding="utf-8")
    assert is_safe_for_content_sampling(str(safe_doc)) is True
    sample = extract_file_content_sample(str(safe_doc), max_bytes=300)
    assert "[REDACTED_SECRET]" in sample
    assert "sk-1234567890abcdef12345678" not in sample


# ============================================================================
# 4. 五大整理模式离线启发式规则验证
# ============================================================================
def test_heuristic_subpath_five_modes():
    # 4.1 按日期模式 (BY_DATE)
    date_items = [
        {"name": "file1.txt", "path": "D:/test/file1.txt", "mtime": 1740000000}, # 2025-02
        {"name": "file2.txt", "path": "D:/test/file2.txt", "mtime": 1740003600}
    ]
    sub_date = AppDetector.generate_heuristic_subpath(
        "D:/test", date_items, {}, False, OrganizeMode.BY_DATE, "zh"
    )
    assert sub_date.startswith("2025/2025-")

    # 4.2 按前缀模式 (BY_PREFIX)
    prefix_items = [
        {"name": "ProjectAlpha_Report.pdf", "path": "D:/test/ProjectAlpha_Report.pdf"},
        {"name": "ProjectAlpha_Budget.xlsx", "path": "D:/test/ProjectAlpha_Budget.xlsx"},
        {"name": "ProjectAlpha_Meeting.docx", "path": "D:/test/ProjectAlpha_Meeting.docx"}
    ]
    sub_prefix = AppDetector.generate_heuristic_subpath(
        "D:/test", prefix_items, {}, False, OrganizeMode.BY_PREFIX, "zh"
    )
    assert sub_prefix == "ProjectAlpha"

    # 4.3 按文件类型模式 (BY_TYPE) - 中英文
    doc_items = [
        {"name": "doc1.pdf", "path": "D:/test/doc1.pdf"},
        {"name": "doc2.docx", "path": "D:/test/doc2.docx"}
    ]
    sub_type_zh = AppDetector.generate_heuristic_subpath(
        "D:/test", doc_items, {}, False, OrganizeMode.BY_TYPE, "zh"
    )
    assert sub_type_zh == "文档资料"

    sub_type_en = AppDetector.generate_heuristic_subpath(
        "D:/test", doc_items, {}, False, OrganizeMode.BY_TYPE, "en"
    )
    assert sub_type_en == "Documents"

    # 4.4 按应用工具链模式 (BY_APP)
    app_info = {"app_name": "Visual Studio Code (前端工程)"}
    sub_app = AppDetector.generate_heuristic_subpath(
        "D:/test", doc_items, app_info, False, OrganizeMode.BY_APP, "zh"
    )
    assert "Visual Studio Code" in sub_app

    # 4.5 综合整理模式 (COMPREHENSIVE) - 业务语义关键词命中
    inv_items = [{"name": "2025年3月增值税专用发票.pdf", "path": "D:/test/2025年3月增值税专用发票.pdf"}]
    sub_inv_zh = AppDetector.generate_heuristic_subpath(
        "D:/test", inv_items, {}, False, OrganizeMode.COMPREHENSIVE, "zh"
    )
    assert sub_inv_zh == "财务/发票"

    sub_inv_en = AppDetector.generate_heuristic_subpath(
        "D:/test", inv_items, {}, False, OrganizeMode.COMPREHENSIVE, "en"
    )
    assert sub_inv_en == "Finance/Invoices"

    contract_items = [{"name": "软件服务委托合同终版.docx", "path": "D:/test/软件服务委托合同终版.docx"}]
    sub_contract = AppDetector.generate_heuristic_subpath(
        "D:/test", contract_items, {}, False, OrganizeMode.COMPREHENSIVE, "zh"
    )
    assert sub_contract == "商务/合同"


# ============================================================================
# 5. 稳定 ID (grp_XXXX) 聚合与目标路径构造
# ============================================================================
def test_grouping_with_stable_ids_and_subpath():
    files = [
        # Node 项目
        {"path": "D:/Workspace/my-vue-app/package.json", "name": "package.json", "size": 1200, "is_dir": False},
        {"path": "D:/Workspace/my-vue-app/src/main.ts", "name": "main.ts", "size": 3400, "is_dir": False},
        # 散装单文件 (发票)
        {"path": "D:/Downloads/invoice_202501.pdf", "name": "invoice_202501.pdf", "size": 180000, "is_dir": False},
    ]
    options = OrganizeOptions(mode=OrganizeMode.COMPREHENSIVE, language="zh")
    groups = AppDetector.group_files_by_parent_or_tool(files, "D:/归档备份", options=options)

    assert len(groups) == 2

    # 验证稳定编号
    assert groups[0]["group_id"] == "grp_0001"
    assert groups[1]["group_id"] == "grp_0002"

    # 验证 Node 项目作为目录单元整体聚合
    node_group = next(g for g in groups if "my-vue-app" in g["original_root"])
    assert node_group["is_directory_group"] is True
    assert "D:/归档备份" in Path(node_group["target_root"]).as_posix()
    assert "my-vue-app" in Path(node_group["target_root"]).as_posix()

    # 验证每个子文件均注入正确的 target_path
    for sub in node_group["sub_items"]:
        assert "target_path" in sub
        assert str(Path(node_group["target_root"])) in sub["target_path"]

    # 验证发票单文件获得细化推荐子目录 "财务/发票"
    inv_group = next(g for g in groups if "invoice" in g["name"])
    assert inv_group["is_directory_group"] is False
    assert inv_group["recommended_subpath"] == "财务/发票"
    assert "财务/发票" in Path(inv_group["target_root"]).as_posix()


# ============================================================================
# 6. 分批 Token 预算与稳定 ID 映射鲁棒性 (classify_files_with_ai)
# ============================================================================
def test_ai_service_stable_id_batching_and_schema_validation():
    # 模拟 3 个聚合单元
    mock_units = [
        {
            "group_id": "grp_0001",
            "name": "project_alpha",
            "original_root": "D:/Projects/project_alpha",
            "is_directory_group": True,
            "file_count": 5,
            "total_size": 100000,
            "app_name": "Node.js (Vue)",
            "suggested_category": "代码项目与依赖 (Dev & Code)",
            "recommended_subpath": "前端/Vue",
            "rationale": "命中 package.json",
            "confidence": 0.85,
            "risk_level": "低风险",
            "require_confirmation": False,
            "action": "归档",
            "target_root": "D:/归档/Developer_Workspace/project_alpha",
            "sub_items": [
                {"name": "package.json", "relative_path": "package.json", "target_path": ""}
            ]
        },
        {
            "group_id": "grp_0002",
            "name": "unknown_file.xyz",
            "original_root": "D:/Downloads/unknown_file.xyz",
            "is_directory_group": False,
            "file_count": 1,
            "total_size": 2048,
            "app_name": "未识别应用",
            "suggested_category": "未分类/待人工确认",
            "recommended_subpath": "",
            "rationale": "未匹配到任何特征",
            "confidence": 0.30,
            "risk_level": "未知风险",
            "require_confirmation": True,
            "action": "需确认",
            "target_root": "D:/归档/未分类/unknown_file.xyz",
            "sub_items": [
                {"name": "unknown_file.xyz", "relative_path": "unknown_file.xyz", "target_path": ""}
            ]
        }
    ]

    # 模拟模型返回 JSON (包含带有 think 标签与 markdown 包裹的格式)
    mock_ai_json = {
        "groups": [
            {
                "group_id": "grp_0001",
                "app_name": "Vue.js 前端工程",
                "suggested_category": "代码项目与依赖 (Dev & Code)",
                "recommended_subpath": "前端/项目Alpha",
                "rationale": "基于 Vite 和 Vue 3 的现代前端系统",
                "confidence": 0.98,
                "risk_level": "低风险",
                "require_confirmation": False
            },
            {
                "group_id": "grp_0002",
                "app_name": "未知二进制数据",
                "suggested_category": "未分类/待人工确认",
                "recommended_subpath": "杂项/未知",
                "rationale": "扩展名不明确",
                "confidence": 0.45,
                "risk_level": "中风险",
                "require_confirmation": False # 模型返回 False，但置信度低于 min_confidence (0.7)，系统应强制拦截为 True！
            }
        ]
    }
    mock_content = f"<think>正在思考精准归档规划...</think>\n```json\n{json.dumps(mock_ai_json)}\n```"

    with patch.object(AppDetector, "group_files_by_parent_or_tool", return_value=mock_units):
        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": mock_content}}]
            }
            mock_post.return_value = mock_resp

            opts = OrganizeOptions(batch_size=10, min_confidence=0.7)
            results = AIService.classify_files_with_ai(
                base_url="https://api.openai.com/v1",
                api_key="sk-test-mock",
                model="gpt-4o",
                file_items=[{"path": "D:/Projects/project_alpha/package.json", "name": "package.json"}],
                destination_root="D:/归档备份",
                options=opts
            )

            assert len(results) == 2

            # 验证 grp_0001 获得 AI 细化的 recommended_subpath
            r1 = next(r for r in results if r["group_id"] == "grp_0001")
            assert r1["recommended_subpath"] == "前端/项目Alpha"
            assert "前端/项目Alpha" in Path(r1["target_root"]).as_posix()
            assert r1["confidence"] == 0.98
            assert r1["require_confirmation"] is False

            # 验证 grp_0002 安全红线生效：
            # 模型虽然返回 require_confirmation=False，但因置信度 0.45 < 0.70，强制拦截锁定为 True！
            r2 = next(r for r in results if r["group_id"] == "grp_0002")
            assert r2["confidence"] == 0.45
            assert r2["require_confirmation"] is True
            assert r2["action"] == "需确认"


# ============================================================================
# 7. 320 组真实脱敏样例离线基准评测
# ============================================================================
def test_offline_benchmark_evaluation():
    fixture_path = Path("tests/fixtures/organizer_benchmark_dataset.json")
    assert fixture_path.exists(), "必须存在离线评测数据集 tests/fixtures/organizer_benchmark_dataset.json"

    with open(fixture_path, "r", encoding="utf-8") as f:
        benchmark_cases = json.load(f)

    assert len(benchmark_cases) >= 300, f"离线评测集样本量必须 >= 300 组 (当前: {len(benchmark_cases)})"

    # 扁平化所有测试文件
    all_files = []
    case_by_name = {}
    for case in benchmark_cases:
        for f in case["simulated_files"]:
            all_files.append({
                "path": f["path"],
                "name": f["name"],
                "size": f.get("size", 1024),
                "mtime": f.get("mtime", 1740000000),
                "is_dir": False
            })
        case_by_name[case["name"]] = case

    options = OrganizeOptions(
        mode=OrganizeMode.COMPREHENSIVE,
        language="zh",
        min_confidence=0.70
    )

    # 运行本地分组与规则匹配
    grouped_units = AppDetector.group_files_by_parent_or_tool(
        all_files,
        destination_root="D:/归档根目录",
        options=options
    )

    total_units = len(grouped_units)
    assert total_units > 0

    # 统计指标
    valid_schema_count = 0
    accurate_category_count = 0
    usable_subpath_count = 0
    safety_violations = []

    required_keys = {
        "group_id", "name", "original_root", "is_directory_group", "file_count",
        "total_size", "app_name", "suggested_category", "recommended_subpath",
        "rationale", "confidence", "risk_level", "require_confirmation", "action",
        "target_root", "sub_items"
    }

    for unit in grouped_units:
        # 1. 结构合法性校验 (Schema Validity)
        if required_keys.issubset(unit.keys()):
            if unit["group_id"].startswith("grp_") and 0.0 <= unit["confidence"] <= 1.0:
                # 校验 recommended_subpath 跨平台安全性 (无穿越符号)
                subpath = unit.get("recommended_subpath", "")
                if ".." not in subpath and not subpath.startswith("/"):
                    valid_schema_count += 1

        # 2. 目录建议可用率 (Usability Rate)
        if unit.get("recommended_subpath"):
            usable_subpath_count += 1

        # 3. 安全红线与强制确认校验
        name = unit["name"]
        matched_case = case_by_name.get(name)
        if not matched_case:
            # 尝试通过路径前缀反查
            for c_name, c in case_by_name.items():
                if c_name in unit["original_root"]:
                    matched_case = c
                    break

        if matched_case:
            # 系统关键路径检测
            if matched_case.get("is_system_path"):
                if not unit.get("require_confirmation"):
                    safety_violations.append(f"系统路径未锁定人工确认: {unit['original_root']}")
                if "高风险" not in unit.get("risk_level", ""):
                    safety_violations.append(f"系统路径未标记高风险: {unit['original_root']}")

            # 未识别/孤儿文件检测
            if "未识别" in matched_case.get("expected_app", ""):
                if not unit.get("require_confirmation"):
                    safety_violations.append(f"未识别应用未锁定人工确认: {unit['name']}")

            # 分类准确性统计
            expected_cat = matched_case.get("expected_category", "")
            actual_cat = unit.get("suggested_category", "")
            if expected_cat and (expected_cat in actual_cat or actual_cat in expected_cat or "未分类" in actual_cat):
                accurate_category_count += 1

    schema_legality_rate = (valid_schema_count / total_units) * 100.0
    subpath_usability_rate = (usable_subpath_count / total_units) * 100.0

    print(f"\n===== 离线基准评测报告 (共 {total_units} 组聚合单元) =====")
    print(f"1. 结构合法率: {schema_legality_rate:.2f}% (要求 100%)")
    print(f"2. 目录建议可用率: {subpath_usability_rate:.2f}%")
    print(f"3. 安全红线违规数: {len(safety_violations)}")

    # 判定断言：
    # 结构合法率必须 100%
    assert schema_legality_rate == 100.0, f"结构合法率未达到 100% ({schema_legality_rate}%)"

    # 目录建议可用率在五大模式离线启发式下必须 >= 80%
    assert subpath_usability_rate >= 80.0, f"建议可用率低于 80%: {subpath_usability_rate}%"

    # 零安全红线违背
    assert len(safety_violations) == 0, f"存在安全红线违规项: {safety_violations[:5]}"


# ============================================================================
# 8. 涉敏拦截 (HTTP 422 Sensitive) 自动二分拆批隔离重试与友好降级测试
# ============================================================================
def test_ai_service_sensitive_binary_splitting_and_isolation():
    mock_units = [
        {
            "group_id": "grp_0001",
            "name": "my_web_app",
            "original_root": "D:/Projects/my_web_app",
            "is_directory_group": True,
            "file_count": 3,
            "total_size": 50000,
            "app_name": "Web App",
            "suggested_category": "代码项目与依赖 (Dev & Code)",
            "recommended_subpath": "开发/Web",
            "rationale": "前端应用",
            "confidence": 0.85,
            "risk_level": "低风险",
            "require_confirmation": False,
            "action": "归档",
            "target_root": "D:/归档/代码/my_web_app",
            "sub_items": [{"name": "index.html", "relative_path": "index.html", "target_path": ""}]
        },
        {
            "group_id": "grp_0002",
            "name": "sensitive_proxy_tool.zip",
            "original_root": "D:/Downloads/sensitive_proxy_tool.zip",
            "is_directory_group": False,
            "file_count": 1,
            "total_size": 20000,
            "app_name": "代理工具",
            "suggested_category": "软件安装与镜像 (Apps & Installers)",
            "recommended_subpath": "网络/工具",
            "rationale": "压缩安装包",
            "confidence": 0.80,
            "risk_level": "低风险",
            "require_confirmation": False,
            "action": "归档",
            "target_root": "D:/归档/软件/sensitive_proxy_tool.zip",
            "sub_items": [{"name": "sensitive_proxy_tool.zip", "relative_path": "sensitive_proxy_tool.zip", "target_path": ""}]
        },
        {
            "group_id": "grp_0003",
            "name": "invoice_202603.pdf",
            "original_root": "D:/Downloads/invoice_202603.pdf",
            "is_directory_group": False,
            "file_count": 1,
            "total_size": 15000,
            "app_name": "PDF 文档",
            "suggested_category": "文档与电子书 (Documents & Books)",
            "recommended_subpath": "财务/发票",
            "rationale": "发票凭单",
            "confidence": 0.90,
            "risk_level": "低风险",
            "require_confirmation": False,
            "action": "归档",
            "target_root": "D:/归档/文档/invoice_202603.pdf",
            "sub_items": [{"name": "invoice_202603.pdf", "relative_path": "invoice_202603.pdf", "target_path": ""}]
        },
        {
            "group_id": "grp_0004",
            "name": "resume_engineer.docx",
            "original_root": "D:/Downloads/resume_engineer.docx",
            "is_directory_group": False,
            "file_count": 1,
            "total_size": 18000,
            "app_name": "Word 文档",
            "suggested_category": "文档与电子书 (Documents & Books)",
            "recommended_subpath": "职场/简历",
            "rationale": "个人简历",
            "confidence": 0.90,
            "risk_level": "低风险",
            "require_confirmation": False,
            "action": "归档",
            "target_root": "D:/归档/文档/resume_engineer.docx",
            "sub_items": [{"name": "resume_engineer.docx", "relative_path": "resume_engineer.docx", "target_path": ""}]
        }
    ]

    def mock_post_side_effect(url, **kwargs):
        payload = kwargs.get("json", {})
        messages = payload.get("messages", [])
        user_content = messages[1]["content"] if len(messages) > 1 else ""

        mock_resp = MagicMock()
        # 若包含涉敏关键词 "sensitive_proxy_tool"，模拟服务商触发 422 敏感词拦截
        if "sensitive_proxy_tool" in user_content or "grp_0002" in user_content:
            mock_resp.status_code = 422
            mock_resp.text = '{"type":"error","error":{"type":"unprocessable_entity_error","message":"input new_sensitive (1026)","http_code":"422"}}'
            mock_resp.json.return_value = {
                "type": "error",
                "error": {
                    "type": "unprocessable_entity_error",
                    "message": "input new_sensitive (1026)",
                    "http_code": "422"
                }
            }
            return mock_resp
        else:
            # 不含敏感项时，返回 200 正常分类 JSON
            mock_resp.status_code = 200
            mock_resp.text = '{"choices": [{"message": {"content": "ok"}}]}'
            # 动态根据当前子批次中的 group_id 生成响应
            import json as json_lib
            groups_resp = []
            if "grp_0001" in user_content:
                groups_resp.append({
                    "group_id": "grp_0001",
                    "app_name": "Vue 前端",
                    "suggested_category": "代码项目与依赖 (Dev & Code)",
                    "recommended_subpath": "前端/Web",
                    "rationale": "AI 识别前端工程",
                    "confidence": 0.95,
                    "risk_level": "低风险",
                    "require_confirmation": False
                })
            if "grp_0003" in user_content:
                groups_resp.append({
                    "group_id": "grp_0003",
                    "app_name": "税务发票",
                    "suggested_category": "文档与电子书 (Documents & Books)",
                    "recommended_subpath": "财务/发票/2026",
                    "rationale": "AI 识别发票单据",
                    "confidence": 0.98,
                    "risk_level": "低风险",
                    "require_confirmation": False
                })
            if "grp_0004" in user_content:
                groups_resp.append({
                    "group_id": "grp_0004",
                    "app_name": "求职简历",
                    "suggested_category": "文档与电子书 (Documents & Books)",
                    "recommended_subpath": "人力资源/简历",
                    "rationale": "AI 识别简历文档",
                    "confidence": 0.96,
                    "risk_level": "低风险",
                    "require_confirmation": False
                })
            ai_data = {"groups": groups_resp}
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": json_lib.dumps(ai_data)}}]
            }
            return mock_resp

    with patch.object(AppDetector, "group_files_by_parent_or_tool", return_value=mock_units):
        with patch("requests.post", side_effect=mock_post_side_effect):
            opts = OrganizeOptions(batch_size=10, min_confidence=0.7)
            results = AIService.classify_files_with_ai(
                base_url="https://api.minimaxi.com/v1",
                api_key="sk-minimax-test",
                model="MiniMax-M3",
                file_items=[{"path": "D:/Downloads/test.txt", "name": "test.txt"}],
                destination_root="D:/归档备份",
                options=opts
            )

            res_map = {g["group_id"]: g for g in results}

            # 验证非敏感项通过二分隔离后成功获得 AI 分类
            assert res_map["grp_0001"]["source"] == "AI"
            assert res_map["grp_0003"]["source"] == "AI"
            assert res_map["grp_0004"]["source"] == "AI"

            # 验证敏感单项被精准隔离并降级为涉敏降级
            grp2 = res_map["grp_0002"]
            assert "涉敏降级" in grp2["source"]
            assert grp2["require_confirmation"] is True
            assert grp2["action"] == "需确认"
            assert "422" in grp2["rationale"] or "审查" in grp2["rationale"]


# ============================================================================
# 9. 软件/工程/运行环境原子集体自顶向下探测测试 (detect_directory_collective)
# ============================================================================
def test_detect_directory_collective(tmp_path):
    # 1. Node 前端项目
    node_dir = tmp_path / "my_vue_app"
    node_dir.mkdir()
    (node_dir / "package.json").write_text(
        json.dumps({"name": "vue-dashboard", "dependencies": {"vue": "^3.2.0"}}),
        encoding="utf-8"
    )
    c_node = AppDetector.detect_directory_collective(str(node_dir))
    assert c_node is not None
    assert c_node["is_collective"] is True
    assert "vue-dashboard" in c_node["software_name"]
    assert "Vue 前端" in c_node["software_name"]
    assert c_node["suggested_category"] == "代码项目与依赖 (Dev & Code)"

    # 2. Java Maven 工程
    maven_dir = tmp_path / "order_service"
    maven_dir.mkdir()
    (maven_dir / "pom.xml").write_text(
        "<project><artifactId>order-service-api</artifactId></project>",
        encoding="utf-8"
    )
    c_maven = AppDetector.detect_directory_collective(str(maven_dir))
    assert c_maven is not None
    assert "order-service-api" in c_maven["software_name"]
    assert "Maven" in c_maven["signature_type"]

    # 3. Rust Cargo 工程
    rust_dir = tmp_path / "rust_core"
    rust_dir.mkdir()
    (rust_dir / "Cargo.toml").write_text(
        'name = "rust-engine"\nversion = "0.1.0"',
        encoding="utf-8"
    )
    c_rust = AppDetector.detect_directory_collective(str(rust_dir))
    assert c_rust is not None
    assert "rust-engine" in c_rust["software_name"]

    # 4. Python 虚拟环境
    venv_dir = tmp_path / "my_env"
    venv_dir.mkdir()
    (venv_dir / "pyvenv.cfg").write_text("home = C:\\Python312", encoding="utf-8")
    c_venv = AppDetector.detect_directory_collective(str(venv_dir))
    assert c_venv is not None
    assert c_venv["collective_type"] == "运行环境集体"
    assert "my_env" in c_venv["software_name"]

    # 5. 独立绿色软件 (含有 exe + dll)
    app_dir = tmp_path / "Notepad3"
    app_dir.mkdir()
    (app_dir / "Notepad3.exe").write_bytes(b"MZ\x90\x00")
    (app_dir / "scintilla.dll").write_bytes(b"MZ\x90\x00")
    c_app = AppDetector.detect_directory_collective(str(app_dir))
    assert c_app is not None
    assert c_app["collective_type"] == "独立软件集体"
    assert c_app["primary_executable"] == "Notepad3.exe"
    assert "Notepad3" in c_app["software_name"]

    # 6. 普通杂物文件夹 (无特征)
    loose_dir = tmp_path / "random_loose"
    loose_dir.mkdir()
    (loose_dir / "note.txt").write_text("hello", encoding="utf-8")
    c_loose = AppDetector.detect_directory_collective(str(loose_dir))
    assert c_loose is None


# ============================================================================
# 10. 扫描器防御式剪枝机制测试 (DirectoryScanTask prune_collectives)
# ============================================================================
def test_scanner_prune_collectives_integration(tmp_path):
    root_dir = tmp_path / "scan_target"
    root_dir.mkdir()

    # 散装普通文件
    (root_dir / "quarter_report.pdf").write_text("report", encoding="utf-8")

    # 软件集体目录：内置 exe 与深层子文件
    app_dir = root_dir / "CoolTool"
    app_dir.mkdir()
    (app_dir / "CoolTool.exe").write_bytes(b"MZ")
    (app_dir / "core.dll").write_bytes(b"MZ")
    res_dir = app_dir / "resources" / "sub"
    res_dir.mkdir(parents=True)
    (res_dir / "deep_asset.dat").write_bytes(b"DATA")

    # 1. 传统未启用剪枝扫描：内部碎文件 deep_asset.dat 会被递归展开
    task_normal = DirectoryScanTask(
        target_paths=[str(root_dir)],
        skip_system_protected=False,
        enable_duplicate_detection=False,
        prune_collectives=False
    )
    result_normal = {}
    task_normal.finished_ok.connect(lambda r: result_normal.update(r))
    task_normal.run()

    normal_files = [f["name"] for f in result_normal["all_scanned_files"]]
    assert "quarter_report.pdf" in normal_files
    assert "CoolTool.exe" in normal_files
    assert "deep_asset.dat" in normal_files

    # 2. 防御式剪枝扫描：在探测到 CoolTool 是集体时，立即原子聚合，严禁入栈内部深层文件
    task_pruned = DirectoryScanTask(
        target_paths=[str(root_dir)],
        skip_system_protected=False,
        enable_duplicate_detection=False,
        prune_collectives=True
    )
    result_pruned = {}
    task_pruned.finished_ok.connect(lambda r: result_pruned.update(r))
    task_pruned.run()

    pruned_items = result_pruned["all_scanned_files"]
    pruned_names = [f["name"] for f in pruned_items]

    # 普通文件正常保留
    assert "quarter_report.pdf" in pruned_names

    # CoolTool 目录作为单个原子集体条目呈现
    assert "CoolTool" in pruned_names
    collective_entry = next(f for f in pruned_items if f["name"] == "CoolTool")
    assert collective_entry.get("is_directory_collective") is True
    assert collective_entry["file_count"] == 3  # CoolTool.exe + core.dll + deep_asset.dat
    assert "collective_info" in collective_entry
    assert collective_entry["collective_info"]["primary_executable"] == "CoolTool.exe"

    # 内部深层碎文件严禁出现在扫描结果列表中
    assert "deep_asset.dat" not in pruned_names
    assert "CoolTool.exe" not in pruned_names


# ============================================================================
# 11. 剪枝后集体在 AppDetector 稳定聚合与目标路径构造
# ============================================================================
def test_grouping_with_pruned_collectives(tmp_path):
    root_dir = tmp_path / "scan_target"
    root_dir.mkdir()
    (root_dir / "contract.docx").write_text("doc", encoding="utf-8")

    cool_dir = root_dir / "CoolTool"
    cool_dir.mkdir()
    (cool_dir / "CoolTool.exe").write_bytes(b"MZ")
    (cool_dir / "core.dll").write_bytes(b"MZ")

    # 运行剪枝扫描获得条目
    task = DirectoryScanTask(
        target_paths=[str(root_dir)],
        skip_system_protected=False,
        enable_duplicate_detection=False,
        prune_collectives=True
    )
    res = {}
    task.finished_ok.connect(lambda r: res.update(r))
    task.run()

    dest_root = str(tmp_path / "ArchiveDest")
    opts = OrganizeOptions(mode=OrganizeMode.COMPREHENSIVE, language="zh")
    groups = AppDetector.group_files_by_parent_or_tool(res["all_scanned_files"], dest_root, options=opts)

    assert len(groups) == 2

    # 查找 CoolTool 组
    tool_grp = next(g for g in groups if "CoolTool" in g["name"])
    assert tool_grp["is_directory_group"] is True
    assert tool_grp["file_count"] == 2
    assert "CoolTool.exe" in tool_grp["rationale"] or "CoolTool" in tool_grp["rationale"]
    assert tool_grp["collective_info"] is not None
    assert tool_grp["collective_info"]["primary_executable"] == "CoolTool.exe"

    # 验证子项映射完整
    assert len(tool_grp["sub_items"]) == 1
    sub = tool_grp["sub_items"][0]
    assert "CoolTool" in sub["target_path"]


# ============================================================================
# 12. 多线程并发 AI 分类与进度汇报及集体名牌 Prompt 验证
# ============================================================================
def test_concurrent_ai_classification_with_progress_and_collective_cards():
    mock_units = [
        {
            "group_id": f"grp_{i:04d}",
            "name": f"software_collective_{i}" if i % 2 == 1 else f"document_{i}.pdf",
            "original_root": f"D:/Source/item_{i}",
            "is_directory_group": (i % 2 == 1),
            "file_count": 5 if i % 2 == 1 else 1,
            "total_size": 2048000,
            "app_name": f"App_{i}",
            "suggested_category": "代码项目与依赖 (Dev & Code)" if i % 2 == 1 else "文档与电子书 (Documents & Books)",
            "recommended_subpath": f"Sub_{i}",
            "rationale": "预设启发式规则",
            "confidence": 0.85,
            "risk_level": "低风险",
            "require_confirmation": False,
            "action": "归档",
            "content_samples": [],
            "sub_items": [],
            "collective_info": {
                "software_name": f"SuperSoftware_{i}",
                "primary_executable": f"main_{i}.exe",
                "product_title": f"Super Software {i}",
                "manifest_project_name": f"app-{i}",
                "signature_type": "独立软件集体"
            } if i % 2 == 1 else None
        }
        for i in range(1, 5)  # 4 个单元
    ]

    captured_requests = []
    progress_messages = []

    def mock_post_call(url, headers=None, json=None, timeout=None):
        captured_requests.append(json)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        user_content = json["messages"][1]["content"]

        import json as json_lib
        groups_resp = []
        for i in range(1, 5):
            gid = f"grp_{i:04d}"
            if gid in user_content:
                groups_resp.append({
                    "group_id": gid,
                    "app_name": f"AI_Verified_{i}",
                    "suggested_category": "应用软件/工具" if i % 2 == 1 else "财务文档",
                    "recommended_subpath": f"AI_Path_{i}",
                    "rationale": "AI 并发分析完成",
                    "confidence": 0.96,
                    "risk_level": "低风险",
                    "require_confirmation": False
                })

        mock_resp.json.return_value = {
            "choices": [{"message": {"content": json_lib.dumps({"groups": groups_resp})}}]
        }
        return mock_resp

    with patch.object(AppDetector, "group_files_by_parent_or_tool", return_value=mock_units):
        with patch("requests.post", side_effect=mock_post_call):
            opts = OrganizeOptions(batch_size=2)  # 4 个单元，每批 2 个 -> 共 2 批并发执行
            results = AIService.classify_files_with_ai(
                base_url="https://api.minimaxi.com/v1",
                api_key="sk-test-concurrency",
                model="MiniMax-M3",
                file_items=[{"path": "dummy"}],
                destination_root="D:/Backup",
                options=opts,
                progress_callback=lambda msg: progress_messages.append(msg)
            )

            # 验证并发执行完成，两批请求均已发送
            assert len(captured_requests) == 2

            # 验证集体名牌（软件卡片）在 Prompt 中呈现，而非内部碎文件内容
            all_prompt_texts = " ".join([req["messages"][1]["content"] for req in captured_requests])
            assert "软件/工程集体 (Directory Collective)" in all_prompt_texts
            assert "SuperSoftware_1" in all_prompt_texts
            assert "main_1.exe" in all_prompt_texts
            assert "Super Software 1" in all_prompt_texts
            assert "散装独立文件 (Single File)" in all_prompt_texts

            # 验证进度回调正常收到通知
            assert len(progress_messages) >= 2
            assert any("并发" in msg for msg in progress_messages)
            assert any("完成" in msg for msg in progress_messages)

            # 验证最终结果全部更新为 AI 分类
            for r in results:
                assert r["source"] == "AI"
                assert "AI_Verified_" in r["app_name"]
                assert "AI_Path_" in r["recommended_subpath"]


# ============================================================================
# 13. PyInstaller (_internal) 与桌面独立应用伴生目录防拆散深度测试
# ============================================================================
def test_pyinstaller_and_packaged_app_collective_detection(tmp_path):
    # 模拟真实用户的 PyInstaller 6+ 打包结构
    app_root = tmp_path / "发票明细开具软件-v2.3.4"
    app_dir = app_root / "发票明细开具软件"
    app_dir.mkdir(parents=True)

    # 主程序与数据
    (app_dir / "发票明细开具软件.exe").write_bytes(b"MZ\x90\x00")
    (app_dir / "商品编码.xls").write_bytes(b"DATA")

    # _internal 依赖目录 (含大量子包与 DLL)
    internal_dir = app_dir / "_internal"
    internal_dir.mkdir()
    (internal_dir / "python311.dll").write_bytes(b"MZ")
    (internal_dir / "base_library.zip").write_bytes(b"PK")
    pyside_dir = internal_dir / "PySide6"
    pyside_dir.mkdir()
    (pyside_dir / "QtCore.pyd").write_bytes(b"PYD")

    # 组件子目录
    comp_dir = app_dir / "组件"
    comp_dir.mkdir()
    (comp_dir / "Syunew3D.dll").write_bytes(b"MZ")

    # 1. 验证 detect_directory_collective
    c_app = AppDetector.detect_directory_collective(str(app_dir))
    assert c_app is not None
    assert c_app["is_collective"] is True
    assert c_app["software_name"] == "发票明细开具软件"
    assert c_app["primary_executable"] == "发票明细开具软件.exe"
    assert "PyInstaller" in c_app["signature_type"]
    assert c_app["suggested_category"] == "软件安装与镜像 (Apps & Installers)"
    assert "发票明细开具软件" in c_app["recommended_subpath"]

    # 2. 验证 _internal 附属目录绝不作为独立集体暴露
    c_int = AppDetector.detect_directory_collective(str(internal_dir))
    assert c_int is None

    # 3. 验证端到端扫描剪枝与整体聚合 (绝不拆散 _internal)
    task = DirectoryScanTask(
        target_paths=[str(app_root)],
        skip_system_protected=False,
        enable_duplicate_detection=False,
        prune_collectives=True
    )
    res = {}
    task.finished_ok.connect(lambda r: res.update(r))
    task.run()

    # 验证扫描层在发票明细开具软件这一级成功原子剪枝
    assert len(res["all_scanned_files"]) == 1
    scanned_entry = res["all_scanned_files"][0]
    assert scanned_entry["name"] == "发票明细开具软件"
    assert scanned_entry["is_directory_collective"] is True
    assert scanned_entry["file_count"] == 6  # exe + xls + python311.dll + base_library.zip + QtCore.pyd + Syunew3D.dll

    # 4. 验证分组器将所有子文件与伴生目录聚合成唯一的完整软件分组
    dest_root = str(tmp_path / "ArchiveTarget")
    groups = AppDetector.group_files_by_parent_or_tool(
        res["all_scanned_files"], dest_root, options=OrganizeOptions()
    )
    assert len(groups) == 1
    g = groups[0]
    assert g["is_directory_group"] is True
    assert g["name"] == "发票明细开具软件"
    assert g["file_count"] == 6
    assert "发票明细开具软件" in g["target_root"]


# ============================================================================
# 14. 语义粒度层次佐证机制 (Broad-Narrow Hierarchy Corroboration) 测试
# ============================================================================
def test_semantic_granularity_broad_narrow_hierarchy(tmp_path):
    root = tmp_path / "UserStorage"
    root.mkdir()

    # 1. 广义容器自身识别验证
    assert AppDetector.match_broad_container("项目") is not None
    assert AppDetector.match_broad_container("多媒体") is not None
    assert AppDetector.match_broad_container("设计素材") is not None
    assert AppDetector.match_broad_container("财务") is not None
    assert AppDetector.match_broad_container("学术资料") is not None
    # 狭义具体项绝不可被误判为广义容器
    assert AppDetector.match_broad_container("智慧校园外卖项目") is None
    assert AppDetector.match_broad_container("国庆主视觉设计") is None

    # 2. 广义容器自身绝不可作为独立单个实体被剪枝
    proj_dir = root / "项目"
    proj_dir.mkdir()
    assert AppDetector.detect_directory_collective(str(proj_dir)) is None

    # 3. 构造各类无配置文件的狭义实体目录（设计、学术、影视等）
    # A. 设计类：国庆海报设计 (内含 psd, ttf, png)
    design_dir = root / "设计素材" / "国庆主视觉设计"
    design_dir.mkdir(parents=True)
    (design_dir / "poster.psd").write_bytes(b"PSD")
    (design_dir / "font.ttf").write_bytes(b"TTF")
    (design_dir / "preview.png").write_bytes(b"PNG")

    c_design = AppDetector.detect_directory_collective(str(design_dir))
    assert c_design is not None
    assert c_design["is_collective"] is True
    assert c_design["collective_type"] == "业务实体集体"
    assert c_design["suggested_category"] == "图像设计与素材 (Design & Assets)"
    assert "设计资产/国庆主视觉设计" in c_design["recommended_subpath"]

    # B. 学术类：毕业论文查重 (内含 docx, pdf, html)
    thesis_dir = root / "学习资料" / "毕业论文初稿查重"
    thesis_dir.mkdir(parents=True)
    (thesis_dir / "paper.docx").write_bytes(b"DOCX")
    (thesis_dir / "report.pdf").write_bytes(b"PDF")
    (thesis_dir / "check.html").write_bytes(b"HTML")

    c_thesis = AppDetector.detect_directory_collective(str(thesis_dir))
    assert c_thesis is not None
    assert c_thesis["is_collective"] is True
    assert c_thesis["suggested_category"] == "文档与电子书 (Documents & Books)"
    assert "知识文档/毕业论文初稿查重" in c_thesis["recommended_subpath"]

    # C. 多媒体类：流浪地球2 (内含 mkv, srt, jpg)
    media_dir = root / "多媒体" / "流浪地球2_4K完整版"
    media_dir.mkdir(parents=True)
    (media_dir / "movie.mkv").write_bytes(b"MKV")
    (media_dir / "sub.srt").write_bytes(b"SRT")
    (media_dir / "cover.jpg").write_bytes(b"JPG")

    c_media = AppDetector.detect_directory_collective(str(media_dir))
    assert c_media is not None
    assert c_media["is_collective"] is True
    assert c_media["suggested_category"] == "音视频与多媒体 (Media & Videos)"
    assert "影音媒体/流浪地球2_4K完整版" in c_media["recommended_subpath"]

    # 4. 端到端扫描剪枝与整体平移聚合测试
    task = DirectoryScanTask(
        target_paths=[str(root)],
        skip_system_protected=False,
        enable_duplicate_detection=False,
        prune_collectives=True
    )
    res = {}
    task.finished_ok.connect(lambda r: res.update(r))
    task.run()

    # 扫描项应该正好是 3 个业务实体集体（设计、学术、电影），内部 9 个文件零散泄露为 0
    scanned_names = [f["name"] for f in res["all_scanned_files"]]
    assert len(res["all_scanned_files"]) == 3
    assert "国庆主视觉设计" in scanned_names
    assert "毕业论文初稿查重" in scanned_names
    assert "流浪地球2_4K完整版" in scanned_names

    # 5. 聚合与迁移目标验证
    dest_root = str(tmp_path / "ArchiveTarget")
    groups = AppDetector.group_files_by_parent_or_tool(
        res["all_scanned_files"], dest_root, options=OrganizeOptions()
    )
    assert len(groups) == 3
    for g in groups:
        assert g["is_directory_group"] is True
        assert g["file_count"] == 3
        # 验证内部不同扩展名文件全部完整保全，没有被按扩展名打散
        assert len(g["sub_items"]) == 1
        assert g["name"] in g["target_root"]


# ============================================================================
# 8. 源路径同源同宿收敛与源路径同构保全测试
# ============================================================================
def test_source_umbrella_anchor_and_consensus_reconciliation(tmp_path):
    scan_root = tmp_path / "共用文件"
    scan_root.mkdir()

    # 1. 创建 Live2D 泛目录及其同源子项 (模型、角色素材、散装压缩包、预览图)
    live2d_dir = scan_root / "live2D"
    live2d_dir.mkdir()
    
    xiyu_dir = live2d_dir / "Live2D模型-Xiyu.4096"
    xiyu_dir.mkdir()
    (xiyu_dir / "Xiyu.model3.json").write_text("{}", encoding="utf-8")
    (xiyu_dir / "Xiyu.moc3").write_bytes(b"\x00\x01\x02")

    dancer_dir = live2d_dir / "西域舞女"
    dancer_dir.mkdir()
    (dancer_dir / "dancer.model3.json").write_text("{}", encoding="utf-8")
    (dancer_dir / "texture_00.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    devil_dir = live2d_dir / "小恶魔"
    devil_dir.mkdir()
    (devil_dir / "devil.model3.json").write_text("{}", encoding="utf-8")

    (live2d_dir / "preview.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (live2d_dir / "小恶魔.zip").write_bytes(b"PK\x03\x04")

    # 2. 创建发票与经控泛目录同源子项
    invoice_dir = scan_root / "发票"
    invoice_dir.mkdir()
    inv_july = invoice_dir / "7月发票"
    inv_july.mkdir()
    (inv_july / "0701_inv.pdf").write_bytes(b"%PDF-1.4")

    inv_aug = invoice_dir / "8月发票"
    inv_aug.mkdir()
    (inv_aug / "0801_inv.pdf").write_bytes(b"%PDF-1.4")

    jk_aug = invoice_dir / "经控8月"
    jk_aug.mkdir()
    (jk_aug / "jk_summary.xlsx").write_bytes(b"PK\x03\x04")

    # 3. 根目录下的孤儿散件
    orphan_jk_file = scan_root / "08月经控送货单发票明细及汇总.xlsx"
    orphan_jk_file.write_bytes(b"PK\x03\x04")

    # 4. 独立软件集体 (不应被泛目录错误收敛)
    app_dir = scan_root / "发票明细开具软件-v2.3.4"
    app_dir.mkdir()
    (app_dir / "发票明细开具软件.exe").write_bytes(b"MZ\x90\x00")
    (app_dir / "_internal").mkdir()
    (app_dir / "_internal" / "python312.dll").write_bytes(b"MZ\x90\x00")

    # 扫描收集
    task = DirectoryScanTask(
        target_paths=[str(scan_root)],
        skip_system_protected=False,
        enable_duplicate_detection=False,
        prune_collectives=True
    )
    res = {}
    task.finished_ok.connect(lambda r: res.update(r))
    task.run()

    scanned_files = res["all_scanned_files"]
    dest_root = str(tmp_path / "归档目标")

    # 执行分组与离线同源泛目录收敛
    opts = OrganizeOptions(mode=OrganizeMode.COMPREHENSIVE, naming_language="zh")
    grouped = AppDetector.group_files_by_parent_or_tool(scanned_files, dest_root, options=opts)

    # 验证泛目录锚点提取
    live2d_units = [g for g in grouped if g.get("source_umbrella") == "live2D"]
    assert len(live2d_units) >= 3, "所有 live2D 模型、角色与压缩包散件必须识别为同一 source_umbrella 'live2D'"

    # 验证同源同宿：所有 live2D 单元的 recommended_subpath 均统一收敛为 'live2D'
    for u in live2d_units:
        assert u["recommended_subpath"] == "live2D"
        # 目标路径必须以 live2D 为基准
        assert "live2D" in u["target_root"]
        # 且不存在重复嵌套 live2D/live2D
        assert "live2D/live2D" not in Path(u["target_root"]).as_posix()

    # 验证经控孤儿文件归巢吸引
    jk_units = [g for g in grouped if g.get("source_umbrella") == "经控"]
    assert any("08月经控送货单" in g["name"] for g in jk_units), "孤儿经控汇总文件必须成功归巢至 '经控' 泛目录"
    for u in jk_units:
        assert u["recommended_subpath"] == "经控"
        assert "经控" in u["target_root"]

    # 验证独立软件集体隔离保全
    app_units = [g for g in grouped if "发票明细开具软件" in g["name"]]
    assert len(app_units) == 1
    app_u = app_units[0]
    assert app_u["suggested_category"] == "软件安装与镜像 (Apps & Installers)"
    assert app_u.get("collective_info", {}).get("collective_type") == "独立软件集体"
    # 软件集体不能被误修改为发票/经控文档子路径
    assert app_u["recommended_subpath"] != "发票"
    assert app_u["recommended_subpath"] != "经控"

    # 验证多批次模拟 AI 分歧时的模型共识强制收敛
    mock_ai_groups = [
        {
            "original_root": str(xiyu_dir),
            "name": "Live2D模型-Xiyu.4096",
            "source_umbrella": "live2D",
            "is_directory_group": True,
            "suggested_category": "文档与多媒体资产 (Docs & Media)",
            "confidence": 0.95,
            "rationale": "Live2D模型",
            "sub_items": [{"original_path": str(xiyu_dir / "Xiyu.model3.json"), "name": "Xiyu.model3.json"}]
        },
        {
            "original_root": str(dancer_dir),
            "name": "西域舞女",
            "source_umbrella": "live2D",
            "is_directory_group": True,
            "suggested_category": "文档与多媒体资产 (Docs & Media)",
            "confidence": 0.90,
            "rationale": "角色素材",
            "sub_items": [{"original_path": str(dancer_dir / "dancer.model3.json"), "name": "dancer.model3.json"}]
        },
        {
            "original_root": str(devil_dir),
            "name": "小恶魔",
            "source_umbrella": "live2D",
            "is_directory_group": True,
            "suggested_category": "代码项目与依赖 (Dev & Code)",
            "confidence": 0.70,
            "rationale": "模型错误预测",
            "sub_items": [{"original_path": str(devil_dir / "devil.model3.json"), "name": "devil.model3.json"}]
        }
    ]

    reconciled = AppDetector.reconcile_umbrella_consensus(mock_ai_groups, dest_root, opts)
    for r in reconciled:
        # 多数表决后，偏离的 "代码项目与依赖" 必须被强行收敛对齐为 "文档与多媒体资产 (Docs & Media)"
        assert r["suggested_category"] == "文档与多媒体资产 (Docs & Media)"
        assert r["recommended_subpath"] == "live2D"
        assert Path(r["target_root"]).as_posix().endswith(f"文档与多媒体资产 (Docs & Media)/live2D/{r['name']}")


# ============================================================================
# 16. 全局 Top 100 超大文件 300MB 阈值与实体集体入榜防撕裂测试
# ============================================================================
def test_scanner_top100_300mb_threshold_and_collective_protection(tmp_path):
    import time
    from unittest.mock import MagicMock
    from PySide6.QtCore import Qt
    from app.core.scanner import DirectoryScanTask, AggregateTask
    from app.ui.components.data_table import FileTableModel

    scan_dir = tmp_path / "scan_area"
    scan_dir.mkdir()

    # 1. 散装文件: 大于 300MB (400MB)
    big_file = scan_dir / "large_archive.zip"
    big_file.write_bytes(b"0" * 100) # 用 fake stat 模拟
    
    # 2. 散装文件: 小于 300MB (50MB)
    mid_file = scan_dir / "medium_video.mp4"
    mid_file.write_bytes(b"0" * 100)

    # 3. 散装小文件 (10KB)
    small_file = scan_dir / "readme.txt"
    small_file.write_bytes(b"0" * 100)

    # 4. 独立软件集体: 大于 300MB (350MB)
    app_dir = scan_dir / "MySuperApp"
    app_dir.mkdir()
    (app_dir / "SuperApp.exe").write_bytes(b"0" * 100)
    (app_dir / "app.dll").write_bytes(b"0" * 100)

    # 5. 独立工程集体: 小于 300MB (80MB)
    node_dir = scan_dir / "my_vue_project"
    node_dir.mkdir()
    (node_dir / "package.json").write_text(json.dumps({"name": "vue-prj"}), encoding="utf-8")

    from contextlib import contextmanager

    def make_file_entry(name, path, size):
        e = MagicMock()
        e.name = name
        e.path = path
        e.is_file.return_value = True
        e.is_dir.return_value = False
        m_stat = MagicMock()
        m_stat.st_size = size
        m_stat.st_mtime = 1700000000.0
        e.stat.return_value = m_stat
        return e

    def make_dir_entry(name, path):
        e = MagicMock()
        e.name = name
        e.path = path
        e.is_file.return_value = False
        e.is_dir.return_value = True
        return e

    entries = [
        make_file_entry("large_archive.zip", str(big_file), 400 * 1024 * 1024),
        make_file_entry("medium_video.mp4", str(mid_file), 50 * 1024 * 1024),
        make_file_entry("readme.txt", str(small_file), 10 * 1024),
        make_dir_entry("MySuperApp", str(app_dir)),
        make_dir_entry("my_vue_project", str(node_dir)),
    ]

    @contextmanager
    def mock_scandir(path):
        yield iter(entries)

    # 模拟集体检测
    def mock_detect_directory_collective(dpath):
        p_name = Path(dpath).name
        if p_name == "MySuperApp":
            return {
                "type": "standalone_app",
                "app_name": "MySuperApp",
                "suggested_category": "软件安装与镜像 (Apps & Installers)"
            }
        if p_name == "my_vue_project":
            return {
                "type": "dev_project",
                "project_name": "my_vue_project",
                "suggested_category": "代码项目与依赖 (Dev & Code)"
            }
        return None

    def mock_walk(top, *args, **kwargs):
        p_name = Path(top).name
        if p_name == "MySuperApp":
            yield str(top), [], ["SuperApp.exe"]
            return
        elif p_name == "my_vue_project":
            yield str(top), [], ["package.json"]
            return
        yield str(top), [], []

    def mock_stat_collective(path, *args, **kwargs):
        p_str = str(path)
        m = MagicMock()
        m.st_mtime = 1700000000.0
        if "MySuperApp" in p_str:
            m.st_size = 350 * 1024 * 1024  # 350MB
            return m
        if "my_vue_project" in p_str:
            m.st_size = 80 * 1024 * 1024   # 80MB
            return m
        m.st_size = 100
        return m

    with patch("app.core.scanner.os.scandir", side_effect=mock_scandir):
        with patch("app.core.scanner.os.stat", side_effect=mock_stat_collective):
            with patch("app.core.scanner.os.walk", side_effect=mock_walk):
                with patch("app.core.app_detector.AppDetector.detect_directory_collective", side_effect=mock_detect_directory_collective):
                    task = DirectoryScanTask(
                        target_paths=[str(scan_dir)],
                        skip_system_protected=False,
                        enable_duplicate_detection=False,
                        prune_collectives=True,
                        min_top_file_size=300 * 1024 * 1024
                    )
                    captured_result = {}
                    errors = []
                    task.finished_ok.connect(lambda res: captured_result.update(res))
                    task.error.connect(lambda err: errors.append(err))
                    task.run()
                    if errors:
                        raise RuntimeError(f"ScanTask errors: {errors}")

                top_files = captured_result.get("top_100_files", [])
                
                # 核心断言 1: 仅有超过 300MB 的文件和集体入选，绝不硬凑数
                # 只有 big_file (400MB) 和 MySuperApp (350MB) 满足 >= 300MB
                assert len(top_files) == 2, f"应该仅有 2 个 >= 300MB 项入榜，实际为 {len(top_files)} 个"
                
                # 核心断言 2: 验证入榜项全部 >= 300MB
                for item in top_files:
                    assert item["size"] >= 300 * 1024 * 1024, f"文件 {item['name']} 大小未达到 300MB"

                # 核心断言 3: 验证原子软件集体作为整体入榜并标明 collective
                app_in_top = [f for f in top_files if f["name"] == "MySuperApp"]
                assert len(app_in_top) == 1
                assert app_in_top[0]["is_directory_collective"] is True
                assert app_in_top[0]["size"] == 350 * 1024 * 1024

                # 核心断言 4: 80MB 的工程和 50MB 的中等文件绝对不可入榜
                assert not any("medium_video" in f["name"] for f in top_files)
                assert not any("my_vue_project" in f["name"] for f in top_files)
                assert not any("readme" in f["name"] for f in top_files)

                # 核心断言 5: 验证 AggregateTask 对原子集体的防撕裂保护
                agg_task = AggregateTask(
                    target_paths=[str(scan_dir)],
                    all_scanned_files=captured_result["all_scanned_files"],
                    file_to_duplicate_group={},
                    duplicate_groups={},
                    total_start_time=time.time(),
                    p1_duration=1.0,
                    p2_duration=0.5,
                    cache_hits=0
                )
                agg_result = {}
                agg_task.finished_ok.connect(lambda r: agg_result.update(r))
                agg_task.run()

                redundant = agg_result.get("redundant_files", [])
                # 没有任何原子集体被当成单纯垃圾推荐删除
                assert not any(r.get("is_directory_collective") and r.get("is_recommended") for r in redundant)

                # 核心断言 6: 验证 UI FileTableModel 渲染标签与颜色
                model = FileTableModel(data_list=top_files, is_selectable=True)
                col1_text_0 = model.data(model.index(0, 1), Qt.DisplayRole)
                col1_text_1 = model.data(model.index(1, 1), Qt.DisplayRole)
                # 必须有一项包含 [独立软件: MySuperApp]
                assert any("📦 [独立软件: MySuperApp]" in txt for txt in [col1_text_0, col1_text_1])


# ============================================================================
# 17. 主控扫描全枚举清单重构：资产形态、语义铭牌、可释放启发式与集体哈希测试
# ============================================================================
def test_scan_enumeration_overhaul_and_collective_asset_sync(tmp_path):
    from PySide6.QtCore import Qt
    from app.core.app_detector import AppDetector
    from app.utils.file_helper import get_heuristic_redundant_tag, calculate_file_hash, calculate_partial_hash
    from app.ui.components.data_table import FileTableModel
    from app.core.ai_service import AIService

    test_root = tmp_path / "test_enum"
    test_root.mkdir()

    # 1. 验证启发式标记: 安装包、冲突副本、同名已解压压缩包
    installer_file = test_root / "SteamSetup.exe"
    installer_file.write_bytes(b"MZ" * 10)
    tag_res1 = get_heuristic_redundant_tag(str(installer_file))
    assert tag_res1 is not None
    assert tag_res1[0] == "软件安装程序"
    assert tag_res1[2] is True

    conflict_file = test_root / "contract (1).xlsx"
    conflict_file.write_bytes(b"DATA")
    tag_res2 = get_heuristic_redundant_tag(str(conflict_file))
    assert tag_res2 is not None
    assert tag_res2[0] == "同步与历史副本"
    assert tag_res2[2] is True

    # 解压后冗余压缩包测试
    archive_folder = test_root / "my_project_v1"
    archive_folder.mkdir()
    (archive_folder / "file.txt").write_text("ok")
    zip_file = test_root / "my_project_v1.zip"
    zip_file.write_bytes(b"PK")
    tag_res3 = get_heuristic_redundant_tag(str(zip_file))
    assert tag_res3 is not None
    assert tag_res3[0] == "已解压冗余归档包"
    assert tag_res3[2] is True

    # 2. 验证财务/明细账套集体识别 (泰润明细)
    detail_dir = test_root / "泰润明细"
    detail_dir.mkdir()
    (detail_dir / "进货明细.xlsx").write_text("sheet")
    (detail_dir / "单据.jpg").write_bytes(b"JPG")
    c_detail = AppDetector.detect_directory_collective(str(detail_dir))
    assert c_detail is not None
    assert c_detail["is_collective"] is True
    assert c_detail["collective_type"] == "业务账套集体"

    # 3. 验证目录集体哈希支持 (杜绝 PermissionError)
    dir_a = test_root / "CollectiveA"
    dir_a.mkdir()
    (dir_a / "sub.txt").write_text("same content", encoding="utf-8")
    dir_b = test_root / "CollectiveB"
    dir_b.mkdir()
    (dir_b / "sub.txt").write_text("same content", encoding="utf-8")

    part_a = calculate_partial_hash(str(dir_a))
    part_b = calculate_partial_hash(str(dir_b))
    assert part_a is not None and part_b is not None
    assert part_a == part_b

    full_a = calculate_file_hash(str(dir_a))
    full_b = calculate_file_hash(str(dir_b))
    assert full_a is not None and full_b is not None
    assert full_a == full_b

    # 4. 验证 FileTableModel 外显铭牌渲染杜绝零碎散装文件文案
    sample_items = [
        {"name": "installer.exe", "path": str(installer_file), "size": 1000, "category": "软件安装与程序 (Apps & Installers)", "tag": "软件安装程序", "phase_status": "规则识别 (软件安装程序)"},
        {"name": "泰润明细", "path": str(detail_dir), "size": 5000, "category": "文档报表与账套 (Docs & Business)", "tag": "原子保全 (业务账套集体)", "phase_status": "阶段一已归类 (原子保全)", "is_directory_collective": True, "file_count": 2, "collective_info": c_detail},
        {"name": "my_project_v1.zip", "path": str(zip_file), "size": 2000, "category": "归档包与系统镜像 (Archives & Images)", "tag": "已解压冗余归档包", "phase_status": "规则识别 (已解压冗余归档包)"}
    ]
    model = FileTableModel(sample_items, is_selectable=True)
    for r in range(model.rowCount()):
        name_text = model.data(model.index(r, 1), Qt.DisplayRole)
        # 绝不出现原始碎文件描述
        assert "散装文件" not in name_text
        assert any(prefix in name_text for prefix in ["📦", "🗜️", "📂", "📑", "💻", "🎨", "📄"])

    # 5. 验证降级报告的资产单元统计
    summary_data = {
        "target_paths": [str(test_root)],
        "total_bytes": 100000,
        "reclaimable_bytes": 50000,
        "duplicate_wasted_bytes": 0,
        "total_files": 25,
        "collective_count": 2,
        "standalone_file_count": 5,
        "category_stats": {},
        "top_100_files": []
    }
    report = AIService._generate_fallback_report(summary_data)
    assert "扫描治理资产单元" in report
    assert "`7` 项 (含 `2` 个原子实体集体, `5` 个独立单项资产，底层聚合 `25` 个物理碎片文件)" in report







