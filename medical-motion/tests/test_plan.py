import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import plan


class PlanTests(unittest.TestCase):
    def test_zero_shots_and_nonoverlapping_mixed_shots(self):
        source = "先做第一步，再观察变化。这里是另一处画面。"
        self.assertEqual(plan.validate_plan({"code_shots": [], "kuaizi_shots": []}, source, False), ([], []))
        raw = {
            "code_shots": [{"source_quote": "先做第一步，再观察变化。", "visual_brief": "先显示第一步方框，再以箭头显示观察变化。", "seconds": 6}],
            "kuaizi_shots": [{"source_sentence": "这里是另一处画面。", "summary": "另一处画面", "anchor": "画面", "style": "warmReal"}],
        }
        codes, ai = plan.validate_plan(raw, source, True)
        self.assertEqual((codes[0]["start"], codes[0]["end"]), (0, 12))
        self.assertEqual(ai[0]["source_sentence"], source[ai[0]["start"]:ai[0]["end"]])
        raw["kuaizi_shots"][0]["source_sentence"] = "再观察变化。"
        with self.assertRaisesRegex(ValueError, "重叠"):
            plan.validate_plan(raw, source, True)

    def test_duplicate_json_key_and_bad_anchor(self):
        with self.assertRaisesRegex(ValueError, "重复键"):
            plan.parse_json('{"code_shots":[],"code_shots":[],"kuaizi_shots":[]}')
        with self.assertRaisesRegex(ValueError, "anchor"):
            plan.validate_plan({"code_shots": [], "kuaizi_shots": [
                {"source_sentence": "原文。", "summary": "原文", "anchor": "器械！", "style": "medical3d"}
            ]}, "原文。", True)
        _, ai = plan.validate_plan({"code_shots": [], "kuaizi_shots": [
            {"source_sentence": "原文。", "summary": "数值为 2.5。", "anchor": "检查单", "style": "warmReal"}
        ]}, "原文。", True)
        self.assertEqual(ai[0]["summary"], "数值为 2.5")

    def test_failed_render_can_resume_but_changed_brief_cannot_skip(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "script.txt"
            source.write_text("先看步骤，再看结果。", encoding="utf-8")
            output = root / "episode"
            raw = {"code_shots": [{"source_quote": "先看步骤，再看结果。", "visual_brief": "画面左侧显示步骤，箭头逐帧移动到右侧结果。", "seconds": 6}], "kuaizi_shots": []}

            def fail_render(html, target, seconds):
                (target / "project").mkdir(parents=True)
                (target / "project" / "index.html").write_text(html.read_text(encoding="utf-8"), encoding="utf-8")
                raise RuntimeError("render failed")

            with mock.patch.object(plan, "worker_plan", return_value=raw), mock.patch.object(plan, "generate_html", return_value="<html></html>"), mock.patch.object(plan, "render_html", side_effect=fail_render), mock.patch.object(sys, "argv", ["plan.py", str(source), str(output)]):
                with self.assertRaisesRegex(RuntimeError, "render failed"):
                    plan.main()
            self.assertTrue((output / "storyboard.json").is_file())
            self.assertTrue((output / "code-01" / "project" / "index.html").is_file())

            def finish_render(html, target, seconds):
                self.assertEqual(html, target / "project" / "index.html")
                (target / "motion.mp4").write_bytes(b"test")

            with mock.patch.object(plan, "generate_html", side_effect=AssertionError("must reuse HTML")), mock.patch.object(plan, "render_html", side_effect=finish_render), mock.patch.object(sys, "argv", ["plan.py", str(source), str(output), "--resume"]):
                plan.main()
            saved = json.loads((output / "storyboard.json").read_text(encoding="utf-8"))
            saved["code_shots"][0]["visual_brief"] += " 修改"
            (output / "storyboard.json").write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(sys, "argv", ["plan.py", str(source), str(output), "--resume"]):
                with self.assertRaisesRegex(ValueError, "方案已变更"):
                    plan.main()


if __name__ == "__main__":
    unittest.main()
