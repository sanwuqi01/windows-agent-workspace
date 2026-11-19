"""渲染：尺寸、五格状态、填充位置、末帧全满、可重复、颜色生效、超框报错、缺字检测。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import chapters_payload, style_payload, write_json
from PIL import Image

from chapterbar.errors import ConfigError
from chapterbar.model import load_plan, validate_plan
from chapterbar.render import (
    BarRenderer,
    TextOverflowError,
    load_font,
    missing_glyphs,
    wrap_text,
)
from chapterbar.style import load_style

COLORS = {"background": "#FFFFFF", "cell": "#FFFFFF", "progress": "#1E6FFF"}


def _rgb(hex_value: str) -> tuple[int, int, int]:
    h = hex_value.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


class RenderTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _renderer(self, *, style_overrides=None, payload=None) -> BarRenderer:
        payload = payload or chapters_payload()
        plan = validate_plan(load_plan(write_json(self.tmp / "c.json", payload)), require_times=True)
        style = load_style(write_json(self.tmp / "s.json", style_payload(**(style_overrides or {}))))
        return BarRenderer(style, plan)

    def test_frame_size_and_mode(self) -> None:
        renderer = self._renderer()
        image = renderer.render(0.0)
        self.assertEqual(image.size, (1080, 112))
        self.assertEqual(image.mode, "RGB")

    def test_start_frame_has_no_fill(self) -> None:
        renderer = self._renderer()
        image = renderer.render(0.0)
        blue = _rgb(COLORS["progress"])
        for index in range(5):
            x0, y0, x1, y1 = renderer.style.cell_box(index)
            self.assertNotEqual(image.getpixel((x0 + 4, (y0 + y1) // 2)), blue)

    def test_full_chapter_is_fully_filled(self) -> None:
        renderer = self._renderer()
        image = renderer.render(3.0)  # 第 1 段 0-2s 已播完
        blue = _rgb(COLORS["progress"])
        x0, y0, x1, y1 = renderer.style.cell_box(0)
        mid_y = (y0 + y1) // 2
        self.assertEqual(image.getpixel((x0 + 2, mid_y)), blue)
        self.assertEqual(image.getpixel((x1 - 2, mid_y)), blue)

    def test_current_chapter_fills_by_actual_duration(self) -> None:
        renderer = self._renderer()
        x0, y0, x1, y1 = renderer.style.cell_box(1)  # 第 2 段 2-6s，共 4s
        image = renderer.render(4.0)  # 走了一半
        blue = _rgb(COLORS["progress"])
        cell_w = x1 - x0 + 1
        rightmost = -1
        for x in range(x0, x1 + 1):
            if any(image.getpixel((x, y)) == blue for y in range(y0, y1 + 1)):
                rightmost = x
        self.assertGreater(rightmost, x0, "当前段应有部分填充")
        filled = rightmost - x0 + 1
        self.assertAlmostEqual(filled / cell_w, 0.5, delta=0.05)

    def test_unplayed_chapters_keep_cell_color(self) -> None:
        renderer = self._renderer()
        image = renderer.render(4.0)
        x0, y0, x1, y1 = renderer.style.cell_box(4)
        self.assertEqual(image.getpixel((x0 + 2, (y0 + y1) // 2)), _rgb(COLORS["cell"]))

    def test_last_frame_is_all_full(self) -> None:
        renderer = self._renderer()
        last_index = renderer.frame_count - 1
        t = renderer.frame_time(last_index)
        self.assertAlmostEqual(t, renderer.duration)
        image = renderer.render(t)
        blue = _rgb(COLORS["progress"])
        for index in range(5):
            x0, y0, x1, y1 = renderer.style.cell_box(index)
            mid_y = (y0 + y1) // 2
            self.assertEqual(image.getpixel((x0 + 2, mid_y)), blue)
            self.assertEqual(image.getpixel((x1 - 2, mid_y)), blue)

    def test_fill_is_below_text(self) -> None:
        """填充必须画在文字下层：文字区域内既要有蓝底，也要有非蓝的文字像素。"""
        renderer = self._renderer()
        image = renderer.render(4.0)
        x0, y0, x1, y1 = renderer.style.cell_box(1)
        blue = _rgb(COLORS["progress"])
        dark = _rgb("#1B1B1B")
        pixels = [
            image.getpixel((x, y))
            for x in range(x0, x1 + 1)
            for y in range(y0, y1 + 1, 3)
        ]
        self.assertIn(blue, pixels)
        self.assertIn(dark, pixels)

    def test_render_is_deterministic(self) -> None:
        first = self._renderer()
        second = self._renderer()
        a = first.render(4.0).tobytes()
        b = second.render(4.0).tobytes()
        self.assertEqual(a, b)
        self.assertEqual(first.render(4.0).tobytes(), first.render(4.0).tobytes())

    def test_color_change_takes_effect(self) -> None:
        renderer = self._renderer(style_overrides={"progress": "#E8452C"})
        image = renderer.render(3.0)
        x0, y0, x1, y1 = renderer.style.cell_box(0)
        self.assertEqual(
            image.getpixel((x0 + 2, (y0 + y1) // 2)), (0xE8, 0x45, 0x2C)
        )

    def test_two_line_title_allowed(self) -> None:
        payload = chapters_payload()
        payload["chapters"][0]["title"] = "早餐到底怎么搭配"
        renderer = self._renderer(payload=payload)
        self.assertEqual(len(renderer._layers[0].lines), 2)

    def test_text_overflow_raises(self) -> None:
        payload = chapters_payload()
        payload["chapters"][0]["title"] = "八个字的超长标题"
        with self.assertRaises(TextOverflowError) as ctx:
            self._renderer(payload=payload, style_overrides={"text_padding": 60})
        self.assertIn("超过 2 行", str(ctx.exception))

    def test_bar_height_overflow_raises(self) -> None:
        payload = chapters_payload()
        payload["chapters"][0]["title"] = "八个字的超长标题"
        with self.assertRaises(TextOverflowError):
            self._renderer(payload=payload, style_overrides={"font_size": 34, "height": 60})

    def test_missing_glyphs_detected(self) -> None:
        font = load_font("C:/Windows/Fonts/msyh.ttc", 30)
        self.assertEqual(missing_glyphs(font, "早餐怎么吃", 30), [])
        self.assertIn("\ue123", missing_glyphs(font, "早\ue123餐", 30))

    def test_wrap_text_respects_width(self) -> None:
        font = load_font("C:/Windows/Fonts/msyh.ttc", 30)
        lines = wrap_text(font, "一二三四五六七八", 100)
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertLessEqual(font.getlength(line), 100)

    def test_wrap_text_balances_orphan_char(self) -> None:
        font = load_font("C:/Windows/Fonts/msyh.ttc", 30)
        lines = wrap_text(font, "男性不育更专业", 196)  # 7 字，30px 下 6 字一行放得下
        self.assertEqual([len(line) for line in lines], [4, 3])
        self.assertEqual("".join(lines), "男性不育更专业")

    def test_frames_generator_is_lazy(self) -> None:
        renderer = self._renderer()
        generator = renderer.frames()
        first = next(generator)
        self.assertEqual(first[0], 0)
        self.assertAlmostEqual(first[1], 0.0)
        self.assertEqual(renderer.frame_count, 480)

    def test_frames_between_short_clip(self) -> None:
        renderer = self._renderer()
        frames = list(renderer.frames_between(5.0, 8.0))
        self.assertEqual(len(frames), 90)
        self.assertEqual(frames[0][0], 150)

    def test_save_png_roundtrip(self) -> None:
        renderer = self._renderer()
        path = self.tmp / "frame.png"
        renderer.render(4.0).save(path)
        with Image.open(path) as image:
            self.assertEqual(image.size, (1080, 112))


class RenderGuardTest(unittest.TestCase):
    def test_render_without_times_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = load_plan(write_json(Path(tmp) / "c.json", chapters_payload(times=[])))
            style = load_style(write_json(Path(tmp) / "s.json", style_payload()))
            with self.assertRaises(ConfigError):
                BarRenderer(style, plan)


if __name__ == "__main__":
    unittest.main()
