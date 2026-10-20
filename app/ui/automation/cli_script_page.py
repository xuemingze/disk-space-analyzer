"""
命令行与脚本页面 (CLI & Script Page)
功能：
1. 规范展示 CLI 语法、--dry-run 模拟参数与自动化参数；
2. 动态生成可复制的 CLI 命令；
3. 一键导出 PowerShell (.ps1) 与批处理脚本 (.bat)；
4. 界面内直接运行 --dry-run 预检模拟测试，展示输出终端。
"""

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QTextEdit, QGroupBox,
    QFileDialog, QMessageBox, QApplication
)
from PySide6.QtCore import Qt, QThread, Signal

from app.automation.cli_generator import CliScriptGenerator


class CliRunnerThread(QThread):
    """后台执行 CLI 预检模拟测试线程"""
    output_line = Signal(str)
    finished_signal = Signal(int)

    def __init__(self, cmd_args: list, parent=None):
        super().__init__(parent)
        self.cmd_args = cmd_args

    def run(self):
        try:
            proc = subprocess.Popen(
                self.cmd_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
            for line in proc.stdout:
                self.output_line.emit(line.rstrip())
            proc.wait()
            self.finished_signal.emit(proc.returncode)
        except Exception as e:
            self.output_line.emit(f"执行异常: {e}")
            self.finished_signal.emit(-1)


class CliScriptPage(QWidget):
    """命令行与脚本视图"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.runner_thread = None
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(14)

        # 头部
        top_box = QVBoxLayout()
        lbl_title = QLabel("💻 命令行与脚本中心 (CLI & Automation Scripts)")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #38BDF8;")
        lbl_desc = QLabel("借鉴优秀自动化整理架构，支持在终端通过 CLI、PowerShell 与计划任务实现无头静默治理与安全预检")
        lbl_desc.setStyleSheet("color: #94A3B8; font-size: 12px;")
        top_box.addWidget(lbl_title)
        top_box.addWidget(lbl_desc)
        main_layout.addLayout(top_box)

        # 参数配置联动生成器
        cfg_group = QGroupBox("⚙️ 命令参数构建器")
        cfg_group.setStyleSheet("QGroupBox { font-weight: bold; color: #38BDF8; }")
        cfg_layout = QVBoxLayout(cfg_group)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("源目录:"))
        self.src_input = QLineEdit(str(Path.home() / "Downloads"))
        btn_src = QPushButton("浏览...")
        btn_src.clicked.connect(self._browse_src)
        self.src_input.textChanged.connect(self._update_command_preview)
        row1.addWidget(self.src_input, 1)
        row1.addWidget(btn_src)
        cfg_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("归档目标:"))
        self.dest_input = QLineEdit("D:/归档备份")
        btn_dest = QPushButton("浏览...")
        btn_dest.clicked.connect(self._browse_dest)
        self.dest_input.textChanged.connect(self._update_command_preview)
        row2.addWidget(self.dest_input, 1)
        row2.addWidget(btn_dest)

        row2.addWidget(QLabel("模式:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("comprehensive", "comprehensive")
        self.mode_combo.addItem("by_type", "by_type")
        self.mode_combo.addItem("by_prefix", "by_prefix")
        self.mode_combo.addItem("by_date", "by_date")
        self.mode_combo.addItem("by_app", "by_app")
        self.mode_combo.currentIndexChanged.connect(self._update_command_preview)
        row2.addWidget(self.mode_combo)

        self.chk_dryrun = QCheckBox("--dry-run 模拟模式 (只预检不移动)")
        self.chk_dryrun.setChecked(True)
        self.chk_dryrun.setStyleSheet("color: #10B981; font-weight: bold;")
        self.chk_dryrun.stateChanged.connect(self._update_command_preview)
        row2.addWidget(self.chk_dryrun)
        cfg_layout.addLayout(row2)

        main_layout.addWidget(cfg_group)

        # 命令展示与操作栏
        cmd_group = QGroupBox("📋 生成的 CLI 命令")
        cmd_group.setStyleSheet("QGroupBox { font-weight: bold; color: #38BDF8; }")
        cmd_layout = QVBoxLayout(cmd_group)

        self.cmd_preview = QTextEdit()
        self.cmd_preview.setReadOnly(True)
        self.cmd_preview.setMaximumHeight(70)
        self.cmd_preview.setStyleSheet("background: #0F172A; color: #38BDF8; font-family: monospace; font-size: 13px; font-weight: bold; padding: 6px;")
        cmd_layout.addWidget(self.cmd_preview)

        btn_row = QHBoxLayout()
        btn_copy = QPushButton("📋 复制 CLI 命令")
        btn_copy.setStyleSheet("background: #0284C7; color: white; font-weight: bold; padding: 6px 14px; border-radius: 4px;")
        btn_copy.clicked.connect(self._copy_command)
        btn_row.addWidget(btn_copy)

        btn_export_ps1 = QPushButton("💾 导出 PowerShell 自动化脚本 (.ps1)")
        btn_export_ps1.setStyleSheet("background: #3B82F6; color: white; padding: 6px 14px; border-radius: 4px;")
        btn_export_ps1.clicked.connect(self._export_ps1)
        btn_row.addWidget(btn_export_ps1)

        btn_test_run = QPushButton("▶️ 执行预检模拟 (--dry-run 测试)")
        btn_test_run.setStyleSheet("background: #10B981; color: white; font-weight: bold; padding: 6px 14px; border-radius: 4px;")
        btn_test_run.clicked.connect(self._run_cli_test)
        btn_row.addWidget(btn_test_run)

        btn_row.addStretch()
        cmd_layout.addLayout(btn_row)
        main_layout.addWidget(cmd_group)

        # 终端模拟输出框
        term_group = QGroupBox("🖥️ 终端模拟输出")
        term_group.setStyleSheet("QGroupBox { font-weight: bold; color: #38BDF8; }")
        term_layout = QVBoxLayout(term_group)
        self.term_output = QTextEdit()
        self.term_output.setReadOnly(True)
        self.term_output.setStyleSheet("background: #0B0F19; color: #E2E8F0; font-family: 'Consolas', monospace; font-size: 12px; border: 1px solid #1E293B;")
        term_layout.addWidget(self.term_output)
        main_layout.addWidget(term_group, 1)

        self._update_command_preview()

    def _browse_src(self):
        d = QFileDialog.getExistingDirectory(self, "选择源目录", self.src_input.text() or str(Path.home()))
        if d:
            self.src_input.setText(d)

    def _browse_dest(self):
        d = QFileDialog.getExistingDirectory(self, "选择目标目录", self.dest_input.text() or "D:/归档备份")
        if d:
            self.dest_input.setText(d)

    def _update_command_preview(self):
        cmd = CliScriptGenerator.generate_cli_command(
            path=self.src_input.text().strip(),
            dest=self.dest_input.text().strip(),
            mode=self.mode_combo.currentText(),
            dry_run=self.chk_dryrun.isChecked()
        )
        self.cmd_preview.setText(cmd)

    def _copy_command(self):
        QApplication.clipboard().setText(self.cmd_preview.toPlainText())
        QMessageBox.information(self, "提示", "命令已复制到剪贴板！")

    def _export_ps1(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "保存 PowerShell 自动化脚本", "auto_organize.ps1", "PowerShell 脚本 (*.ps1)")
        if file_path:
            content = CliScriptGenerator.generate_powershell_script(
                path=self.src_input.text().strip(),
                dest=self.dest_input.text().strip(),
                mode=self.mode_combo.currentText(),
                dry_run=self.chk_dryrun.isChecked()
            )
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            QMessageBox.information(self, "导出成功", f"PowerShell 脚本已导出至:\n{file_path}")

    def _run_cli_test(self):
        """在终端输出框中直接异步运行 CLI 测试"""
        self.term_output.clear()
        self.term_output.append(">>> 正在启动 CLI 进程进行安全预检模拟...\n")

        python_exe = sys.executable
        cli_script = str(Path(__file__).resolve().parents[3] / "cli.py")
        if not os.path.exists(cli_script):
            cli_script = "cli.py"

        args = [
            python_exe,
            cli_script,
            "organize",
            "--path", self.src_input.text().strip(),
            "--dest", self.dest_input.text().strip(),
            "--mode", self.mode_combo.currentText(),
            "--dry-run"
        ]

        self.runner_thread = CliRunnerThread(args, parent=self)
        self.runner_thread.output_line.connect(self.term_output.append)
        self.runner_thread.finished_signal.connect(lambda code: self.term_output.append(f"\n>>> 预检执行完毕，退出码: {code}"))
        self.runner_thread.start()
