"""style.json 校验：色号、字体、尺寸、间距等实际失败条件。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import style_payload, write_json  # noqa: F401  (helpers 里已把项目根加进 sys.path)

from chapterbar.errors import ConfigError
from chapterbar.style import load_style


class StyleValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _load(self, **overrides):
        path = write_json(self.tmp / "style.json", style_payload(**overrides))
        return load_style(path)

    def test_default_ok(self) -> None:
        style = self._load()
        self.assertEqual((style.width, style.height, style.fps), (1080, 112, 30))
        self.assertEqual(style.cell_width, 208)
        self.assertEqual(style.bar_height, 96)

    def test_bad_color_format(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            self._load(progress="blue")
        self.assertIn("progress", str(ctx.exception))

    def test_short_hex_color(self) -> None:
        with self.assertRaises(ConfigError):
            self._load(background="#fff")

    def test_missing_font_file(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            self._load(font={"path": "C:/Windows/Fonts/not-exist-font.ttf"})
        self.assertIn("字体文件不存在", str(ctx.exception))

    def test_odd_width_rejected(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            self._load(width=1081)
        self.assertIn("偶数", str(ctx.exception))

    def test_odd_height_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            self._load(height=95)

    def test_gap_too_large(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            self._load(gap=400)
        self.assertIn("单格宽度", str(ctx.exception))

    def test_unknown_key_rejected(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            self._load(colour="#FFFFFF")
        self.assertIn("未知字段", str(ctx.exception))

    def test_missing_required_key(self) -> None:
        payload = style_payload()
        payload.pop("progress")
        path = write_json(self.tmp / "s2.json", payload)
        with self.assertRaises(ConfigError) as ctx:
            load_style(path)
        self.assertIn("缺少必填字段", str(ctx.exception))

    def test_fps_out_of_range(self) -> None:
        with self.assertRaises(ConfigError):
            self._load(fps=0)

    def test_bar_height_smaller_than_font(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            self._load(height=40, padding=8, font_size=60)
        self.assertIn("条高", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
