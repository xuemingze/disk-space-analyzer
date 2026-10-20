"""
快速整理管理器 (Quick Organize Manager)
预置高频系统目录（桌面、下载、文档等）的一键整理入口，
遵循安全规范：快速扫描后直接弹出整理预览确认窗口，由用户勾选确认，绝不直接暗箱物理移动。
"""

import os
from pathlib import Path
from typing import List, Dict, Any

from app.automation.models import QuickPreset


class QuickOrganizeManager:
    """高频目录快速整理管理"""

    @staticmethod
    def get_default_presets() -> List[QuickPreset]:
        """获取系统默认高频整理预设列表"""
        user_home = Path.home()
        desktop = user_home / "Desktop"
        downloads = user_home / "Downloads"
        documents = user_home / "Documents"
        pictures = user_home / "Pictures"

        presets = [
            QuickPreset(
                key="desktop",
                name="桌面清理",
                icon="🖥️",
                path=str(desktop) if desktop.exists() else str(user_home),
                description="快速归档桌面散乱的临时截图、文档与安装程序，恢复清爽工作台"
            ),
            QuickPreset(
                key="downloads",
                name="下载目录整理",
                icon="📥",
                path=str(downloads) if downloads.exists() else str(user_home),
                description="自动聚合解压包、安装包与历史下载单据，分门别类归宿"
            ),
            QuickPreset(
                key="documents",
                name="我的文档整理",
                icon="📄",
                path=str(documents) if documents.exists() else str(user_home),
                description="梳理零散办公报表、合同发票与个人文档，构建树状业务拓扑"
            ),
            QuickPreset(
                key="pictures",
                name="图片与素材库",
                icon="🎨",
                path=str(pictures) if pictures.exists() else str(user_home),
                description="归档各类截图、设计素材与多媒体资产，保持目录整洁"
            )
        ]
        return presets
