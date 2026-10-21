import json
import time
import uuid
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional

GLOBAL_CATEGORIES_FILE = Path.home() / ".disk_space_analyzer" / "global_categories.json"
PRECIPITATED_RULES_FILE = Path.home() / ".disk_space_analyzer" / "precipitated_rules.json"

class CategoryManager:
    _instance = None
    _lock = threading.RLock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(CategoryManager, cls).__new__(cls)
                    cls._instance._categories = []
                    cls._instance._rules = []
                    cls._instance.load()
        return cls._instance

    def load(self):
        with self._lock:
            # 1. 加载全局 2~3 级分类树
            if GLOBAL_CATEGORIES_FILE.exists():
                try:
                    with open(GLOBAL_CATEGORIES_FILE, 'r', encoding='utf-8') as f:
                        self._categories = json.load(f)
                except Exception:
                    self._categories = self._get_default_categories()
            else:
                self._categories = self._get_default_categories()
                self.save_categories()

            if not self._categories:
                self._categories = self._get_default_categories()
                self.save_categories()

            # 2. 加载自沉淀规则库
            if PRECIPITATED_RULES_FILE.exists():
                try:
                    with open(PRECIPITATED_RULES_FILE, 'r', encoding='utf-8') as f:
                        self._rules = json.load(f)
                except Exception:
                    self._rules = []
            else:
                self._rules = []

    def _get_default_categories(self) -> List[Dict[str, Any]]:
        # 默认 2~3 级分类规范结构树
        return [
            {
                "category_id": "cat_code_project",
                "name": "代码项目与依赖 (Dev & Code)",
                "description": "存放代码源码、Git仓库、Node_modules、构建产物等开发资产。",
                "target_path_template": "{archive_root}/Developer_Workspace/{app_name}",
                "priority": 100,
                "enabled": True,
                "level": 1,
                "children": [
                    {
                        "category_id": "cat_frontend_proj",
                        "name": "前端工程",
                        "target_path_template": "{archive_root}/Developer_Workspace/Frontend/{app_name}",
                        "priority": 95,
                        "enabled": True,
                        "level": 2,
                        "children": []
                    },
                    {
                        "category_id": "cat_backend_proj",
                        "name": "后端服务与工具",
                        "target_path_template": "{archive_root}/Developer_Workspace/Backend/{app_name}",
                        "priority": 90,
                        "enabled": True,
                        "level": 2,
                        "children": []
                    }
                ],
                "created_at": time.time(),
                "updated_at": time.time(),
                "source": "global"
            },
            {
                "category_id": "cat_ops_tools",
                "name": "运维工具 (DevOps Tools)",
                "description": "运维管理、网络诊断、系统巡检与自动化工具链。",
                "target_path_template": "{archive_root}/Ops_Tools/{app_name}",
                "priority": 95,
                "enabled": True,
                "level": 1,
                "children": [
                    {
                        "category_id": "cat_net_troubleshoot",
                        "name": "网络排障",
                        "target_path_template": "{archive_root}/Ops_Tools/Network_Diagnostics/{app_name}",
                        "priority": 90,
                        "enabled": True,
                        "level": 2,
                        "children": [
                            {
                                "category_id": "cat_packet_capture",
                                "name": "抓包工具",
                                "target_path_template": "{archive_root}/Ops_Tools/Network_Diagnostics/Capture/{app_name}",
                                "priority": 85,
                                "enabled": True,
                                "level": 3,
                                "children": []
                            }
                        ]
                    },
                    {
                        "category_id": "cat_sys_monitor",
                        "name": "系统监控",
                        "target_path_template": "{archive_root}/Ops_Tools/System_Monitor/{app_name}",
                        "priority": 88,
                        "enabled": True,
                        "level": 2,
                        "children": []
                    }
                ],
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
                "level": 1,
                "children": [],
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
                "level": 1,
                "children": [
                    {
                        "category_id": "cat_biz_docs",
                        "name": "业务单据与报表",
                        "target_path_template": "{archive_root}/Documents_And_Media/Business_Docs/{app_name}",
                        "priority": 85,
                        "enabled": True,
                        "level": 2,
                        "children": []
                    }
                ],
                "created_at": time.time(),
                "updated_at": time.time(),
                "source": "global"
            }
        ]

    def save_categories(self):
        with self._lock:
            GLOBAL_CATEGORIES_FILE.parent.mkdir(parents=True, exist_ok=True)
            temp_file = GLOBAL_CATEGORIES_FILE.with_suffix(".tmp")
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self._categories, f, indent=2, ensure_ascii=False)
            try:
                temp_file.replace(GLOBAL_CATEGORIES_FILE)
            except Exception:
                with open(GLOBAL_CATEGORIES_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self._categories, f, indent=2, ensure_ascii=False)
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except Exception:
                        pass

    def save_rules(self):
        with self._lock:
            PRECIPITATED_RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
            temp_file = PRECIPITATED_RULES_FILE.with_suffix(".tmp")
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self._rules, f, indent=2, ensure_ascii=False)
            try:
                temp_file.replace(PRECIPITATED_RULES_FILE)
            except Exception:
                with open(PRECIPITATED_RULES_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self._rules, f, indent=2, ensure_ascii=False)
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except Exception:
                        pass

    def save(self):
        with self._lock:
            self.save_categories()
            self.save_rules()

    def get_tree(self) -> List[Dict[str, Any]]:
        """获取层级完整的 2~3 级分类树"""
        with self._lock:
            return list(self._categories)

    def save_tree(self, tree: List[Dict[str, Any]]):
        """保存由 AI 统揽构建或用户调整的完整分类树"""
        with self._lock:
            self._categories = tree
            self.save_categories()

    def get_all(self, flatten: bool = False) -> List[Dict[str, Any]]:
        """
        获取分类列表。
        flatten=False 时返回根节点列表 (兼容既有代码)，
        flatten=True 时递归打平成一维列表，每个节点包含 full_path。
        """
        if not flatten:
            return sorted(self._categories, key=lambda x: x.get("priority", 0), reverse=True)
        
        flat_list = []
        def _flatten(nodes, prefix=""):
            for n in nodes:
                full_name = f"{prefix} / {n['name']}" if prefix else n['name']
                item = dict(n)
                item["full_path"] = full_name
                flat_list.append(item)
                children = n.get("children", [])
                if children:
                    _flatten(children, full_name)

        _flatten(self._categories)
        return sorted(flat_list, key=lambda x: x.get("priority", 0), reverse=True)
        
    def get_active(self, flatten: bool = False) -> List[Dict[str, Any]]:
        """获取所有已启用的分类"""
        return [c for c in self.get_all(flatten=flatten) if c.get("enabled", True)]

    def find_node_by_id(self, cat_id: str) -> Optional[Dict[str, Any]]:
        """根据 ID 递归查找节点"""
        def _search(nodes):
            for n in nodes:
                if n.get("category_id") == cat_id:
                    return n
                sub = _search(n.get("children", []))
                if sub:
                    return sub
            return None
        return _search(self._categories)

    def find_node_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """根据名称或路径模糊/精准查找节点"""
        clean_name = name.strip()
        for node in self.get_all(flatten=True):
            if node.get("name") == clean_name or node.get("full_path") == clean_name:
                return node
        return None

    def add_category(self, cat: Dict[str, Any], parent_id: Optional[str] = None):
        """新增分类，可挂载至特定父节点实现 2~3 级树状拓扑"""
        with self._lock:
            if "category_id" not in cat or not cat["category_id"]:
                cat["category_id"] = "cat_" + str(uuid.uuid4())[:8]
            if "children" not in cat:
                cat["children"] = []
            cat["source"] = cat.get("source", "global")
            cat["created_at"] = time.time()
            cat["updated_at"] = time.time()
            
            if parent_id:
                parent = self.find_node_by_id(parent_id)
                if parent:
                    cat["level"] = parent.get("level", 1) + 1
                    parent.setdefault("children", []).append(cat)
                    self.save_categories()
                    return
            
            cat["level"] = 1
            self._categories.append(cat)
            self.save_categories()

    def update_category(self, cat_id: str, updates: Dict[str, Any]):
        """递归更新指定分类节点属性"""
        with self._lock:
            node = self.find_node_by_id(cat_id)
            if node:
                node.update(updates)
                node["updated_at"] = time.time()
                self.save_categories()

    def delete_category(self, cat_id: str):
        """递归删除指定分类节点"""
        with self._lock:
            def _del_from(nodes):
                for i, n in enumerate(nodes):
                    if n.get("category_id") == cat_id:
                        del nodes[i]
                        return True
                    if _del_from(n.get("children", [])):
                        return True
                return False
            if _del_from(self._categories):
                self.save_categories()

    def snap_to_tree(self, path_or_text: str) -> Optional[Dict[str, Any]]:
        """
        分类树吸附算法：
        根据用户手改规划路径或关键词，向现存 2~3 级分类树深度吸附定位最近节点。
        支持 Windows 盘符、UNC 网络共享路径、多级深层嵌套与中英文模板混合吸附。
        """
        if not path_or_text:
            return None
        norm_text = path_or_text.replace("\\", "/").strip().lower()
        parts = [p.strip() for p in norm_text.split("/") if p.strip()]

        # 过滤盘符与 UNC 共享服务器名 (//server/share)
        if norm_text.startswith("//") and len(parts) >= 2:
            clean_parts = parts[2:]
        else:
            clean_parts = [p for p in parts if not (len(p) <= 2 and p.endswith(":"))]

        best_match = None
        best_depth = -1

        norm_no_space = norm_text.replace(" ", "")

        # 遍历扁平化的全量树节点，优先命中层级更深(3级 > 2级 > 1级)的节点
        all_nodes = self.get_all(flatten=True)
        for node in all_nodes:
            n_name = node.get("name", "").lower()
            f_path = node.get("full_path", "").lower()
            level = node.get("level", 1)
            
            # 完整路径匹配、名称匹配 (忽略英文括号注解) 或目标模板匹配
            clean_n_name = n_name.split("(")[0].strip()
            clean_tmpl = node.get("target_path_template", "").lower()
            for ph in ["{archive_root}/", "{archive_root}", "/{app_name}", "{app_name}"]:
                clean_tmpl = clean_tmpl.replace(ph, "")
            clean_tmpl = clean_tmpl.strip("/")

            tmpl_matched = bool(clean_tmpl and (clean_tmpl in norm_text or (len(norm_text) >= 4 and norm_text in clean_tmpl)))
            f_path_no_space = f_path.replace(" ", "")

            matched = (
                f_path in norm_text
                or f_path_no_space in norm_no_space
                or n_name in norm_text
                or (clean_n_name and clean_n_name in norm_text)
                or tmpl_matched
                or any(clean_n_name in p for p in clean_parts if len(p) >= 2)
                or any(p in clean_n_name for p in clean_parts if len(p) >= 3)
            )

            if matched:
                if level > best_depth:
                    best_depth = level
                    best_match = node

        return best_match

    # =========================================================================
    # 自沉淀规则引擎与生命周期持久化
    # =========================================================================

    def add_precipitated_rule(self, rule: Dict[str, Any]):
        """
        增量自沉淀规则入库：
        根据用户手动调整审核通过的结果，持久化资产特征吸附规则。
        """
        with self._lock:
            if "rule_id" not in rule:
                rule["rule_id"] = "rule_" + str(uuid.uuid4())[:8]
            rule["created_at"] = time.time()
            rule["updated_at"] = time.time()

            # 按 pattern 去重并更新
            pat = rule.get("pattern", "").strip().lower()
            if not pat:
                return

            existing = next((r for r in self._rules if r.get("pattern", "").lower() == pat), None)
            if existing:
                existing.update(rule)
                existing["updated_at"] = time.time()
            else:
                self._rules.append(rule)
            
            self.save_rules()

    def get_precipitated_rules(self) -> List[Dict[str, Any]]:
        """获取所有自沉淀规则"""
        with self._lock:
            return list(self._rules)

    def clear_precipitated_rules(self):
        """清空规则 (主要供单元测试使用)"""
        with self._lock:
            self._rules = []
            self.save_rules()

    def _format_matched_rule(self, rule: Dict[str, Any], clean_asset_name: str) -> Dict[str, Any]:
        target_sub = rule.get("target_subpath", "")
        target_sub_formatted = target_sub.replace("{asset_name}", clean_asset_name).replace("{app_name}", clean_asset_name)
        return {
            "category": rule.get("category", ""),
            "target_subpath": target_sub_formatted,
            "rule": rule,
            "rule_pattern": rule.get("pattern", "")
        }

    def match_asset(
        self,
        name: str,
        path: str = "",
        is_collective: bool = False,
        collective_info: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        资产扫描自沉淀优先命中匹配：
        当扫描器扫描新资产时，自动优先匹配自沉淀规则，命中对应树状节点并输出对应规划路径。
        严格优先级：精确 app_name > 精确全文件名 > 精确主干名(stem) > 子串包含匹配 > 路径包含匹配。
        同一优先级内以最新的规则 (reversed) 优先。
        """
        with self._lock:
            if not self._rules:
                return None
            rules_rev = list(reversed(self._rules))

        name_lower = name.strip().lower()
        original_stem = Path(name).stem
        stem_lower = original_stem.lower()
        path_lower = path.replace("\\", "/").lower() if path else ""

        app_name = ""
        original_app_name = ""
        if collective_info:
            original_app_name = str(collective_info.get("app_name") or collective_info.get("software_name") or "").strip()
            app_name = original_app_name.lower()

        clean_name = original_app_name or original_stem or name

        # 优先级 1: 精确 app_name 匹配
        if app_name:
            for rule in rules_rev:
                pat = rule.get("pattern", "").strip().lower()
                if pat and pat == app_name:
                    return self._format_matched_rule(rule, clean_name)

        # 优先级 2: 精确全文件名匹配
        for rule in rules_rev:
            pat = rule.get("pattern", "").strip().lower()
            if pat and pat == name_lower:
                return self._format_matched_rule(rule, clean_name)

        # 优先级 3: 精确主干名 (stem) 匹配
        for rule in rules_rev:
            pat = rule.get("pattern", "").strip().lower()
            if pat and pat == stem_lower:
                return self._format_matched_rule(rule, clean_name)

        # 优先级 4: 子串包含匹配 (pattern 长度 >= 3)
        for rule in rules_rev:
            pat = rule.get("pattern", "").strip().lower()
            if len(pat) >= 3 and (pat in name_lower or pat in stem_lower):
                return self._format_matched_rule(rule, clean_name)

        # 优先级 5: 所在路径包含匹配
        if path_lower:
            for rule in rules_rev:
                pat = rule.get("pattern", "").strip().lower()
                if len(pat) >= 3 and pat in path_lower:
                    return self._format_matched_rule(rule, clean_name)

        return None

global_category_manager = CategoryManager()

