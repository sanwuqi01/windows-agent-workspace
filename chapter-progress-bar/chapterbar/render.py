"""Pillow 逐帧渲染：五格等宽、白底条、蓝填充在文字下层、末帧全满。

内存策略：文字层每格只预渲染一次（RGBA），每帧只按时间算进度、贴填充、贴文字层，
逐帧直接写进 FFmpeg 管道，不把整段帧堆在内存里（16s@30fps=480 帧也只占一帧内存）。

可重复性：所有几何量取整、进度按帧时刻计算（末帧强制取成片时长），同一配置两次渲染得到逐像素一致的帧。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterator

from PIL import Image, ImageDraw, ImageFont

from .errors import ConfigError
from .model import Plan
from .style import Style

MAX_LINES = 2  # 标题最多两行（任务单：标题常显可两行）


class TextOverflowError(ConfigError):
    """标题在当前字号/格宽下排不进两行，或单个字形就超宽/超高。"""


def load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size=size)
    except OSError as exc:  # pragma: no cover - 依赖本机字体
        raise ConfigError(f"无法加载字体 {path}：{exc}") from exc


def _glyph_bitmap(font: ImageFont.FreeTypeFont, char: str, box: int) -> bytes:
    image = Image.new("L", (box, box), 255)
    ImageDraw.Draw(image).text((box // 4, box // 4), char, font=font, fill=0)
    return image.tobytes()


def missing_glyphs(font: ImageFont.FreeTypeFont, text: str, font_size: int) -> list[str]:
    """用私用区字形做「豆腐块」基准，找出字体里没有字形的字符。

    中文字体缺失时字符会渲染成同一个 .notdef 方框（或空白），与私用区字符的位图相同，
    因此可以据此判定「缺字」，而不是靠肉眼看预览。
    """
    box = max(32, int(font_size * 2.5))
    ref = _glyph_bitmap(font, "\ue000", box)
    missing: list[str] = []
    for char in dict.fromkeys(text):
        if char.isspace():
            continue
        if _glyph_bitmap(font, char, box) == ref:
            missing.append(char)
    return missing


def _greedy_lines(font: ImageFont.FreeTypeFont, text: str, max_width: float) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and font.getlength(candidate) > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _balanced_lines(text: str, count: int) -> list[str]:
    """把字符尽量均分到 count 行；避免出现 6+1 这种孤字尾巴。"""
    cap = math.ceil(len(text) / count)
    lines: list[str] = []
    current = ""
    for char in text:
        if len(current) < cap:
            current += char
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def wrap_text(font: ImageFont.FreeTypeFont, text: str, max_width: float) -> list[str]:
    """按像素宽度折行；中文按字断行（标题 ≤8 字，不做词法分析）。

    放不下一行时先用贪心求最小行数，再在行数不变的前提下把字均分，
    这样 7 字标题是 4+3 而不是 6+1（孤字）。
    """
    if not text:
        return []
    if font.getlength(text) <= max_width:
        return [text]
    greedy = _greedy_lines(font, text, max_width)
    if len(greedy) <= 1:
        return greedy
    balanced = _balanced_lines(text, len(greedy))
    if all(font.getlength(line) <= max_width for line in balanced):
        return balanced
    return greedy


@dataclass
class _CellLayer:
    lines: list[str]
    image: Image.Image  # RGBA，格内尺寸，背景透明


def layout_title(
    style: Style, font: ImageFont.FreeTypeFont, title: str, index: int
) -> list[str]:
    """只做排版计算（不画图）：返回标题被折成的行。

    供 `check` 在渲染前就发现「文字溢出」，也是 BarRenderer 预渲染文字层的前置步骤。
    """
    cell_w = style.cell_width
    bar_h = style.bar_height
    max_width = cell_w - 2 * style.text_padding
    if max_width <= 0:
        raise TextOverflowError(
            f"第 {index} 段：格宽 {cell_w}px 减掉 text_padding 后没有可用宽度"
        )
    lines = wrap_text(font, title, max_width)
    if len(lines) > MAX_LINES:
        raise TextOverflowError(
            f"第 {index} 段标题「{title}」在 {style.font_size}px 字号 / {max_width}px 格宽下"
            f"排成 {len(lines)} 行（{lines}），超过 {MAX_LINES} 行；"
            "请缩短标题、减小 font_size 或加大 width"
        )
    for line in lines:
        width = font.getlength(line)
        if width > max_width:
            raise TextOverflowError(
                f"第 {index} 段标题「{title}」单行「{line}」宽 {width:.1f}px，超出可用 {max_width}px"
            )
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    block_h = line_h * len(lines) + style.line_gap * (len(lines) - 1)
    if block_h > bar_h - 2 * max(0, style.text_padding // 2):
        raise TextOverflowError(
            f"第 {index} 段标题「{title}」{len(lines)} 行共 {block_h}px 高，"
            f"超出条高 {bar_h}px；请减小 font_size 或加大 height"
        )
    return lines


class BarRenderer:
    """把 chapters + style 变成逐帧 RGB 位图。"""

    def __init__(self, style: Style, plan: Plan):
        if not plan.has_times:
            raise ConfigError("chapters.json 缺少 start/end，先跑 align 生成时码再渲染")
        self.style = style
        self.plan = plan
        self.duration = float(plan.chapters[-1].end or 0.0)
        if self.duration <= 0:
            raise ConfigError("成片时长必须为正")
        self.font = load_font(style.font_path, style.font_size)

        titles = "".join(ch.title for ch in plan.chapters)
        missing = missing_glyphs(self.font, titles, style.font_size)
        if missing:
            raise ConfigError(
                f"字体 {style.font_path} 缺少这些字的字形：{' '.join(missing)}；"
                "换一个含中文字形的字体（如 C:/Windows/Fonts/msyh.ttc）"
            )

        self._size = (style.width, style.height)
        self._background = style.rgb("background")
        self._cell_rgb = style.rgb("cell")
        self._progress_rgb = style.rgb("progress")
        self._text_rgba = style.rgb("text") + (255,)
        self._stroke_rgba = style.rgb("stroke") + (255,)
        self._border_rgb = style.rgb("cell_border") if style.cell_border else None
        self._layers = [self._build_layer(ch.title, ch.index) for ch in plan.chapters]
        self._fill_mask = self._build_fill_mask()

    # ---- 预渲染 ---------------------------------------------------------
    def _build_layer(self, title: str, index: int) -> _CellLayer:
        style = self.style
        cell_w = style.cell_width
        bar_h = style.bar_height
        lines = layout_title(style, self.font, title, index)
        ascent, descent = self.font.getmetrics()
        line_h = ascent + descent
        block_h = line_h * len(lines) + style.line_gap * (len(lines) - 1)

        layer = Image.new("RGBA", (cell_w, bar_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        top = (bar_h - block_h) // 2
        for pos, line in enumerate(lines):
            center_y = top + pos * (line_h + style.line_gap) + line_h // 2
            draw.text(
                (cell_w // 2, center_y),
                line,
                font=self.font,
                fill=self._text_rgba,
                anchor="mm",
                stroke_width=style.stroke_width,
                stroke_fill=self._stroke_rgba,
            )
        return _CellLayer(lines=lines, image=layer)

    def _build_fill_mask(self) -> Image.Image | None:
        style = self.style
        if style.corner_radius <= 0:
            return None
        mask = Image.new("L", (style.cell_width, style.bar_height), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, style.cell_width - 1, style.bar_height - 1],
            radius=min(style.corner_radius, style.bar_height // 2),
            fill=255,
        )
        return mask

    # ---- 进度与帧 -------------------------------------------------------
    @property
    def frame_count(self) -> int:
        return max(1, int(round(self.duration * self.style.fps)))

    def progress(self, index: int, t: float) -> float:
        chapter = self.plan.chapters[index]
        start = float(chapter.start or 0.0)
        end = float(chapter.end or 0.0)
        if t <= start:
            return 0.0
        if t >= end:
            return 1.0
        if end <= start:
            return 1.0
        return (t - start) / (end - start)

    def render(self, t: float) -> Image.Image:
        """渲染时刻 t 的一帧（t 为「该帧覆盖到的时刻」，末帧传 duration 即全满）。"""
        style = self.style
        image = Image.new("RGB", self._size, self._background)
        draw = ImageDraw.Draw(image)
        fill_layer = None

        for index, chapter in enumerate(self.plan.chapters):
            x0, y0, x1, y1 = style.cell_box(index)
            draw.rectangle(
                [x0, y0, x1, y1],
                fill=self._cell_rgb,
                outline=self._border_rgb,
                width=style.cell_border_width if self._border_rgb else 0,
            )
            px = int(round(self.progress(index, t) * style.cell_width))
            px = max(0, min(px, style.cell_width))
            if px > 0:
                if self._fill_mask is None:
                    draw.rectangle([x0, y0, x0 + px - 1, y1], fill=self._progress_rgb)
                else:
                    if fill_layer is None:
                        fill_layer = Image.new("RGB", (style.cell_width, style.bar_height), self._progress_rgb)
                    # 圆角填充：整体圆角遮罩，把超出 px 的部分遮掉，保持左圆右直
                    mask = self._fill_mask
                    if px < style.cell_width:
                        mask = mask.copy()
                        ImageDraw.Draw(mask).rectangle(
                            [px, 0, style.cell_width - 1, style.bar_height - 1], fill=0
                        )
                    image.paste(fill_layer, (x0, y0), mask)
            # 文字永远最后贴，保证填充在文字下层
            image.paste(self._layers[index].image, (x0, y0), self._layers[index].image)
        return image

    def frame_time(self, frame_index: int) -> float:
        """第 frame_index 帧（0 基）用于计算进度的时间点。

        取帧起始时刻（第 0 帧 = 0s，开始预览不出现橡皮头蓝边），
        但**最后一帧强制取 duration**，保证「末帧全满」；两者差不到 1 帧，肉眼无感。
        """
        if frame_index >= self.frame_count - 1:
            return self.duration
        return frame_index / self.style.fps

    def frames(self) -> Iterator[tuple[int, float, Image.Image]]:
        for frame_index in range(self.frame_count):
            t = self.frame_time(frame_index)
            yield frame_index, t, self.render(t)

    def frames_between(self, start: float, end: float) -> Iterator[tuple[int, float, Image.Image]]:
        """只渲染 [start, end) 区间（短动画预览用），帧号仍按全片计算，进度与全片一致。"""
        first = max(0, int(start * self.style.fps))
        last = min(self.frame_count, int(end * self.style.fps))
        for frame_index in range(first, last):
            t = self.frame_time(frame_index)
            yield frame_index, t, self.render(t)

    def preview_time(self, seconds: float) -> tuple[int, float]:
        """把一个时刻落到实际帧上：返回 (帧号, 该帧用于算进度的时间)。"""
        frame_index = int(seconds * self.style.fps)
        frame_index = max(0, min(frame_index, self.frame_count - 1))
        return frame_index, self.frame_time(frame_index)
