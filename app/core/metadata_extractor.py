"""
资产多态元数据萃取与身份确权引擎 (Asset Metadata Extractor & Identity Engine)

本模块为系统资产提供高精度的底层元数据萃取与身份确权支持：
1. 原生 PE 家族 (.exe, .dll, .sys, .scr, .ocx, .cpl): 萃取 ProductName, FileDescription, FileVersion, CompanyName, OriginalFilename
2. Windows Installer 体系 (.msi, .msp): 萃取 Title, Subject, Author, ProductVersion
3. 免安装绿色压缩包 (.zip, .7z): 嗅探包内主可执行文件与项目骨架
4. 办公文档 (Office docx/xlsx/pptx): 萃取 docProps 核心元数据
5. 目录级原子实体集体 (Collective): 通过主程序 PE 签名完成集体真实身份与版本确权
6. 哈希/乱码下载文件名判定与智能规范重命名建议
"""

from __future__ import annotations

import os
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.utils.logger import app_logger


ORDERED_DOMAIN_SECTORS: List[str] = [
    "01_AI与模型工具",
    "02_云盘与同步",
    "03_游戏工具与优化",
    "04_远程控制",
    "05_下载与媒体",
    "06_办公与通讯",
    "07_系统工具",
    "_已解压程序与归档",
]

SECTOR_KEYWORDS: Dict[str, List[str]] = {
    "01_AI与模型工具": [
        "ai", "gpt", "model", "llm", "gemini", "lobster", "prompt", "antigravity",
        "agent", "deepseek", "chat", "claude", "ollama", "openai", "copilot"
    ],
    "02_云盘与同步": [
        "netdisk", "pan", "cloud", "sync", "quark", "baidu", "drive", "syncthing",
        "115", "aliyun", "weiyun", "onedrive", "dropbox", "夸克", "网盘", "同步"
    ],
    "03_游戏工具与优化": [
        "game", "steam", "ww", "nte", "wuthering", "neverness", "pavise", "accelerator",
        "fps", "bypass", "鸣潮", "异环", "原神", "加速器", "游戏"
    ],
    "04_远程控制": [
        "sunlogin", "awesun", "todesk", "gameviewer", "remote", "anydesk", "teamviewer",
        "vnc", "rdp", "向日葵", "远程", "串流", "uu"
    ],
    "05_下载与媒体": [
        "download", "mediago", "motrix", "thunder", "aria2", "torrent", "sniff",
        "media", "player", "ffmpeg", "迅雷", "嗅探", "下载器", "播放器"
    ],
    "06_办公与通讯": [
        "dingtalk", "dingding", "wps", "wechat", "weixin", "feishu", "lark", "office",
        "word", "excel", "pdf", "mail", "钉钉", "微信", "飞书", "办公", "文档"
    ],
    "07_系统工具": [
        "clean", "everything", "optimizer", "duck", "fatduck", "dism", "geek",
        "autorun", "sys", "process", "disk", "bench", "清理", "优化", "搜索", "运维"
    ]
}


KNOWN_SOFTWARE_ALIASES: Dict[str, str] = {
    "baiduyunguanjia": "百度网盘",
    "baidunetdisk": "百度网盘",
    "awesun": "向日葵",
    "dingtalk": "钉钉",
    "wps office": "WPS Office",
    "geminisetup": "Gemini",
    "gameviewer": "网易GameViewer",
}


def infer_domain_sector(contract: AssetMetadataContract, file_name: str = "") -> str:
    """基于元数据特征与关键字推断所属的八大业务领域规范目录"""
    if contract.morphology == "portable_runtime_dir":
        return "_已解压程序与归档"

    test_tokens = [
        contract.software_name.lower(),
        contract.file_description.lower(),
        contract.original_filename.lower(),
        contract.publisher.lower(),
        file_name.lower()
    ]
    combined = " ".join([t for t in test_tokens if t])
    if not combined:
        return ""

    for sector, kw_list in SECTOR_KEYWORDS.items():
        for kw in kw_list:
            kw_l = kw.lower()
            # 中文关键词或长度 >= 4 的长英文词直接子串匹配；<= 3 字符短英文词必须全词边界匹配，杜绝误伤 (如 baidu 误伤 ai)
            if re.search(r'[\u4e00-\u9fa5]', kw_l) or len(kw_l) >= 4:
                if kw_l in combined:
                    return sector
            else:
                if re.search(r'(?<![a-z0-9])' + re.escape(kw_l) + r'(?![a-z0-9])', combined):
                    return sector

    return ""


@dataclass
class AssetMetadataContract:
    """资产多态元数据标准化契约实体"""
    software_name: str = ""               # 真实软件名/产品名 (如: "钉钉", "网易UU远程", "向日葵")
    product_version: str = ""             # 识别版本号 (如: "9.0.2.261011003", "4.40.1")
    file_description: str = ""            # 功能描述 (如: "网易UU远程安装程序")
    publisher: str = ""                   # 开发者/供应商 (如: "Alibaba Group.", "Netease")
    original_filename: str = ""           # 编译原始文件名 (如: "DingTalk.exe")
    morphology: str = "standalone_file"   # 资产形态: "installer_pe" | "installer_msi" | "portable_runtime_dir" | "portable_archive" | "general_document" | "media" | "standalone_file"
    is_obfuscated_name: bool = False      # 是否为哈希/纯数字/下载代号乱码名 (如: 8799-...exe)
    normalized_name: str = ""             # 建议规范命名 (如: "钉钉_9.0.2.exe")
    domain_sector: str = ""               # 建议业务领域分类 (如: "06_办公与通讯", "04_远程控制")
    lifecycle_recommendation: str = ""    # 生命周期治理建议 ("推荐保留最新版" | "旧版建议淘汰归档" | "建议移出安装包池至绿色软件盘")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "software_name": self.software_name,
            "product_version": self.product_version,
            "file_description": self.file_description,
            "publisher": self.publisher,
            "original_filename": self.original_filename,
            "morphology": self.morphology,
            "is_obfuscated_name": self.is_obfuscated_name,
            "normalized_name": self.normalized_name,
            "domain_sector": self.domain_sector,
            "lifecycle_recommendation": self.lifecycle_recommendation,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AssetMetadataContract:
        if not data or not isinstance(data, dict):
            return cls()
        return cls(
            software_name=str(data.get("software_name", "")),
            product_version=str(data.get("product_version", "")),
            file_description=str(data.get("file_description", "")),
            publisher=str(data.get("publisher", "")),
            original_filename=str(data.get("original_filename", "")),
            morphology=str(data.get("morphology", "standalone_file")),
            is_obfuscated_name=bool(data.get("is_obfuscated_name", False)),
            normalized_name=str(data.get("normalized_name", "")),
            domain_sector=str(data.get("domain_sector", "")),
            lifecycle_recommendation=str(data.get("lifecycle_recommendation", "")),
        )


def is_obfuscated_filename(file_name: str) -> bool:
    """
    判定文件名是否为纯哈希、随机长数字、时间戳下载代号等乱码文件名。
    例如:
      - 8799-2026-10-13020405-1791871445526.exe
      - 1303-2026-09-15055636-1789466196073.exe
      - 6196-2026-01-23025447-1769151287280.exe
      - a8f7c9e034b12398d.exe
    """
    stem = Path(file_name).stem
    if not stem:
        return False

    # 1. 下载器典型格式: 4位以上数字-日期-长数字 (如 8799-2026-10-...)
    if re.match(r'^\d{3,}[-_]\d{4,}[-_]\d+', stem):
        return True

    # 2. 纯十六进制哈希或纯数字长度 >= 16 位
    if re.match(r'^[0-9a-fA-F]{16,}$', stem):
        return True

    # 3. 纯数字大于 10 位 (如时间戳命名 1789466196073.exe)
    if stem.isdigit() and len(stem) >= 10:
        return True

    return False


def clean_version_string(ver: str) -> str:
    """清洗提取规范的纯净版本号 (如 9.0.2.261011003 -> 9.0.2 或保持规范)"""
    if not ver:
        return ""
    v = ver.strip().replace(",", ".")
    m = re.search(r'\d+(?:\.\d+)+', v)
    if m:
        parts = m.group(0).split(".")
        if len(parts) >= 3:
            return ".".join(parts[:3])
        return m.group(0)
    return v


class PEExtractor:
    """Windows 原生 PE 家族 (.exe, .dll, .sys, .scr, .ocx, .cpl) 元数据萃取器"""

    @classmethod
    def extract(cls, file_path: str) -> AssetMetadataContract:
        meta = AssetMetadataContract(morphology="installer_pe")
        path_obj = Path(file_path)
        meta.is_obfuscated_name = is_obfuscated_filename(path_obj.name)

        try:
            import win32api
            trans = win32api.GetFileVersionInfo(str(path_obj), "\\VarFileInfo\\Translation")
            if trans:
                candidate_names: List[str] = []
                candidate_descs: List[str] = []

                for lang, codepage in trans:
                    str_prefix = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\"

                    def _get_val(key_name: str) -> str:
                        try:
                            val = win32api.GetFileVersionInfo(str(path_obj), str_prefix + key_name)
                            return str(val).strip() if val else ""
                        except Exception:
                            return ""

                    p_name = _get_val("ProductName")
                    f_desc = _get_val("FileDescription")
                    f_ver = _get_val("FileVersion") or _get_val("ProductVersion")
                    c_name = _get_val("CompanyName")
                    orig_name = _get_val("OriginalFilename")

                    if p_name:
                        candidate_names.append(p_name)
                    if f_desc:
                        candidate_descs.append(f_desc)
                    if f_ver and not meta.product_version:
                        meta.product_version = clean_version_string(f_ver)
                    if c_name and not meta.publisher:
                        meta.publisher = c_name
                    if orig_name and not meta.original_filename:
                        meta.original_filename = orig_name

                # 优先选择包含中文的本地化产品名称 (例如 "钉钉" 优于 "DingTalk Installer")
                zh_names = [n for n in candidate_names if re.search(r'[\u4e00-\u9fa5]', n)]
                if zh_names:
                    meta.software_name = zh_names[0]
                elif candidate_names:
                    meta.software_name = candidate_names[0]

                zh_descs = [d for d in candidate_descs if re.search(r'[\u4e00-\u9fa5]', d)]
                if zh_descs:
                    meta.file_description = zh_descs[0]
                elif candidate_descs:
                    meta.file_description = candidate_descs[0]
        except Exception:
            pass

        # 清洗并赋默认值
        chosen_name = meta.software_name or meta.file_description
        if not chosen_name:
            if not meta.is_obfuscated_name:
                chosen_name = path_obj.stem
            else:
                chosen_name = ""

        # 循环清理 Windows 安装包常见的废话后缀 (如 "Windows 客户端安装包", "桌面版", " Installer", " Setup", " 安装程序", " Application")
        clean_name = chosen_name
        while True:
            new_name = re.sub(
                r'[\s_\-]*(?:Windows\s*客户端|Windows客户端|客户端|Windows\s*桌面版|Windows桌面版|桌面版|PC版|正式版|Release|Installer|Setup|安装包|安装程序|Windows|Application|App|\(x64\)|\(x86\)|x64|x86)$',
                '', clean_name, flags=re.IGNORECASE
            ).strip()
            if new_name == clean_name or not new_name:
                break
            clean_name = new_name

        # 检查已知通用软件别名映射
        stem_l = path_obj.stem.lower()
        clean_l = clean_name.lower()
        if clean_l in KNOWN_SOFTWARE_ALIASES:
            clean_name = KNOWN_SOFTWARE_ALIASES[clean_l]
        elif stem_l in KNOWN_SOFTWARE_ALIASES:
            clean_name = KNOWN_SOFTWARE_ALIASES[stem_l]
        elif clean_l == "google" and "gemini" in stem_l:
            clean_name = "Gemini"

        if clean_name:
            meta.software_name = clean_name

        # 智能生成规范化重命名建议
        if meta.software_name:
            ver_part = f"_{meta.product_version}" if meta.product_version else ""
            meta.normalized_name = f"{meta.software_name}{ver_part}{path_obj.suffix.lower()}"
        else:
            meta.normalized_name = path_obj.name

        meta.domain_sector = infer_domain_sector(meta, path_obj.name)
        return meta


class MSIExtractor:
    """Windows Installer (.msi, .msp) 数据库元数据萃取器"""

    @classmethod
    def extract(cls, file_path: str) -> AssetMetadataContract:
        meta = AssetMetadataContract(morphology="installer_msi")
        path_obj = Path(file_path)
        meta.is_obfuscated_name = is_obfuscated_filename(path_obj.name)

        try:
            import ctypes
            from ctypes import wintypes

            msi = ctypes.windll.msi
            h_summary = wintypes.HANDLE()
            res = msi.MsiGetSummaryInformationW(0, str(path_obj), 0, ctypes.byref(h_summary))
            if res == 0 and h_summary.value:
                def _read_prop(prop_id: int) -> str:
                    buf_type = wintypes.UINT()
                    buf_val = wintypes.INT()
                    buf_str = ctypes.create_unicode_buffer(512)
                    buf_len = wintypes.DWORD(512)
                    if msi.MsiSummaryInfoGetPropertyW(
                        h_summary, prop_id, ctypes.byref(buf_type),
                        ctypes.byref(buf_val), None, buf_str, ctypes.byref(buf_len)
                    ) == 0:
                        return buf_str.value.strip()
                    return ""

                title = _read_prop(2)
                subject = _read_prop(3)
                author = _read_prop(4)
                msi.MsiCloseHandle(h_summary)

                if title or subject:
                    meta.software_name = subject or title
                    meta.file_description = title or subject
                if author:
                    meta.publisher = author
        except Exception:
            pass

        if not meta.software_name:
            if not meta.is_obfuscated_name:
                meta.software_name = path_obj.stem
            meta.normalized_name = path_obj.name
        else:
            ver_part = f"_{meta.product_version}" if meta.product_version else ""
            meta.normalized_name = f"{meta.software_name}{ver_part}{path_obj.suffix.lower()}"

        meta.domain_sector = infer_domain_sector(meta, path_obj.name)
        return meta


class ArchiveSniffer:
    """免安装绿色压缩包 (.zip, .7z) 虚拟集合透视萃取器"""

    @classmethod
    def extract(cls, file_path: str) -> AssetMetadataContract:
        meta = AssetMetadataContract(morphology="portable_archive")
        path_obj = Path(file_path)
        meta.is_obfuscated_name = is_obfuscated_filename(path_obj.name)

        stem = path_obj.stem
        v_match = re.search(r'[vV]?(\d+\.\d+(?:\.\d+)?)', stem)
        if v_match:
            meta.product_version = v_match.group(1)

        if path_obj.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(str(path_obj), "r") as z:
                    names = z.namelist()
                    exe_candidates = [n for n in names if n.lower().endswith(".exe") and not n.startswith("__MACOSX")]
                    if exe_candidates:
                        best_exe = sorted(exe_candidates, key=lambda x: (x.count("/"), len(x)))[0]
                        exe_name = Path(best_exe).stem
                        meta.software_name = exe_name
                        meta.file_description = f"免安装绿色压缩归档 (内含主程序: {Path(best_exe).name})"
                    elif names:
                        top_dirs = {n.split("/")[0] for n in names if "/" in n}
                        if len(top_dirs) == 1:
                            meta.software_name = list(top_dirs)[0]
                            meta.file_description = "免安装绿色运行目录压缩包"
            except Exception:
                pass

        if not meta.software_name and not meta.is_obfuscated_name:
            meta.software_name = stem

        meta.normalized_name = path_obj.name
        meta.domain_sector = infer_domain_sector(meta, path_obj.name)
        return meta


class OfficeMetadataExtractor:
    """Office OpenXML (.docx, .xlsx, .pptx) 核心属性萃取器"""

    @classmethod
    def extract(cls, file_path: str) -> AssetMetadataContract:
        meta = AssetMetadataContract(morphology="general_document")
        path_obj = Path(file_path)
        meta.is_obfuscated_name = is_obfuscated_filename(path_obj.name)

        if path_obj.suffix.lower() in {".docx", ".xlsx", ".pptx"}:
            try:
                with zipfile.ZipFile(str(path_obj), "r") as z:
                    if "docProps/core.xml" in z.namelist():
                        xml_bytes = z.read("docProps/core.xml")
                        root = ET.fromstring(xml_bytes)
                        ns = {
                            "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
                            "dc": "http://purl.org/dc/elements/1.1/",
                            "dcterms": "http://purl.org/dc/terms/"
                        }
                        title_el = root.find("dc:title", ns)
                        creator_el = root.find("dc:creator", ns)
                        subject_el = root.find("dc:subject", ns)

                        if title_el is not None and title_el.text:
                            meta.file_description = title_el.text.strip()
                        if creator_el is not None and creator_el.text:
                            meta.publisher = creator_el.text.strip()
                        if subject_el is not None and subject_el.text and not meta.file_description:
                            meta.file_description = subject_el.text.strip()
            except Exception:
                pass

        meta.normalized_name = path_obj.name
        meta.domain_sector = infer_domain_sector(meta, path_obj.name)
        return meta


class MetadataExtractorFactory:
    """资产多态元数据萃取工厂 (Metadata Extractor Factory)"""

    @classmethod
    def extract(cls, file_path: Path | str) -> AssetMetadataContract:
        p = Path(file_path)
        ext = p.suffix.lower()

        if ext in {".exe", ".dll", ".sys", ".scr", ".ocx", ".cpl"}:
            meta = PEExtractor.extract(str(p))
        elif ext in {".msi", ".msp"}:
            meta = MSIExtractor.extract(str(p))
        elif ext in {".zip", ".7z", ".rar", ".tar", ".gz"}:
            meta = ArchiveSniffer.extract(str(p))
        elif ext in {".docx", ".xlsx", ".pptx"}:
            meta = OfficeMetadataExtractor.extract(str(p))
        elif ext in {".mp4", ".mkv", ".avi", ".mov", ".flv"}:
            meta = AssetMetadataContract(morphology="media")
            meta.is_obfuscated_name = is_obfuscated_filename(p.name)
            meta.normalized_name = p.name
            meta.domain_sector = infer_domain_sector(meta, p.name)
        else:
            meta = AssetMetadataContract(morphology="standalone_file")
            meta.is_obfuscated_name = is_obfuscated_filename(p.name)
            meta.normalized_name = p.name
            meta.domain_sector = infer_domain_sector(meta, p.name)

        if not meta.domain_sector:
            meta.domain_sector = infer_domain_sector(meta, p.name)
        return meta

    @classmethod
    def extract_collective(cls, dir_path: Path | str, primary_executable: str = "") -> AssetMetadataContract:
        """
        为【原子实体集体 (Collective)】进行身份证铭牌确权：
        通过目录内主入口程序的 PE 铭牌，赋予集合不可争辩的真实产品名与版本。
        """
        p = Path(dir_path)
        meta = AssetMetadataContract(morphology="portable_runtime_dir")
        meta.software_name = p.name
        meta.domain_sector = "_已解压程序与归档"
        meta.lifecycle_recommendation = "已解压运行目录，建议移入独立软件目录或归档"

        exe_path = None
        try:
            if primary_executable and (p / primary_executable).exists():
                exe_path = p / primary_executable
            else:
                top_exes = [f for f in p.glob("*.exe") if not f.name.lower().startswith("unins")]
                if top_exes:
                    exe_path = sorted(top_exes, key=lambda x: len(x.name))[0]

            if exe_path and exe_path.exists():
                pe_meta = PEExtractor.extract(str(exe_path))
                if pe_meta.software_name:
                    meta.software_name = pe_meta.software_name
                if pe_meta.product_version:
                    meta.product_version = pe_meta.product_version
                if pe_meta.file_description:
                    meta.file_description = pe_meta.file_description
                if pe_meta.publisher:
                    meta.publisher = pe_meta.publisher
        except Exception:
            pass

        meta.normalized_name = f"{meta.software_name}_运行目录"
        return meta
