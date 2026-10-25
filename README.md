# 🚀 Disk Space Panorama Analyzer & AI Smart Governance System

[![Platform: Windows](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011%20(64--bit)-blueviolet.svg)](https://www.microsoft.com/windows)
[![Release: v1.9.3](https://img.shields.io/badge/Release-v1.9.3-brightgreen.svg)](https://github.com/xuemingze/disk-space-analyzer/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GUI: PySide6 / Qt6](https://img.shields.io/badge/GUI-Modern%20Dark%20Qt6-blue.svg)](https://pypi.org/project/PySide6/)
[![Test Suite: 100% Passed](https://img.shields.io/badge/Tests-100%25%20Passing-brightgreen.svg)](./tests/)

> **A high-performance Windows desktop application built for deep disk space cleanup, AI-assisted file classification, and storage lifecycle governance**.  
> Say goodbye to full C: drive anxiety, tens of thousands of scattered files slowing down your PC, and duplicated gigabytes eating your storage.  
> **Portable, instant-start, zero dependencies required. Runs 100% offline out-of-the-box.**

[English Manual](./README.md) | [中文使用手册](./README_ZH.md)

---

## 📥 Quick Download & 10-Second Setup

No need to install Python or configure dependencies. Download and run directly:

| Package Type | Highlights & Best For | Download |
| :--- | :--- | :---: |
| **`DiskSpaceAnalyzer-1.9.3-win64-portable.zip`** | **⭐ Highly Recommended (Portable Zip)**. Extract to any directory and double-click `DiskSpaceAnalyzer.exe`. Leaves no background clutter. | [⬇️ Download Portable Zip](https://github.com/xuemingze/disk-space-analyzer/releases/latest/download/DiskSpaceAnalyzer-1.9.3-win64-portable.zip) |
| `DiskSpaceAnalyzer-1.9.3-win64.exe` | **Single-file Standalone Exe**. Double-click to run directly without extracting. Perfect for USB flash drives. | [⬇️ Download Standalone Exe](https://github.com/xuemingze/disk-space-analyzer/releases/latest/download/DiskSpaceAnalyzer-1.9.3-win64.exe) |

* 🖥️ **Operating System**: Windows 10 / 11 64-bit;
* 🔒 **Safety Guarantees**: Cleanup operations move files to the **Windows Recycle Bin** by default; app migrations feature **one-click atomic rollback**; critical system paths are permanently protected.

---

## 🎯 What Problems Does It Solve?

Are you dealing with these common storage headaches?

1. **C: drive constantly running low on space**: Unknown caches and temporary installers are eating up gigabytes, and you are afraid to delete files because of system crashes;
2. **Messy Downloads and Desktop folders**: Thousands of unorganized installers, archives, screenshots, documents, and code fragments;
3. **Duplicate files wasting storage**: Identical video files, documents, or installers duplicated across projects and disks;
4. **Massive installed apps trapping C: drive**: You want to move them to D: drive, but manual copying breaks desktop shortcuts, registries, and launch paths;
5. **Fear of accidentally modifying files currently in use**: Cleaning tools might accidentally touch an open Word/Excel document or an active development build.

**Disk Space Panorama Analyzer** is specifically engineered to solve these problems safely and efficiently.

---

## 📖 Practical Step-by-Step User Guide (5 Core Scenarios)

### Scenario 1: Panorama Scan & Safe Cleanup (Fixing Full C: Drive)

When your C: drive turns red, use this feature to find storage hogs and clean them in seconds:

```text
Select Drive ──► Click "Quick Scan" ──► Inspect Sunburst Chart & Top 100 ──► Click "One-Click Cleanup"
```

1. **Select a Drive**: Launch the app, click a drive card at the top (e.g. `C:\` or `D:\`), or click **"📁 Select Path"** on the right to choose any folder;
2. **Start Analysis**:
   * Click **"⚡ Quick Scan"**: Streams directory traversal in seconds, rendering an interactive space distribution sunburst chart and storage usage dashboard;
   * Click **"🔍 Deep Analysis"**: Extracts deep file metadata, PE signatures, and build artifacts to produce an exhaustive inventory;
3. **Locate Large Files & Junk**:
   * Look at the **"Top 100 Largest Files"** tab to immediately spot virtual machine images, forgotten installer packages, and hidden video caches;
   * Browse assets by category (Installers, Media, Dev Dependencies, Temporary Logs);
4. **Safe Cleanup**:
   * Click **"📑 AI Deep Health Report"** to view health diagnostics and reclaimable space recommendations;
   * Click **"🧹 One-Click Cleanup"**: Redundant junk files are safely sent to the **Recycle Bin**. If you ever change your mind, restore them directly from the Recycle Bin!

---

### Scenario 2: Smart File Organization (From Cluttered Folders to Neat Hierarchies)

Have thousands of scattered files in your Downloads or Desktop folder? Use AI-assisted organization to clean them up:

```text
Switch to "AI File Organizer" ──► Select Folder ──► Smart Planning ──► Preview/Edit ──► Execute
```

1. **Navigate to Organizer**: Click **"🤖 AI File Organizer"** on the left navigation bar;
2. **Select Source Folder**: Pick the folder you want to tidy up (e.g., `Downloads` or `Desktop`);
3. **Click "Smart Analysis & Planning"**:
   * The system analyzes each file's real-world context (e.g., distinguishing between an office tool installer, AI model weights, or a receipt document);
   * Automatically generates a clean 2~3 level directory structure;
4. **Preview & Manual Fine-Tuning (Never moves files blindly)**:
   * A preview confirmation window displays exactly where each file originated and where it is proposed to go;
   * **In-Place Fine-Tuning**: If you want to change any proposed path, simply **double-click** or press **`F2`** in Column 3 (Planned Target Path) to edit directly. Hit Enter, and your custom rule will be saved;
5. **Execute**: Click **"🚀 Start Organizing"** to neatly place all files into their designated folders.

---

### Scenario 3: Zero-Space Duplicate Merging (Reclaim Gigabytes While Keeping Files Usable)

When identical large files exist across projects, standard deletion breaks existing workflows. Our **NTFS Hardlink Merging** solves this:

```text
Click "Dedup & Merge" ──► Select Comparison Folders ──► Review Duplicates ──► Select "Hardlink Merge" ──► Execute
```

1. **Navigate to Dedup**: Click **"🔗 Dedup & Merge"** in the left sidebar;
2. **Select Folders**: Add the directories you want to scan for duplicates and click **"Next"**;
3. **3-Tier Concurrent Hashing**: Size pre-filtering ➔ 8KB sampling ➔ full concurrent hashing identifies exact duplicate file groups in seconds;
4. **Recommended Primary Copy**: The engine automatically suggests the best primary copy based on creation date, modification time, and directory hierarchy;
5. **Select Governance Solution**:
   * **⭐ Solution 2: NTFS Hardlink Merge (Highly Recommended)**:  
     Leverages Windows NTFS filesystem capabilities to point duplicate files to the exact same physical storage blocks. **Physical storage is halved immediately, but files in both paths remain completely intact and functional!**
   * **Solution 1: Safe Archive** (packages duplicates into a backup directory);
   * **Solution 3: Recycle Bin Isolation** (moves redundant copies to the Recycle Bin).
6. **Click "Execute"** to instantly reclaim disk space.

---

### Scenario 4: Lossless Cross-Drive App & Project Migration

Have large applications or toolchains eating space on C: drive? Moving them manually breaks shortcuts and registries. Use automated migration:

```text
Find App in Table ──► Right-Click "Migrate Application" ──► Pick D: Target ──► Check Sync Shortcuts ──► Migrate
```

1. **Locate Target Application**: In the scanned asset list, find a standalone application, portable package, or dev project;
2. **Initiate Migration**: Right-click the asset and select **"📦 Migrate Application"**;
3. **Configure Destination**:
   * Select a target directory on a drive with ample storage (e.g., `D:\MigratedApps`);
   * **Check "Sync Desktop Shortcuts & Registry"**;
4. **Execute Migration**:
   * The app smoothly moves files to the target drive;
   * Automatically creates an **NTFS Directory Junction** in the original C: location, allowing Windows and all programs to transparently access files at the original path;
   * Updates desktop shortcuts (`.lnk`), Start Menu items, and registry keys;
   * **One-Click Reversible**: A migration manifest is created so you can restore the app to its original location with a single click if needed.

---

### Scenario 5: Automation Center (Silent Background Health Checks & Protection)

Open **"🤖 Automation Center"** on the left menu to access 5 convenient submodules:

1. **⚡ Quick Organize**:  
   Pre-configured one-click cards for **Desktop Cleanup**, **Downloads Organization**, **Documents Organizer**, and **Media & Pictures**. One click scans, plans, and prompts a confirmation dialog;
2. **⏰ Scheduled Tasks**:  
   Set daily, weekly, or hourly checks for key folders. By default, it generates proposals for your review;
3. **🛡️ Directory Watcher**:  
   Monitor specific folders (e.g., `Downloads`). When new files settle and are free of I/O locks, clean proposals are generated;
4. **🔒 In-Use Lock Protection (In-Use Guard)**:  
   Before moving any file, the system inspects process handle locks and Office/WPS temporary lock files. **Any file currently open or program running is safely skipped to prevent data corruption**;
5. **🌐 AI Audit & Topology Routing**:  
   Inspect the master knowledge base routing table. Rules are strictly prioritized: **User Manual Confirmations (P1, Top Priority) ➔ AI-Learned (P2) ➔ System Built-In (P3)**, with the most recently edited rules shown first.

---

## 💡 Keyboard Shortcuts & Pro Tips

| Action / Shortcut | Where to Use | Description |
| :--- | :--- | :--- |
| **`F2`** or **Double-Click** | Table Column 3 (Planned Path) | **Edit planned path in-place**. The text is preserved and selected. Press Enter to save as a custom rule; |
| **Double-Click** | Any column other than Column 3 | **Instantly reveal and highlight** the file in Windows File Explorer; |
| **Right-Click** | Any row in data tables | Opens contextual actions (Migrate App, Promote to Collective, Open Folder, etc.); |
| **Double-Click Tab** | Tab Headers / Workspace | **Maximize to fullscreen**, giving you maximum space for dense table viewing; |
| **`Del` Key** | Scanned Asset Table | Directly sends the selected redundant junk item to the Windows Recycle Bin. |

---

## ⚙️ Optional LLM Configuration

> 💡 **Notice**: The software includes a tuned **offline heuristic expert rules engine**.  
> **Even without an internet connection or any API Key configured, all scanning, deduplication, migration, file organization, and automation features function 100% reliably!**

If you want to connect an online LLM for enhanced semantic clustering:

```text
Click "Settings" on sidebar ──► Enter Base URL & API Key ──► Fetch Models & Test ──► Save
```

1. Click **"⚙️ Settings"** on the left navigation bar;
2. **Base URL**: Enter any OpenAI-compatible endpoint, such as:
   * DeepSeek: `https://api.deepseek.com/v1`
   * MiniMax: `https://api.minimaxi.com/v1`
   * Qwen (DashScope): `https://dashscope.aliyuncs.com/compatible-mode/v1`
   * Local Ollama: `http://localhost:11434/v1`
   * Official OpenAI: `https://api.openai.com/v1`
3. **API Key**: Enter your provider's API key;
4. Click **"🔄 Fetch Available Models"** and pick your desired model;
5. Click **"⚡ Test Connection"** and click **"Save Settings"**.

---

## ❓ Frequently Asked Questions (FAQ)

#### Q1: Is it safe to clean or move files with this software? Will it delete system files?
> **A: Completely safe.**  
> 1. The software enforces a strict Windows system whitelist (`C:\Windows`, `System32`, `WinSxS`, `Program Files` critical drivers, etc.);  
> 2. Cleaned files default to the Windows Recycle Bin;  
> 3. Organization requires preview confirmation before files are moved.

#### Q2: What is NTFS Hardlink Merging? Does it really save disk space?
> **A: Yes, it is a native Windows NTFS filesystem capability.**  
> When two files have 100% identical contents, a hardlink merges the two directory entries so they point to the exact same physical sectors on disk. Physical space is freed immediately while both file paths remain usable.

#### Q3: After migrating an application across drives, will desktop shortcuts still work?
> **A: Yes, completely normally.**  
> The migration engine builds an NTFS Directory Junction at the original location so Windows transparently forwards calls to the new drive, and updates desktop `.lnk` shortcuts and registry keys automatically.

#### Q4: Where are error and runtime logs stored?
> **A:** Logs and crash dumps are stored under the `logs/` directory inside the application folder (`logs/app.log`, `logs/error.log`).

---

## 📄 License

Distributed under the [MIT License](LICENSE).
