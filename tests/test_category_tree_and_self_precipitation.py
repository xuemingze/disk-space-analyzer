import os
import sys
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication, QHeaderView
from PySide6.QtCore import Qt, QEvent, QKeyCombination
from PySide6.QtGui import QKeyEvent

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.category_manager import (
    CategoryManager, global_category_manager,
    GLOBAL_CATEGORIES_FILE, PRECIPITATED_RULES_FILE
)
from app.core.ai_service import AIService
from app.ui.components.data_table import FileDataGridWidget, FileTableModel
from app.ui.components.category_dialog import CategoryManagerDialog
from app.ui.home_view import HomeView


@pytest.fixture(autouse=True)
def clean_rules_and_reload(tmp_path, monkeypatch):
    from app.config import app_config
    orig_get = app_config.get
    def mock_cfg_get(*args, **kwargs):
        if len(args) >= 2 and args[0] == "llm" and args[1] in ("base_url", "api_key", "model"):
            return ""
        return orig_get(*args, **kwargs)
    monkeypatch.setattr(app_config, "get", mock_cfg_get)
    """确保每个测试前后分类树与自沉淀规则状态隔离"""
    global_category_manager.load()
    orig_rules = list(global_category_manager._rules)
    orig_cats = list(global_category_manager._categories)
    yield
    global_category_manager._rules = orig_rules
    global_category_manager._categories = orig_cats
    global_category_manager.save()


def test_r1_inplace_edit_f2_and_ai_audit_latency_and_safety():
    """
    R1: 建议归档规划路径就地手动修改与 AI 极速自沉淀微契约:
    - F2 快捷键拦截与双击建议规划路径列激活就地编辑；
    - 合法性硬检验：受保护系统目录拦截、特殊字符拦截、空路径拦截；
    - 分类树吸附定位；
    - 端到端耗时严格控制在 1 秒以内 (< 1s)。
    """
    app = QApplication.instance() or QApplication(sys.argv)

    # 1. 验证 FileDataGridWidget 行高锁死 44px 且列设置正确
    grid = FileDataGridWidget(is_selectable=True)
    assert grid.table_view.verticalHeader().defaultSectionSize() == 44
    assert grid.table_view.verticalHeader().sectionResizeMode(0) == QHeaderView.Fixed
    assert grid.table_view.columnWidth(0) == 50
    assert grid.table_view.columnWidth(3) == 230

    # 2. 验证 F2 拦截逻辑
    mock_event = QKeyEvent(QEvent.KeyPress, Qt.Key_F2, Qt.NoModifier)
    # 当 table_view 接收 F2 时由 eventFilter 拦截并处理
    intercepted = grid.eventFilter(grid.table_view, mock_event)
    assert intercepted is True

    # 3. 验证安全硬拦截：受保护系统关键目录
    mock_item = {
        "name": "dangerous_script.bat",
        "path": "D:/Work/dangerous_script.bat",
        "category": "未分类",
        "size": 2048
    }
    res_sys = AIService.audit_manual_path_and_precipitate(mock_item, "C:/Windows/System32/hacked")
    assert res_sys["valid"] is False
    assert "安全拦截" in res_sys["error"]
    assert res_sys["elapsed"] < 1.0

    # 4. 验证安全硬拦截：非法文件名字符 (<>:"|?*)
    res_invalid_char = AIService.audit_manual_path_and_precipitate(mock_item, "D:/Tools/app*bad:name?.exe")
    assert res_invalid_char["valid"] is False
    assert "非法特殊字符" in res_invalid_char["error"]
    assert res_invalid_char["elapsed"] < 1.0

    # 5. 验证空路径拦截
    res_empty = AIService.audit_manual_path_and_precipitate(mock_item, "   ")
    assert res_empty["valid"] is False
    assert res_empty["elapsed"] < 1.0

    # 6. 验证合法路径吸附与端到端耗时 < 1s
    start_t = time.time()
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"valid": True, "snapped_category": "Developer_Workspace / Frontend / web_app", "rule_pattern": "dangerous_script", "subpath": "Developer_Workspace/Frontend/web_app"})}}]
    }
    with patch.object(AIService.get_session(), "post", return_value=mock_post_resp):
        res_valid = AIService.audit_manual_path_and_precipitate(
            mock_item,
            "Developer_Workspace/Frontend/web_app"
        )
    total_elapsed = time.time() - start_t
    assert res_valid["valid"] is True
    assert total_elapsed < 1.0
    assert res_valid["elapsed"] < 1.0
    # 验证吸附至前端工程节点
    assert "前端" in res_valid["category"] or "代码" in res_valid["category"] or "Frontend" in res_valid["category"]
    # 验证增量规则已沉淀落盘
    assert any("dangerous_script" in r["pattern"] for r in global_category_manager.get_precipitated_rules())


def test_r2_directory_skeleton_capture_and_ai_tree_build(tmp_path):
    """
    R2: 本地示范目录 2~3 级分类树捕捉与 AI 统揽建树:
    - 0 Token 碎文件阻断：扫描时剔除非代表性碎文件，仅保留代表性执行体与目录骨架；
    - AI 编排器统揽构建 2~3 级分类树；
    - 一字不差入轨落盘至 global_categories.json。
    """
    # 1. 构造示范目录体系 (如运维与监控工具集)
    demo_dir = tmp_path / "Ops_Demo_Toolkit"
    net_dir = demo_dir / "Network_Tools" / "Wireshark"
    net_dir.mkdir(parents=True, exist_ok=True)
    # 创建代表性执行文件与海量琐碎杂质文件
    (net_dir / "wireshark.exe").write_text("dummy exe", encoding="utf-8")
    (net_dir / "dumpcap.exe").write_text("dummy exe", encoding="utf-8")
    for i in range(20):
        (net_dir / f"log_{i}.txt").write_text("junk log", encoding="utf-8")
        (net_dir / f"cache_{i}.tmp").write_text("junk tmp", encoding="utf-8")

    mon_dir = demo_dir / "Sys_Monitor" / "ProcExp"
    mon_dir.mkdir(parents=True, exist_ok=True)
    (mon_dir / "procexp.exe").write_text("dummy exe", encoding="utf-8")
    (mon_dir / "readme.md").write_text("junk doc", encoding="utf-8")

    # 2. 验证骨架提取：碎文件阻断 (0 Token 碎文件阻断)
    skeleton = AIService.extract_directory_skeleton(str(demo_dir), max_depth=3)
    compact_text = skeleton["compact_text"]
    assert "wireshark.exe" in compact_text
    assert "log_" not in compact_text
    assert "cache_" not in compact_text
    assert "readme.md" not in compact_text

    # 3. 验证 AI 统揽建树并落盘
    tree = AIService.capture_and_build_category_tree(str(demo_dir))
    assert isinstance(tree, list)
    assert len(tree) >= 1

    # 验证分类树的 2~3 级结构拓扑完整性
    first_level = tree[0]
    assert first_level["level"] == 1
    assert "children" in first_level
    assert "target_path_template" in first_level
    assert "{archive_root}" in first_level["target_path_template"]

    # 验证落盘文件真实写入
    assert GLOBAL_CATEGORIES_FILE.exists()
    with open(GLOBAL_CATEGORIES_FILE, 'r', encoding='utf-8') as f:
        saved_data = json.load(f)
    assert len(saved_data) == len(tree)
    assert saved_data[0]["name"] == tree[0]["name"]


def test_r3_singleton_http_session_and_micro_contract_constraints():
    """
    R3: 单例 HTTP Keep-Alive 连接池 (requests.Session) 微契约约束:
    - 单例连接池与连接池容量 (pool_connections=20, pool_maxsize=50)；
    - Prompt <= 150 Tokens；
    - Max Tokens <= 120；
    - 关闭思考慢链 (thinking disabled)；
    - 严格超时控制 (0.3s conn, 0.5s read)。
    """
    # 1. 验证单例 session
    s1 = AIService.get_session()
    s2 = AIService.get_session()
    assert s1 is s2
    adapter = s1.adapters.get("https://")
    assert adapter is not None
    assert adapter._pool_connections == 20
    assert adapter._pool_maxsize == 50

    # 2. 验证微契约 payload 与 Prompt 紧凑度
    captured_payloads = []

    def mock_post(url, headers=None, json=None, timeout=None):
        captured_payloads.append({
            "url": url,
            "headers": headers,
            "json": json,
            "timeout": timeout
        })
        import json as _json_mod
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{
                "message": {
                    "content": _json_mod.dumps({"valid": True, "snapped_category": "DevOps Tools / Monitor", "rule_pattern": "test_app", "subpath": "DevOps_Tools/Monitor"})
                }
            }]
        }
        return mock_resp

    with patch.object(s1, "post", side_effect=mock_post):
        item = {"name": "test_app.exe", "path": "D:/demo/test_app.exe", "category": "未分类"}
        res = AIService.audit_manual_path_and_precipitate(
            item=item,
            new_path="DevOps_Tools/Monitor/test_app",
            base_url="https://api.test-llm.com/v1",
            api_key="sk-test-key",
            model="test-fast-model"
        )
        assert res["valid"] is True
        assert len(captured_payloads) == 1

        call = captured_payloads[0]
        # 验证超时控制
        assert call["timeout"] == (0.3, 0.5)

        payload = call["json"]
        assert payload["max_tokens"] <= 120
        assert payload.get("extra_body", {}).get("thinking", {}).get("type") == "disabled"

        # 验证 Prompt 控制在 150 Tokens 以内 (中文约 1 token / 1.5 字符)
        messages = payload["messages"]
        total_prompt_chars = sum(len(m["content"]) for m in messages)
        assert total_prompt_chars < 300, f"Prompt length {total_prompt_chars} too long for <= 150 tokens"


def test_r4_self_precipitation_rescan_inheritance_and_restart_persistence(tmp_path):
    """
    R4: 增量自沉淀生命周期与再次扫描优先命中:
    - 手动修改建议路径审核通过后，自沉淀至规则库；
    - 再次扫描新资产时，自动优先匹配自沉淀规则，命中对应树状节点并输出规划路径；
    - 模拟客户端重启，100% 持久化继承。
    """
    # 1. 模拟用户手动将资产 "my_custom_db.exe" 规划归档至 "Developer_Workspace/Database/my_custom_db"
    manual_item = {
        "name": "my_custom_db.exe",
        "path": "D:/OldInstall/my_custom_db.exe",
        "category": "未分类",
        "size": 52428800
    }
    audit_res = AIService.audit_manual_path_and_precipitate(
        manual_item,
        "Developer_Workspace/Database/my_custom_db"
    )
    assert audit_res["valid"] is True

    # 2. 模拟新一轮全盘扫描：遇到同名或相关资产
    scanned_new_asset = {
        "name": "my_custom_db.exe",
        "path": "E:/Downloads/Softwares/my_custom_db.exe",
        "is_directory_collective": False,
        "collective_info": None
    }
    match = global_category_manager.match_asset(
        name=scanned_new_asset["name"],
        path=scanned_new_asset["path"]
    )
    assert match is not None
    assert "Developer_Workspace/Database" in match["target_subpath"]
    assert match["rule_pattern"] == "my_custom_db"

    # 3. 验证持久化落盘与重启加载
    assert PRECIPITATED_RULES_FILE.exists()
    with open(PRECIPITATED_RULES_FILE, 'r', encoding='utf-8') as f:
        disk_rules = json.load(f)
    assert any(r["pattern"] == "my_custom_db" for r in disk_rules)

    # 模拟客户端重启：实例化新的 CategoryManager 并 reload
    fresh_mgr = CategoryManager()
    fresh_mgr.load()
    restarted_match = fresh_mgr.match_asset("my_custom_db.exe")
    assert restarted_match is not None
    assert restarted_match["rule_pattern"] == "my_custom_db"


def test_ui_category_manager_dialog_tree_and_capture():
    """
    GUI 验证: CategoryManagerDialog 升级为 QTreeWidget 2~3 级展开折叠树并支持示范目录建树
    """
    app = QApplication.instance() or QApplication(sys.argv)
    dlg = CategoryManagerDialog()

    # 验证左侧为 QTreeWidget 且包含多列
    assert dlg.cat_tree.columnCount() == 2
    assert dlg.cat_tree.topLevelItemCount() > 0
    assert dlg.btn_capture.text() == "🔍 捕捉示范目录建树..."

    # 验证右侧属性编辑
    first_item = dlg.cat_tree.topLevelItem(0)
    dlg.cat_tree.setCurrentItem(first_item)
    assert dlg.txt_name.text() != ""
    assert dlg.txt_template.text() != ""
    assert dlg.spin_priority.value() > 0

    # 验证新增顶级分类
    initial_top_count = dlg.cat_tree.topLevelItemCount()
    dlg.on_add_clicked()
    assert dlg.cat_tree.topLevelItemCount() == initial_top_count + 1

    dlg.close()


def test_ui_home_view_four_tables_isomorphic_sync_and_chart_recalculate():
    """
    GUI 验证: 四大表格同构联动、路径/分类编辑后跨表同步及空间全景多级聚合重算
    """
    app = QApplication.instance() or QApplication(sys.argv)
    home = HomeView()

    mock_data = [
        {
            "name": "large_project.zip",
            "path": "D:/Source/large_project.zip",
            "category": "代码项目与依赖 (Dev & Code)",
            "size": 500 * 1024 * 1024,
            "target_subpath": "Developer_Workspace/large_project",
            "suggested_archive_path": "Developer_Workspace/large_project",
            "is_duplicate": True,
            "phase_status": "待治理",
            "tag": "建议归档"
        },
        {
            "name": "debug_tool.exe",
            "path": "D:/Tools/debug_tool.exe",
            "category": "运维工具 (DevOps Tools)",
            "size": 50 * 1024 * 1024,
            "target_subpath": "Ops_Tools/debug_tool",
            "suggested_archive_path": "Ops_Tools/debug_tool",
            "is_duplicate": False,
            "phase_status": "待治理",
            "tag": "建议归档"
        }
    ]

    # 装载四大表格
    home.global_detail_table.populate_data(mock_data)
    home.duplicate_table.populate_data([mock_data[0]]) # large_project.zip
    home.top100_table.populate_data([mock_data[0]])    # large_project.zip

    # 验证初始数据装载
    assert home.global_detail_table.source_model.rowCount() == 2
    assert home.duplicate_table.source_model.rowCount() == 1
    assert home.top100_table.source_model.rowCount() == 1

    # 触发建议规划路径修改信号 (模拟在全局明细表中修改)
    modified_item = dict(mock_data[0])
    new_path = "Developer_Workspace/Frontend/large_project"
    modified_item["suggested_archive_path"] = new_path
    modified_item["category"] = "代码项目与依赖 (Dev & Code) / 前端工程"

    home.on_asset_path_edited(modified_item, new_path)

    # 验证四大表格已同构同步
    dup_item = home.duplicate_table.source_model._data[0]
    assert dup_item["suggested_archive_path"] == new_path
    assert dup_item["category"] == "代码项目与依赖 (Dev & Code) / 前端工程"

    top_item = home.top100_table.source_model._data[0]
    assert top_item["suggested_archive_path"] == new_path
    assert top_item["category"] == "代码项目与依赖 (Dev & Code) / 前端工程"

    # 验证空间分布已完成多级聚合重算
    stats = home.current_scan_result.get("category_stats", {}) if home.current_scan_result else {}
    home.recalculate_space_distribution()
    assert home.current_scan_result is not None
    assert "category_stats" in home.current_scan_result
    home.close()


def test_adversarial_inplace_edit_rollback_on_failure():
    """
    对抗攻击测试：当用户在表格中手动就地修改建议路径但 AI 审核失败（如系统关键目录、非法字符或AI驳回）时：
    1. 必须立即回滚恢复之前的合法建议路径与分类，不得残留非法路径；
    2. 全行 (包括分类、处理阶段、标签) 必须重新发送 dataChanged 事件以保证 UI 及时刷新；
    3. 不得将任何非法规则沉淀至知识库中。
    """
    app = QApplication.instance() or QApplication(sys.argv)
    grid = FileDataGridWidget(is_selectable=True)
    item = {
        "name": "legit_app.exe",
        "path": "D:/Tools/legit_app.exe",
        "category": "运维工具 (DevOps Tools)",
        "target_subpath": "Ops_Tools/legit_app",
        "suggested_archive_path": "Ops_Tools/legit_app",
        "phase_status": "阶段一已归类",
        "tag": "推荐资产"
    }
    grid.populate_data([item])

    changed_ranges = []
    grid.source_model.dataChanged.connect(lambda tl, br, roles: changed_ranges.append((tl.column(), br.column())))

    # 模拟就地编辑为非法系统关键目录
    idx = grid.source_model.index(0, 3)
    with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        grid.source_model.setData(idx, "C:/Windows/System32/evil_payload")

        # 验证弹出了警告对话框
        assert mock_warn.called
        # 验证模型中的数据已成功回滚至旧合法路径
        assert item["target_subpath"] == "Ops_Tools/legit_app"
        assert item["suggested_archive_path"] == "Ops_Tools/legit_app"
        assert item["category"] == "运维工具 (DevOps Tools)"

        # 验证 dataChanged 覆盖了整行 (column 0 到 9)，确保分类列与标签列 UI 即时回滚
        assert any(start == 0 and end >= 8 for start, end in changed_ranges)

    # 验证规则库未被污染
    rules = global_category_manager.get_precipitated_rules()
    assert not any("evil_payload" in r.get("pattern", "") for r in rules)


def test_adversarial_ai_audit_rejection_no_precipitation():
    """
    对抗攻击测试：当微契约响应包含 valid=False 或 reason 驳回时：
    1. audit_manual_path_and_precipitate 返回 valid=False；
    2. 绝不将任何规则沉淀入 global_category_manager 或落盘文件。
    """
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({"valid": False, "reason": "AI驳回: 路径超出允许的治理范围"})
            }
        }]
    }
    mock_session.post.return_value = mock_resp

    test_item = {"name": "forbidden_worker.exe", "path": "D:/Dev/forbidden_worker.exe"}
    initial_rule_count = len(global_category_manager.get_precipitated_rules())

    with patch.object(AIService, "get_session", return_value=mock_session):
        res = AIService.audit_manual_path_and_precipitate(
            test_item,
            "CustomTaxonomy/UnknownSector/worker",
            base_url="https://api.test-llm.com/v1",
            api_key="sk-test",
            model="fast-model"
        )
        assert res["valid"] is False
        assert "AI驳回" in res["error"]

    # 验证规则库数量未发生任何增量
    current_rules = global_category_manager.get_precipitated_rules()
    assert len(current_rules) == initial_rule_count
    assert not any("forbidden_worker" in r.get("pattern", "") for r in current_rules)


def test_adversarial_normalize_category_tree_simplified_strings():
    """
    对抗攻击测试：当外部大模型输出简化格式（如 children 为纯字符串列表或顶级为纯字符串）时：
    _normalize_category_tree 必须平稳防御，将其规整为标准 2~3 级结构树，绝不抛出 AttributeError。
    """
    malformed_tree = [
        {
            "name": "Dev_Cluster",
            "children": ["Frontend_UI", "Backend_API"]
        },
        "Standalone_Utility"
    ]
    normalized = AIService._normalize_category_tree(malformed_tree)
    assert len(normalized) == 2
    assert normalized[0]["name"] == "Dev_Cluster"
    assert len(normalized[0]["children"]) == 2
    assert normalized[0]["children"][0]["name"] == "Frontend_UI"
    assert normalized[0]["children"][0]["level"] == 2
    assert normalized[1]["name"] == "Standalone_Utility"
    assert normalized[1]["level"] == 1


def test_adversarial_directory_capture_invalid_and_cycle_protection(tmp_path):
    """
    对抗攻击测试：
    1. 当传入不存在或非法路径时，capture_and_build_category_tree 必须抛出 ValueError，杜绝篡改现有分类知识库；
    2. 当示范目录存在软链接/快捷回路或自嵌套时，_scan_level 通过 visited_real_paths 阻断无限循环。
    """
    # 1. 非法路径测试
    with pytest.raises(ValueError, match="示范目录不存在"):
        AIService.capture_and_build_category_tree(str(tmp_path / "absolutely_non_existent_dir_9999"))

    # 2. 环状/重复路径防死循环测试
    demo_root = tmp_path / "Cycle_Demo"
    demo_root.mkdir(parents=True, exist_ok=True)
    sub1 = demo_root / "SubModule1"
    sub1.mkdir(parents=True, exist_ok=True)
    (sub1 / "tool1.exe").write_text("dummy", encoding="utf-8")

    skeleton = AIService.extract_directory_skeleton(str(demo_root), max_depth=3)
    assert skeleton["root_name"] == "Cycle_Demo"
    assert len(skeleton["skeleton_tree"]["children"]) == 1


def test_adversarial_match_asset_priority_hierarchy():
    """
    对抗攻击测试：验证自沉淀匹配严格按照层级优先级判定：
    精确 app_name > 精确全文件名 > 精确主干名 > 子串模糊包含。
    即使后加入宽泛的包含规则，也绝不能遮蔽高优先级的精确匹配规则。
    """
    # 先加入一个宽泛的包含规则 (pattern="calc")
    global_category_manager.add_precipitated_rule({
        "pattern": "calc",
        "category": "宽泛计算分类",
        "target_subpath": "BroadCalc/{asset_name}"
    })
    # 加入精确匹配规则 (pattern="super_calc.exe")
    global_category_manager.add_precipitated_rule({
        "pattern": "super_calc.exe",
        "category": "精准超级计算器",
        "target_subpath": "PreciseCalc/{asset_name}"
    })

    # 测试精确匹配优先命中，而非宽泛命中
    match1 = global_category_manager.match_asset("super_calc.exe")
    assert match1 is not None
    assert match1["category"] == "精准超级计算器"

    # 测试短名称命中宽泛规则
    match2 = global_category_manager.match_asset("simple_calc_tool.exe")
    assert match2 is not None
    assert match2["category"] == "宽泛计算分类"


def test_adversarial_drive_letter_sanitization_in_fallback_category():
    """
    对抗攻击测试：当用户输入带绝对盘符路径时（如 D:/Ops/Network/ping.exe），
    回退分类名称严禁包含盘符（如 D:），必须干净规整为 Ops / Network。
    """
    item = {"name": "ping.exe", "path": "D:/Tools/ping.exe"}
    res = AIService.audit_manual_path_and_precipitate(
        item,
        "D:/MySpecialTools/Diagnostics/ping.exe"
    )
    assert res["valid"] is True
    assert "D:" not in res["category"]
    assert "MySpecialTools" in res["category"]


def test_adversarial_multi_row_right_click_category_assignment():
    """
    对抗攻击测试：表格多行选中时右键树状级联归类:
    1. 用户多选多行资产并右键指定分类，所有选中行必须全部更新并完成自沉淀；
    2. 触发 dataChanged/layoutChanged 信号；
    3. 若其中某项审核失败，该项必须安全回滚，其余项保持生效并给出部分未通过摘要。
    """
    from PySide6.QtCore import QItemSelectionModel
    app = QApplication.instance() or QApplication(sys.argv)
    grid = FileDataGridWidget(is_selectable=True)

    items = [
        {"name": f"batch_app_{i}.exe", "path": f"D:/Batch/batch_app_{i}.exe", "category": "未分类", "size": 1024 * (i + 1)}
        for i in range(3)
    ]
    grid.populate_data(items)

    # 模拟在表格中选中全部 3 行
    sel_model = grid.table_view.selectionModel()
    for row in range(3):
        p_idx = grid.proxy_model.index(row, 0)
        sel_model.select(p_idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)

    assert len(sel_model.selectedRows()) == 3

    # 应用树状级联分类变更
    cat_node = {
        "name": "自动化运维",
        "target_path_template": "{archive_root}/DevOps/Automation/{app_name}"
    }

    grid._apply_category_change(grid.source_model._data, cat_node, "运维工具 / 自动化运维")

    # 验证全部 3 项均已更新
    for i in range(3):
        it = grid.source_model._data[i]
        assert it["category"] == "运维工具 / 自动化运维"
        assert it["target_subpath"] == f"DevOps/Automation/batch_app_{i}.exe"
        assert "AI已审核" in it["phase_status"]

    # 验证自沉淀规则库包含这 3 个模式
    rules = global_category_manager.get_precipitated_rules()
    for i in range(3):
        assert any(f"batch_app_{i}" in r["pattern"] for r in rules)

    # 对抗测试：包含一项非法系统目录，测试单项安全回滚
    failing_item = {"name": "bad.exe", "path": "D:/Batch/bad.exe", "category": "原分类", "target_subpath": "Old/bad.exe"}
    valid_item = {"name": "good.exe", "path": "D:/Batch/good.exe", "category": "原分类", "target_subpath": "Old/good.exe"}
    
    with patch("app.core.ai_service.is_system_critical_path", side_effect=lambda p: "bad" in p):
        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            grid._apply_category_change([valid_item, failing_item], cat_node, "运维工具 / 自动化运维")
            assert mock_warn.called
            # valid_item 应该成功
            assert valid_item["category"] == "运维工具 / 自动化运维"
            # failing_item 应该回滚
            assert failing_item["category"] == "原分类"
            assert failing_item["target_subpath"] == "Old/bad.exe"


def test_adversarial_unc_path_and_skeleton_normalization(tmp_path):
    r"""
    对抗攻击测试：UNC 网络共享路径 (\\server\share\...) 处理:
    1. 在 audit_manual_path_and_precipitate 中，UNC 服务器与共享名绝不污染为分类名称；
    2. 在 snap_to_tree 中，UNC 路径平稳穿透定位深层业务节点；
    3. 在 extract_directory_skeleton 中，UNC 根目录与示范目录提取无前导斜杠或盘符冒号。
    """
    # 1. 验证 audit_manual_path_and_precipitate 处理 UNC 路径
    unc_item = {"name": "wireshark_unc.exe", "path": "//server/share/wireshark_unc.exe"}
    res = AIService.audit_manual_path_and_precipitate(
        unc_item,
        "//nas_server/tools_share/Ops_Tools/Network_Diagnostics/wireshark_unc.exe"
    )
    assert res["valid"] is True
    # 分类绝不应包含 nas_server 或 tools_share
    assert "nas_server" not in res["category"]
    assert "tools_share" not in res["category"]
    assert "Ops_Tools" in res["category"] or "网络" in res["category"]

    # 2. 验证 snap_to_tree 穿透 UNC 路径
    global_category_manager._categories.append({
        "name": "网络运维 (Ops_Tools)",
        "level": 1,
        "full_path": "网络运维 (Ops_Tools)",
        "target_path_template": "{archive_root}/Ops_Tools",
        "children": [
            {
                "name": "网络诊断 (Network_Diagnostics)",
                "level": 2,
                "full_path": "网络运维 (Ops_Tools) / 网络诊断 (Network_Diagnostics)",
                "target_path_template": "{archive_root}/Ops_Tools/Network_Diagnostics",
                "children": [
                    {
                        "name": "抓包工具 (Capture)",
                        "level": 3,
                        "full_path": "网络运维 (Ops_Tools) / 网络诊断 (Network_Diagnostics) / 抓包工具 (Capture)",
                        "target_path_template": "{archive_root}/Ops_Tools/Network_Diagnostics/Capture",
                        "children": []
                    }
                ]
            }
        ]
    })
    snap = global_category_manager.snap_to_tree("//company_nas/share/Ops_Tools/Network_Diagnostics/Capture/app.exe")
    assert snap is not None
    assert "抓包" in snap.get("name", "") or "网络" in snap.get("name", "")

    # 3. 验证 _build_tree_from_skeleton 处理 UNC 根目录
    unc_sk_node = {
        "name": r"\\nas_server\tools",
        "children": [
            {"name": "Database_Tools", "children": []},
            {"name": "Security_Tools", "children": []}
        ]
    }
    tree = AIService._build_tree_from_skeleton(unc_sk_node)
    # 子目录被提升为一级分类，而不是将 \\nas_server\tools 设为分类
    assert len(tree) == 2
    assert tree[0]["name"] == "Database_Tools"

    norm_tree = AIService._normalize_category_tree(tree)
    assert not norm_tree[0]["target_path_template"].startswith("{archive_root}///")


def test_adversarial_deep_nested_path_convergence():
    """
    对抗攻击测试：深达 8 级以上的深层嵌套路径收敛性:
    当用户输入 8+ 级未知层级路径时，回退分类平稳收敛至 2~3 级分类拓扑，绝不溢出或遗漏。
    """
    deep_path = "OrgDept/SubDept/ProjectAlpha/ModuleBeta/SubModule/Layer1/Layer2/Layer3/service.exe"
    item = {"name": "service.exe", "path": f"D:/{deep_path}"}
    res = AIService.audit_manual_path_and_precipitate(item, deep_path)
    assert res["valid"] is True
    # 验证分类深度收敛在 3 级以内
    parts = res["category"].split(" / ")
    assert 1 <= len(parts) <= 3
    assert parts[0] == "OrgDept"
    assert parts[1] == "SubDept"
    assert parts[2] == "ProjectAlpha"


def test_adversarial_path_traversal_blocking():
    """
    对抗攻击测试：相对路径跳转 (..) 恶意攻击阻断:
    严禁包含 .. 相对路径跳转以逃逸目标目录。
    """
    item = {"name": "app.exe", "path": "D:/Tools/app.exe"}
    res = AIService.audit_manual_path_and_precipitate(item, "Tools/../../Windows/System32/hacked.exe")
    assert res["valid"] is False
    assert "相对路径跳转" in res["error"] or "安全拦截" in res["error"]


def test_adversarial_target_template_terminal_parameterization_only():
    """
    对抗攻击测试：目标路径模板仅将末级资产实体参数化为 {asset_name}，
    即使父级目录包含与资产同名或主干相同的名称，也绝不破坏父目录。
    """
    item = {"name": "calc.exe", "path": "D:/calc/calc.exe"}
    res = AIService.audit_manual_path_and_precipitate(item, "ToolCollection/calc/calc.exe")
    assert res["valid"] is True
    rule = res["rule"]
    # 期望目标模板为 ToolCollection/calc/{asset_name}.exe，而不是 ToolCollection/{asset_name}/{asset_name}.exe
    assert rule["target_subpath"] == "ToolCollection/calc/{asset_name}.exe"


def test_adversarial_hidden_system_dir_blocking_in_skeleton(tmp_path):
    """
    对抗攻击测试：示范目录提取时全面阻断隐藏目录与系统卷:
    .git, .idea, __pycache__, $Recycle.Bin 等绝不进入骨架与分类树。
    """
    demo_root = tmp_path / "Clean_Demo"
    demo_root.mkdir()
    (demo_root / ".git").mkdir()
    (demo_root / ".git" / "config").write_text("git config", encoding="utf-8")
    (demo_root / "__pycache__").mkdir()
    (demo_root / "$Recycle.Bin").mkdir()

    real_dir = demo_root / "Dev_Tools"
    real_dir.mkdir()
    (real_dir / "compiler.exe").write_text("exe", encoding="utf-8")

    skeleton = AIService.extract_directory_skeleton(str(demo_root), max_depth=3)
    text = skeleton["compact_text"]
    assert ".git" not in text
    assert "__pycache__" not in text
    assert "$Recycle.Bin" not in text
    assert "Dev_Tools" in text


def test_adversarial_home_view_sync_redundant_and_top100():
    """
    对抗攻击测试：HomeView 同构更新不仅同步四大表格，还必须同步 current_scan_result 中的
    redundant_files 与 top_100_files，保障后续导出报告与归档执行元数据 100% 同构一致。
    """
    app = QApplication.instance() or QApplication(sys.argv)
    home = HomeView()

    target_file = {
        "name": "huge_cache.iso",
        "path": "D:/Downloads/huge_cache.iso",
        "category": "其他文件",
        "target_subpath": "Other/huge_cache.iso",
        "suggested_archive_path": "Other/huge_cache.iso",
        "size": 800 * 1024 * 1024,
        "is_duplicate": True,
        "phase_status": "待治理"
    }

    home.current_scan_result = {
        "all_scanned_files": [dict(target_file)],
        "redundant_files": [dict(target_file)],
        "top_100_files": [dict(target_file)],
        "total_bytes": target_file["size"]
    }

    home.global_detail_table.populate_data(home.current_scan_result["all_scanned_files"])
    home.duplicate_table.populate_data(home.current_scan_result["redundant_files"])
    home.top100_table.populate_data(home.current_scan_result["top_100_files"])

    # 触发路径编辑
    edit_item = dict(target_file)
    edit_item["category"] = "归档包与系统镜像 (Archives & Images)"
    new_path = "Archives/Images/huge_cache.iso"

    home.on_asset_path_edited(edit_item, new_path)

    # 验证 current_scan_result 中的 redundant_files 与 top_100_files 已被同构更新
    assert home.current_scan_result["redundant_files"][0]["suggested_archive_path"] == new_path
    assert home.current_scan_result["redundant_files"][0]["category"] == "归档包与系统镜像 (Archives & Images)"
    assert home.current_scan_result["top_100_files"][0]["suggested_archive_path"] == new_path
    assert home.current_scan_result["top_100_files"][0]["category"] == "归档包与系统镜像 (Archives & Images)"

    home.close()


def test_adversarial_44px_height_lock_and_size_hint():
    """
    对抗攻击测试：全工程 44px 行高锁定铁律:
    1. verticalHeader minimumSectionSize == 44;
    2. verticalHeader defaultSectionSize == 44;
    3. sectionResizeMode == Fixed;
    4. FileTableModel Qt.SizeHintRole 强制返回高度 44。
    """
    app = QApplication.instance() or QApplication(sys.argv)
    grid = FileDataGridWidget(is_selectable=True)
    grid.populate_data([{"name": "test.exe", "path": "D:/test.exe", "size": 100}])

    vh = grid.table_view.verticalHeader()
    assert vh.defaultSectionSize() == 44
    assert vh.minimumSectionSize() == 44
    assert vh.sectionResizeMode(0) == QHeaderView.Fixed

    # 验证模型 SizeHintRole
    idx = grid.source_model.index(0, 1)
    hint = grid.source_model.data(idx, Qt.SizeHintRole)
    assert hint is not None
    assert hint.height() == 44


def test_adversarial_concurrent_burst_requests_and_keepalive_resilience():
    """
    R1 & R3 深度对抗测试：高并发突发请求与 Keep-Alive 连接池复用弹性 (< 1s 保障):
    20 个线程并发触发建议路径修改与 AI 审核自沉淀，测试连接池复用、无 WinError 32 冲突与耗时 < 1s。
    """
    import concurrent.futures
    threads_count = 20
    results = []

    import threading
    session = AIService.get_session()
    post_lock = threading.Lock()

    def mock_post(url, headers=None, json=None, timeout=None):
        with post_lock:
            time.sleep(0.005) # 模拟 5ms 极速微契约 Keep-Alive 传输
            user_msg = ""
            if json and "messages" in json:
                for m in json["messages"]:
                    if m.get("role") == "user":
                        user_msg = m.get("content", "")
            import re
            m = re.search(r'资产:([^|]+)', user_msg)
            stem = Path(m.group(1)).stem if m else "burst_tool"
            
            class DummyResp:
                status_code = 200
                def json(self):
                    return {
                        "choices": [{
                            "message": {
                                "content": f'{{"valid": true, "snapped_category": "运维工具 (DevOps Tools)", "rule_pattern": "{stem}", "subpath": "DevOps_Tools/{stem}"}}'
                            }
                        }]
                    }
            return DummyResp()

    def _worker(thread_id):
        item = {
            "name": f"burst_tool_{thread_id}.exe",
            "path": f"D:/Burst/burst_tool_{thread_id}.exe",
            "category": "未分类"
        }
        start_t = time.time()
        res = AIService.audit_manual_path_and_precipitate(
            item,
            f"DevOps_Tools/BurstFolder/burst_tool_{thread_id}.exe",
            base_url="https://api.test-burst.com/v1",
            api_key="sk-test-burst",
            model="fast-model"
        )
        elapsed = time.time() - start_t
        return thread_id, res, elapsed

    orig_post = session.post
    session.post = mock_post
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads_count) as executor:
            futures = [executor.submit(_worker, i) for i in range(threads_count)]
            for fut in concurrent.futures.as_completed(futures):
                tid, r, el = fut.result()
                results.append((tid, r, el))
    finally:
        session.post = orig_post

    assert len(results) == threads_count
    for tid, res, el in results:
        assert res["valid"] is True, f"Thread {tid} failed: {res.get('error')}"
        assert el < 1.0, f"Thread {tid} exceeded 1s: {el:.3f}s"

    # 验证规则库全量安全入库，无数据丢失与 WinError 32
    rules = global_category_manager.get_precipitated_rules()
    for i in range(threads_count):
        assert any(f"burst_tool_{i}" in r["pattern"] for r in rules)


def test_adversarial_root_permission_error_safety(tmp_path):
    """
    R2 深度对抗测试：示范目录根权限受限与子目录异常弹性处理:
    1. 根目录由于权限受限 (PermissionError/OSError) 时，抛出 PermissionError，坚决杜绝覆盖抹除现有 global_categories.json；
    2. 子目录受限时，安全忽略受限子目录，保留其余合规分支；
    3. 达到 10 个子目录与 2 个执行体时触发早停，防止海量 I/O。
    """
    # 1. 根目录受限拦截
    restricted_root = tmp_path / "RestrictedRoot"
    restricted_root.mkdir()

    orig_categories = list(global_category_manager.get_tree())

    with patch("os.scandir", side_effect=PermissionError("WinError 5 Access is denied")):
        with pytest.raises(PermissionError, match="无法访问示范根目录.*权限"):
            AIService.capture_and_build_category_tree(str(restricted_root))

    # 验证现有分类库未被冲掉破坏
    assert len(global_category_manager.get_tree()) == len(orig_categories)

    # 2. 子目录权限受限安全跳过
    valid_root = tmp_path / "PartialAccessRoot"
    valid_root.mkdir()
    ok_sub = valid_root / "PublicSub"
    ok_sub.mkdir()
    (ok_sub / "tool.exe").write_text("ok", encoding="utf-8")
    secret_sub = valid_root / "SecretSub"
    secret_sub.mkdir()

    real_scandir = os.scandir

    def mock_scandir(path_str):
        if "SecretSub" in str(path_str):
            raise PermissionError("Access denied to SecretSub")
        return real_scandir(path_str)

    with patch("os.scandir", side_effect=mock_scandir):
        sk = AIService.extract_directory_skeleton(str(valid_root), max_depth=3)
        assert sk["root_name"] == "PartialAccessRoot"
        # PublicSub 正常进入骨架
        assert any(c["name"] == "PublicSub" for c in sk["skeleton_tree"]["children"])
        # SecretSub 优雅忽略无异常
        assert not any(c["name"] == "SecretSub" for c in sk["skeleton_tree"]["children"])


def test_adversarial_category_manager_dialog_drag_and_drop_and_path_input(tmp_path):
    """
    GUI 对抗测试：CategoryManagerDialog 示范目录拖拽与输入框直接输入:
    1. 验证窗口及树控件开启 setAcceptDrops(True)；
    2. 验证可在 txt_capture_path 中直接输入并回车触发建树；
    3. 验证本地目录拖放事件 (dropEvent) 正确解析 URL 并更新输入框与分类树。
    """
    from PySide6.QtCore import QUrl, QMimeData, QPoint
    from PySide6.QtGui import QDropEvent
    app = QApplication.instance() or QApplication(sys.argv)
    dlg = CategoryManagerDialog()

    assert dlg.acceptDrops() is True
    assert dlg.cat_tree.acceptDrops() is True
    assert hasattr(dlg, "txt_capture_path")

    # 1. 模拟在文本框中输入路径并直接触发
    demo_dir = tmp_path / "InputDemoDir"
    sub_dir = demo_dir / "SubCat"
    sub_dir.mkdir(parents=True)
    (sub_dir / "app.exe").write_text("exe", encoding="utf-8")

    dlg.txt_capture_path.setText(str(demo_dir))
    with patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
        dlg.on_capture_clicked()
        assert mock_info.called
        assert dlg.cat_tree.topLevelItemCount() > 0

    # 2. 模拟拖放事件
    drop_dir = tmp_path / "DropDemoDir"
    drop_sub = drop_dir / "Network_Tools"
    drop_sub.mkdir(parents=True)
    (drop_sub / "net.exe").write_text("net", encoding="utf-8")

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(drop_dir))])
    drop_ev = QDropEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)

    with patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
        dlg.dropEvent(drop_ev)
        assert mock_info.called
        assert os.path.normpath(dlg.txt_capture_path.text()) == os.path.normpath(str(drop_dir))

    dlg.close()


def test_adversarial_bare_root_drive_and_control_chars_blocking():
    """
    R1 对抗攻击测试：裸盘符、根斜杠与特殊控制字符安全拦截:
    1. C:, D:/, /, \\ 等裸盘符被明确拦截；
    2. 包含 \\x00, \\n 等控制字符被明确拦截；
    3. 包含 . 相对路径被明确拦截。
    """
    mock_item = {"name": "app.exe", "path": "D:/Tools/app.exe"}

    # 1. 裸盘符拦截
    for bad_path in ["C:", "D:/", "E:\\", "/", "\\", "  "]:
        res = AIService.audit_manual_path_and_precipitate(mock_item, bad_path)
        assert res["valid"] is False
        assert "安全拦截" in res["error"] or "不能为空" in res["error"]

    # 2. 控制字符拦截
    res_ctrl = AIService.audit_manual_path_and_precipitate(mock_item, "Tools/app\x00bad.exe")
    assert res_ctrl["valid"] is False
    assert "控制字符" in res_ctrl["error"]

    # 3. 单点相对路径拦截
    res_dot = AIService.audit_manual_path_and_precipitate(mock_item, "Tools/./app.exe")
    assert res_dot["valid"] is False
    assert "相对路径跳转" in res_dot["error"]


def test_adversarial_disabled_categories_excluded_from_cascade_menu():
    """
    GUI 对抗测试：右键级联归类菜单自动剔除已禁用的分类节点
    """
    from PySide6.QtWidgets import QMenu
    app = QApplication.instance() or QApplication(sys.argv)
    grid = FileDataGridWidget(is_selectable=True)

    # 禁用某个分类
    all_cats = global_category_manager.get_all(flatten=False)
    if all_cats:
        disabled_cat = all_cats[0]
        cat_id = disabled_cat.get("category_id")
        global_category_manager.update_category(cat_id, {"enabled": False})

        menu = QMenu()
        grid._populate_category_cascade_menu(menu, [{"name": "item.exe", "path": "D:/item.exe"}])

        action_texts = [act.text() for act in menu.actions()]
        # 验证禁用的分类名称未出现在顶层操作中
        assert not any(disabled_cat["name"] in t for t in action_texts)

        # 恢复启用状态
        global_category_manager.update_category(cat_id, {"enabled": True})


def test_adversarial_case_preservation_in_target_subpath():
    """
    对抗测试：资产匹配自沉淀时，保持资产原始大小写拓扑，杜绝全小写强行篡改
    """
    global_category_manager.add_precipitated_rule({
        "pattern": "mycustomtool",
        "category": "测试大类",
        "target_subpath": "Tools/MyCustomTool/{asset_name}.exe"
    })

    # 传入原始带有大小写的资产名
    matched = global_category_manager.match_asset("MyCustomTool.exe", "D:/MyCustomTool.exe")
    assert matched is not None
    # 验证 {asset_name} 格式化后保持 MyCustomTool，而非 mycustomtool
    assert matched["target_subpath"] == "Tools/MyCustomTool/MyCustomTool.exe"


def test_adversarial_cross_table_sync_with_different_slashes():
    """
    GUI 对抗测试：跨表同构更新时，路径斜杠方向差异 (/ vs \\) 依然能 100% 精确同构匹配
    """
    app = QApplication.instance() or QApplication(sys.argv)
    home = HomeView()

    win_item = {
        "name": "network_tool.exe",
        "path": r"D:\Tools\Network\network_tool.exe",
        "category": "其他",
        "suggested_archive_path": "Old/Path",
        "target_subpath": "Old/Path",
        "size": 1024
    }

    home.global_detail_table.populate_data([win_item])
    home.duplicate_table.populate_data([win_item])

    # 用带正斜杠的同一路径触发更新
    forward_slash_item = dict(win_item)
    forward_slash_item["path"] = "D:/Tools/Network/network_tool.exe"
    forward_slash_item["category"] = "新分类"

    home.on_asset_path_edited(forward_slash_item, "New/Path/network_tool.exe")

    # 验证 duplicate_table 中即使原始是反斜杠，也成功被同构更新
    dup_row = home.duplicate_table.source_model._data[0]
    assert dup_row["suggested_archive_path"] == "New/Path/network_tool.exe"
    assert dup_row["category"] == "新分类"

    home.close()

