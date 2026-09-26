import json
import time
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional

GLOBAL_CATEGORIES_FILE = Path.home() / ".disk_space_analyzer" / "global_categories.json"

class CategoryManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CategoryManager, cls).__new__(cls)
            cls._instance._categories = []
            cls._instance.load()
        return cls._instance

    def load(self):
        if GLOBAL_CATEGORIES_FILE.exists():
            try:
                with open(GLOBAL_CATEGORIES_FILE, 'r', encoding='utf-8') as f:
                    self._categories = json.load(f)
            except Exception:
                self._categories = self._get_default_categories()
        else:
            self._categories = self._get_default_categories()
            self.save()

    def _get_default_categories(self) -> List[Dict[str, Any]]:
        # Some default AI classification mappings as global categories
        return [
            {
                "category_id": "cat_code_project",
                "name": "代码项目与依赖 (Dev & Code)",
                "description": "存放代码源码、Git仓库、Node_modules、构建产物等开发资产。",
                "target_path_template": "{archive_root}/Developer_Workspace/{app_name}",
                "priority": 100,
                "enabled": True,
                "created_at": time.time(),
                "updated_at": time.time(),
                "source": "global"
            },
            {
                "category_id": "cat_cache_tmp",
                "name": "缓存与临时数据 (Caches & Temp)",
                "description": "存放各软件的运行时缓存、Log日志、临时下载文件等，安全清理风险低。",
                "target_path_template": "{archive_root}/App_Caches_Trash/{app_name}",
                "priority": 90,
                "enabled": True,
                "created_at": time.time(),
                "updated_at": time.time(),
                "source": "global"
            },
            {
                "category_id": "cat_doc_media",
                "name": "文档与多媒体资产 (Docs & Media)",
                "description": "图片、视频、设计稿、Office文档、PDF资料等非执行性质的资产。",
                "target_path_template": "{archive_root}/Documents_And_Media/{app_name}",
                "priority": 80,
                "enabled": True,
                "created_at": time.time(),
                "updated_at": time.time(),
                "source": "global"
            }
        ]

    def save(self):
        GLOBAL_CATEGORIES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(GLOBAL_CATEGORIES_FILE, 'w', encoding='utf-8') as f:
            json.dump(self._categories, f, indent=2, ensure_ascii=False)

    def get_all(self) -> List[Dict[str, Any]]:
        return sorted(self._categories, key=lambda x: x.get("priority", 0), reverse=True)
        
    def get_active(self) -> List[Dict[str, Any]]:
        return [c for c in self.get_all() if c.get("enabled", True)]

    def add_category(self, cat: Dict[str, Any]):
        if "category_id" not in cat or not cat["category_id"]:
            cat["category_id"] = "cat_" + str(uuid.uuid4())[:8]
        cat["source"] = "global"
        cat["created_at"] = time.time()
        cat["updated_at"] = time.time()
        self._categories.append(cat)
        self.save()

    def update_category(self, cat_id: str, updates: Dict[str, Any]):
        for cat in self._categories:
            if cat.get("category_id") == cat_id:
                cat.update(updates)
                cat["updated_at"] = time.time()
                break
        self.save()

    def delete_category(self, cat_id: str):
        self._categories = [c for c in self._categories if c.get("category_id") != cat_id]
        self.save()

global_category_manager = CategoryManager()
