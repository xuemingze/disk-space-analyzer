import os
import shutil
from pathlib import Path
import pytest

from app.core.registry_detector import CUSTOM_APPS_PERSIST_FILE, RegistryAppDetector
from app.config import DEFAULT_CONFIG_PATH, app_config
from app.core.category_manager import (
    GLOBAL_CATEGORIES_FILE, PRECIPITATED_RULES_FILE, global_category_manager
)

@pytest.fixture(scope="session", autouse=True)
def protect_user_config_and_custom_apps():
    """
    会话级全自动保护夹具：
    测试运行期间备份用户的真实 config.json、custom_apps.json、global_categories.json 与 precipitated_rules.json，
    并在全量测试结束后完整恢复，确保本地自动化测试绝不破坏或覆盖用户自定义沉淀数据。
    """
    backup_dir = Path.home() / ".disk_space_analyzer" / "_test_backup"
    backup_dir.mkdir(parents=True, exist_ok=True)

    cfg_bak = backup_dir / "config.json.bak"
    apps_bak = backup_dir / "custom_apps.json.bak"
    cat_bak = backup_dir / "global_categories.json.bak"
    rules_bak = backup_dir / "precipitated_rules.json.bak"

    if DEFAULT_CONFIG_PATH.exists():
        shutil.copy2(DEFAULT_CONFIG_PATH, cfg_bak)
    if CUSTOM_APPS_PERSIST_FILE.exists():
        shutil.copy2(CUSTOM_APPS_PERSIST_FILE, apps_bak)
    if GLOBAL_CATEGORIES_FILE.exists():
        shutil.copy2(GLOBAL_CATEGORIES_FILE, cat_bak)
    if PRECIPITATED_RULES_FILE.exists():
        shutil.copy2(PRECIPITATED_RULES_FILE, rules_bak)

    yield

    # 测试结束后恢复
    if cfg_bak.exists():
        shutil.copy2(cfg_bak, DEFAULT_CONFIG_PATH)
        cfg_bak.unlink()
    if apps_bak.exists():
        shutil.copy2(apps_bak, CUSTOM_APPS_PERSIST_FILE)
        apps_bak.unlink()
    if cat_bak.exists():
        shutil.copy2(cat_bak, GLOBAL_CATEGORIES_FILE)
        cat_bak.unlink()
    if rules_bak.exists():
        shutil.copy2(rules_bak, PRECIPITATED_RULES_FILE)
        rules_bak.unlink()

    # 清理备份目录
    try:
        shutil.rmtree(backup_dir, ignore_errors=True)
    except Exception:
        pass

    # 重新加载配置与应用缓存
    try:
        app_config.reload()
        RegistryAppDetector.get_installed_apps(force_reload=True)
        global_category_manager.load()
    except Exception:
        pass
