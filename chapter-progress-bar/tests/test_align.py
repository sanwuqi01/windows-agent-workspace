"""对齐：按原句定位、跨卡句、歧义/删句候选、显式确认边界、连续化。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import DEFAULT_ANCHORS, chapters_payload, write_json

from chapterbar.align import align_plan, format_report
from chapterbar.errors import ConfigError
from chapterbar.model import load_plan
from chapterbar.subtitles import Cue, parse_srt


def cues_from_pairs(pairs):
    return [Cue(index=i, start=s, end=e, text=t) for i, (s, e, t) in enumerate(pairs, start=1)]


BASE_PAIRS = [
    (0.0, 2.0, "早餐到底该怎么吃？今天一次讲清。"),
    (2.0, 6.0, "第一件事是蛋白质，鸡蛋牛奶都算。"),
    (6.0, 7.6, "第二步看主食，粗细搭配。"),
    (7.6, 9.0, "别只吃白粥配咸菜。"),
    (9.0, 11.5, "误区一是空腹喝咖啡，"),
    (11.5, 14.0, "误区二是把水果当正餐。"),
    (14.0, 16.0, "记住这三句，早餐就不难。"),
]


class AlignTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _plan(self, **kwargs):
        path = write_json(self.tmp / "chapters.json", chapters_payload(**kwargs))
        return load_plan(path)

    def test_exact_unequal_five_chapters(self) -> None:
        result = align_plan(self._plan(times=[]), cues_from_pairs(BASE_PAIRS), duration=16.0)
        self.assertTrue(result.ok, result.issues)
        got = [(round(c["start"], 3), round(c["end"], 3)) for c in result.chapters]
        self.assertEqual(got, [(0.0, 2.0), (2.0, 6.0), (6.0, 9.0), (9.0, 14.0), (14.0, 16.0)])
        durations = [round(c["end"] - c["start"], 3) for c in result.chapters]
        self.assertEqual(durations, [2.0, 4.0, 3.0, 5.0, 2.0])
        self.assertNotEqual(len(set(durations)), 1, "不能退化成总时长五等分")

    def test_sentence_spanning_two_cues(self) -> None:
        pairs = list(BASE_PAIRS)
        pairs[0] = (0.0, 1.0, "早餐到底该怎么")
        pairs.insert(1, (1.0, 2.0, "吃？今天一次讲清。"))
        result = align_plan(self._plan(times=[]), cues_from_pairs(pairs), duration=16.0)
        self.assertTrue(result.ok, result.issues)
        self.assertEqual(round(result.chapters[0]["start"], 3), 0.0)
        self.assertEqual(round(result.chapters[0]["end"], 3), 2.0)

    def test_ambiguous_anchor_reports_candidates(self) -> None:
        pairs = [
            (0.0, 2.0, "早餐到底该怎么吃？今天一次讲清。"),
            (2.0, 4.0, "第一步先喝水。"),
            (4.0, 6.0, "第一步先喝水。"),
            (6.0, 9.0, "第二步看主食，粗细搭配。"),
            (9.0, 14.0, "误区一是空腹喝咖啡，误区二是把水果当正餐。"),
            (14.0, 16.0, "记住这三句，早餐就不难。"),
        ]
        anchors = list(DEFAULT_ANCHORS)
        anchors[1] = ("第一步先喝水", "第一步先喝水")
        result = align_plan(
            self._plan(anchors=anchors, times=[]), cues_from_pairs(pairs), duration=16.0
        )
        self.assertFalse(result.ok)
        ambiguous = [i for i in result.issues if i["kind"] == "ambiguous"]
        self.assertTrue(ambiguous)
        self.assertGreaterEqual(len(ambiguous[0]["candidates"]), 2)
        self.assertIn("cue", ambiguous[0]["candidates"][0])

    def test_deleted_sentence_reports_candidates(self) -> None:
        pairs = [
            (0.0, 2.0, "早餐到底该怎么吃？今天一次讲清。"),
            (2.0, 6.0, "第一件事是蛋白质，鸡蛋牛奶都算。"),
            # 第 3 段整段被删
            (6.0, 11.0, "误区一是空腹喝咖啡，误区二是把水果当正餐。"),
            (11.0, 16.0, "记住这三句，早餐就不难。"),
        ]
        result = align_plan(self._plan(times=[]), cues_from_pairs(pairs), duration=16.0)
        self.assertFalse(result.ok)
        not_found = [i for i in result.issues if i["kind"] == "not_found"]
        self.assertTrue(not_found)
        self.assertTrue(not_found[0]["candidates"])
        self.assertIn("similarity", not_found[0]["candidates"][0])

    def test_fuzzy_match_is_warning(self) -> None:
        pairs = list(BASE_PAIRS)
        # 字幕把「把水果当正餐」说成「拿水果当正餐」：止句只部分匹配
        pairs[5] = (11.5, 14.0, "误区二是拿水果当正餐。")
        result = align_plan(self._plan(times=[]), cues_from_pairs(pairs), duration=16.0)
        self.assertTrue(result.ok, result.issues)
        self.assertTrue(any(w["kind"] == "fuzzy_end" for w in result.warnings))

    def test_strict_upgrades_fuzzy_to_issue(self) -> None:
        pairs = list(BASE_PAIRS)
        pairs[5] = (11.5, 14.0, "误区二是拿水果当正餐。")
        result = align_plan(
            self._plan(times=[]), cues_from_pairs(pairs), duration=16.0, strict=True
        )
        self.assertFalse(result.ok)
        self.assertTrue(any(i["kind"].startswith("strict_") for i in result.issues))

    def test_resolved_cue_override(self) -> None:
        anchors = list(DEFAULT_ANCHORS)
        anchors[1] = ("第一步先喝水", "第一步先喝水")
        anchors[2] = ("第二步看主食", "粗细搭配")
        payload = chapters_payload(anchors=anchors, times=[])
        payload["chapters"][1]["resolved"] = {"start_cue": 3, "end_cue": 3}
        pairs = [
            (0.0, 2.0, "早餐到底该怎么吃？今天一次讲清。"),
            (2.0, 4.0, "第一步先喝水。"),
            (4.0, 6.0, "第一步先喝水。"),
            (6.0, 9.0, "第二步看主食，粗细搭配。"),
            (9.0, 14.0, "误区一是空腹喝咖啡，误区二是把水果当正餐。"),
            (14.0, 16.0, "记住这三句，早餐就不难。"),
        ]
        path = write_json(self.tmp / "resolved.json", payload)
        result = align_plan(load_plan(path), cues_from_pairs(pairs), duration=16.0)
        self.assertTrue(result.ok, result.issues)
        self.assertEqual(result.chapters[1]["start_cue"], 3)
        self.assertEqual(round(result.chapters[1]["anchor_start_time"], 3), 4.0)
        self.assertEqual(round(result.chapters[1]["anchor_end_time"], 3), 6.0)

    def test_resolved_cue_out_of_range(self) -> None:
        payload = chapters_payload(times=[])
        payload["chapters"][1]["resolved"] = {"start_cue": 99}
        path = write_json(self.tmp / "bad_resolved.json", payload)
        result = align_plan(load_plan(path), cues_from_pairs(BASE_PAIRS), duration=16.0)
        self.assertFalse(result.ok)
        self.assertIn("bad_override", {i["kind"] for i in result.issues})

    def test_confirmed_explicit_times(self) -> None:
        payload = chapters_payload(times=[])
        payload["chapters"][4].update({"start": 14.5, "end": 16.0, "confirmed": True})
        payload["chapters"][4]["anchor"] = {"start_sentence": "自定义边界", "end_sentence": "自定义边界"}
        path = write_json(self.tmp / "confirmed.json", payload)
        result = align_plan(load_plan(path), cues_from_pairs(BASE_PAIRS), duration=16.0)
        self.assertTrue(result.ok, result.issues)
        self.assertEqual(round(result.chapters[4]["start"], 3), 14.5)
        self.assertEqual(round(result.chapters[4]["end"], 3), 16.0)

    def test_lead_in_absorbed_into_first_chapter(self) -> None:
        pairs = [
            (0.0, 1.0, "（开场白）"),
            (1.0, 3.0, "早餐到底该怎么吃？今天一次讲清。"),
            (3.0, 7.0, "第一件事是蛋白质，鸡蛋牛奶都算。"),
            (7.0, 8.6, "第二步看主食，粗细搭配。"),
            (8.6, 10.0, "别只吃白粥配咸菜。"),
            (10.0, 12.5, "误区一是空腹喝咖啡，"),
            (12.5, 15.0, "误区二是把水果当正餐。"),
            (15.0, 17.0, "记住这三句，早餐就不难。"),
        ]
        result = align_plan(self._plan(times=[]), cues_from_pairs(pairs), duration=17.0)
        self.assertTrue(result.ok, result.issues)
        self.assertEqual(round(result.chapters[0]["start"], 3), 0.0)
        self.assertEqual(round(result.chapters[0]["anchor_start_time"], 3), 1.0)
        self.assertTrue(any(w["kind"] in ("lead_in", "gap") for w in result.warnings))
        self.assertIn("段 | 标题", format_report(result))

    def test_tail_absorbed_into_last_chapter(self) -> None:
        pairs = list(BASE_PAIRS)
        pairs[-1] = (14.0, 15.0, "记住这三句，早餐就不难。")
        result = align_plan(self._plan(times=[]), cues_from_pairs(pairs), duration=16.0)
        self.assertTrue(result.ok, result.issues)
        self.assertEqual(round(result.chapters[-1]["end"], 3), 16.0)

    def test_order_violation_detected(self) -> None:
        payload = chapters_payload(times=[])
        payload["chapters"][1]["anchor"] = {"start_sentence": "记住这三句", "end_sentence": "早餐就不难"}
        path = write_json(self.tmp / "order.json", payload)
        result = align_plan(load_plan(path), cues_from_pairs(BASE_PAIRS), duration=16.0)
        self.assertFalse(result.ok)

    def test_srt_parse_roundtrip(self) -> None:
        content = (
            "1\n00:00:00,000 --> 00:00:02,000\n早餐到底该怎么吃？\n\n"
            "2\n00:00:02,000 --> 00:00:06,000\n第一件事是蛋白质。\n"
        )
        cues = parse_srt(content)
        self.assertEqual(len(cues), 2)
        self.assertAlmostEqual(cues[1].start, 2.0)
        self.assertAlmostEqual(cues[1].end, 6.0)

    def test_bad_srt_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            parse_srt("1\n00:00:02,000 --> 00:00:01,000\n倒序\n")


if __name__ == "__main__":
    unittest.main()
