"""生成应用图标 assets/app.ico（磁盘占用环形图意象，呼应产品主题）。

图标只需生成一次并提交到仓库；构建脚本检测到缺失时会调用本模块重建。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent
ICON_PATH = ASSETS_DIR / "app.ico"

# 与 app/ui/styles.py 深色主题保持一致
BG_TOP = (26, 32, 44)
BG_BOTTOM = (15, 19, 28)
SEGMENTS = (
    (16, 185, 129),  # #10B981 安全
    (245, 158, 11),  # #F59E0B 警告
    (239, 68, 68),   # #EF4444 危险
    (59, 130, 246),  # #3B82F6 信息
)
SIZES = (256, 128, 64, 48, 32, 16)


def _rounded_rect_mask(px: int, radius_ratio: float = 0.22):
    """返回 px x px 的圆角矩形遮罩（与目标位图同尺寸）。"""
    from PIL import Image, ImageDraw

    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, px - 1, px - 1),
        radius=int(px * radius_ratio),
        fill=255,
    )
    return mask


def _render(size: int):
    from PIL import Image, ImageDraw

    scale = 4
    canvas = size * scale
    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))

    # 垂直渐变背景
    grad = Image.new("RGBA", (1, canvas))
    for y in range(canvas):
        t = y / max(canvas - 1, 1)
        grad.putpixel(
            (0, y),
            (
                int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t),
                int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t),
                int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t),
                255,
            ),
        )
    img.paste(grad.resize((canvas, canvas), Image.NEAREST), (0, 0))
    img.putalpha(_rounded_rect_mask(canvas))

    # 环形占用图：4 段按比例分配
    draw = ImageDraw.Draw(img)
    margin = canvas * 0.19
    box = (margin, margin, canvas - margin, canvas - margin)
    weights = (0.42, 0.26, 0.18, 0.14)
    start = -90.0
    for weight, color in zip(weights, SEGMENTS):
        extent = 360.0 * weight
        draw.pieslice(box, start=start + 1.6, end=start + extent - 1.6, fill=color + (255,))
        start += extent

    # 中心挖空成圆环，并留出中心高光点
    inner = canvas * 0.30
    draw.ellipse(
        (inner, inner, canvas - inner, canvas - inner),
        fill=BG_BOTTOM + (255,),
    )
    dot = canvas * 0.055
    cx = cy = canvas / 2
    draw.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=(226, 232, 240, 255))

    return img.resize((size, size), Image.LANCZOS)


def build_icon(path: Path = ICON_PATH) -> Path:
    try:
        # Pillow 的 ICO 插件只接受单张主图 + sizes 列表（自行降采样），
        # 传入 append_images 会报 "images do not match"。
        base = _render(max(SIZES))
        path.parent.mkdir(parents=True, exist_ok=True)
        base.save(
            path,
            format="ICO",
            sizes=[(s, s) for s in SIZES],
        )
        return path
    except Exception as exc:  # noqa: BLE001
        import traceback

        print(
            f"[icon] 图标生成失败，将使用 PyInstaller 默认图标: {exc}\n"
            f"{traceback.format_exc()}",
            file=sys.stderr,
        )
        return path


if __name__ == "__main__":
    out = build_icon()
    print(f"icon written: {out}" if out.exists() else "icon NOT written")
