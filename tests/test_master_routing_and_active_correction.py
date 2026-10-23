"""
拓扑主路由表主导、元数据三阶裁决、绝对纠偏与用户覆盖最高优先级回归测试集
(Test Master Routing, Active Correction, Metadata Arbitration & User Overwrite Law)

严格覆盖面向对象五大准则：
1. 路由表为主导与元数据三阶裁决 (Master Routing Table Dominance & Three-Tier Metadata Conflict Resolution)
2. 绝对纠偏而非静默降级 (Absolute Active Correction over Silent Downgrade)
3. 分析完成即写入 (Analysis-Time Immediate Precipitation)
4. 手动修改最高优先级强制覆盖 (User Override Absolute Overwrite Law: P1 > P2 > P3)
5. 人为可操控的 AI 审查机制与全域生态联动 (GUI, Import/Export & Policy Config)
"""

import os
import json
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure Qt offscreen for headless environments
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from app.core.domain_models import (
    TopologyRoutingTable, MasterRoutingRule, MorphologyType, KnowledgeProvenance,
    TopologyRole, TopologyPolicy, AuditCorrectionRecord, AIAuditPolicyConfig,
    MasterConflictResolver
)
from app.core.organize_models import OrganizeOptions, OrganizeMode
from app.core.app_detector import AppDetector
from app.core.ai_service import AIService


@pytest.fixture(autouse=True)
def clean_topology_table(tmp_path):
    """每个测试隔离使用独立的拓扑文件与 AI 审查配置文件"""
    test_file = tmp_path / "test_topology.json"
    test_policy = tmp_path / "test_ai_policy.json"

    TopologyRoutingTable.reset_instance_for_testing()
    table = TopologyRoutingTable.instance()
    table._file_path = test_file
    table._routes.clear()
    table._master_rules.clear()

    policy = AIAuditPolicyConfig.get_instance()
    policy._file_path = test_policy
    policy.enabled = True
    policy.confidence_threshold = 0.80
    policy.strict_strip_staging_containers = True
    policy.custom_instruction_prompt = ""

    yield table, policy

    TopologyRoutingTable.reset_instance_for_testing()


def test_three_tier_metadata_arbitration_and_active_correction(clean_topology_table):
    """
    准则 1 & 2: 路由表主导与元数据三阶裁决 + 绝对纠偏而非静默降级
    - 当资产具有强类型 PE 元数据时，元数据胜出；
    - 遭遇中转容器污染时，出具 AuditCorrectionRecord 绝对纠偏，严禁静默降级为猜测。
    """
    table, _ = clean_topology_table

    # 1. PE 元数据指明为 MotrixNext 下载器
    pe_meta = {
        "software_name": "MotrixNext",
        "publisher": "Motrix Team",
        "product_version": "2.1.0"
    }

    # 路径位于中转目录 "共用文件"
    cand_path = "D:/共用文件/MotrixNext_Setup.exe"
    cand_name = "MotrixNext_Setup.exe"

    resolution, rule, correction = MasterConflictResolver.resolve_asset_route(
        candidate_name=cand_name,
        candidate_path=cand_path,
        pe_metadata=pe_meta,
        is_directory=False
    )

    # 必须裁定为 PE 元数据胜出并触发纠偏
    assert resolution in ("METADATA_WINS", "METADATA_CORRECTED", "DIRECT_HIT")
    assert correction is not None
    assert correction.is_absolute_correction is True
    assert "[AI已纠偏" in correction.diagnostic_tag
    assert "中转" in correction.reason or "剥离" in correction.reason


def test_non_metadata_assets_delegate_to_ai_semantic(clean_topology_table):
    """
    准则 1: 缺少元数据的无结构资产 (照片、相册、个人录屏、零散文档)
    坚决绕开死板离线词典，由 AI 核心理解并编排，杜绝粗暴误杀。
    """
    table, _ = clean_topology_table

    media_assets = [
        ("IMG_20261022_120301.jpg", "D:/DCIM/Camera/IMG_20261022_120301.jpg"),
        ("Family_Trip_Tokyo.mp4", "D:/Videos/Family_Trip_Tokyo.mp4"),
        ("personal_diary.docx", "D:/Documents/personal_diary.docx"),
        ("random_clip.mov", "D:/Downloads/random_clip.mov")
    ]

    for name, fpath in media_assets:
        resolution, rule, correction = MasterConflictResolver.resolve_asset_route(
            candidate_name=name,
            candidate_path=fpath,
            pe_metadata=None,
            is_directory=False
        )
        assert resolution == "DELEGATE_TO_AI_SEMANTIC", f"媒体资产 {name} 未能委托 AI 语义裁决"


def test_analysis_time_immediate_precipitation(clean_topology_table):
    """
    准则 3: 分析完成即写入主路由表
    AI 分析完毕后，在弹出确认弹窗之前立即将高置信度规划提炼入主路由表，
    杜绝用户必须执行归档才能写入的重复用工问题。
    """
    table, _ = clean_topology_table

    mock_grouped_units = [
        {
            "group_id": "grp_0001",
            "name": "MotrixNext_v2.1.0.exe",
            "original_root": "D:/Downloads/MotrixNext_v2.1.0.exe",
            "is_directory_group": False,
            "source": "AI",
            "app_name": "MotrixNext",
            "suggested_category": "软件安装与程序 (Apps & Installers)",
            "recommended_subpath": "网络与下载",
            "rationale": "基于 PE 签名识别为 MotrixNext 下载客户端",
            "confidence": 0.95,
            "risk_level": "低风险",
            "require_confirmation": False,
            "action": "归档",
            "target_root": "D:/归档备份/软件安装与程序/网络与下载/MotrixNext_v2.1.0.exe",
            "sub_items": []
        },
        {
            "group_id": "grp_0002",
            "name": "project_antigravity",
            "original_root": "D:/Projects/project_antigravity",
            "is_directory_group": True,
            "source": "AI",
            "app_name": "Python/FastAPI",
            "suggested_category": "代码项目与依赖 (Dev & Code)",
            "recommended_subpath": "Python/FastAPI",
            "rationale": "检测到 pyproject.toml 与 FastAPI 代码结构",
            "confidence": 0.92,
            "risk_level": "低风险",
            "require_confirmation": False,
            "action": "归档",
            "target_root": "D:/归档备份/代码项目与依赖/Python/FastAPI/project_antigravity",
            "sub_items": []
        }
    ]

    # 执行分析完成即时沉淀
    precipitated_count = table.precipitate_ai_decisions(mock_grouped_units, min_confidence=0.8)
    assert precipitated_count == 2

    # 验证规则已成功持久化并进入主路由表
    rules = table.get_master_rules()
    patterns = [r.pattern for r in rules]
    assert any("motrixnext" in p.lower() for p in patterns)
    assert any("project_antigravity" in p.lower() for p in patterns)

    # 验证后续同类文件秒级 0-Token 命中
    matched = table.match_master_rule("MotrixNext_v3.0.0.exe")
    assert matched is not None
    assert matched.target_category == "软件安装与程序 (Apps & Installers)"
    assert matched.provenance == KnowledgeProvenance.AI_LEARNED


def test_user_override_absolute_overwrite_law(clean_topology_table):
    """
    准则 4: 手动修改最高优先级强制覆盖 (P1 USER_CONFIRMED > P2 AI_LEARNED > P3 SYSTEM_BUILTIN)
    用户就地修改分类或路径后，直接锁定为 USER_CONFIRMED，永不被 AI 自学覆盖。
    """
    table, _ = clean_topology_table

    # 1. 用户手动修改，确立 USER_CONFIRMED 规则
    user_rule = table.record_user_override(
        pattern_or_name="MotrixNext_*.exe",
        new_cat="自定义下载工具分类",
        new_target="我的专属路径/Motrix",
        morphology=MorphologyType.INDEPENDENT_ASSET
    )
    assert user_rule.provenance == KnowledgeProvenance.USER_CONFIRMED

    # 2. 模拟 AI 重新分析，试图以 AI_LEARNED 覆写该规则
    ai_attempt = MasterRoutingRule(
        rule_id="ai_001",
        pattern="MotrixNext_*.exe",
        morphology=MorphologyType.INDEPENDENT_ASSET,
        topology_role=TopologyRole.STAGING_BUCKET,
        target_category="被冲刷的AI分类",
        target_subpath_template="被冲刷的路径",
        provenance=KnowledgeProvenance.AI_LEARNED
    )
    # 尝试 upsert（非强制模式）
    success = table.upsert_master_rule(ai_attempt, force_override=False)
    assert success is False, "AI_LEARNED 绝不可覆写 USER_CONFIRMED 规则！"

    # 3. 验证规则仍然保留用户的原始定义
    matched = table.match_master_rule("MotrixNext_v2.5.0.exe")
    assert matched is not None
    assert matched.target_category == "自定义下载工具分类"
    assert matched.provenance == KnowledgeProvenance.USER_CONFIRMED


def test_export_and_import_master_rules(clean_topology_table, tmp_path):
    """
    准则 5: 路由表全量导入 (Import) 与导出 (Export)
    支持增量合并 (merge) 与完全覆盖 (overwrite)。
    """
    table, _ = clean_topology_table

    # 预置 2 条规则
    table.record_user_override("wechat.exe", "通讯工具", morphology=MorphologyType.INDEPENDENT_ASSET)
    table.record_user_override("qq.exe", "通讯工具", morphology=MorphologyType.INDEPENDENT_ASSET)

    # 导出文件
    export_json = tmp_path / "exported_rules.json"
    ok = table.export_master_rules(export_json)
    assert ok is True
    assert export_json.exists()

    with open(export_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["format"] == "DiskSpaceAnalyzer_MasterRoutingTable"
    assert len(data["master_rules"]) == 2

    # 增量导入测试
    import_candidate = tmp_path / "new_rules.json"
    new_payload = {
        "format": "DiskSpaceAnalyzer_MasterRoutingTable",
        "master_rules": [
            {
                "rule_id": "r_99",
                "pattern": "dingtalk.exe",
                "morphology": "independent_asset",
                "topology_role": "staging_bucket",
                "target_category": "企业办公与通讯",
                "target_subpath_template": "",
                "provenance": "user_confirmed",
                "hit_count": 5,
                "updated_at": time.time()
            }
        ]
    }
    with open(import_candidate, "w", encoding="utf-8") as f:
        json.dump(new_payload, f)

    imported, overwritten = table.import_master_rules(import_candidate, strategy="merge")
    assert imported == 1
    assert len(table.get_master_rules()) == 3

    # 完全覆盖导入测试
    imported2, overwritten2 = table.import_master_rules(import_candidate, strategy="overwrite")
    assert len(table.get_master_rules()) == 1
    assert table.get_master_rules()[0].pattern == "dingtalk.exe"


def test_ai_audit_policy_dialog_and_config(clean_topology_table):
    """
    准则 5: 人为操控的 AI 审查配置对话框与策略落盘
    """
    _, policy = clean_topology_table
    from app.ui.components.routing_table_viewer import AIAuditPolicyDialog

    dlg = AIAuditPolicyDialog()
    assert dlg.chk_enabled.isChecked() is True
    assert dlg.spin_conf.value() == 0.80

    # 修改配置并保存
    dlg.chk_strip.setChecked(True)
    dlg.spin_conf.setValue(0.85)
    dlg.txt_prompt.setPlainText("禁止在任何归档子路径中包含临时批次编号")
    dlg._save()

    saved_policy = AIAuditPolicyConfig.get_instance()
    assert saved_policy.confidence_threshold == 0.85
    assert "临时批次编号" in saved_policy.custom_instruction_prompt
    dlg.close()


def test_routing_table_viewer_dialog_initialization(clean_topology_table):
    """
    UI 铁律与知识库主视图呈现测试：
    1. verticalHeader().defaultSectionSize() 必须为 44px
    2. 支持主规则列表正确呈现
    """
    table, _ = clean_topology_table
    table.record_user_override("MotrixNext_*.exe", "软件安装与程序", morphology=MorphologyType.INDEPENDENT_ASSET)

    from app.ui.components.routing_table_viewer import RoutingTableViewerDialog
    viewer = RoutingTableViewerDialog()

    assert viewer.table.verticalHeader().defaultSectionSize() == 44
    assert viewer.table.rowCount() == 1
    item = viewer.table.item(0, 0)
    assert "MotrixNext_*.exe" in item.text()
    viewer.close()


def test_organize_preview_dialog_correction_badge_and_user_override(clean_topology_table):
    """
    UI 联动测试：
    1. OrganizePreviewDialog 中正确呈现 [AI已纠偏] 徽章与诊断提示；
    2. 就地编辑建议归档路径后，自动触发 TopologyRoutingTable.record_user_override 顶格覆写。
    """
    table, _ = clean_topology_table
    from app.ui.components.organize_dialog import OrganizePreviewDialog

    mock_items = [
        {
            "group_id": "grp_0001",
            "name": "MotrixNext_Setup.exe",
            "original_root": "D:/共用文件/MotrixNext_Setup.exe",
            "is_directory_group": False,
            "source": "AI",
            "action": "已纠偏",
            "correction_record": {
                "diagnostic_tag": "[AI已纠偏: 剥离中转名]",
                "reason": "已从目标路径中安全剥离中转容器名 '共用文件'"
            },
            "app_name": "MotrixNext",
            "suggested_category": "软件安装与程序 (Apps & Installers)",
            "recommended_subpath": "网络工具",
            "rationale": "基于 PE 元数据识别",
            "confidence": 0.95,
            "risk_level": "低风险",
            "require_confirmation": False,
            "target_root": "D:/归档备份/软件安装与程序/网络工具/MotrixNext_Setup.exe",
            "sub_items": []
        }
    ]

    dlg = OrganizePreviewDialog(
        classification_items=mock_items,
        destination_root="D:/归档备份",
        allow_execute=False
    )
    dlg.populate_tree()

    # 验证 [AI已纠偏] 徽章与气泡提示
    top_item = dlg.tree.topLevelItem(0)
    assert top_item is not None
    col1_text = top_item.text(1)
    assert "[AI已纠偏]" in col1_text
    assert top_item.text(8) == "已纠偏"
    assert "中转容器名" in top_item.toolTip(1)

    # 模拟用户双击/F2 就地编辑第 3 列 (规划路径)
    new_user_path = "D:/归档备份/极客专属软件/MotrixNext_Setup.exe"
    dlg._on_path_edited(top_item, new_user_path)

    # 必须以 USER_CONFIRMED 顶格写入主路由表
    matched = table.match_master_rule("MotrixNext_Setup.exe")
    assert matched is not None
    assert matched.provenance == KnowledgeProvenance.USER_CONFIRMED
    assert matched.target_subpath_template == new_user_path
    dlg.close()


def test_analysis_time_precipitation_from_direct_plan_and_preview_dialog(clean_topology_table):
    """
    问题 1 专项回归测试：
    验证无论是 convert_execution_plan_to_groups (source="AI (智能直出)") 还是进入 OrganizePreviewDialog，
    分析结果均 100% 自动即时沉淀写入主路由表。
    """
    table, _ = clean_topology_table

    exec_plan = [
        {
            "path": "D:/Downloads/MotrixNext_v2.5.0.exe",
            "name": "MotrixNext_v2.5.0.exe",
            "app_name": "MotrixNext",
            "suggested_category": "软件安装与程序 (Apps & Installers)",
            "target_subpath": "网络工具",
            "action": "归档",
            "confidence": 0.95
        }
    ]

    groups = AIService.convert_execution_plan_to_groups(exec_plan, "D:/归档备份")
    assert len(groups) == 1
    assert groups[0]["source"] == "AI (智能直出)"

    # 验证 convert_execution_plan_to_groups 执行后已即刻沉淀入主路由表
    matched = table.match_master_rule("MotrixNext_v2.5.0.exe")
    assert matched is not None
    assert matched.target_category == "软件安装与程序 (Apps & Installers)"
    assert matched.target_subpath_template == "网络工具"

    # 验证 OrganizePreviewDialog 打开也能兜底即时沉淀
    table._master_rules.clear()
    assert table.match_master_rule("MotrixNext_v2.5.0.exe") is None

    from app.ui.components.organize_dialog import OrganizePreviewDialog
    dlg = OrganizePreviewDialog(groups, "D:/归档备份", allow_execute=False)
    matched2 = table.match_master_rule("MotrixNext_v2.5.0.exe")
    assert matched2 is not None
    dlg.close()


def test_ai_audit_routing_page_and_sidebar_integration(clean_topology_table):
    """
    问题 2 & 3 专项回归测试：
    1. 验证 AI 审查设置与拓扑主路由子页面 (AiAuditRoutingPage) 正常初始化与配置保存，无报错；
    2. 验证左侧主菜单「自动化中心」子菜单包含「🌐 AI审查与拓扑路由」并无缝路由至子页面 4。
    """
    table, policy = clean_topology_table
    from app.ui.automation.ai_audit_routing_page import AiAuditRoutingPage
    from app.ui.main_window import MainWindow

    # 1. 验证子页面功能
    page = AiAuditRoutingPage()
    assert page.table.verticalHeader().defaultSectionSize() == 44
    assert page.chk_enabled.isChecked() is True

    page.txt_prompt.setText("统一采用财务年份与季度子目录")
    page.spin_conf.setValue(0.90)
    page._save_policy()

    saved_policy = AIAuditPolicyConfig.get_instance()
    assert saved_policy.confidence_threshold == 0.90
    assert "财务年份" in saved_policy.custom_instruction_prompt
    page.close()

    # 2. 验证 MainWindow 侧边栏联动
    win = MainWindow()
    # 验证子菜单包含 5 个按钮，第 5 个为 AI 审查与拓扑路由
    assert len(win.sub_nav_btns) == 5
    btn_ai, sub_idx = win.sub_nav_btns[4]
    assert sub_idx == 4
    assert "AI审查" in btn_ai.text()

    # 切换到自动化中心的第 4 子页面
    win.switch_view(2, sub_index=4)
    assert win.automation_view.sub_stack.currentIndex() == 4
    assert isinstance(win.automation_view.sub_stack.currentWidget(), AiAuditRoutingPage)
    win.close()


def test_routing_rule_edit_dialog_enum_coercion_and_refresh_table_no_crash(clean_topology_table):
    """
    专项回归测试：
    修复在 AiAuditRoutingPage / RoutingTableViewerDialog 中编辑主路由规则后，
    因 QComboBox.currentData() 将 (str, Enum) 退化为纯 str 导致 refresh_table()
    访问 r.morphology.value 抛出 AttributeError: 'str' object has no attribute 'value' 的崩溃。
    """
    table, _ = clean_topology_table
    from app.ui.automation.ai_audit_routing_page import AiAuditRoutingPage
    from app.ui.components.routing_table_viewer import RoutingRuleEditDialog, RoutingTableViewerDialog

    # 1. 验证 MasterRoutingRule 对纯字符串参数的强类型 Enum 自动收敛
    raw_rule = MasterRoutingRule(
        rule_id="r_str_01",
        pattern="SteamSetup*.exe",
        morphology="independent_asset",
        topology_role="staging_bucket",
        target_category="游戏娱乐",
        target_subpath_template="客户端",
        provenance="USER_CONFIRMED"
    )
    assert isinstance(raw_rule.morphology, MorphologyType)
    assert isinstance(raw_rule.topology_role, TopologyRole)
    assert isinstance(raw_rule.provenance, KnowledgeProvenance)

    table.upsert_master_rule(raw_rule, force_override=True)

    # 2. 模拟通过 RoutingRuleEditDialog 编辑并确认保存
    dlg = RoutingRuleEditDialog(raw_rule)
    dlg.edt_cat.setText("游戏")
    dlg._on_confirm()
    assert hasattr(dlg, "result_rule")
    assert isinstance(dlg.result_rule.morphology, MorphologyType)
    assert isinstance(dlg.result_rule.topology_role, TopologyRole)
    assert isinstance(dlg.result_rule.provenance, KnowledgeProvenance)

    table.upsert_master_rule(dlg.result_rule, force_override=True)

    # 3. 验证 AiAuditRoutingPage.refresh_table() 与 RoutingTableViewerDialog.refresh_table() 零异常刷新
    page = AiAuditRoutingPage()
    page.refresh_table()
    assert page.table.rowCount() == 1
    assert page.table.item(0, 1).text() == "独立资产"
    assert page.table.item(0, 4).text() == "游戏"
    page.close()

    viewer = RoutingTableViewerDialog()
    viewer.refresh_table()
    assert viewer.table.rowCount() == 1
    assert viewer.table.item(0, 1).text() == "独立资产"
    viewer.close()
    dlg.close()


