"""chapters.json 校验 + 五段梗概语义质量（占位符/重复/原文锚点）。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import DEFAULT_ANCHORS, DEFAULT_TITLES, chapters_payload, write_json

from chapterbar.errors import ConfigError
from chapterbar.model import load_plan, validate_plan
from chapterbar.outline import (
    title_problems,
    uniformity_problems,
    verify_anchors,
)

TRANSCRIPT = (
    "早餐到底该怎么吃？今天一次讲清。第一件事是蛋白质，鸡蛋牛奶都算。"
    "第二步看主食，粗细搭配。别只吃白粥配咸菜。误区一是空腹喝咖啡，"
    "误区二是把水果当正餐。记住这三句，早餐就不难。"
)


class ChapterValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _plan(self, **kwargs):
        path = write_json(self.tmp / "chapters.json", chapters_payload(**kwargs))
        return load_plan(path)

    def test_five_chapters_with_times_ok(self) -> None:
        plan = validate_plan(self._plan(), require_times=True)
        self.assertEqual([c.title for c in plan.chapters], DEFAULT_TITLES)
        self.assertAlmostEqual(plan.chapters[-1].end, 16.0)

    def test_four_chapters_rejected(self) -> None:
        plan = self._plan(titles=DEFAULT_TITLES[:4])
        with self.assertRaises(ConfigError) as ctx:
            validate_plan(plan, require_times=False)
        self.assertIn("必须恰好 5 段", str(ctx.exception))

    def test_six_chapters_rejected(self) -> None:
        titles = DEFAULT_TITLES + ["多余一段"]
        plan = self._plan(titles=titles)
        with self.assertRaises(ConfigError):
            validate_plan(plan, require_times=False)

    def test_title_longer_than_eight_chars(self) -> None:
        titles = list(DEFAULT_TITLES)
        titles[0] = "这是一个超过八个字的标题"
        plan = self._plan(titles=titles)
        with self.assertRaises(ConfigError) as ctx:
            validate_plan(plan, require_times=False)
        self.assertIn("超过 8 字上限", str(ctx.exception))

    def test_placeholder_title_rejected(self) -> None:
        titles = list(DEFAULT_TITLES)
        titles[1] = "第二段"
        plan = self._plan(titles=titles)
        with self.assertRaises(ConfigError) as ctx:
            validate_plan(plan, require_times=False)
        self.assertIn("占位", str(ctx.exception))

    def test_duplicate_title_rejected(self) -> None:
        titles = list(DEFAULT_TITLES)
        titles[3] = titles[0]
        plan = self._plan(titles=titles)
        with self.assertRaises(ConfigError) as ctx:
            validate_plan(plan, require_times=False)
        self.assertIn("重复", str(ctx.exception))

    def test_missing_anchor_rejected(self) -> None:
        payload = chapters_payload()
        payload["chapters"][2].pop("anchor")
        path = write_json(self.tmp / "no_anchor.json", payload)
        with self.assertRaises(ConfigError) as ctx:
            validate_plan(load_plan(path), require_times=False)
        self.assertIn("anchor", str(ctx.exception))

    def test_times_required_for_render(self) -> None:
        plan = self._plan(times=[])
        with self.assertRaises(ConfigError) as ctx:
            validate_plan(plan, require_times=True)
        self.assertIn("缺少 start/end", str(ctx.exception))

    def test_non_contiguous_times_rejected(self) -> None:
        times = [(0.0, 2.0), (3.0, 6.0), (6.0, 9.0), (9.0, 14.0), (14.0, 16.0)]
        plan = self._plan(times=times)
        with self.assertRaises(ConfigError) as ctx:
            validate_plan(plan, require_times=True)
        self.assertIn("不连续", str(ctx.exception))

    def test_negative_time_rejected(self) -> None:
        times = [(-1.0, 2.0), (2.0, 6.0), (6.0, 9.0), (9.0, 14.0), (14.0, 16.0)]
        plan = self._plan(times=times)
        with self.assertRaises(ConfigError) as ctx:
            validate_plan(plan, require_times=True)
        self.assertIn("必须从 0 开始", str(ctx.exception))

    def test_zero_length_chapter_rejected(self) -> None:
        times = [(0.0, 2.0), (2.0, 2.0), (2.0, 9.0), (9.0, 14.0), (14.0, 16.0)]
        plan = self._plan(times=times)
        with self.assertRaises(ConfigError) as ctx:
            validate_plan(plan, require_times=True)
        self.assertIn("时长非正", str(ctx.exception))

    def test_last_end_mismatch_duration(self) -> None:
        times = [(0.0, 2.0), (2.0, 6.0), (6.0, 9.0), (9.0, 14.0), (14.0, 15.0)]
        plan = self._plan(times=times)
        with self.assertRaises(ConfigError) as ctx:
            validate_plan(plan, require_times=True)
        self.assertIn("与成片时长", str(ctx.exception))

    def test_unpaired_time_rejected(self) -> None:
        payload = chapters_payload(times=[])
        payload["chapters"][0]["start"] = 0.0
        path = write_json(self.tmp / "unpaired.json", payload)
        with self.assertRaises(ConfigError) as ctx:
            validate_plan(load_plan(path), require_times=False)
        self.assertIn("成对", str(ctx.exception))


class OutlineTest(unittest.TestCase):
    def test_title_problems(self) -> None:
        self.assertEqual(title_problems("早餐怎么吃"), [])
        self.assertTrue(title_problems(""))
        self.assertTrue(title_problems("九个字呢这已经是九个字"))
        self.assertTrue(title_problems("第一段"))
        self.assertTrue(title_problems("标题1"))
        self.assertTrue(title_problems("TBD"))
        self.assertTrue(title_problems("早餐怎么吃？"))

    def test_uniformity(self) -> None:
        self.assertEqual(uniformity_problems(DEFAULT_TITLES), [])
        self.assertTrue(uniformity_problems(["早餐一", "早餐二", "早餐三", "早餐四", "早餐五"]))
        self.assertTrue(uniformity_problems(["甲", "乙", "丙", "丁", "戊"]))

    def test_anchors_present_and_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(Path(tmp) / "c.json", chapters_payload(times=[]))
            plan = load_plan(path)
        report = verify_anchors(plan, TRANSCRIPT)
        self.assertTrue(report.anchors[0].start_ok)
        self.assertTrue(all(a.start_ok and a.end_ok for a in report.anchors))
        self.assertEqual(report.problems, [])

    def test_fabricated_anchor_detected(self) -> None:
        anchors = list(DEFAULT_ANCHORS)
        anchors[2] = ("第三步看蔬菜", "别只吃白粥配咸菜")
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(Path(tmp) / "c.json", chapters_payload(anchors=anchors, times=[]))
            plan = load_plan(path)
        report = verify_anchors(plan, TRANSCRIPT)
        self.assertFalse(report.ok)
        self.assertTrue(any("未出现在原文" in p for p in report.problems))


if __name__ == "__main__":
    unittest.main()
