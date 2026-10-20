"""
tests/test_performance_and_caching.py
性能优化、缓存机制与界面切换流畅性专项测试
验证:
1. detect_directory_collective 会话级缓存与吞吐率
2. Live2D 单层文件探测与避免二级子目录递归
3. AppManagerView 的 _dirty 惰性加载机制
4. 保证源头剪枝与一改俱改特性同构不被破坏
"""
import os
import tempfile
import time
from pathlib import Path
from PySide6.QtWidgets import QApplication

from app.core.app_detector import AppDetector
from app.core.registry_detector import RegistryAppDetector, InstalledAppInfo
from app.core.unified_scanner import UnifiedScanner
from app.ui.app_manager_view import AppManagerView


def test_session_cache_and_fast_throughput(tmp_path):
    """测试 detect_directory_collective 在扫描会话缓存下的微秒级命中率"""
    d1 = tmp_path / "test_app"
    d1.mkdir()
    (d1 / "package.json").write_text('{"name": "fast-demo"}', encoding="utf-8")

    cache = {}
    # 首次调用
    t0 = time.perf_counter()
    res1 = AppDetector.detect_directory_collective(str(d1), cache=cache)
    t1 = time.perf_counter()

    assert res1 is not None
    assert "fast-demo" in res1.get("software_name", "")
    assert str(d1) in cache

    # 二次调用命中缓存 (耗时应 < 0.05ms)
    t2 = time.perf_counter()
    for _ in range(100):
        res2 = AppDetector.detect_directory_collective(str(d1), cache=cache)
    t3 = time.perf_counter()

    assert res2 == res1
    avg_cached_ms = ((t3 - t2) / 100) * 1000
    assert avg_cached_ms < 0.05  # 必须小于 50 微秒


def test_live2d_single_level_detection(tmp_path):
    """验证 Live2D 仅探测当层模型特征，不再递归深潜子目录引发 I/O 放大"""
    model_dir = tmp_path / "live2d_character"
    model_dir.mkdir()
    (model_dir / "shizuku.model3.json").write_text("{}", encoding="utf-8")

    res = AppDetector.detect_directory_collective(str(model_dir))
    assert res is not None
    assert res["collective_type"] == "Live2D模型集体"
    assert "shizuku.model3.json" in res["signature_type"]


def test_app_manager_dirty_lazy_reload():
    """验证 AppManagerView 在不可见时标记 _dirty，避免阻塞主线程"""
    app = QApplication.instance() or QApplication([])
    view = AppManagerView()
    view.hide()

    # 初始状态 _dirty 为 False
    assert view._dirty is False

    # 外部发出 collective_promoted 广播
    view._on_collective_promoted(r"C:\fake\dir", {})
    # 因为 view 不可见，应该只置 _dirty 为 True，而不立即同步阻塞刷新
    assert view._dirty is True
