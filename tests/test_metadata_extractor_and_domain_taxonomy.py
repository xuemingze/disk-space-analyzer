"""
单元测试：资产多态元数据萃取引擎、八大业务领域规范分类与解混淆确权体系
(Tests for Asset Metadata Extractor, Domain Sector Taxonomy & Obfuscation De-anonymization)
"""

import os
import sys
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.metadata_extractor import (
    AssetMetadataContract,
    MetadataExtractorFactory,
    PEExtractor,
    MSIExtractor,
    ArchiveSniffer,
    OfficeMetadataExtractor,
    is_obfuscated_filename,
    clean_version_string,
    infer_domain_sector,
    ORDERED_DOMAIN_SECTORS,
)
from app.core.domain_models import ScannedAsset, AssetUnit
from app.core.app_detector import AppDetector
from app.ui.components.data_table import FileTableModel, FileDataGridWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor


def test_is_obfuscated_filename():
    """测试下载器时间戳/纯哈希/长数字乱码文件名检测器"""
    assert is_obfuscated_filename("8799-2026-10-13020405-1791871445526.exe") is True
    assert is_obfuscated_filename("1303-2026-09-15055636-1789466196073.exe") is True
    assert is_obfuscated_filename("6196-2026-01-23025447-1769151287280.exe") is True
    assert is_obfuscated_filename("1789466196073.exe") is True
    assert is_obfuscated_filename("a8f7c9e034b12398d2345.exe") is True

    # 规范软件命名绝不可误判为乱码
    assert is_obfuscated_filename("lobsterai26.9.23.exe") is False
    assert is_obfuscated_filename("DingTalk_v9.0.2.exe") is False
    assert is_obfuscated_filename("QuarkPC_V7.4.0.1015.exe") is False
    assert is_obfuscated_filename("W.P.S.20.2706.exe") is False
    assert is_obfuscated_filename("syncthing-windows-setup.exe") is False


def test_clean_version_string():
    """测试多格式版本号清洗提炼"""
    assert clean_version_string("9.0.2.261011003") == "9.0.2"
    assert clean_version_string("16,5,0,30560") == "16.5.0"
    assert clean_version_string("v2.1.3") == "2.1.3"
    assert clean_version_string("7.4.0") == "7.4.0"
    assert clean_version_string("") == ""


def test_ordered_domain_sectors_taxonomy():
    """测试八大规范业务领域目录推断"""
    assert len(ORDERED_DOMAIN_SECTORS) == 8

    # 01_AI与模型工具
    c1 = AssetMetadataContract(software_name="LobsterAI", file_description="LobsterAI Desktop Agent")
    assert infer_domain_sector(c1, "lobsterai26.9.23.exe") == "01_AI与模型工具"

    c1_2 = AssetMetadataContract(software_name="GeminiSetup", file_description="Google Gemini")
    assert infer_domain_sector(c1_2, "GeminiSetup.exe") == "01_AI与模型工具"

    # 02_云盘与同步
    c2 = AssetMetadataContract(software_name="百度网盘", file_description="百度网盘客户端")
    assert infer_domain_sector(c2, "BaiduNetdisk.exe") == "02_云盘与同步"

    c2_2 = AssetMetadataContract(software_name="夸克", file_description="夸克PC端")
    assert infer_domain_sector(c2_2, "QuarkPC.exe") == "02_云盘与同步"

    c2_3 = AssetMetadataContract(software_name="syncthing", file_description="Syncthing sync service")
    assert infer_domain_sector(c2_3, "syncthing.zip") == "02_云盘与同步"

    # 03_游戏工具与优化
    c3 = AssetMetadataContract(software_name="ok-ww", file_description="鸣潮游戏助手自动化脚本")
    assert infer_domain_sector(c3, "ok-ww-setup.exe") == "03_游戏工具与优化"

    c3_2 = AssetMetadataContract(software_name="Pavise Auto", file_description="游戏调度与BypassIO性能优化")
    assert infer_domain_sector(c3_2, "Pavise.exe") == "03_游戏工具与优化"

    # 04_远程控制
    c4 = AssetMetadataContract(software_name="向日葵", file_description="贝锐向日葵远程控制")
    assert infer_domain_sector(c4, "AweSun.exe") == "04_远程控制"

    c4_2 = AssetMetadataContract(software_name="网易UU远程", file_description="网易UU远程客户端")
    assert infer_domain_sector(c4_2, "1303-2026.exe") == "04_远程控制"

    # 05_下载与媒体
    c5 = AssetMetadataContract(software_name="MediaGo", file_description="在线视频嗅探提取与下载")
    assert infer_domain_sector(c5, "mediago-setup.exe") == "05_下载与媒体"

    c5_2 = AssetMetadataContract(software_name="MotrixNext", file_description="全能下载管理器")
    assert infer_domain_sector(c5_2, "MotrixNext.exe") == "05_下载与媒体"

    # 06_办公与通讯
    c6 = AssetMetadataContract(software_name="钉钉", file_description="钉钉Windows客户端安装包")
    assert infer_domain_sector(c6, "8799-2026.exe") == "06_办公与通讯"

    c6_2 = AssetMetadataContract(software_name="WPS Office", file_description="金山办公WPS")
    assert infer_domain_sector(c6_2, "W.P.S.exe") == "06_办公与通讯"

    # 07_系统工具
    c7 = AssetMetadataContract(software_name="Everything", file_description="Everything 文件急速搜索")
    assert infer_domain_sector(c7, "6196-2026.exe") == "07_系统工具"

    c7_2 = AssetMetadataContract(software_name="fatDuck", file_description="Windows系统垃圾清理与性能优化")
    assert infer_domain_sector(c7_2, "optimizerDuck.exe") == "07_系统工具"

    # _已解压程序与归档
    c_coll = AssetMetadataContract(morphology="portable_runtime_dir", software_name="AweSun")
    assert infer_domain_sector(c_coll, "AweSun") == "_已解压程序与归档"


def test_scanned_asset_domain_model_metadata():
    """测试 ScannedAsset 强类型实体携带多态元数据与规范化名称"""
    meta_dict = {
        "software_name": "钉钉",
        "product_version": "9.0.2",
        "publisher": "Alibaba Group.",
        "morphology": "installer_pe",
        "is_obfuscated_name": True,
        "normalized_name": "钉钉_9.0.2.exe",
        "domain_sector": "06_办公与通讯"
    }

    asset = ScannedAsset(
        id="FILE_001",
        name="8799-2026-10-13020405-1791871445526.exe",
        path=r"D:\安装包\8799-2026-10-13020405-1791871445526.exe",
        size=491238400,
        metadata=meta_dict,
        normalized_name="钉钉_9.0.2.exe"
    )

    assert asset.software_name == "钉钉"
    assert asset.display_name == "钉钉_9.0.2.exe"
    assert asset["metadata"]["domain_sector"] == "06_办公与通讯"

    # 序列化与反序列化一致性 (防撕裂)
    d = asset.to_dict()
    assert d["normalized_name"] == "钉钉_9.0.2.exe"
    assert d["metadata"]["software_name"] == "钉钉"

    restored = ScannedAsset.from_dict(d)
    assert restored.normalized_name == "钉钉_9.0.2.exe"
    assert restored.software_name == "钉钉"
    assert restored.display_name == "钉钉_9.0.2.exe"


def test_archive_sniffer_virtual_collective():
    """测试对免安装绿色压缩包内部虚拟主程序的透视嗅探"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        zip_path = Path(tmp_dir) / "syncthing-windows-v2.1.3.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("syncthing-windows/syncthing.exe", b"MZDummyPEHeader")
            z.writestr("syncthing-windows/README.txt", b"Syncthing documentation")

        meta = MetadataExtractorFactory.extract(str(zip_path))
        assert meta.morphology == "portable_archive"
        assert meta.software_name == "syncthing"
        assert meta.domain_sector == "02_云盘与同步"


def test_pe_heterogeneity_prevents_collective_collapse():
    """
    测试准则三：PE 元数据多态异构判定法则 (PE Heterogeneity Test)
    当目录内包含多个属于不同软件产品名称的 exe 时，坚决禁止折叠为单一软件集体！
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        p = Path(tmp_dir)
        (p / "Installer1.exe").write_bytes(b"MZDummy1")
        (p / "Installer2.exe").write_bytes(b"MZDummy2")

        # 模拟不同软件产品名称 (如 百度网盘 vs 钉钉)
        def mock_extract(fpath):
            if "Installer1" in fpath:
                return AssetMetadataContract(software_name="百度网盘")
            return AssetMetadataContract(software_name="钉钉")

        with patch("app.core.metadata_extractor.MetadataExtractorFactory.extract", side_effect=mock_extract):
            coll = AppDetector.detect_directory_collective(str(p))
            assert coll is None, "多不同软件产品混杂的安装包目录坚决不可坍塌为单一集体！"


def test_single_app_with_helpers_allows_collective():
    """测试同一软件的多个辅助程序 (如 SunloginClient.exe + SunloginService.exe) 允许形成集体"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        p = Path(tmp_dir) / "AweSun"
        p.mkdir()
        (p / "SunloginClient.exe").write_bytes(b"MZDummy1")
        (p / "SunloginService.exe").write_bytes(b"MZDummy2")
        (p / "res").mkdir() # 配套资源子目录

        def mock_extract(fpath):
            return AssetMetadataContract(software_name="向日葵")

        with patch("app.core.metadata_extractor.MetadataExtractorFactory.extract", side_effect=mock_extract):
            with patch("app.core.app_detector._extract_pe_version_info", return_value=("向日葵", "向日葵远程控制")):
                coll = AppDetector.detect_directory_collective(str(p))
                assert coll is not None, "同源软件配套运行时目录应识别为不可拆分独立应用集体！"
                assert coll["is_collective"] is True
                assert coll["software_name"] == "向日葵"


def test_data_table_deobfuscation_rendering():
    """测试 GUI 表格在展示哈希乱码文件时呈现已还原真实软件铭牌及专属标签"""
    test_item = {
        "name": "8799-2026-10-13020405-1791871445526.exe",
        "path": r"D:\安装包\8799-2026-10-13020405-1791871445526.exe",
        "size": 491238400,
        "category": "软件安装与镜像 (Apps & Installers)",
        "tag": "已还原真实软件铭牌",
        "target_subpath": "06_办公与通讯",
        "normalized_name": "钉钉_9.0.2.exe",
        "metadata": {
            "software_name": "钉钉",
            "product_version": "9.0.2",
            "publisher": "Alibaba Group.",
            "is_obfuscated_name": True,
            "normalized_name": "钉钉_9.0.2.exe",
            "domain_sector": "06_办公与通讯"
        }
    }

    model = FileTableModel([test_item], is_selectable=True)

    # 第一列：资产项名称呈现规范名称与原文件名对照
    idx_name = model.index(0, 1)
    display_name = model.data(idx_name, Qt.DisplayRole)
    assert "已还原铭牌" in display_name
    assert "钉钉_9.0.2.exe" in display_name
    assert "8799-2026" in display_name

    # 第三列：呈现建议归档规划路径
    idx_subpath = model.index(0, 3)
    assert model.data(idx_subpath, Qt.DisplayRole) == "06_办公与通讯"

    # 第六列：呈现已还原真实软件铭牌
    idx_tag = model.index(0, 6)
    assert model.data(idx_tag, Qt.DisplayRole) == "已还原真实软件铭牌"
    brush = model.data(idx_tag, Qt.ForegroundRole)
    assert brush.color() == QColor("#34D399")

    # Tooltip 悬浮提示包含富元数据
    tooltip = model.data(idx_name, Qt.ToolTipRole)
    assert "真实软件名称: 钉钉" in tooltip
    assert "识别版本号: 9.0.2" in tooltip
    assert "Alibaba Group." in tooltip
    assert "06_办公与通讯" in tooltip


def test_unified_scanner_extracts_metadata_and_deobfuscates():
    """测试 UnifiedScanner 扫描单文件时自动提取多态元数据并打上已还原铭牌标记"""
    from app.core.unified_scanner import UnifiedScanner

    with tempfile.TemporaryDirectory() as tmp_dir:
        p = Path(tmp_dir)
        obf_file = p / "8799-2026-10-13020405-1791871445526.exe"
        obf_file.write_bytes(b"MZDummyPE")

        def mock_extract(fpath):
            return AssetMetadataContract(
                software_name="钉钉",
                product_version="9.0.2",
                is_obfuscated_name=True,
                normalized_name="钉钉_9.0.2.exe",
                domain_sector="06_办公与通讯"
            )

        with patch("app.core.metadata_extractor.MetadataExtractorFactory.extract", side_effect=mock_extract):
            assets = UnifiedScanner.scan_directory([tmp_dir])
            assert len(assets) == 1
            asset = assets[0]
            assert asset.name == "8799-2026-10-13020405-1791871445526.exe"
            assert asset.normalized_name == "钉钉_9.0.2.exe"
            assert asset.tag == "已还原真实软件铭牌"
            assert "钉钉" in asset.reason
            assert asset.metadata["software_name"] == "钉钉"
            assert asset.target_subpath == "06_办公与通讯"


def test_unified_scanner_extracts_collective_runtime_dir():
    """测试 UnifiedScanner 扫描已释放运行目录时自动赋权 _已解压程序与归档 路径"""
    from app.core.unified_scanner import UnifiedScanner

    with tempfile.TemporaryDirectory() as tmp_dir:
        p = Path(tmp_dir)
        app_dir = p / "AweSun"
        app_dir.mkdir()
        (app_dir / "AweSun.exe").write_bytes(b"MZDummy")
        (app_dir / "res").mkdir()

        mock_collective_info = {
            "is_collective": True,
            "collective_type": "独立软件集体",
            "software_name": "向日葵",
            "primary_executable": "AweSun.exe"
        }

        def mock_extract_collective(dpath, primary_exe):
            return AssetMetadataContract(
                software_name="向日葵",
                product_version="16.5.0",
                morphology="portable_runtime_dir",
                domain_sector="_已解压程序与归档",
                normalized_name="向日葵_运行目录"
            )

        with patch("app.core.app_detector.AppDetector.detect_directory_collective", return_value=mock_collective_info):
            with patch("app.core.metadata_extractor.MetadataExtractorFactory.extract_collective", side_effect=mock_extract_collective):
                assets = UnifiedScanner.scan_directory([tmp_dir])
                assert len(assets) == 1
                asset = assets[0]
                assert asset.is_collective is True
                assert asset.metadata["morphology"] == "portable_runtime_dir"
                assert asset.target_subpath == "_已解压程序与归档/向日葵"



def test_table_column_auto_fit_and_rich_tooltips():
    """验证表格自适应列宽动态计算与全字段 ToolTip 提示，杜绝省略号截断"""
    app = QApplication.instance() or QApplication(sys.argv)
    grid = FileDataGridWidget(is_selectable=True)
    
    test_data = [
        {
            "name": "BaiduNetdisk_lxsd1_8.8.6.102_pc_pf30002_release.exe",
            "path": "D:/安装包/BaiduNetdisk_lxsd1_8.8.6.102_pc_pf30002_release.exe",
            "category": "02_云盘与同步 (Cloud & Sync)",
            "suggested_archive_path": "02_云盘与同步/百度网盘/BaiduNetdisk.exe",
            "size": 520 * 1024 * 1024,
            "phase_status": "阶段一已归类 (待治理)",
            "tag": "建议保留最新正本",
            "reason": "已识别官方完整安装程序并解析真实版本号",
            "duplicate_group_id": "DUP-GRP-001",
            "mtime": 1700000000
        }
    ]
    
    # 填充数据，触发 auto_fit_columns
    grid.populate_data(test_data)
    
    # 验证动态列宽下限均足够充裕，杜绝 ... 省略号截断
    assert grid.table_view.columnWidth(1) >= 280 # 资产名称
    assert grid.table_view.columnWidth(2) >= 180 # 高阶分类
    assert grid.table_view.columnWidth(3) >= 220 # 规划路径
    assert grid.table_view.columnWidth(6) >= 180 # 治理标记/理由
    assert grid.table_view.columnWidth(9) >= 260 # 绝对路径
    
    # 验证所有 10 列均支持悬浮显示无截断完整信息
    model = grid.source_model
    for col in range(10):
        tip = model.data(model.index(0, col), Qt.ToolTipRole)
        assert tip is not None and str(tip).strip() != ""


def test_ai_audit_and_precipitation_safety_and_obfuscation_guard():
    """
    验证 AI 手改审核与自沉淀安全防护：
    1. 超时或网络异常时，恪守本地不抢功原则，严禁自沉淀乱码规则；
    2. 乱码文件名 (8799-...) 坚决杜绝进入规则库；
    3. 安装包冗余版本后缀 (BaiduNetdisk_lxsd1_8.8.6.102) 自动提炼为通用软件名并吸附至有序业务领域目录。
    """
    from app.core.ai_service import AIService
    from app.core.category_manager import global_category_manager

    # 1. 模拟乱码安装包超时场景
    obf_item = {
        "name": "8799-2026-10-13020405-1791871445526.exe",
        "path": "D:/Downloads/8799-2026-10-13020405-1791871445526.exe",
        "category": "未分类"
    }
    
    # 模拟网络超时
    with patch.object(AIService.get_session(), "post", side_effect=requests.exceptions.ReadTimeout("read timeout=0.5")):
        res_timeout = AIService.audit_manual_path_and_precipitate(
            obf_item,
            "06_办公与通讯/钉钉/钉钉_9.0.2.exe",
            base_url="https://api.test-llm.com/v1",
            api_key="sk-test",
            model="fast-model"
        )
        assert res_timeout["valid"] is True
        assert res_timeout["ai_audited"] is False
        assert res_timeout["rule"] is None # 严禁沉淀乱码规则
        assert not any("8799-2026" in r.get("pattern", "") for r in global_category_manager.get_precipitated_rules())

    # 2. 模拟真实 AI 审核通过 BaiduNetdisk 安装包
    baidu_item = {
        "name": "BaiduNetdisk_lxsd1_8.8.6.102.exe",
        "path": "D:/安装包/BaiduNetdisk_lxsd1_8.8.6.102.exe",
        "category": "未分类",
        "metadata": {"software_name": "百度网盘"}
    }
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "valid": True,
                    "snapped_category": "02_云盘与同步",
                    "rule_pattern": "百度网盘",
                    "subpath": "02_云盘与同步/百度网盘/BaiduNetdisk_lxsd1_8.8.6.102.exe"
                })
            }
        }]
    }
    
    with patch.object(AIService.get_session(), "post", return_value=mock_resp):
        res_baidu = AIService.audit_manual_path_and_precipitate(
            baidu_item,
            "02_云盘与同步/百度网盘/BaiduNetdisk_lxsd1_8.8.6.102.exe",
            base_url="https://api.test-llm.com/v1",
            api_key="sk-test",
            model="fast-model"
        )
        assert res_baidu["valid"] is True
        assert res_baidu["ai_audited"] is True
        rule = res_baidu["rule"]
        assert rule is not None
        assert rule["pattern"] == "百度网盘"
        assert rule["category"] == "02_云盘与同步"
        assert "{asset_name}" in rule["target_subpath"]
        assert "lxsd1_8.8.6.102" not in rule["pattern"]
