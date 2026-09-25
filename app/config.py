import os
import json
import copy
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

DEFAULT_CONFIG_PATH = Path.home() / ".disk_space_analyzer" / "config.json"

# 底座硬编码默认配置 (Level 0: Default Baseline)
BASE_CONFIG_SCHEMA = {
    "scan_paths": ["C:\\"],
    "exclude_dirs": ["$Recycle.Bin", "System Volume Information", "Windows\\WinSxS", "Windows\\System32"],
    "ignore_folders": [],
    "hash_algorithm": "md5",
    "archive_dir": str(Path("D:/归档备份").resolve() if Path("D:/").exists() else Path.home() / "DiskAnalyzerArchive"),
    "migration_dir": str(Path("D:/软件与文件迁移").resolve() if Path("D:/").exists() else Path.home() / "MigratedApps"),
    "clean_policy": "recycle_bin",  # recycle_bin | permanent
    "llm": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o-mini",
        "timeout": 30,
        "available_models": ["gpt-4o-mini", "gpt-4o", "deepseek-chat", "qwen-max", "claude-3-5-sonnet"]
    },
    "perf_options": {
        "concurrency": 4,           # 并发哈希线程数 (1-16)
        "chunk_size_kb": 1024,      # 分块流式读取大小 (KB)
        "sample_size_kb": 8,        # 头部采样哈希大小 (KB)
        "ui_throttle_ms": 60,       # UI 进度刷新节流 (ms)
        "use_hash_cache": True,     # 是否启用 SQLite 哈希缓存
        "large_file_threshold_mb": 100,
        "skip_system_dirs": True
    },
    "migration_options": {
        "create_junction": True,
        "sync_shortcuts": True,
        "sync_registry": True,
        "create_rollback_manifest": True
    },
    "ui": {
        "theme": "dark",
        "window_width": 1320,
        "window_height": 880
    }
}

# 内置预设模板 (Level 2 Profiles)
BUILTIN_PROFILES = {
    "default": {
        "name": "默认均衡模式 (Default)",
        "description": "全局配置直通模式，兼顾扫描深度与执行速度",
        "parent": "base",
        "overrides": {}
    },
    "fast_scan": {
        "name": "极速扫描预设 (Fast)",
        "description": "跳过深度哈希比对，极速输出空间分布与 Top 大文件",
        "parent": "default",
        "overrides": {
            "perf_options": {
                "concurrency": 8,
                "skip_system_dirs": True
            },
            "hash_algorithm": "md5"
        }
    },
    "deep_clean": {
        "name": "深度查重与强安全预设 (Deep)",
        "description": "启用多线程 SHA256 分块查重与强安全审计",
        "parent": "default",
        "overrides": {
            "hash_algorithm": "sha256",
            "perf_options": {
                "concurrency": 6,
                "sample_size_kb": 16,
                "skip_system_dirs": True
            }
        }
    },
    "dev_governance": {
        "name": "开发环境与大依赖治理预设 (Dev)",
        "description": "针对 node_modules, uv, pnpm, pip 等包缓存深度排查与智能治理",
        "parent": "default",
        "overrides": {
            "perf_options": {
                "large_file_threshold_mb": 50
            }
        }
    }
}


class ConfigManager:
    """
    三层配置继承引擎:
    - Level 0: Default Baseline (系统默认)
    - Level 1: Global Config (全局持久化配置)
    - Level 2: Profile / Task Overrides (任务/预设级覆盖配置，最高优先级)
    """

    def __init__(self, config_file: Path = DEFAULT_CONFIG_PATH):
        self.config_file = config_file
        self.raw_data = self._load_raw()

    def _load_raw(self) -> dict:
        if not self.config_file.exists():
            initial_data = {
                "active_profile": "default",
                "global_config": copy.deepcopy(BASE_CONFIG_SCHEMA),
                "profiles": copy.deepcopy(BUILTIN_PROFILES)
            }
            self._save_raw(initial_data)
            return initial_data

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 兼容旧版本单层配置升级
            if "global_config" not in data:
                old_settings = data.get("base_config", data.copy())
                data = {
                    "active_profile": data.get("active_profile", "default"),
                    "global_config": copy.deepcopy(BASE_CONFIG_SCHEMA),
                    "profiles": data.get("profiles", copy.deepcopy(BUILTIN_PROFILES))
                }
                self._deep_merge(data["global_config"], old_settings)
                self._save_raw(data)

            # 确保内置预设完整
            profiles = data.setdefault("profiles", {})
            for p_id, p_val in BUILTIN_PROFILES.items():
                if p_id not in profiles:
                    profiles[p_id] = copy.deepcopy(p_val)

            return data
        except Exception as e:
            print(f"配置文件加载异常: {e}，重置为默认配置")
            return {
                "active_profile": "default",
                "global_config": copy.deepcopy(BASE_CONFIG_SCHEMA),
                "profiles": copy.deepcopy(BUILTIN_PROFILES)
            }

    def _save_raw(self, data: dict):
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"保存配置文件失败: {e}")

    @staticmethod
    def _deep_merge(target: dict, source: dict):
        for k, v in source.items():
            if isinstance(v, dict) and k in target and isinstance(target[k], dict):
                ConfigManager._deep_merge(target[k], v)
            else:
                target[k] = copy.deepcopy(v)

    def get_active_profile_name(self) -> str:
        return self.raw_data.get("active_profile", "default")

    def set_active_profile(self, profile_name: str) -> bool:
        if profile_name in self.raw_data.get("profiles", {}):
            self.raw_data["active_profile"] = profile_name
            self._save_raw(self.raw_data)
            return True
        return False

    def list_profiles(self) -> Dict[str, Dict[str, Any]]:
        return self.raw_data.get("profiles", {})

    def resolve_effective_config(self, profile_name: Optional[str] = None) -> dict:
        """
        计算最终生效配置 (Effective Config):
        Default Schema -> Global Config -> Profile Overrides
        """
        p_name = profile_name or self.get_active_profile_name()
        profiles = self.raw_data.get("profiles", {})

        # 1. 基础默认值
        effective = copy.deepcopy(BASE_CONFIG_SCHEMA)

        # 2. 全局配置覆盖
        global_cfg = self.raw_data.get("global_config", {})
        self._deep_merge(effective, global_cfg)

        # 3. 继承链预设覆盖
        chain = []
        curr = p_name
        visited = set()
        while curr and curr != "base" and curr in profiles and curr not in visited:
            visited.add(curr)
            chain.append(curr)
            curr = profiles[curr].get("parent", "base")

        for pid in reversed(chain):
            overrides = profiles[pid].get("overrides", {})
            self._deep_merge(effective, overrides)

        return effective

    def get(self, *keys, default=None):
        """获取当前生效配置值"""
        cfg = self.resolve_effective_config()
        curr = cfg
        for k in keys:
            if isinstance(curr, dict) and k in curr:
                curr = curr[k]
            else:
                return default
        return curr

    def get_with_source(self, *keys, default=None) -> Tuple[Any, str]:
        """
        获取配置值并追溯其生效来源:
        返回 (value, "任务级预设" | "全局配置" | "系统默认")
        """
        p_name = self.get_active_profile_name()
        profiles = self.raw_data.get("profiles", {})
        
        # 1. 检查当前 Profile overrides
        if p_name in profiles:
            overrides = profiles[p_name].get("overrides", {})
            curr = overrides
            found_in_profile = True
            for k in keys:
                if isinstance(curr, dict) and k in curr:
                    curr = curr[k]
                else:
                    found_in_profile = False
                    break
            if found_in_profile:
                return curr, "任务级预设"

        # 2. 检查全局配置
        global_cfg = self.raw_data.get("global_config", {})
        curr = global_cfg
        found_in_global = True
        for k in keys:
            if isinstance(curr, dict) and k in curr:
                curr = curr[k]
            else:
                found_in_global = False
                break
        if found_in_global:
            return curr, "全局配置"

        # 3. 检查硬编码默认
        curr = BASE_CONFIG_SCHEMA
        found_in_default = True
        for k in keys:
            if isinstance(curr, dict) and k in curr:
                curr = curr[k]
            else:
                found_in_default = False
                break
        if found_in_default:
            return curr, "系统默认"

        return default, "未配置"

    def set(self, *keys_and_value, level: str = "global"):
        """
        设置配置项
        :param level: "global" (写入全局配置) 或 "profile" (写入当前任务方案覆盖)
        """
        if len(keys_and_value) < 2:
            return
        keys = keys_and_value[:-1]
        val = keys_and_value[-1]

        if level == "profile":
            p_name = self.get_active_profile_name()
            overrides = self.raw_data["profiles"].setdefault(p_name, {}).setdefault("overrides", {})
            curr = overrides
            for k in keys[:-1]:
                if k not in curr or not isinstance(curr[k], dict):
                    curr[k] = {}
                curr = curr[k]
            curr[keys[-1]] = val
        else:
            # 写入 global_config
            global_cfg = self.raw_data.setdefault("global_config", copy.deepcopy(BASE_CONFIG_SCHEMA))
            curr = global_cfg
            for k in keys[:-1]:
                if k not in curr or not isinstance(curr[k], dict):
                    curr[k] = {}
                curr = curr[k]
            curr[keys[-1]] = val

        self._save_raw(self.raw_data)

    def create_custom_profile(self, profile_id: str, name: str, description: str, parent: str = "default") -> bool:
        profiles = self.raw_data.setdefault("profiles", {})
        if profile_id in profiles:
            return False
        profiles[profile_id] = {
            "name": name,
            "description": description,
            "parent": parent,
            "overrides": {}
        }
        self._save_raw(self.raw_data)
        return True

    def delete_custom_profile(self, profile_id: str) -> bool:
        if profile_id in BUILTIN_PROFILES:
            return False
        if profile_id in self.raw_data.get("profiles", {}):
            del self.raw_data["profiles"][profile_id]
            if self.raw_data.get("active_profile") == profile_id:
                self.raw_data["active_profile"] = "default"
            self._save_raw(self.raw_data)
            return True
        return False


app_config = ConfigManager()
