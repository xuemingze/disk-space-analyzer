import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Any, List

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.core.domain_models import (
    TopologyRole,
    TopologyPolicy,
    TopologyRoute,
    TopologyRoutingTable,
    AIAssetPayloadBuilder,
    ArchiveDestinationPath,
    ScannedAsset,
)
from app.core.app_detector import AppDetector
from app.core.organize_models import OrganizeOptions, OrganizeMode


def test_topology_routing_table_lpm_and_matching():
    """验证 TopologyRoutingTable 的基础匹配与最长前缀匹配 (LPM)"""
    table = TopologyRoutingTable.instance()

    # 1. 默认中转/原材料容器关键词匹配
    assert table.is_staging_bucket("共用文件") is True
    assert table.is_staging_bucket("Downloads") is True
    assert table.is_staging_bucket("桌面") is True
    assert table.is_staging_bucket("待整理") is True
    assert table.is_staging_bucket(r"D:\共用文件") is True
    assert table.is_staging_bucket(r"C:\Users\Admin\Downloads") is True

    # 2. 正常业务目录不属于中转容器
    assert table.is_staging_bucket("发票") is False
    assert table.is_staging_bucket("live2D") is False
    assert table.is_staging_bucket("财务报表") is False
    assert table.is_staging_bucket("07_系统工具") is False

    # 3. 最长前缀匹配 (LPM) 验证：
    # 容器外壳: D:/共用文件 -> STAGING_BUCKET
    # 嵌套应用: D:/共用文件/应用包/AweSun -> APP_COLLECTIVE (PRESERVE_ATOMIC)
    table.learn(
        r"D:\共用文件",
        role=TopologyRole.STAGING_BUCKET,
        policy=TopologyPolicy.STRIP_CONTAINER,
        source="builtin"
    )
    table.learn(
        r"D:\共用文件\应用包\AweSun",
        role=TopologyRole.APP_COLLECTIVE,
        policy=TopologyPolicy.PRESERVE_ATOMIC,
        source="ai"
    )

    # 普通松散文件命中父级 STAGING_BUCKET
    loose_route = table.match_route(r"D:\共用文件\Everything.exe")
    assert loose_route is not None
    assert loose_route.role == TopologyRole.STAGING_BUCKET
    assert loose_route.should_strip_from_target() is True

    # 嵌套应用目录中的文件通过 LPM 优先命中更细粒度的 APP_COLLECTIVE 规则
    nested_route = table.match_route(r"D:\共用文件\应用包\AweSun\SunloginClient.exe")
    assert nested_route is not None
    assert nested_route.role == TopologyRole.APP_COLLECTIVE
    assert nested_route.policy == TopologyPolicy.PRESERVE_ATOMIC
    assert nested_route.should_strip_from_target() is False


def test_topology_learning_and_persistence():
    """验证路由表的动态学习自沉淀与持久化重载"""
    # 使用临时文件测试持久化
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = Path(tmp_dir) / "test_topology.json"
        
        table = TopologyRoutingTable.instance()
        orig_file = table._file_path
        try:
            table._file_path = test_file
            table.reset_instance_for_testing()
            
            fresh_table = TopologyRoutingTable.instance()
            fresh_table._file_path = test_file
            
            # 学习新中转箱
            fresh_table.learn("自定义临时收集箱", role=TopologyRole.STAGING_BUCKET, policy=TopologyPolicy.STRIP_CONTAINER, source="ai")
            assert fresh_table.is_staging_bucket("自定义临时收集箱") is True
            assert test_file.exists()

            # 重新实例化验证重载继承
            TopologyRoutingTable.reset_instance_for_testing()
            reloaded_table = TopologyRoutingTable.instance()
            reloaded_table._file_path = test_file
            reloaded_table.load()
            
            assert reloaded_table.is_staging_bucket("自定义临时收集箱") is True
            route = reloaded_table.match_route("自定义临时收集箱")
            assert route is not None
            assert route.source == "ai"
        finally:
            table._file_path = orig_file
            TopologyRoutingTable.reset_instance_for_testing()


def test_archive_destination_path_purges_staging_containers():
    """验证 ArchiveDestinationPath 坚决剥离目标路径中的原材料/中转容器名"""
    dest_root = r"D:\归档备份"

    # 1. entity_name 传入原材料/中转容器 '共用文件'，坚决剔除
    dest1 = ArchiveDestinationPath.build(
        dest_root=dest_root,
        category="07_系统工具",
        subpath="",
        entity_name="共用文件",
        is_dir=True
    )
    norm1 = dest1.raw_path.replace("\\", "/")
    assert "共用文件" not in norm1
    assert norm1.endswith("07_系统工具")

    # 2. subpath 中传入原材料/中转容器 '共用文件'，坚决剔除
    dest2 = ArchiveDestinationPath.build(
        dest_root=dest_root,
        category="07_系统工具",
        subpath="共用文件",
        entity_name="",
        is_dir=False
    )
    norm2 = dest2.raw_path.replace("\\", "/")
    assert "共用文件" not in norm2
    assert norm2.endswith("07_系统工具")

    # 3. subpath 为复合路径 '07_系统工具/共用文件'，中转容器段被清洗，重复段被折叠
    dest3 = ArchiveDestinationPath.build(
        dest_root=dest_root,
        category="07_系统工具",
        subpath="07_系统工具/共用文件",
        entity_name="",
        is_dir=False
    )
    norm3 = dest3.raw_path.replace("\\", "/")
    assert "共用文件" not in norm3
    assert norm3.endswith("07_系统工具")

    # 4. 真正独立的软件集体 (AweSun, WeChat) 作为 entity_name，必须被完整保全
    dest4 = ArchiveDestinationPath.build(
        dest_root=dest_root,
        category="04_远程控制",
        subpath="",
        entity_name="AweSun",
        is_dir=True
    )
    norm4 = dest4.raw_path.replace("\\", "/")
    assert norm4.endswith("04_远程控制/AweSun")

    # 5. 散装安装包单项 (Everything-1.4.1.exe)，is_dir=False 时只归入分类目录，文件名由 relative_join 拼接
    dest5 = ArchiveDestinationPath.build(
        dest_root=dest_root,
        category="07_系统工具",
        subpath="",
        entity_name="Everything-1.4.1.exe",
        is_dir=False
    )
    target_file = dest5.relative_join("Everything-1.4.1.exe").replace("\\", "/")
    assert target_file.endswith("07_系统工具/Everything-1.4.1.exe")
    assert "共用文件" not in target_file


def test_app_detector_loose_files_in_staging_bucket_vs_atomic_collective():
    """验证扫描 D:\\共用文件 时，散装安装包独立打散，解压绿色软件保持原子集体"""
    scan_root = r"D:\共用文件"
    mock_files = [
        # 散装独立安装包 (原材料)
        {
            "name": "Everything-1.4.1.exe",
            "path": r"D:\共用文件\Everything-1.4.1.exe",
            "size": 2 * 1024 * 1024,
            "scan_root": scan_root,
            "metadata": {
                "software_name": "Everything",
                "product_version": "1.4.1.1024",
                "publisher": "voidtools",
                "domain_sector": "07_系统工具",
                "morphology": "独立单项"
            }
        },
        {
            "name": "ChromeSetup.exe",
            "path": r"D:\共用文件\ChromeSetup.exe",
            "size": 1 * 1024 * 1024,
            "scan_root": scan_root,
            "metadata": {
                "software_name": "Google Chrome",
                "product_version": "120.0",
                "publisher": "Google LLC",
                "domain_sector": "07_系统工具",
                "morphology": "独立单项"
            }
        },
        # 解压绿色应用目录 (原子集体)
        {
            "name": "SunloginClient.exe",
            "path": r"D:\共用文件\AweSun\SunloginClient.exe",
            "size": 15 * 1024 * 1024,
            "scan_root": scan_root,
            "metadata": {
                "software_name": "向日葵远程控制",
                "product_version": "13.2.0",
                "publisher": "Oray",
                "domain_sector": "04_远程控制",
                "morphology": "原子实体集体"
            }
        },
        {
            "name": "SunloginClient.dll",
            "path": r"D:\共用文件\AweSun\SunloginClient.dll",
            "size": 5 * 1024 * 1024,
            "scan_root": scan_root,
        }
    ]

    dest_root = r"D:\归档备份"
    grouped = AppDetector.group_files_by_parent_or_tool(mock_files, dest_root)

    # 散装安装包应该作为独立单元，不被错误聚合为名叫 '共用文件' 的伪集体
    everything_unit = None
    chrome_unit = None
    awesun_unit = None

    for g in grouped:
        name = g.get("name", "")
        # 检验目标路径绝不能包含 '共用文件'
        target_root_norm = g.get("target_root", "").replace("\\", "/")
        assert "共用文件" not in target_root_norm, f"单元 {name} 的目标路径错误渗入了中转容器名: {target_root_norm}"

        if "Everything" in name:
            everything_unit = g
        elif "Chrome" in name:
            chrome_unit = g
        elif "AweSun" in name:
            awesun_unit = g

    assert everything_unit is not None, "必须存在独立的 Everything 处理单元"
    assert everything_unit["is_directory_group"] is False, "散装 Everything 安装包必须是单文件单元 (is_directory_group=False)"
    
    assert chrome_unit is not None, "必须存在独立的 ChromeSetup 处理单元"
    assert chrome_unit["is_directory_group"] is False, "散装 Chrome 安装包必须是单文件单元"

    assert awesun_unit is not None, "必须识别 AweSun 目录为处理单元"
    assert awesun_unit["is_directory_group"] is True, "解压应用 AweSun 必须保持目录原子集体"
    assert awesun_unit["target_root"].replace("\\", "/").endswith("AweSun")


def test_extract_source_umbrella_purges_staging_bucket():
    """验证 extract_source_umbrella 绝不将原材料/中转容器作为泛目录锚点"""
    scan_roots = [r"D:\共用文件"]

    # 1. 中转容器内的普通程序 -> umbrella 为 None (杜绝共用文件作为泛目录)
    umb_loose = AppDetector.extract_source_umbrella(r"D:\共用文件\Everything.exe", scan_roots)
    assert umb_loose is None

    # 2. 中转容器内的实际业务项目 (如 live2D, 发票) -> 正确保全业务泛目录
    umb_live2d = AppDetector.extract_source_umbrella(r"D:\共用文件\live2D\西域舞女\model.json", scan_roots)
    assert umb_live2d == "live2D"

    umb_invoice = AppDetector.extract_source_umbrella(r"D:\共用文件\发票\7月发票\0701_inv.pdf", scan_roots)
    assert umb_invoice == "发票"


def test_ai_asset_payload_builder_zero_metadata_omission():
    """验证 AIAssetPayloadBuilder 完整封装全部 9 大 PE 元数据与形态字段，零遗漏送大模型"""
    sample_asset = {
        "group_id": "grp_0001",
        "name": "Everything-1.4.1.exe",
        "path": r"D:\共用文件\Everything-1.4.1.exe",
        "size": 3345678,
        "suggested_category": "07_系统工具",
        "recommended_subpath": "07_系统工具",
        "is_directory_group": False,
        "normalized_name": "Everything_1.4.1.exe",
        "metadata": {
            "software_name": "Everything",
            "product_version": "1.4.1.1024",
            "publisher": "voidtools",
            "domain_sector": "07_系统工具",
            "is_obfuscated_name": False,
            "normalized_name": "Everything_1.4.1.exe",
            "morphology": "独立单项",
            "file_description": "Everything Search Engine"
        }
    }

    item = AIAssetPayloadBuilder.build_summary_item(sample_asset, is_directory_group=False)

    # 严格检验 9 大关键元数据
    assert item["software_name"] == "Everything"
    assert item["product_version"] == "1.4.1.1024"
    assert item["publisher"] == "voidtools"
    assert item["domain_sector"] == "07_系统工具"
    assert item["normalized_name"] == "Everything_1.4.1.exe"
    assert item["morphology"] == "独立单项"
    assert item["file_count"] == 1
    assert item["size_mb"] == round(3345678 / (1024 * 1024), 2)
    assert item["unit_type"] == "散装独立文件 (Single File)"
    assert item["extension"] == ".exe"

    # 检验解压应用目录集体
    collective_asset = {
        "group_id": "grp_0002",
        "name": "AweSun",
        "original_root": r"D:\共用文件\AweSun",
        "total_size": 25 * 1024 * 1024,
        "file_count": 42,
        "suggested_category": "04_远程控制",
        "is_directory_group": True,
        "metadata": {
            "software_name": "向日葵远程控制",
            "product_version": "13.2.0",
            "publisher": "Oray",
            "domain_sector": "04_远程控制",
            "is_obfuscated_name": False,
            "morphology": "原子实体集体"
        },
        "collective_info": {
            "primary_executable": "SunloginClient.exe",
            "product_title": "向日葵远程控制客户端",
            "signature_type": "绿色解压软件"
        }
    }

    c_item = AIAssetPayloadBuilder.build_summary_item(collective_asset, is_directory_group=True)
    assert c_item["unit_type"] == "软件/工程集体 (Directory Collective)"
    assert c_item["directory_name"] == "AweSun"
    assert c_item["software_name"] == "向日葵远程控制"
    assert c_item["product_version"] == "13.2.0"
    assert c_item["publisher"] == "Oray"
    assert c_item["domain_sector"] == "04_远程控制"
    assert c_item["primary_executable"] == "SunloginClient.exe"
    assert c_item["morphology"] == "原子实体集体"
    assert c_item["file_count"] == 42


def test_online_ai_topology_context_and_export():
    """验证 export_ai_topology_context 导出规范紧凑的拓扑上下文 Prompt"""
    table = TopologyRoutingTable.instance()
    ctx = table.export_ai_topology_context()

    assert "STAGING_BUCKET" in ctx
    assert "共用文件" in ctx
    assert "APP_COLLECTIVE" in ctx
    assert "禁止注入" in ctx or "绝不可" in ctx
