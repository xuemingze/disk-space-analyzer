import os
import sys
import json
import tempfile
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.rollback_worker import RollbackWorker


def test_rollback_worker_success(tmp_path):
    # Setup directories
    orig_dir = tmp_path / "orig"
    arch_dir = tmp_path / "arch"
    orig_dir.mkdir()
    arch_dir.mkdir()

    # Create archived file
    arch_file = arch_dir / "file1.txt"
    arch_file.write_text("hello rollback", encoding="utf-8")
    orig_file = orig_dir / "file1.txt"

    manifest_file = tmp_path / "manifest_test.json"
    manifest_data = {
        "backup_id": "BK_TEST_001",
        "operation_status": "COMPLETED",
        "rollback_status": "NONE",
        "items": [
            {
                "entry_id": "ENTRY_0",
                "original_path": str(orig_file),
                "archived_path": str(arch_file),
                "operation_status": "success",
                "rollback_status": "none",
                "size": len("hello rollback")
            }
        ]
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    # Run RollbackWorker
    worker = RollbackWorker(manifest_path=str(manifest_file), selected_entry_ids=["ENTRY_0"])
    
    finished_results = []
    worker.finished_signal.connect(lambda ok, summary: finished_results.append((ok, summary)))
    worker.run()

    assert len(finished_results) == 1
    ok, summary = finished_results[0]
    assert ok is True
    assert summary["success_count"] == 1
    assert orig_file.exists()
    assert orig_file.read_text(encoding="utf-8") == "hello rollback"
    assert not arch_file.exists()

    # Check manifest updated
    updated_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert updated_manifest["rollback_status"] == "FULL_ROLLEDBACK"
    assert updated_manifest["items"][0]["rollback_status"] == "success"


def test_rollback_worker_conflict_skipped(tmp_path):
    orig_dir = tmp_path / "orig"
    arch_dir = tmp_path / "arch"
    orig_dir.mkdir()
    arch_dir.mkdir()

    arch_file = arch_dir / "conflict.txt"
    arch_file.write_text("archived content", encoding="utf-8")
    orig_file = orig_dir / "conflict.txt"
    orig_file.write_text("existing original content", encoding="utf-8")

    manifest_file = tmp_path / "manifest_conflict.json"
    manifest_data = {
        "backup_id": "BK_TEST_002",
        "items": [
            {
                "entry_id": "ENTRY_0",
                "original_path": str(orig_file),
                "archived_path": str(arch_file),
                "operation_status": "success",
                "rollback_status": "none",
                "size": 10
            }
        ]
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    worker = RollbackWorker(manifest_path=str(manifest_file))
    finished_results = []
    worker.finished_signal.connect(lambda ok, summary: finished_results.append((ok, summary)))
    worker.run()

    assert len(finished_results) == 1
    ok, summary = finished_results[0]
    assert summary["skipped_count"] == 1
    # Orig file should remain intact and not overwritten
    assert orig_file.read_text(encoding="utf-8") == "existing original content"
    assert arch_file.exists()
