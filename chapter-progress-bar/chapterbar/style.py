"""style.json：样式（色号 / 字体 / 字号 / 尺寸 / 间距）加载与校验。

设计原则：字段固定、未知字段直接报错（避免拼错 key 却静默取默认值）；
所有颜色必须是 `#RRGGBB`；字体文件不存在立即报错，不静默换字体。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigError, DependencyError
from .util import is_even_int, require_int, require_number

HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")

# 找不到中文字体时的兜底候选（只在 style.json 完全没写 font.path 时使用）
DEFAULT_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)

REQUIRED_KEYS = (
    "width",
    "height",
    "fps",
    "background",
    "cell",
    "progress",
    "text",
    "stroke",
    "font",
    "font_size",
    "padding",
    "gap",
)

OPTIONAL_KEYS = (
    "line_gap",
    "stroke_width",
    "corner_radius",
    "cell_border",
    "cell_border_width",
    "text_padding",
    "letter_spacing",
)

ALLOWED_KEYS = set(REQUIRED_KEYS) | set(OPTIONAL_KEYS)


def _color(raw: dict[str, Any], key: str, default: str | None = None) -> str:
    value = raw.get(key, default)
    if not isinstance(value, str) or not HEX_COLOR.match(value):
        raise ConfigError(f"style.{key} 必须是 #RRGGBB 色号，当前为 {value!r}")
    return value.upper()


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def resolve_default_font() -> str:
    for candidate in DEFAULT_FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    raise DependencyError(
        "style.font.path 未填写，且本机找不到中文字体候选；请在 style.json 里显式写 font.path"
    )


@dataclass(frozen=True)
class Style:
    """校验通过的样式。所有派生像素量都在这里算好。"""

    width: int
    height: int
    fps: int
    background: str
    cell: str
    progress: str
    text: str
    stroke: str
    font_path: str
    font_size: int
    padding: int
    gap: int
    line_gap: int = 6
    stroke_width: int = 2
    corner_radius: int = 0
    cell_border: str | None = None
    cell_border_width: int = 0
    text_padding: int = 6
    letter_spacing: int = 0
    segment_count: int = 5
    source_path: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    # ---- 派生尺寸 -------------------------------------------------------
    @property
    def cell_width(self) -> int:
        usable = self.width - 2 * self.padding - self.gap * (self.segment_count - 1)
        return usable // self.segment_count

    @property
    def bar_height(self) -> int:
        return self.height - 2 * self.padding

    def cell_box(self, index: int) -> tuple[int, int, int, int]:
        """返回第 index 格（0 基）的闭区间像素框 (x0, y0, x1, y1)。"""
        cw = self.cell_width
        x0 = self.padding + index * (cw + self.gap)
        y0 = self.padding
        return x0, y0, x0 + cw - 1, y0 + self.bar_height - 1

    def rgb(self, key: str) -> tuple[int, int, int]:
        return _rgb(getattr(self, key))

    def as_dict(self) -> dict[str, Any]:
        data = {
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "background": self.background,
            "cell": self.cell,
            "progress": self.progress,
            "text": self.text,
            "stroke": self.stroke,
            "font": {"path": self.font_path},
            "font_size": self.font_size,
            "padding": self.padding,
            "gap": self.gap,
            "line_gap": self.line_gap,
            "stroke_width": self.stroke_width,
            "corner_radius": self.corner_radius,
            "cell_border": self.cell_border,
            "cell_border_width": self.cell_border_width,
            "text_padding": self.text_padding,
            "letter_spacing": self.letter_spacing,
        }
        return data


def load_style(path: str | Path) -> Style:
    """读取并校验 style.json。字面量错误一次性统一报出。"""
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"style 文件不存在：{p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"style 文件不是合法 JSON：{p}（{exc}）") from exc
    if not isinstance(raw, dict):
        raise ConfigError("style.json 顶层必须是对象")

    problems: list[str] = []
    unknown = sorted(set(raw) - ALLOWED_KEYS)
    if unknown:
        problems.append(f"未知字段：{', '.join(unknown)}（允许：{', '.join(sorted(ALLOWED_KEYS))}）")
    missing = [k for k in REQUIRED_KEYS if k not in raw]
    if missing:
        problems.append(f"缺少必填字段：{', '.join(missing)}")
    if problems:
        raise ConfigError("style.json 校验失败：\n- " + "\n- ".join(problems))

    width = require_int(raw["width"], "style.width")
    height = require_int(raw["height"], "style.height")
    fps = require_int(raw["fps"], "style.fps")

    if not is_even_int(width):
        raise ConfigError(f"style.width 必须是偶数（H.264/yuv420p 要求），当前 {width}")
    if not is_even_int(height):
        raise ConfigError(f"style.height 必须是偶数（H.264/yuv420p 要求），当前 {height}")
    if width < 320:
        raise ConfigError(f"style.width 太小（{width}），五格窄条至少 320")
    if height < 40:
        raise ConfigError(f"style.height 太小（{height}），两行标题至少 40")
    if fps <= 0 or fps > 120:
        raise ConfigError(f"style.fps 必须在 1..120，当前 {fps}")

    font_raw = raw["font"]
    if isinstance(font_raw, dict):
        font_path = font_raw.get("path")
        if font_path in (None, ""):
            font_path = resolve_default_font()
    elif isinstance(font_raw, str):
        font_path = font_raw
    else:
        raise ConfigError("style.font 必须是对象 {path: ...} 或字符串路径")
    if not Path(str(font_path)).is_file():
        raise ConfigError(
            f"style.font.path 指向的字体文件不存在：{font_path}\n"
            f"候选：{', '.join(DEFAULT_FONT_CANDIDATES[:3])}"
        )

    padding = require_int(raw["padding"], "style.padding")
    gap = require_int(raw["gap"], "style.gap")
    font_size = require_int(raw["font_size"], "style.font_size")
    if padding < 0 or gap < 0:
        raise ConfigError("style.padding / style.gap 不能为负")
    if font_size <= 0:
        raise ConfigError(f"style.font_size 必须为正，当前 {font_size}")

    style = Style(
        width=width,
        height=height,
        fps=fps,
        background=_color(raw, "background"),
        cell=_color(raw, "cell"),
        progress=_color(raw, "progress"),
        text=_color(raw, "text"),
        stroke=_color(raw, "stroke"),
        font_path=str(font_path),
        font_size=font_size,
        padding=padding,
        gap=gap,
        line_gap=require_int(raw.get("line_gap", 6), "style.line_gap"),
        stroke_width=require_int(raw.get("stroke_width", 2), "style.stroke_width"),
        corner_radius=require_int(raw.get("corner_radius", 0), "style.corner_radius"),
        cell_border=_color(raw, "cell_border") if raw.get("cell_border") else None,
        cell_border_width=require_int(raw.get("cell_border_width", 0), "style.cell_border_width"),
        text_padding=require_int(raw.get("text_padding", 6), "style.text_padding"),
        letter_spacing=require_int(raw.get("letter_spacing", 0), "style.letter_spacing"),
        source_path=str(p),
        raw=raw,
    )

    if style.cell_width < 40:
        raise ConfigError(
            f"单格宽度只剩 {style.cell_width}px（width={width}, padding={padding}, gap={gap}），"
            "放不下两个字，请减小 padding/gap 或加大 width"
        )
    if style.bar_height < font_size:
        raise ConfigError(
            f"条高 {style.bar_height}px 小于字号 {font_size}px（height={height}, padding={padding}）"
        )
    if style.stroke_width < 0 or style.corner_radius < 0 or style.line_gap < 0:
        raise ConfigError("stroke_width / corner_radius / line_gap 不能为负")
    return style
