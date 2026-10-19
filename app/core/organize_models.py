import os
import re
from enum import Enum
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set

from app.utils.file_helper import is_system_critical_path


class OrganizeMode(str, Enum):
    """文件与目录整理模式枚举"""
    COMPREHENSIVE = "comprehensive"   # 综合整理：综合App、文件类型、前缀及日期进行全局智能规划
    BY_TYPE = "by_type"               # 按格式类型：基于扩展名与业务格式大类划分
    BY_PREFIX = "by_prefix"           # 按文件名前缀：基于项目名、编号、前缀特征聚类
    BY_DATE = "by_date"               # 按修改日期：基于年份/月份/时间线归档
    BY_APP = "by_app"                 # 按应用工具链：优先保持软件与生态工具链原子目录完整性


@dataclass
class OrganizeOptions:
    """整理规划的高级配置选项 (吸收 FolderFox 模式与交互偏好)"""
    mode: OrganizeMode = OrganizeMode.COMPREHENSIVE
    naming_language: str = "zh"           # "zh" 中文目录名 | "en" 英文目录名
    custom_instructions: str = ""         # 用户自定义 Prompt 指令 (如: "发票文件统一归入 财务/发票")
    work_personal_ratio: float = 0.6      # 工作相关权重 (0.0 - 1.0)
    min_confidence: float = 0.70          # 自动勾选最低置信度 (低于此值强制要求人工确认)
    unknown_policy: str = "manual"        # "manual" 转入人工确认 | "misc" 放入归档杂项 | "skip" 跳过
    conflict_policy: str = "auto_rename"  # "auto_rename" 自动重命名 | "skip" 跳过 | "overwrite" 覆盖
    high_risk_policy: str = "block"       # "block" 强制拦截 | "allow_manual" 允许解锁
    sample_content_enabled: bool = False  # 是否开启深层内容抽样感知 (默认关闭)
    sample_content_max_bytes: int = 300   # 内容抽样最大字节数
    batch_size: int = 20                  # 单次向大模型提交的目录组批量上限
    max_batch_tokens: int = 4000          # 单批次输入 token 预算控制

    # 别名入参兼容
    language: Optional[str] = None
    custom_prompt: Optional[str] = None
    enable_content_sampling: Optional[bool] = None
    work_ratio: Optional[float] = None
    personal_ratio: Optional[float] = None

    def __post_init__(self):
        if self.language is not None:
            self.naming_language = self.language
        else:
            self.language = self.naming_language

        if self.custom_prompt is not None:
            self.custom_instructions = self.custom_prompt
        else:
            self.custom_prompt = self.custom_instructions

        if self.enable_content_sampling is not None:
            self.sample_content_enabled = self.enable_content_sampling
        else:
            self.enable_content_sampling = self.sample_content_enabled

        if self.work_ratio is not None:
            self.work_personal_ratio = self.work_ratio
        else:
            self.work_ratio = self.work_personal_ratio


# 允许进行内容抽样的安全文本扩展名白名单
SAFE_TEXT_EXTENSIONS: Set[str] = {
    ".txt", ".md", ".markdown", ".json", ".csv", ".tsv",
    ".yaml", ".yml", ".xml", ".ini", ".cfg", ".log",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css",
    ".sql", ".sh", ".bat", ".ps1", ".rst", ".toml"
}

# 敏感文件与凭据文件名黑名单 (绝对禁止读取内容样本)
SENSITIVE_FILENAME_PATTERNS: List[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"^passwd$", r"^shadow$", r"^id_rsa", r"^id_ed25519", r"^id_ecdsa",
        r"^known_hosts$", r"^\.env", r"secret", r"credential", r"token",
        r"api_?key", r"private_?key", r"\.pem$", r"\.key$", r"\.pfx$", r"\.p12$",
        r"keystore", r"\.kdbx$", r"auth", r"password", r"passwd", r"service_?account"
    ]
]

# 隐私敏感内容脱敏正则表达式
SENSITIVE_CONTENT_PATTERNS = [
    (re.compile(r'(?:api[_-]?key|secret|token|password|passwd|auth)\s*[:=]\s*["\']?([a-zA-Z0-9_\-\.]{8,})["\']?', re.IGNORECASE), r'\g<0> -> [REDACTED_SECRET]'),
    (re.compile(r'Bearer\s+[a-zA-Z0-9_\-\.]{15,}', re.IGNORECASE), 'Bearer [REDACTED_TOKEN]'),
    (re.compile(r'sk-[a-zA-Z0-9]{20,}', re.IGNORECASE), 'sk-[REDACTED_APIKEY]'),
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b'), '[REDACTED_EMAIL]'),
    (re.compile(r'\b1[3-9]\d{9}\b'), '[REDACTED_PHONE]')
]


def is_safe_for_content_sampling(file_path: str) -> bool:
    """检查文件是否符合安全抽样条件：非系统受保护、属于安全文本格式、且不属于敏感凭据"""
    if not file_path or is_system_critical_path(file_path):
        return False

    p = Path(file_path)
    # 检查敏感文件名黑名单 (必须优先于文件存在性检查，确保防御先行)
    fname = p.name.lower()
    for pattern in SENSITIVE_FILENAME_PATTERNS:
        if pattern.search(fname):
            return False

    # 检查扩展名
    if p.suffix.lower() not in SAFE_TEXT_EXTENSIONS:
        return False

    return True


def extract_file_content_sample(file_path: str, max_bytes: int = 300) -> str:
    """
    对安全文本文件抽取前 max_bytes 字符的脱敏内容摘要。
    严格保证：非安全文本返回空字符串，敏感凭证全量清洗脱敏。
    """
    if not is_safe_for_content_sampling(file_path):
        return ""

    try:
        p = Path(file_path)
        if not p.is_file():
            return ""

        # 读取前 max_bytes*2 字节以容纳多字节编码
        with open(file_path, "rb") as f:
            raw_bytes = f.read(max_bytes * 2)

        # 尝试使用 utf-8 解码，失败回退 gbk
        try:
            text = raw_bytes.decode("utf-8", errors="ignore")
        except Exception:
            text = raw_bytes.decode("gbk", errors="ignore")

        if not text:
            return ""

        # 截断到指定长度
        sample = text[:max_bytes]

        # 正则脱敏敏感凭据
        for pattern, replacement in SENSITIVE_CONTENT_PATTERNS:
            sample = pattern.sub(replacement, sample)

        # 清洗换行与控制字符
        clean_sample = " ".join(sample.split())
        return clean_sample if clean_sample else ""
    except Exception:
        return ""


def sanitize_subpath(subpath: str) -> str:
    """
    清洗并规范化子目录路径：
    - 剥离 Windows 驱动器盘符 (如 C:, D:)
    - 移除非法字符 (< > : " | ? *)
    - 消除连续斜杠与 .. 目录穿越攻击
    - 规范为跨平台中立的相对路径
    """
    if not subpath:
        return ""

    raw = subpath.strip()
    # 剥离 Windows 盘符
    raw = re.sub(r'^[a-zA-Z]:', '', raw)
    # 统一将反斜杠转为正斜杠
    raw = raw.replace("\\", "/")
    # 替换非法字符（保留 / 供层级划分）
    raw = re.sub(r'[\<\>\:"\|\?\*]', '', raw)

    parts = [p.strip() for p in raw.split("/") if p.strip() and p.strip() != "."]
    safe_parts: List[str] = []
    for part in parts:
        if part == "..":
            if safe_parts:
                safe_parts.pop()
        else:
            clean_part = part.strip()
            if clean_part:
                safe_parts.append(clean_part)

    return "/".join(safe_parts)
