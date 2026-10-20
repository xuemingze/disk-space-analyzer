"""
命令行与脚本生成引擎 (CLI & Script Generator)
借鉴优秀自动化组织工具，提供：
1. 规范的标准命令行语法生成；
2. --dry-run 预检模拟与安全参数指引；
3. 导出当前候选整理方案为标准 JSON 凭证；
4. 一键导出 PowerShell (.ps1) 与 Windows 批处理 (.bat) 自动化执行脚本。
"""

import os
import json
from typing import List, Dict, Any, Optional
from pathlib import Path

from app.automation.models import ProposedPlan


class CliScriptGenerator:
    """CLI 与自动化脚本生成器"""

    @staticmethod
    def generate_cli_command(
        path: str,
        dest: str = "D:/归档备份",
        mode: str = "comprehensive",
        dry_run: bool = True,
        conflict_policy: str = "auto_rename"
    ) -> str:
        """生成标准 CLI 执行命令字符串"""
        dry_flag = " --dry-run" if dry_run else ""
        return (
            f'python cli.py organize --path "{path}" '
            f'--dest "{dest}" '
            f'--mode {mode} '
            f'--conflict {conflict_policy}'
            f'{dry_flag}'
        )

    @staticmethod
    def generate_powershell_script(
        path: str,
        dest: str = "D:/归档备份",
        mode: str = "comprehensive",
        dry_run: bool = True
    ) -> str:
        """生成 Windows PowerShell 自动化脚本模板"""
        dry_flag = "$true" if dry_run else "$false"
        script = f"""# ========================================================
# 空间全景深度分析与自动化整理 PowerShell 脚本
# 生成时间: {os.path.basename(path)} 自动化治理
# 安全准则: 默认启用 -DryRun 预览模拟，确认无误后再设为 $false
# ========================================================

$TargetPath = "{path}"
$DestPath = "{dest}"
$Mode = "{mode}"
$DryRun = {dry_flag}

Write-Host "🚀 开始执行自动化整理检查..." -ForegroundColor Cyan
Write-Host "目标目录: $TargetPath"
Write-Host "归档目标: $DestPath"
Write-Host "整理模式: $Mode"
Write-Host "模拟预览 (DryRun): $DryRun"

if (-not (Test-Path $TargetPath)) {{
    Write-Error "❌ 目标目录不存在: $TargetPath"
    exit 1
}}

# 调用 DiskSpaceAnalyzer CLI 引擎
$cliArgs = @("cli.py", "organize", "--path", $TargetPath, "--dest", $DestPath, "--mode", $Mode)
if ($DryRun) {{
    $cliArgs += "--dry-run"
}}

python @cliArgs
"""
        return script

    @staticmethod
    def export_plan_to_json(plan: ProposedPlan, output_file: str) -> bool:
        """将候选整理计划导出为 JSON"""
        try:
            Path(output_file).parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(plan.to_dict(), f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"导出计划失败: {e}")
            return False
