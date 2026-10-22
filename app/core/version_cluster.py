"""
多版本文件与相似文档聚类识别引擎 (Version Cluster Engine)

本模块以面向对象思维为根本，提供同族多版本文件的识别、特征提取与聚类：
1. 词干归一化与版本特征剥离 (剥离 _v1, _v2, _draft, _final, _定稿, _修改版, (1), _copy 等)
2. 隐私敏感内容脱敏抽样集成 (extract_file_content_sample)
3. 同族多版本聚合 (VersionClusterGroup)
4. 单文件同族邻居发现 (find_sibling_versions)
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from app.core.domain_models import (
    ScannedAsset,
    VersionClusterGroup,
    VersionClusterItem,
)
from app.core.organize_models import extract_file_content_sample


class VersionClusterDetector:
    """
    同族多版本文件聚类探测器 (Version Cluster Detector)
    """

    # 常见多版本/副本标记正则模式 (从文件名末尾匹配)
    SUFFIX_PATTERNS = [
        # 1. 括号副本号: " (1)", " (2)", "（1）", "(副本)"
        re.compile(r'[\s_\-]*[（\(](?:\d+|副本|copy|复件)[）\)]$', re.IGNORECASE),
        # 2. 中文版本阶段标识: "_初稿", "-修改版", "_定稿", "_最新版", "_最终版", "_终稿", "_备份", "_副本", "_草稿", "_复件"
        re.compile(r'[\s_\-]+(?:初稿|修改版|定稿|最新版|最终版|终稿|备份|副本|草稿|复件)$', re.IGNORECASE),
        # 3. 英文版本阶段标识: "_draft", "-final", "_copy", "_backup", "_new", "_old", "_temp", "_revised", "_rev"
        re.compile(r'[\s_\-]+(?:draft|final\d*|copy|backup|new|old|temp|revised|rev)$', re.IGNORECASE),
        # 4. 数字版本号: "_v1", "-v2.1", "_ver3", "_V1.0.2", "_1", "-2"
        re.compile(r'[\s_\-]+(?:v|ver|version)?\d+(?:\.\d+)*(?:[a-zA-Z])?$', re.IGNORECASE),
        # 5. 年月日时间戳尾缀: "_20231012", "-2024-05-01", "_2023.12.01"
        re.compile(r'[\s_\-]+(?:19|20)\d{2}[-_.]?\d{2}[-_.]?\d{2}(?:[-_.]?\d{2,6})?$', re.IGNORECASE),
    ]

    @classmethod
    def extract_version_info(cls, file_name: str) -> Tuple[str, str]:
        """
        从文件名中解析出归一化词干与版本后缀标识。
        例如:
        - "年度财务报告_v2_定稿.docx" -> ("年度财务报告", "_v2_定稿")
        - "需求规划文档 (1).pdf" -> ("需求规划文档", " (1)")
        - "main_backup.py" -> ("main", "_backup")
        - "README.md" -> ("README", "")
        """
        if not file_name:
            return "", ""

        # 分离主名与扩展名
        p = Path(file_name)
        stem = p.stem
        # 处理双扩展名如 .tar.gz
        if stem.endswith(".tar"):
            stem = stem[:-4]

        orig_stem = stem
        peeled_suffixes: List[str] = []

        # 循环剥离末尾匹配的版本模式 (最多剥离 5 层，防止死循环)
        changed = True
        iterations = 0
        while changed and iterations < 5:
            changed = False
            iterations += 1
            for pat in cls.SUFFIX_PATTERNS:
                m = pat.search(stem)
                if m:
                    match_str = m.group(0)
                    candidate_stem = stem[:m.start()].rstrip(" _-")
                    # 确保剥离后词干不为空
                    if candidate_stem:
                        peeled_suffixes.insert(0, match_str)
                        stem = candidate_stem
                        changed = True
                        break

        if peeled_suffixes:
            version_suffix = "".join(peeled_suffixes)
        else:
            version_suffix = ""

        # 归一化词干 (去除冗余空格)
        normalized_stem = stem.strip()
        if not normalized_stem:
            normalized_stem = orig_stem.strip()
            version_suffix = ""

        return normalized_stem, version_suffix

    @classmethod
    def build_cluster_item(
        cls,
        asset: Union[ScannedAsset, Dict[str, Any], str],
        extract_snippet: bool = True
    ) -> VersionClusterItem:
        """
        将资产对象、字典或路径构造成强类型的 VersionClusterItem
        """
        if isinstance(asset, str):
            path = asset
            name = os.path.basename(path)
            size = 0
            mtime = time.time()
            if os.path.exists(path):
                try:
                    stat = os.stat(path)
                    size = stat.st_size
                    mtime = stat.st_mtime
                except Exception:
                    pass
            category = "文档/多版本"
        elif isinstance(asset, ScannedAsset):
            path = asset.path
            name = asset.name or os.path.basename(path)
            size = asset.size
            mtime = asset.mtime
            category = asset.category or "文档/多版本"
        elif isinstance(asset, dict):
            path = asset.get("path", "")
            name = asset.get("name") or os.path.basename(path)
            size = asset.get("size", 0)
            mtime = asset.get("mtime", time.time())
            category = asset.get("category", "文档/多版本")
        else:
            path = str(asset)
            name = os.path.basename(path)
            size = 0
            mtime = time.time()
            category = "文档/多版本"

        stem, v_suffix = cls.extract_version_info(name)

        snippet = ""
        if extract_snippet and path and os.path.isfile(path):
            try:
                snippet = extract_file_content_sample(path, max_bytes=300)
            except Exception:
                snippet = ""

        return VersionClusterItem(
            path=path,
            name=name,
            size=size,
            mtime=mtime,
            stem=stem,
            version_suffix=v_suffix,
            category=category,
            content_snippet=snippet,
            is_recommended_keep=False,
            retention_action="待AI研判",
            decision_reason="",
        )

    @classmethod
    def find_clusters(
        cls,
        assets: List[Union[ScannedAsset, Dict[str, Any], str]],
        extract_snippets: bool = True,
        same_dir_only: bool = True
    ) -> List[VersionClusterGroup]:
        """
        在给定的资产集合中识别同族多版本文件聚类。
        返回成员数 >= 2 的聚类组列表。
        """
        if not assets:
            return []

        # 1. 构造所有项目
        items: List[VersionClusterItem] = []
        for a in assets:
            try:
                items.append(cls.build_cluster_item(a, extract_snippet=extract_snippets))
            except Exception:
                continue

        # 2. 分组聚类: key = (normalized_stem.lower(), directory if same_dir_only else "")
        groups_dict: Dict[Tuple[str, str], List[VersionClusterItem]] = {}
        for it in items:
            p = it.path
            dir_key = os.path.normpath(os.path.dirname(p)).lower() if same_dir_only else ""
            key = (it.stem.lower(), dir_key)
            if key not in groups_dict:
                groups_dict[key] = []
            groups_dict[key].append(it)

        # 3. 过滤并组装 VersionClusterGroup (仅保留成员数 >= 2 的组)
        result: List[VersionClusterGroup] = []
        idx = 1
        for (stem_lower, dir_key), grp_items in groups_dict.items():
            if len(grp_items) < 2:
                continue

            # 使用第一个项的 stem 和实际目录
            common_stem = grp_items[0].stem
            common_dir = os.path.dirname(grp_items[0].path)

            group_obj = VersionClusterGroup(
                group_id=f"cluster_{idx:03d}",
                normalized_stem=common_stem,
                directory=common_dir,
                items=grp_items,
                recommended_keep_path="",
                ai_summary="",
                ai_evaluated=False,
            )
            result.append(group_obj)
            idx += 1

        return result

    @classmethod
    def find_sibling_versions(
        cls,
        target_path: str,
        candidate_pool: Optional[List[Union[ScannedAsset, Dict[str, Any], str]]] = None,
        search_filesystem_if_empty: bool = True
    ) -> Optional[VersionClusterGroup]:
        """
        为单个目标文件查找其在候选池或物理同级目录中的同族兄弟版本。
        若发现至少 1 个同族兄弟（包含自身共 >= 2 个），返回 VersionClusterGroup，否则返回 None。
        """
        if not target_path:
            return None

        target_name = os.path.basename(target_path)
        target_stem, _ = cls.extract_version_info(target_name)
        if not target_stem:
            return None

        target_dir = os.path.dirname(os.path.abspath(target_path))
        target_stem_lower = target_stem.lower()

        # 1. 如果有候选池，优先在候选池中查找同目录且同词干的项
        if candidate_pool:
            pool_items: List[Union[ScannedAsset, Dict[str, Any], str]] = []
            for item in candidate_pool:
                p = item.path if isinstance(item, ScannedAsset) else (item.get("path") if isinstance(item, dict) else str(item))
                if not p:
                    continue
                if os.path.normpath(os.path.dirname(os.path.abspath(p))).lower() == os.path.normpath(target_dir).lower():
                    s, _ = cls.extract_version_info(os.path.basename(p))
                    if s.lower() == target_stem_lower:
                        pool_items.append(item)

            if len(pool_items) >= 2:
                clusters = cls.find_clusters(pool_items, extract_snippets=True, same_dir_only=True)
                if clusters:
                    return clusters[0]

        # 2. 若候选池未满足且允许探测物理文件系统，扫描所在父目录
        if search_filesystem_if_empty and os.path.isdir(target_dir):
            try:
                disk_files: List[str] = []
                for entry in os.listdir(target_dir):
                    full = os.path.join(target_dir, entry)
                    if os.path.isfile(full):
                        s, _ = cls.extract_version_info(entry)
                        if s.lower() == target_stem_lower:
                            disk_files.append(full)

                if len(disk_files) >= 2:
                    clusters = cls.find_clusters(disk_files, extract_snippets=True, same_dir_only=True)
                    if clusters:
                        return clusters[0]
            except Exception:
                pass

        return None
