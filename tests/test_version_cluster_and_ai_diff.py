"""
tests/test_version_cluster_and_ai_diff.py
AI 语义多版本文档比对、聚类引擎与保留决策专项回归测试

覆盖以下测试范畴：
1. 面向对象领域模型 (VersionClusterItem, VersionClusterGroup, SemanticDiffDecision)
2. 词干提取与多版本后缀智能剥离 (VersionClusterDetector.extract_version_info)
3. 资产聚类与同族版本发现 (VersionClusterDetector.find_clusters & find_sibling_versions)
4. AI 语义比对微契约 (audit_similar_versions_with_ai) 成功与离线兜底不越权校验
5. GUI 对话框设计铁律测试 (行高 44px 锁死、禁用斑马纹、操作容器 28px)
"""

import os
import json
import pytest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication, QHeaderView

from app.core.domain_models import (
    ScannedAsset,
    VersionClusterItem,
    VersionClusterGroup,
    SemanticDiffDecision,
)
from app.core.version_cluster import VersionClusterDetector
from app.core.ai_service import AIService
from app.ui.components.version_diff_dialog import VersionDiffDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ==============================================================================
# 1. 领域模型测试
# ==============================================================================
def test_domain_models_version_cluster():
    item = VersionClusterItem(
        path="C:/docs/report_v2.docx",
        name="report_v2.docx",
        size=1024,
        mtime=1700000000.0,
        stem="report",
        version_suffix="_v2",
        category="文档",
        content_snippet="这是脱敏后的样本"
    )
    assert item.stem == "report"
    assert item["version_suffix"] == "_v2"
    assert item.get("size") == 1024

    d = item.to_dict()
    assert d["stem"] == "report"
    assert d["content_snippet"] == "这是脱敏后的样本"

    restored = VersionClusterItem.from_dict(d)
    assert restored.path == item.path
    assert restored.stem == item.stem

    group = VersionClusterGroup(
        group_id="cluster_001",
        normalized_stem="report",
        directory="C:/docs",
        items=[item]
    )
    assert group.group_id == "cluster_001"
    assert len(group.items) == 1

    gd = group.to_dict()
    assert len(gd["items"]) == 1
    assert gd["items"][0]["stem"] == "report"

    restored_grp = VersionClusterGroup.from_dict(gd)
    assert restored_grp.normalized_stem == "report"
    assert len(restored_grp.items) == 1
    assert isinstance(restored_grp.items[0], VersionClusterItem)


# ==============================================================================
# 2. 词干提取与多版本后缀智能剥离测试
# ==============================================================================
@pytest.mark.parametrize("file_name, expected_stem, expected_suffix", [
    ("年度财务结算报告_v1.docx", "年度财务结算报告", "_v1"),
    ("年度财务结算报告_v2_定稿.docx", "年度财务结算报告", "_v2_定稿"),
    ("需求规格说明书 (1).pdf", "需求规格说明书", " (1)"),
    ("需求规格说明书 (2).pdf", "需求规格说明书", " (2)"),
    ("main_backup.py", "main", "_backup"),
    ("main_draft.py", "main", "_draft"),
    ("数据清单_20231012.xlsx", "数据清单", "_20231012"),
    ("产品方案-修改版.pptx", "产品方案", "-修改版"),
    ("纯文本.txt", "纯文本", ""),
    ("archive_v1.2.tar.gz", "archive", "_v1.2"),
])
def test_extract_version_info(file_name, expected_stem, expected_suffix):
    stem, suffix = VersionClusterDetector.extract_version_info(file_name)
    assert stem == expected_stem
    assert suffix == expected_suffix


# ==============================================================================
# 3. 资产聚类识别与同族版本发现测试
# ==============================================================================
def test_find_clusters(tmp_path):
    f1 = tmp_path / "立项书_初稿.txt"
    f2 = tmp_path / "立项书_v2.txt"
    f3 = tmp_path / "立项书_定稿.txt"
    f4 = tmp_path / "独立不相干文件.txt"

    f1.write_text("立项初稿内容", encoding="utf-8")
    f2.write_text("立项第二版修改内容", encoding="utf-8")
    f3.write_text("立项最终定稿内容", encoding="utf-8")
    f4.write_text("孤立文件", encoding="utf-8")

    assets = [
        ScannedAsset(path=str(f1), name=f1.name, size=100),
        ScannedAsset(path=str(f2), name=f2.name, size=200),
        ScannedAsset(path=str(f3), name=f3.name, size=300),
        ScannedAsset(path=str(f4), name=f4.name, size=50),
    ]

    clusters = VersionClusterDetector.find_clusters(assets, extract_snippets=True, same_dir_only=True)
    assert len(clusters) == 1

    c = clusters[0]
    assert c.normalized_stem == "立项书"
    assert len(c.items) == 3
    # 验证脱敏样本提取
    for item in c.items:
        assert len(item.content_snippet) > 0


def test_find_sibling_versions(tmp_path):
    f1 = tmp_path / "测试文档_v1.txt"
    f2 = tmp_path / "测试文档_v2.txt"
    f1.write_text("内容1", encoding="utf-8")
    f2.write_text("内容2", encoding="utf-8")

    sibling_group = VersionClusterDetector.find_sibling_versions(str(f1), search_filesystem_if_empty=True)
    assert sibling_group is not None
    assert sibling_group.normalized_stem == "测试文档"
    assert len(sibling_group.items) == 2


# ==============================================================================
# 4. AI 语义比对与不越权降级测试
# ==============================================================================
def test_audit_similar_versions_with_ai_mock_success():
    item1 = VersionClusterItem(path="D:/docs/plan_v1.docx", name="plan_v1.docx", size=100, mtime=1000, stem="plan", version_suffix="_v1")
    item2 = VersionClusterItem(path="D:/docs/plan_final.docx", name="plan_final.docx", size=300, mtime=2000, stem="plan", version_suffix="_final")
    cluster = VersionClusterGroup(group_id="c1", normalized_stem="plan", directory="D:/docs", items=[item1, item2])

    fake_ai_resp = {
        "recommended_path": "D:/docs/plan_final.docx",
        "explanation": "plan_final.docx 具有更晚的修改时间和更完整的内容，推荐作为唯一正本保留。",
        "version_comparison": [
            {
                "path": "D:/docs/plan_final.docx",
                "version_tag": "_final",
                "difference_summary": "定稿正本",
                "retention_advice": "建议保留正本"
            },
            {
                "path": "D:/docs/plan_v1.docx",
                "version_tag": "_v1",
                "difference_summary": "历史早期草稿",
                "retention_advice": "建议归档历史"
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(fake_ai_resp)}}]
    }

    with patch.object(AIService, "get_session") as mock_session_getter:
        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp
        mock_session_getter.return_value = mock_session

        decision = AIService.audit_similar_versions_with_ai(
            cluster=cluster,
            base_url="https://api.fake.com",
            api_key="sk-fake",
            model="gpt-test"
        )

        assert decision.recommended_path == "D:/docs/plan_final.docx"
        assert decision.confidence == 1.0
        assert cluster.ai_evaluated is True
        assert cluster.recommended_keep_path == "D:/docs/plan_final.docx"
        assert item2.is_recommended_keep is True
        assert item1.is_recommended_keep is False
        assert item1.retention_action == "建议归档历史"


def test_audit_similar_versions_ai_offline_non_overreach():
    """方针三 (本地不抢功冒进): 当 AI 不可用时，严禁假冒 AI 裁决，ai_evaluated=False，留给用户自主定夺"""
    item1 = VersionClusterItem(path="D:/docs/a_v1.txt", name="a_v1.txt", size=100, mtime=1000, stem="a", version_suffix="_v1")
    item2 = VersionClusterItem(path="D:/docs/a_v2.txt", name="a_v2.txt", size=200, mtime=3000, stem="a", version_suffix="_v2")
    cluster = VersionClusterGroup(group_id="c2", normalized_stem="a", directory="D:/docs", items=[item1, item2])

    decision = AIService.audit_similar_versions_with_ai(
        cluster=cluster,
        base_url="", # 无 AI 配置
        api_key="",
        model=""
    )

    # 验证不越权：置信度为 0，标记未经过 AI 裁决
    assert decision.confidence == 0.0
    assert cluster.ai_evaluated is False
    assert "不越权" in decision.explanation or "未配置" in decision.explanation
    # 最新时间项作为物理事实基准参考
    assert cluster.recommended_keep_path == "D:/docs/a_v2.txt"


# ==============================================================================
# 5. GUI 对话框铁律测试
# ==============================================================================
def test_version_diff_dialog_gui_rules(qapp):
    item1 = VersionClusterItem(path="D:/docs/spec_v1.pdf", name="spec_v1.pdf", size=100, mtime=1000, stem="spec", version_suffix="_v1")
    item2 = VersionClusterItem(path="D:/docs/spec_v2.pdf", name="spec_v2.pdf", size=200, mtime=2000, stem="spec", version_suffix="_v2")
    cluster = VersionClusterGroup(group_id="c3", normalized_stem="spec", directory="D:/docs", items=[item1, item2])

    dlg = VersionDiffDialog(cluster, auto_start_ai=False)

    # 准则二 铁律 1: 锁死 44px 行高
    vh = dlg.table.verticalHeader()
    assert vh.defaultSectionSize() == 44
    assert vh.sectionResizeMode(0) == QHeaderView.Fixed

    # 准则二 铁律 2: 禁用斑马纹
    assert dlg.table.alternatingRowColors() is False

    # 验证列数
    assert dlg.table.columnCount() == 8
    assert dlg.table.rowCount() == 2

    # 验证操作栏容器与单选容器
    cell_w = dlg.table.cellWidget(0, 0)
    assert cell_w is not None
    assert cell_w.layout() is not None

    dlg.close()
