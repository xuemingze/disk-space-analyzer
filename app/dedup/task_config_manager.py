"""
app/dedup/task_config_manager.py
查重与融合用户配置与历史预设管理器
"""
import json
from pathlib import Path
from typing import Dict, Any
from app.dedup.models import DedupScanConfig
from app.utils.logger import app_logger

CONFIG_FILE_PATH = Path.home() / ".disk_space_analyzer" / "dedup_task_config.json"


class DedupTaskConfigManager:
    """查重与融合配置持久化"""

    @classmethod
    def load_config(cls) -> DedupScanConfig:
        if not CONFIG_FILE_PATH.exists():
            return DedupScanConfig()

        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                data: Dict[str, Any] = json.load(f)
            return DedupScanConfig(
                source_dirs=data.get("source_dirs", []),
                target_dir=data.get("target_dir"),
                isolation_dir=data.get("isolation_dir"),
                prune_collectives=data.get("prune_collectives", True),
                skip_system_protected=data.get("skip_system_protected", True),
                min_file_size=data.get("min_file_size", 1),
                hash_algorithm=data.get("hash_algorithm", "sha256"),
                ignore_folders=data.get("ignore_folders", []),
                dedup_keep_preference=data.get("dedup_keep_preference", "keep_primary")
            )
        except Exception as e:
            app_logger.warning("读取查重配置失败，使用默认配置: %s", e)
            return DedupScanConfig()

    @classmethod
    def save_config(cls, config: DedupScanConfig) -> bool:
        try:
            CONFIG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "source_dirs": config.source_dirs,
                "target_dir": config.target_dir,
                "isolation_dir": config.isolation_dir,
                "prune_collectives": config.prune_collectives,
                "skip_system_protected": config.skip_system_protected,
                "min_file_size": config.min_file_size,
                "hash_algorithm": config.hash_algorithm,
                "ignore_folders": config.ignore_folders,
                "dedup_keep_preference": config.dedup_keep_preference
            }
            with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            app_logger.error("保存查重配置失败: %s", e)
            return False
