import os
import sys
import pytest

from app.core.domain_models import (
    ScannedAsset,
    AssetUnit,
    GovernancePlan,
    ScanSessionSummary,
)
from app.core.scan_pipeline import (
    ScanPipeline,
    ScanPipelineContext,
    FastMetadataDiscoveryStep,
    RedundancyHeuristicsStep,
)


def test_scanned_asset_property_and_dict_compatibility():
    """
    测试 ScannedAsset 领域模型的面向对象属性访问与字典向下兼容契约
    """
    asset = ScannedAsset(
        id="test_1",
        name="Docker.exe",
        path="C:/Program Files/Docker/Docker.exe",
        size=1024 * 1024 * 80,
        category="系统与运维工具",
        is_collective=False,
        target_subpath="系统与运维工具/Docker",
        tag="独立软件",
        reason="测试用例",
    )

    # 1. 强类型属性访问
    assert asset.name == "Docker.exe"
    assert asset.path == "C:/Program Files/Docker/Docker.exe"
    assert asset.size == 1024 * 1024 * 80
    assert asset.target_subpath == "系统与运维工具/Docker"

    # 2. 智能别名映射 (planning_path & suggested_archive_path -> target_subpath)
    assert asset.planning_path == "系统与运维工具/Docker"
    assert asset.suggested_archive_path == "系统与运维工具/Docker"
    assert asset.is_directory_collective is False

    # 3. 字典下标访问向下兼容
    assert asset["name"] == "Docker.exe"
    assert asset["path"] == "C:/Program Files/Docker/Docker.exe"
    assert asset["size"] == 1024 * 1024 * 80
    assert asset["planning_path"] == "系统与运维工具/Docker"
    assert asset["suggested_archive_path"] == "系统与运维工具/Docker"
    assert asset["is_directory_collective"] is False

    # 4. get() 方法向下兼容
    assert asset.get("name") == "Docker.exe"
    assert asset.get("planning_path") == "系统与运维工具/Docker"
    assert asset.get("non_existent_key", "default_val") == "default_val"
    assert "target_subpath" in asset
    assert "planning_path" in asset

    # 5. 就地修改属性与下标赋值同步
    asset["planning_path"] = "系统与运维工具/Docker_Desktop"
    assert asset.target_subpath == "系统与运维工具/Docker_Desktop"
    assert asset.planning_path == "系统与运维工具/Docker_Desktop"

    asset.target_subpath = "系统与运维工具/Docker_Community"
    assert asset["planning_path"] == "系统与运维工具/Docker_Community"


def test_scanned_asset_serialization_and_deserialization():
    """
    测试 ScannedAsset 的 to_dict() 与 from_dict() 零损失往返序列化
    """
    raw_dict = {
        "id": "asset_col_1",
        "name": "Navicat_Toolchain",
        "path": "D:/Dev/Navicat",
        "size": 500 * 1024 * 1024,
        "mtime": 1700000000.0,
        "file_count": 250,
        "is_directory_collective": True,
        "collective_type": "独立软件",
        "category": "开发与运维工具",
        "tag": "原子保全 (独立软件)",
        "reason": "检测为独立便携软件",
        "planning_path": "开发与运维工具/Navicat",
        "custom_metadata_field": "custom_val_123"
    }

    # 从字典还原强类型领域对象
    asset = ScannedAsset.from_dict(raw_dict)
    assert asset.is_collective is True
    assert asset.is_directory_collective is True
    assert asset.file_count == 250
    assert asset.target_subpath == "开发与运维工具/Navicat"
    assert asset["custom_metadata_field"] == "custom_val_123"

    # 导出为标准全字段字典
    exported = asset.to_dict()
    assert exported["is_directory_collective"] is True
    assert exported["is_collective"] is True
    assert exported["target_subpath"] == "开发与运维工具/Navicat"
    assert exported["planning_path"] == "开发与运维工具/Navicat"
    assert exported["custom_metadata_field"] == "custom_val_123"


def test_asset_unit_alias_compatibility():
    """
    验证 AssetUnit 作为 ScannedAsset 别名的向后兼容性
    """
    assert AssetUnit is ScannedAsset
    unit = AssetUnit(name="test.txt", path="C:/test.txt", size=100)
    assert isinstance(unit, ScannedAsset)
    assert unit.name == "test.txt"
    assert unit.get("size") == 100


def test_governance_plan_model():
    """
    测试 GovernancePlan 治理规划实体数据模型
    """
    plan = GovernancePlan(
        original_root="D:/Downloads/nginx-1.24.0",
        suggested_category="开发与运维工具/Web服务器",
        target_subpath="开发与运维工具/Web服务器/nginx-1.24.0",
        action="建议归档",
        confidence=0.98,
        risk_level="低风险",
        app_name="Nginx",
        is_collective=True,
        file_count=120,
        total_bytes=1024 * 1024 * 15,
    )
    assert plan.suggested_category == "开发与运维工具/Web服务器"
    d = plan.to_dict()
    assert d["confidence"] == 0.98
    restored = GovernancePlan.from_dict(d)
    assert restored.app_name == "Nginx"
    assert restored.is_collective is True


def test_scan_pipeline_execution_and_streaming_batches(tmp_path):
    """
    测试 ScanPipeline 流式管线执行与批量批次发射
    """
    # 构建测试临时目录结构
    test_dir = tmp_path / "pipeline_test"
    test_dir.mkdir()
    for i in range(15):
        sub = test_dir / f"file_{i}.log"
        sub.write_text("sample log content " * 10, encoding="utf-8")

    ctx = ScanPipelineContext(
        target_paths=[str(test_dir)],
        batch_size=5,
        min_top_file_size=10,  # 降低门槛测试 Top 大文件堆
    )

    batches = list(ScanPipeline.stream_batches(ctx))
    assert len(batches) >= 3  # 15 个文件分批产生
    all_streamed = [f for b in batches for f in b]
    assert len(all_streamed) == 15
    for item in all_streamed:
        assert isinstance(item, ScannedAsset)
        assert item.name.startswith("file_")

    assert ctx.summary is not None
    assert ctx.summary.total_files == 15
    assert ctx.summary.total_bytes > 0
    assert len(ctx.summary.all_scanned_files) == 15
