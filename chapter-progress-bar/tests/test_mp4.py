"""端到端：真实编码 MP4 + ffprobe 自检（无 ffmpeg 时自动跳过）。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import chapters_payload, style_payload, write_json

from chapterbar import mp4
from chapterbar.errors import DependencyError, RenderError
from chapterbar.model import load_plan, validate_plan
from chapterbar.render import BarRenderer
from chapterbar.style import load_style


def _ffmpeg_available() -> bool:
    try:
        mp4.ffmpeg_bin()
        mp4.ffprobe_bin()
    except DependencyError:
        return False
    return True


@unittest.skipUnless(_ffmpeg_available(), "本机没有 ffmpeg/ffprobe，跳过编码测试")
class EncodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _renderer(self) -> BarRenderer:
        plan = validate_plan(
            load_plan(write_json(self.tmp / "c.json", chapters_payload())), require_times=True
        )
        style = load_style(write_json(self.tmp / "s.json", style_payload()))
        return BarRenderer(style, plan)

    def test_encode_full_and_verify(self) -> None:
        renderer = self._renderer()
        out = self.tmp / "bar.mp4"
        frames = renderer.frames()
        mp4.encode(
            (frame for _, _, frame in frames),
            width=renderer.style.width,
            height=renderer.style.height,
            fps=renderer.style.fps,
            out_path=out,
            preset="ultrafast",
            total_frames=renderer.frame_count,
        )
        info, problems = mp4.verify(
            out,
            width=renderer.style.width,
            height=renderer.style.height,
            fps=renderer.style.fps,
            duration=renderer.duration,
        )
        self.assertEqual(problems, [])
        self.assertEqual(info["width"], renderer.style.width)
        self.assertEqual(info["height"], renderer.style.height)
        self.assertAlmostEqual(info["fps"], 30.0, places=2)
        self.assertAlmostEqual(info["duration"], 16.0, delta=1 / 30 + 1e-3)
        self.assertFalse(info["has_audio"])
        self.assertEqual(info["codec"], "h264")
        self.assertEqual(info["pix_fmt"], "yuv420p")

    def test_duration_mismatch_is_reported(self) -> None:
        renderer = self._renderer()
        out = self.tmp / "bar2.mp4"
        mp4.encode(
            (frame for _, _, frame in renderer.frames_between(0.0, 2.0)),
            width=renderer.style.width,
            height=renderer.style.height,
            fps=renderer.style.fps,
            out_path=out,
            preset="ultrafast",
        )
        _, problems = mp4.verify(out, width=renderer.style.width, height=renderer.style.height, fps=renderer.style.fps, duration=16.0)
        self.assertTrue(any("时长不符" in p for p in problems))

    def test_wrong_size_is_reported(self) -> None:
        renderer = self._renderer()
        out = self.tmp / "bar3.mp4"
        mp4.encode(
            (frame for _, _, frame in renderer.frames_between(0.0, 1.0)),
            width=renderer.style.width,
            height=renderer.style.height,
            fps=renderer.style.fps,
            out_path=out,
            preset="ultrafast",
        )
        _, problems = mp4.verify(out, width=1920, height=1080, fps=30, duration=1.0)
        self.assertTrue(any("尺寸不符" in p for p in problems))

    def test_refuse_overwrite(self) -> None:
        renderer = self._renderer()
        out = self.tmp / "exists.mp4"
        out.write_bytes(b"x")
        with self.assertRaises(RenderError) as ctx:
            mp4.encode(
                (frame for _, _, frame in renderer.frames_between(0.0, 0.5)),
                width=renderer.style.width,
                height=renderer.style.height,
                fps=renderer.style.fps,
                out_path=out,
            )
        self.assertIn("不覆盖", str(ctx.exception))

    def test_frame_size_mismatch_raises(self) -> None:
        renderer = self._renderer()
        with self.assertRaises(RenderError):
            mp4.encode(
                (frame for _, _, frame in renderer.frames_between(0.0, 0.5)),
                width=1000,
                height=96,
                fps=30,
                out_path=self.tmp / "wrong.mp4",
            )


if __name__ == "__main__":
    unittest.main()
