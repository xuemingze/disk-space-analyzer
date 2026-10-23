# 🚀 Disk Space Panorama Analyzer & AI Smart Governance System

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PySide6 / Qt6](https://img.shields.io/badge/GUI-PySide6%20%2F%20Qt6-brightgreen.svg)](https://pypi.org/project/PySide6/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows%2010%2B-blueviolet.svg)](https://www.microsoft.com/windows)
[![Version: v1.9.2](https://img.shields.io/badge/Release-v1.9.2-blue.svg)](https://github.com/xuemingze/disk-space-analyzer/releases/latest)
[![Test Suite: 192 Passed](https://img.shields.io/badge/Tests-192%20Passed%20(100%25)-brightgreen.svg)](./tests/)

> **A high-performance Windows desktop application built for deep disk space cleanup, AI-assisted file classification, and storage lifecycle governance**.  
> Say goodbye to full C: drive anxiety, tens of thousands of scattered files slowing down your PC, and duplicated gigabytes eating your storage. **Utility-driven, easy to use, and lightning-fast.**

[English Documentation](./README.md) | [中文说明文档](./README_ZH.md) | [Core Architecture & Theory Guide](./docs/Core_Architecture_Theory.md)

---

## 📥 Quick Download & Installation

**➡️ [Go to Latest Release (v1.9.2)](https://github.com/xuemingze/disk-space-analyzer/releases/latest)** · [Release Notes History](./docs/) · [Detailed Usage Guide (Chinese)](./docs/使用说明.md)

| Package | Size | Highlights & Best For | Download |
| :--- | ---: | :--- | :---: |
| **`DiskSpaceAnalyzer-1.9.2-win64-portable.zip`** | ~80 MB | **⭐ Highly Recommended (Portable Zip)**. Extract to any folder and double-click `DiskSpaceAnalyzer.exe`. **No Python installation required.** Instant startup. | [⬇️ Download](https://github.com/xuemingze/disk-space-analyzer/releases/latest/download/DiskSpaceAnalyzer-1.9.2-win64-portable.zip) |
| `DiskSpaceAnalyzer-1.9.2-win64.exe` | ~80 MB | **Single-file standalone executable**. Run directly without extraction. Fast automatic self-decompression on first boot. | [⬇️ Download](https://github.com/xuemingze/disk-space-analyzer/releases/latest/download/DiskSpaceAnalyzer-1.9.2-win64.exe) |
| Run from Source (Developers) | — | Command-line execution: `pip install -r requirements.txt && python main.py` | [View GitHub Releases](https://github.com/xuemingze/disk-space-analyzer/releases/latest) |

* 🖥️ **Operating System**: Windows 10 / 11 64-bit.
* 🔒 **Safety & Privacy**: All cleanup operations safely move files to the **Recycle Bin** by default or support **atomic rollback**. Critical system directories are protected.

---

## 🎯 What It Does: Solving 5 Major Storage Headaches

```text
 How Disk Space Analyzer solves common Windows storage issues:
 ─────────────────────────────────────────────────────────────────────────────
 1. C: Drive running out of space ───► Instant disk snapshot, discover deep logs/caches, clean safely
 2. Messy folders with 10,000+ files ─► AI understands real purposes (projects/tools) to organize hierarchy
 3. Identical large files wasting GBs ─► Zero-space NTFS Hardlink merging: save storage, keep files usable
 4. Afraid to move big installed apps ─► Lossless cross-drive migration with automatic Junction & registry sync
 5. Files accidentally deleted in use ─► Automation Center with in-use lock protection to prevent file corruption
```

### 1. 🔍 Space Panorama Insight: Pinpoint Storage Eaters
* **Sub-second streaming snapshots**: Rapid directory traversal paints interactive space distribution charts and file-type rankings;
* **Top 100 Largest Files List**: Instantly find VM images, monolithic archives, obsolete installers, and video caches;
* **Safe One-Click Cleanup**: Windows protection whitelist protects system files. Move redundant junk safely to the Recycle Bin.

### 2. 🤖 AI Smart File Organization: From Chaos to Clarity
* **Semantic business understanding**: Instead of dumb extensions (like lumping all `.zip` files together), the AI categorizes assets by actual workflow context (e.g., Development Toolchains, Financial Receipts, Live2D Models);
* **Exemplar directory learning**: Point to a tidy folder you like (e.g. `D:\Tools`), and the AI adapts its categorization structure to mirror your organizational habits;
* **Offline heuristic engine fallback**: Even without internet or API keys, the built-in offline rules engine works seamlessly with millisecond responsiveness.

### 3. 🔗 Zero-Space Duplicate Merging (NTFS Hardlink)
* **3-tier hash funnel**: Size pre-filtering + 8KB sample hash + full concurrent hashing finds identical files in seconds;
* **NTFS Hardlink innovation**:
  * Merges duplicated files on the same drive into a single physical data block, immediately reclaiming tens of gigabytes;
  * Both file paths remain fully functional and can be opened as normal without disrupting your daily workflow.

### 4. 📦 Lossless App & Toolchain Migration Across Drives
* **NTFS Directory Junctions**: Relocate massive 50GB software or standalone toolchains from `C:` to `D:`, creating seamless junction points;
* **Automatic shortcut and registry sync**: Desktop/Start Menu `.lnk` shortcuts and system registry paths are automatically updated;
* **One-click atomic rollback**: If you ever want to revert, restore the entire directory with a single click.

### 5. 🛡️ Automation Center: Safe In-Use Guard
* **In-Use lock protection**: Detects process file handle locks before cleanup or archiving. Files currently being written or programs running are safely skipped to avoid data corruption;
* **Scheduled silent scans**: Set periodic health checks to keep your disks clean over time.

---

## 🚀 Quick Step-by-Step Usage Guide

### Scenario 1: Panorama Scan & Safe Cleanup
1. Launch the app and select a drive card (e.g. `C:\` or `D:\`), or click **"📁 Select Path"**;
2. Click **"⚡ Quick Scan"** or **"🔍 Deep Analysis"**;
3. View the space distribution chart and Top 100 big files list;
4. Review the **"📑 AI Deep Health Report"** and click **"🧹 One-Click Cleanup"**.

### Scenario 2: AI File Organization
1. Switch to **"AI File Organizer"** in the sidebar;
2. Select your disorganized source folder (e.g. `Downloads`, `Desktop`);
3. Click **"🤖 Smart Analysis & Planning"**;
4. In the preview dialog, review the 10-column planned directory tree. Double-click Column 3 to fine-tune paths in-place;
5. Click **"🚀 Start Organizing"** to execute reorganization cleanly.

### Scenario 3: Duplicate File Deduplication & Merging
1. Click **"Dedup & Merge"** in the sidebar;
2. Pick directories to compare and click **"Next"** to run concurrent hash analysis;
3. Review the duplicate groups table: the system automatically recommends keeping the best primary copy;
4. Choose your preferred governance mode:
   * **Mode 1: Safe Archive** (pack redundant copies into an archive);
   * **Mode 2: NTFS Hardlink Merge (Recommended)** (reclaim storage while keeping both file paths valid);
   * **Mode 3: Isolate & Recycle** (send duplicates to Recycle Bin);
5. Click **"Execute"** to reclaim storage.

### Scenario 4: Cross-Drive App Migration
1. In the asset detail table, select an identified standalone software or dev project;
2. Right-click and choose **"📦 Migrate Application"**;
3. Choose the target drive (e.g. `D:\MigratedApps`) and check **"Sync Shortcuts & Registry"**;
4. Click **"Start Migration"** to free up C: drive space while keeping apps fully usable.

---

## 💡 Productivity Tips & Shortcuts

* ✏️ **In-Place Path Preserving Edit**:  
  Double-click or press **`F2`** on Column 3 (Planned Target Path) to edit directly in the table. The original text is preserved and pre-selected. Press Enter to submit and save the rule to your personal library;
* 📂 **Native Explorer Selection**:  
  Double-click any column other than Column 3 (File Name, Category, Size, etc.) to instantly reveal and highlight the item in Windows File Explorer;
* 📦 **Right-Click "Promote to Collective"**:  
  Got a messy collection of thousands of tiny project files? Right-click in the table and choose **"📦 Promote to Collective"** to bundle them into an atomic single entity;
* 🖥️ **Fullscreen Maximized Workspace**:  
  Double-click any tab header to maximize the data grid to fullscreen for easier high-density viewing.

---

## ⚙️ Optional LLM Configuration

> 💡 **Notice**: The software includes a robust offline heuristic rules engine. **Even with no API Key configured, all scanning, deduplication, migration, and file organizing features remain 100% operational.**

To connect an online AI model for enhanced semantic clustering:
1. Open **"Settings"** in the sidebar;
2. Input your OpenAI-compatible **Base URL** (e.g. `https://api.openai.com/v1`, DeepSeek, MiniMax, Qwen, or local Ollama `http://localhost:11434/v1`);
3. Enter your **API Key**;
4. Click **"🔄 Fetch Available Models"** to select a model, test connection, and save.

---

## 📖 Architecture & Theory for Developers

This project is engineered upon core system principles including the **"AI-First Orchestration Contract"**, **"Three Core Organizing Principles"** (Atomic Collective Protection, Broad Category Semantic Inheritance, Source Umbrella Consistency), and **"GUI Invariable Law"** with sub-second micro-contracts.

For deep technical insights on algorithm designs, 0-Token fragment blocking, or concurrent hash caching:

👉 **[📄 Core Architecture & Theory Specification](./docs/Core_Architecture_Theory.md)**  
👉 **[📜 Project Execution Journey & Architecture Evolution (Chinese)](./docs/项目全景执行历程与架构演化.md)**  
👉 **[📑 Release Notes Changelog](./docs/)**

---

## 🛠️ FAQ & Troubleshooting

#### Q1: Is it safe to clean or migrate files with this tool?
> **A**: Yes, strictly safe. Built-in Windows protection whitelists prevent touching critical system folders (`System32`, `WinSxS`, etc.). Cleanup defaults to the Windows Recycle Bin, and migrations support instant one-click rollback.

#### Q2: What is NTFS Hardlink merging? Does it actually save space?
> **A**: It is a native Windows NTFS filesystem capability. Two directory paths point to the exact same physical storage blocks on disk. Reclaim gigabytes without deleting files or breaking existing shortcuts.

#### Q3: Where do I find runtime logs for debugging?
> **A**: Unhandled exceptions and runtime traces are logged to the `logs/` directory inside the application folder (`logs/app.log` and `logs/error.log`).

---

## 📄 License

Distributed under the [MIT License](LICENSE).
