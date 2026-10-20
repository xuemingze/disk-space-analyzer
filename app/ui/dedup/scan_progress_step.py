"""
app/ui/dedup/scan_progress_step.py
步骤 2: 扫描与三阶哈希多阶段进度仪表盘
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QFrame
)
from PySide6.QtCore import Qt, Signal, QThread
from app.dedup.models import DedupScanConfig, DedupScanResult
from app.dedup.detector import DedupDetector
from app.utils.file_helper import format_size


class DedupScanWorker(QThread):
    """查重与冲突检测后台工作线程"""
    progress_signal = Signal(str, int, int, str)
    finished_signal = Signal(object)

    def __init__(self, config: DedupScanConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        detector = DedupDetector(self.config)

        def _prog_cb(phase, cur, total, msg):
            self.progress_signal.emit(phase, cur, total, msg)

        def _cancel_check():
            return self._is_running

        result = detector.scan_and_analyze(
            progress_cb=_prog_cb,
            cancel_check=_cancel_check
        )
        self.finished_signal.emit(result)


class ScanProgressStep(QWidget):
    """步骤 2: 进度看板卡片"""
    scan_completed = Signal(object)
    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: DedupScanWorker = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # 头部说明
        title = QLabel("⚡ 步骤 2: 正在执行多源联合索引与三阶精准查重")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1e293b;")
        desc = QLabel("引擎正依据防御性递归、上位大抽屉同构映射及三阶哈希漏斗对全部资产进行精准分析，杜绝误判。")
        desc.setStyleSheet("font-size: 12px; color: #64748b;")
        layout.addWidget(title)
        layout.addWidget(desc)

        # 状态卡片容器
        card = QFrame()
        card.setStyleSheet("QFrame { background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; }")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(14)

        self.lbl_phase = QLabel("正在准备扫描...")
        self.lbl_phase.setStyleSheet("font-size: 14px; font-weight: bold; color: #2563eb;")
        card_layout.addWidget(self.lbl_phase)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(18)
        self.progress_bar.setStyleSheet(
            "QProgressBar { background-color: #e2e8f0; border-radius: 9px; text-align: center; font-size: 11px; }"
            "QProgressBar::chunk { background-color: #3b82f6; border-radius: 9px; }"
        )
        card_layout.addWidget(self.progress_bar)

        self.lbl_current_item = QLabel("准备就绪")
        self.lbl_current_item.setStyleSheet("font-size: 11px; color: #64748b;")
        self.lbl_current_item.setWordWrap(True)
        card_layout.addWidget(self.lbl_current_item)

        # 核心指标统计
        stats_box = QHBoxLayout()
        self.stat_files = QLabel("总文件: 0")
        self.stat_files.setStyleSheet("font-size: 12px; font-weight: bold; color: #334155;")
        self.stat_bytes = QLabel("总容量: 0 B")
        self.stat_bytes.setStyleSheet("font-size: 12px; font-weight: bold; color: #334155;")
        self.stat_dups = QLabel("重复候选: 0 组")
        self.stat_dups.setStyleSheet("font-size: 12px; font-weight: bold; color: #ef4444;")

        stats_box.addWidget(self.stat_files)
        stats_box.addSpacing(20)
        stats_box.addWidget(self.stat_bytes)
        stats_box.addSpacing(20)
        stats_box.addWidget(self.stat_dups)
        stats_box.addStretch()
        card_layout.addLayout(stats_box)

        layout.addWidget(card)
        layout.addStretch()

        # 底部取消按钮
        bottom_bar = QHBoxLayout()
        self.btn_cancel = QPushButton("🛑 取消本次扫描")
        self.btn_cancel.setFixedHeight(34)
        self.btn_cancel.setStyleSheet(
            "background-color: #fee2e2; color: #ef4444; border: 1px solid #fca5a5; border-radius: 6px; font-weight: bold; padding: 0 16px;"
        )
        self.btn_cancel.clicked.connect(self._on_cancel)
        bottom_bar.addStretch()
        bottom_bar.addWidget(self.btn_cancel)
        layout.addLayout(bottom_bar)

    def start_scan(self, config: DedupScanConfig):
        self.progress_bar.setValue(0)
        self.lbl_phase.setText("启动扫描引擎...")
        self.lbl_current_item.setText("正在加载 UnifiedScanner 底座...")

        self.worker = DedupScanWorker(config, self)
        self.worker.progress_signal.connect(self._on_progress)
        self.worker.finished_signal.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, phase: str, cur: int, total: int, msg: str):
        pct = int(cur / total * 100) if total > 0 else 0
        self.progress_bar.setValue(pct)
        self.lbl_current_item.setText(msg)

        phase_names = {
            "phase1_scan": "1/5 正在遍历多源目录并抽取资产元数据",
            "phase2_size": "2/5 正在进行文件字节体积一阶漏斗聚类",
            "phase3_sample": "3/5 正在计算稀疏采样摘要 (Sparse Sample Hash)",
            "phase4_full": "4/5 正在流式计算完整哈希 (Full SHA-256)",
            "phase5_collision": "5/5 正在分析同名冲突与独占锁探针"
        }
        self.lbl_phase.setText(phase_names.get(phase, phase))

    def _on_finished(self, result: DedupScanResult):
        self.progress_bar.setValue(100)
        self.lbl_phase.setText("✅ 查重与冲突分析完成！")
        self.stat_files.setText(f"总文件: {result.total_files:,}")
        self.stat_bytes.setText(f"总容量: {format_size(result.total_bytes)}")
        self.stat_dups.setText(f"完全重复组: {len(result.duplicate_groups)} 组 (可释放 {format_size(result.total_wasted_bytes)})")
        self.scan_completed.emit(result)

    def _on_cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.lbl_phase.setText("正在中止扫描任务...")
            self.btn_cancel.setEnabled(False)
        self.cancel_requested.emit()
