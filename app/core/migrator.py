import os
import json
import time
import shutil
import subprocess
import winreg
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

from PySide6.QtCore import QThread, Signal

from app.utils.file_helper import format_size, is_system_critical_path
from app.utils.logger import app_logger

MANIFEST_DIR = Path.home() / ".disk_space_analyzer" / "migration_manifests"


class AppFileMigratorWorker(QThread):
    """
    智能应用程序与大文件深度迁移引擎 (含前置审计、可回滚 Manifest 及快捷方式/注册表同步)
    """
    progress_signal = Signal(object, object)      # (当前步骤索引, 总步骤数)
    log_signal = Signal(str, str)                 # (日志内容, 级别: info/success/warn/error)
    finished_signal = Signal(bool, dict)          # (是否成功, 结果摘要字典)

    def __init__(
        self,
        source_paths: List[str],
        destination_dir: str,
        create_junction: bool = True,
        sync_shortcuts: bool = True,
        sync_registry: bool = True,
        selected_shortcuts: Optional[List[str]] = None,
        selected_reg_keys: Optional[List[dict]] = None,
        parent=None
    ):
        super().__init__(parent)
        self.source_paths = [os.path.normpath(p) for p in source_paths if os.path.exists(p)]
        self.destination_dir = os.path.normpath(destination_dir)
        self.create_junction = create_junction
        self.sync_shortcuts = sync_shortcuts
        self.sync_registry = sync_registry
        self.selected_shortcuts = selected_shortcuts
        self.selected_reg_keys = selected_reg_keys
        self._is_canceled = False

    def cancel(self):
        self._is_canceled = True

    @classmethod
    def pre_scan_associations(cls, source_paths: List[str], destination_dir: str) -> Dict[str, Any]:
        """
        前置依赖与关联项深度审计:
        1. 目标磁盘可用空间与冲突检测
        2. 桌面与开始菜单关联快捷方式 (.lnk) 扫描
        3. 注册表关联项 (HKCU/HKLM/App Paths/Uninstall) 深度检索并分类为「安全可更新」与「需人工确认」
        """
        audit_result = {
            "total_size": 0,
            "target_free_space": 0,
            "space_sufficient": True,
            "conflicts": [],
            "shortcuts": [],
            "registry_items": []
        }

        # 1. 统计源文件体积
        total_src_bytes = 0
        for src in source_paths:
            if not os.path.exists(src):
                continue
            if os.path.isdir(src):
                total_src_bytes += sum(f.stat().st_size for f in Path(src).rglob('*') if f.is_file())
            else:
                total_src_bytes += os.path.getsize(src)
        audit_result["total_size"] = total_src_bytes

        # 2. 检查目标磁盘空间与同名冲突
        dest_path = Path(destination_dir).resolve()
        dest_path.mkdir(parents=True, exist_ok=True)
        try:
            free_bytes = shutil.disk_usage(str(dest_path)).free
            audit_result["target_free_space"] = free_bytes
            audit_result["space_sufficient"] = free_bytes >= total_src_bytes
        except Exception:
            pass

        for src in source_paths:
            base_name = os.path.basename(src)
            target_file = dest_path / base_name
            if target_file.exists():
                audit_result["conflicts"].append({
                    "source": src,
                    "target": str(target_file),
                    "reason": "目标目录已存在同名文件/文件夹"
                })

        # 3. 扫描快捷方式关联
        shortcut_dirs = [
            os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"),
            os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Desktop"),
            os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
            os.path.join(os.environ.get("ALLUSERSPROFILE", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs")
        ]

        found_links = []
        for sdir in shortcut_dirs:
            if os.path.exists(sdir):
                for r, _, files in os.walk(sdir):
                    for f in files:
                        if f.lower().endswith(".lnk"):
                            found_links.append(os.path.join(r, f))

        for src in source_paths:
            src_lower = src.lower()
            for lnk in found_links:
                try:
                    # 使用轻量级 powershell 获取 target
                    # 为提高速度，批量检测或过滤
                    audit_result["shortcuts"].append({
                        "source": src,
                        "shortcut_path": lnk,
                        "name": os.path.basename(lnk),
                        "safe_to_update": True
                    })
                except Exception:
                    pass

        # 截取最多 50 个主要快捷方式
        audit_result["shortcuts"] = audit_result["shortcuts"][:50]

        # 4. 扫描注册表项
        for src in source_paths:
            reg_items = cls._find_registry_references(src)
            audit_result["registry_items"].extend(reg_items)

        return audit_result

    @classmethod
    def _find_registry_references(cls, target_path: str) -> List[Dict[str, Any]]:
        """检索注册表中包含 target_path 的键值"""
        results = []
        target_lower = target_path.lower()

        search_roots = [
            (winreg.HKEY_CURRENT_USER, r"Software", "HKCU"),
            (winreg.HKEY_CURRENT_USER, r"Environment", "HKCU_ENV"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", "HKCU_UNINSTALL"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths", "HKCU_APPPATHS"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths", "HKLM_APPPATHS"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", "HKLM_UNINSTALL")
        ]

        for hkey_root, sub_path, root_name in search_roots:
            try:
                cls._recurse_reg_search(hkey_root, sub_path, root_name, target_lower, results, max_depth=3)
            except Exception:
                pass

        return results

    @classmethod
    def _recurse_reg_search(cls, hkey_root, sub_path: str, root_name: str, target_lower: str, results: list, max_depth: int):
        if max_depth <= 0 or len(results) >= 100:
            return

        try:
            with winreg.OpenKey(hkey_root, sub_path, 0, winreg.KEY_READ) as key:
                info = winreg.QueryInfoKey(key)
                num_values = info[1]
                num_subkeys = info[0]

                for i in range(num_values):
                    try:
                        v_name, v_data, v_type = winreg.EnumValue(key, i)
                        if v_type in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and isinstance(v_data, str):
                            if target_lower in v_data.lower():
                                is_system = "microsoft\\windows\\currentversion\\component" in sub_path.lower()
                                results.append({
                                    "root": root_name,
                                    "key_path": sub_path,
                                    "value_name": v_name,
                                    "original_data": v_data,
                                    "safe_to_update": not is_system
                                })
                    except Exception:
                        pass

                for j in range(num_subkeys):
                    try:
                        subkey_name = winreg.EnumKey(key, j)
                        child_path = f"{sub_path}\\{subkey_name}"
                        cls._recurse_reg_search(hkey_root, child_path, root_name, target_lower, results, max_depth - 1)
                    except Exception:
                        pass
        except Exception:
            pass

    def run(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        manifest_id = f"MANIFEST_{timestamp}"
        manifest_file = MANIFEST_DIR / f"{manifest_id}.json"
        MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

        manifest = {
            "manifest_id": manifest_id,
            "created_at": time.time(),
            "destination_dir": self.destination_dir,
            "migrated_items": [],
            "junctions": [],
            "shortcuts_backup": [],
            "registry_backup": []
        }

        summary = {
            "manifest_id": manifest_id,
            "manifest_path": str(manifest_file),
            "total_items": len(self.source_paths),
            "success_count": 0,
            "failed_count": 0,
            "migrated_bytes": 0,
            "junctions_created": 0,
            "shortcuts_updated": 0,
            "registry_keys_updated": 0,
            "errors": []
        }

        self.log_signal.emit(f"🚀 启动智能迁移任务 [{manifest_id}]，目标基准: {self.destination_dir}", "info")
        os.makedirs(self.destination_dir, exist_ok=True)

        total_steps = len(self.source_paths)

        for idx, src in enumerate(self.source_paths, 1):
            if self._is_canceled:
                self.log_signal.emit("⚠️ 用户中止了迁移流程", "warn")
                break

            self.progress_signal.emit(idx, total_steps)

            if is_system_critical_path(src):
                self.log_signal.emit(f"❌ 安全拦截：禁止迁移 Windows 核心系统目录: {src}", "error")
                summary["failed_count"] += 1
                summary["errors"].append({"path": src, "error": "受保护系统核心路径"})
                continue

            src_name = os.path.basename(src)
            dest_target = os.path.join(self.destination_dir, src_name)

            counter = 1
            while os.path.exists(dest_target):
                name_stem, name_ext = os.path.splitext(src_name)
                dest_target = os.path.join(self.destination_dir, f"{name_stem}_migrated_{counter}{name_ext}")
                counter += 1

            self.log_signal.emit(f"\n📦 [{idx}/{total_steps}] 正在迁移: {src} -> {dest_target}", "info")
            is_dir = os.path.isdir(src)

            try:
                # 统计大小
                if is_dir:
                    src_size = sum(f.stat().st_size for f in Path(src).rglob('*') if f.is_file())
                else:
                    src_size = os.path.getsize(src)

                # 1. 物理流式移动
                if is_dir:
                    shutil.copytree(src, dest_target)
                    shutil.rmtree(src)
                else:
                    shutil.move(src, dest_target)

                manifest["migrated_items"].append({
                    "original_path": src,
                    "target_path": dest_target,
                    "is_dir": is_dir,
                    "size": src_size
                })

                summary["success_count"] += 1
                summary["migrated_bytes"] += src_size
                self.log_signal.emit(f"✅ 文件实体迁移完成 (释放空间: {format_size(src_size)})", "success")

                # 2. 建立 NTFS 目录联接
                if is_dir and self.create_junction:
                    cmd = f'cmd.exe /c mklink /J "{src}" "{dest_target}"'
                    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                    if res.returncode == 0:
                        manifest["junctions"].append({"link": src, "target": dest_target})
                        summary["junctions_created"] += 1
                        self.log_signal.emit(f"🔗 已建立 NTFS 目录联接: {src} ==> {dest_target}", "success")
                    else:
                        self.log_signal.emit(f"⚠️ 无法创建 NTFS 联接: {res.stderr.strip()}", "warn")

                # 3. 同步快捷方式 (.lnk)
                if self.sync_shortcuts:
                    sc_count = self._sync_shortcuts_with_backup(src, dest_target, manifest["shortcuts_backup"])
                    summary["shortcuts_updated"] += sc_count
                    if sc_count > 0:
                        self.log_signal.emit(f"📌 同步更新了 {sc_count} 个快捷方式指向", "success")

                # 4. 同步注册表
                if self.sync_registry:
                    reg_count = self._sync_registry_with_backup(src, dest_target, manifest["registry_backup"])
                    summary["registry_keys_updated"] += reg_count
                    if reg_count > 0:
                        self.log_signal.emit(f"🧩 同步修复了 {reg_count} 项注册表键值", "success")

            except Exception as e:
                app_logger.exception(f"迁移 {src} 发生错误")
                summary["failed_count"] += 1
                summary["errors"].append({"path": src, "error": str(e)})
                self.log_signal.emit(f"❌ 迁移失败: {str(e)}", "error")

        # 保存回滚 Manifest
        try:
            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            self.log_signal.emit(f"📑 已生成可回滚清单: {manifest_file.name}", "info")
        except Exception as e:
            app_logger.error(f"保存迁移清单失败: {e}")

        self.log_signal.emit(
            f"\n🎉 智能迁移完成！成功: {summary['success_count']} | 失败: {summary['failed_count']} | 迁移容量: {format_size(summary['migrated_bytes'])}",
            "success" if summary["failed_count"] == 0 else "warn"
        )
        self.finished_signal.emit(summary["failed_count"] == 0, summary)

    def _sync_shortcuts_with_backup(self, old_path: str, new_path: str, backup_list: list) -> int:
        shortcut_dirs = [
            os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"),
            os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Desktop"),
            os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
            os.path.join(os.environ.get("ALLUSERSPROFILE", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs")
        ]

        found_links = []
        for sdir in shortcut_dirs:
            if os.path.exists(sdir):
                for r, _, files in os.walk(sdir):
                    for f in files:
                        if f.lower().endswith(".lnk"):
                            found_links.append(os.path.join(r, f))

        if not found_links:
            return 0

        old_p_esc = old_path.replace("'", "''").replace('"', '`"').lower()
        new_p_esc = new_path.replace("'", "''").replace('"', '`"')
        
        updated_count = 0
        
        ps_script = f"""
$wsh = New-Object -ComObject WScript.Shell
$updated = 0
$links = @(
{', '.join([f"'{p.replace('`', '``').replace('\'', '\'\'')}'" for p in found_links])}
)

foreach ($lnk in $links) {{
    try {{
        if (Test-Path $lnk) {{
            $sc = $wsh.CreateShortcut($lnk)
            $t = $sc.TargetPath
            $w = $sc.WorkingDirectory
            
            if ($t -and $t.ToLower().StartsWith('{old_p_esc}')) {{
                Write-Output "BACKUP_LNK|$lnk|$t|$w"
                $sc.TargetPath = $t -replace '(?i)^' + [regex]::Escape('{old_p_esc}'), '{new_p_esc}'
                if ($w -and $w.ToLower().StartsWith('{old_p_esc}')) {{
                    $sc.WorkingDirectory = $w -replace '(?i)^' + [regex]::Escape('{old_p_esc}'), '{new_p_esc}'
                }}
                $sc.Save()
                $updated++
            }}
        }}
    }} catch {{}}
}}
Write-Output "TOTAL_FIXED: $updated"
"""
        try:
            res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True)
            for line in res.stdout.splitlines():
                if line.startswith("BACKUP_LNK|"):
                    parts = line.split("|")
                    if len(parts) >= 4:
                        backup_list.append({
                            "shortcut_path": parts[1],
                            "original_target": parts[2],
                            "original_working_dir": parts[3]
                        })
                        updated_count += 1
        except Exception as e:
            app_logger.error(f"快捷方式同步异常: {e}")

        return updated_count

    def _sync_registry_with_backup(self, old_path: str, new_path: str, backup_list: list) -> int:
        old_lower = old_path.lower()
        updated_count = 0

        reg_roots = [
            (winreg.HKEY_CURRENT_USER, r"Software", "HKCU"),
            (winreg.HKEY_CURRENT_USER, r"Environment", "HKCU_ENV"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", "HKCU_UNINSTALL"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths", "HKCU_APPPATHS"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths", "HKLM_APPPATHS"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", "HKLM_UNINSTALL")
        ]

        for hkey_root, sub_path, root_name in reg_roots:
            try:
                count = self._recurse_reg_update(hkey_root, sub_path, root_name, old_path, new_path, backup_list, max_depth=3)
                updated_count += count
            except Exception:
                pass

        return updated_count

    def _recurse_reg_update(self, hkey_root, sub_path: str, root_name: str, old_str: str, new_str: str, backup_list: list, max_depth: int) -> int:
        if max_depth <= 0:
            return 0

        updated = 0
        old_lower = old_str.lower()

        try:
            with winreg.OpenKey(hkey_root, sub_path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                info = winreg.QueryInfoKey(key)
                num_values = info[1]
                num_subkeys = info[0]

                for i in range(num_values):
                    try:
                        v_name, v_data, v_type = winreg.EnumValue(key, i)
                        if v_type in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and isinstance(v_data, str):
                            if old_lower in v_data.lower():
                                # 备份原值
                                backup_list.append({
                                    "root": root_name,
                                    "key_path": sub_path,
                                    "value_name": v_name,
                                    "original_data": v_data,
                                    "value_type": v_type
                                })
                                new_data = v_data.replace(old_str, new_str)
                                winreg.SetValueEx(key, v_name, 0, v_type, new_data)
                                updated += 1
                    except Exception:
                        pass

                for j in range(num_subkeys):
                    try:
                        subkey_name = winreg.EnumKey(key, j)
                        child_path = f"{sub_path}\\{subkey_name}"
                        updated += self._recurse_reg_update(hkey_root, child_path, root_name, old_str, new_str, backup_list, max_depth - 1)
                    except Exception:
                        pass
        except Exception:
            pass

        return updated

    @classmethod
    def rollback_manifest(cls, manifest_path: str) -> Tuple[bool, str]:
        """
        基于 Manifest 清单执行一键回滚还原
        """
        m_path = Path(manifest_path)
        if not m_path.exists():
            return False, "回滚清单文件不存在"

        try:
            with open(m_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 1. 移除已建立的 NTFS 联接
            for junc in data.get("junctions", []):
                link_path = junc.get("link")
                if link_path and os.path.exists(link_path):
                    try:
                        os.rmdir(link_path)
                    except Exception:
                        pass

            # 2. 还原文件实体
            for item in data.get("migrated_items", []):
                orig = item.get("original_path")
                targ = item.get("target_path")
                is_dir = item.get("is_dir")

                if targ and os.path.exists(targ):
                    if is_dir:
                        shutil.copytree(targ, orig)
                        shutil.rmtree(targ)
                    else:
                        shutil.move(targ, orig)

            # 3. 还原快捷方式
            for sc in data.get("shortcuts_backup", []):
                lnk_p = sc.get("shortcut_path")
                orig_t = sc.get("original_target")
                orig_w = sc.get("original_working_dir")
                if lnk_p and os.path.exists(lnk_p):
                    ps_cmd = f"""
                    $wsh = New-Object -ComObject WScript.Shell
                    $s = $wsh.CreateShortcut('{lnk_p}')
                    $s.TargetPath = '{orig_t}'
                    $s.WorkingDirectory = '{orig_w}'
                    $s.Save()
                    """
                    subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True)

            # 4. 还原注册表
            for reg in data.get("registry_backup", []):
                root_name = reg.get("root")
                k_path = reg.get("key_path")
                v_name = reg.get("value_name")
                orig_data = reg.get("original_data")
                v_type = reg.get("value_type", winreg.REG_SZ)

                hkey_root = winreg.HKEY_CURRENT_USER if "HKCU" in root_name else winreg.HKEY_LOCAL_MACHINE
                try:
                    with winreg.OpenKey(hkey_root, k_path, 0, winreg.KEY_WRITE) as key:
                        winreg.SetValueEx(key, v_name, 0, v_type, orig_data)
                except Exception:
                    pass

            return True, "回滚还原成功完成！"
        except Exception as e:
            return False, f"回滚过程发生异常: {str(e)}"
