#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DiskSpaceAnalyzer 自动化整理命令行工具 (CLI)
支持：
- 目录分析与整理规划 (--path, --mode, --dest)
- 安全模拟预检 (--dry-run)
- 快速预设整理 (--preset)
- 规划结果 JSON 导出 (--export)
"""

import os
import sys
import argparse
import json
from pathlib import Path

# 确保项目根路径进入 sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.core.app_detector import AppDetector
from app.core.organize_models import OrganizeOptions, OrganizeMode
from app.utils.file_helper import format_size
from app.automation.quick_organizer import QuickOrganizeManager


def handle_organize(args):
    target = os.path.abspath(args.path)
    if not os.path.exists(target):
        print(f"❌ 错误: 目标路径不存在: {target}")
        sys.exit(1)

    dest = os.path.abspath(args.dest)
    dry_run = args.dry_run

    print("==================================================")
    print("🚀 DiskSpaceAnalyzer 自动化整理命令行")
    print(f"📁 目标目录: {target}")
    print(f"📦 归档目标: {dest}")
    print(f"⚙️ 整理模式: {args.mode}")
    print(f"🛡️ 模拟模式 (--dry-run): {'开启 (只规划不移动)' if dry_run else '关闭 (将执行物理整理)'}")
    print("==================================================")

    # 扫描目标目录
    scanned_files = []
    print("\n🔍 正在扫描文件...")
    try:
        with os.scandir(target) as it:
            for entry in it:
                if entry.is_file():
                    stat = entry.stat()
                    scanned_files.append({
                        "path": entry.path,
                        "name": entry.name,
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                        "ext": os.path.splitext(entry.name)[1].lower(),
                        "category": "其他"
                    })
    except Exception as e:
        print(f"❌ 扫描异常: {e}")
        sys.exit(1)

    if not scanned_files:
        print("ℹ️ 目标目录内无待整理文件。")
        return

    print(f"✅ 扫描完成: 共发现 {len(scanned_files)} 个文件，总大小: {format_size(sum(f['size'] for f in scanned_files))}")

    # 计算整理规划
    try:
        mode_enum = OrganizeMode(args.mode)
    except Exception:
        mode_enum = OrganizeMode.COMPREHENSIVE

    options = OrganizeOptions(mode=mode_enum, conflict_policy=args.conflict)
    print("🤖 正在构建以应用/业务实体为原子单元的树状整理拓扑...")
    groups = AppDetector.group_files_by_parent_or_tool(scanned_files, dest, options)

    print(f"\n📊 整理方案总览: 生成 {len(groups)} 个规划组")
    print("--------------------------------------------------")
    for idx, g in enumerate(groups, 1):
        g_name = g.get("name") or g.get("app_name") or "未命名组"
        cat = g.get("suggested_category") or "未分类"
        subpath = g.get("recommended_subpath") or ""
        f_count = g.get("file_count", len(g.get("sub_items", [])))
        sz = format_size(g.get("total_size", 0))
        is_coll = g.get("collective_info", {}).get("is_collective", False)
        coll_flag = "📦 [原子实体集体]" if is_coll else "📄 [独立单项]"
        print(f"#{idx:02d} {coll_flag} {g_name} ({f_count} 文件, {sz})")
        print(f"     分类: [{cat}] -> 推荐子路径: {subpath}")

    # 导出方案
    if args.export:
        export_path = os.path.abspath(args.export)
        try:
            Path(export_path).parent.mkdir(parents=True, exist_ok=True)
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump({"target": target, "destination": dest, "mode": args.mode, "groups": groups}, f, indent=2, ensure_ascii=False)
            print(f"\n💾 整理方案已导出至: {export_path}")
        except Exception as e:
            print(f"\n⚠️ 方案导出失败: {e}")

    if dry_run:
        print("\n🛡️ 当前为 --dry-run 预检模拟模式，未进行任何物理文件迁移。")
        print("💡 如需正式执行，请在命令中移除 --dry-run 参数，或在 GUI 客户端中点击确认。")
    else:
        print("\n⚠️ 正在调用底层 ArchiveWorker 执行安全归档平移...")
        # 正式执行
        from app.core.cleaner import ArchiveWorker
        file_items = []
        for g in groups:
            for sub in g.get("sub_items", []):
                file_items.append({
                    "path": sub.get("original_path") or sub.get("path"),
                    "target_path": sub.get("target_path"),
                    "size": sub.get("size", 0),
                    "name": sub.get("name", "")
                })

        worker = ArchiveWorker(
            file_items=file_items,
            destination_root=dest,
            conflict_policy=args.conflict
        )
        worker.run()
        print("✅ 整理执行完毕，已生成恢复 Manifest 凭证。")


def main():
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="DiskSpaceAnalyzer 自动化文件整理与治理命令行工具"
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # organize
    org_parser = subparsers.add_parser("organize", help="对指定目录执行规则分析与整理规划")
    org_parser.add_argument("--path", "-p", required=True, help="待整理的源根目录")
    org_parser.add_argument("--dest", "-d", default="D:/归档备份", help="归档迁移目标目录")
    org_parser.add_argument("--mode", "-m", default="comprehensive",
                            choices=["comprehensive", "by_type", "by_prefix", "by_date", "by_app"],
                            help="整理拓扑模式")
    org_parser.add_argument("--conflict", default="auto_rename",
                            choices=["auto_rename", "skip", "overwrite"],
                            help="同名冲突策略")
    org_parser.add_argument("--dry-run", action="store_true", default=False,
                            help="预检模拟运行，仅输出计划不移动文件")
    org_parser.add_argument("--export", "-e", help="将整理计划导出为 JSON 文件")

    # quick
    quick_parser = subparsers.add_parser("quick", help="快速预设整理 (桌面/下载/文档)")
    quick_parser.add_argument("--preset", choices=["desktop", "downloads", "documents", "pictures"], required=True)
    quick_parser.add_argument("--dest", "-d", default="D:/归档备份")
    quick_parser.add_argument("--dry-run", action="store_true", default=True)

    args = parser.parse_args()
    if args.command == "organize":
        handle_organize(args)
    elif args.command == "quick":
        presets = {p.key: p.path for p in QuickOrganizeManager.get_default_presets()}
        args.path = presets.get(args.preset, str(Path.home()))
        args.mode = "comprehensive"
        args.conflict = "auto_rename"
        args.export = None
        handle_organize(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
