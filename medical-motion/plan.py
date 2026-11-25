"""Plan an approved full narration, then render only its code-motion shots."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unicodedata

from generate import MODULE, generate_html, render_html


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 重复键：{key}")
        result[key] = value
    return result


def parse_json(value):
    return json.loads(value, object_pairs_hook=unique_object)


def locate(source, quote):
    """Find one exact passage, allowing whitespace differences in the model reply."""
    if not isinstance(quote, str) or not quote.strip():
        raise ValueError("镜头缺少原文引用")
    words = re.findall(r"\S+", quote)
    pattern = r"\s*".join(re.escape(word) for word in words)
    matches = list(re.finditer(pattern, source))
    if len(matches) != 1:
        raise ValueError(f"原文引用必须唯一定位，实际匹配 {len(matches)} 次：{quote[:50]}")
    return matches[0].span()


def worker_plan(source, mixed):
    prompt = f"""你是医疗科普视频分镜规划者。阅读下面整期已定稿的口播正文，只返回一个 JSON 对象，不加 Markdown 或解释。
JSON 格式：{{"code_shots":[{{"source_quote":"原文连续片段","visual_brief":"可直接编写 HTML/SVG/GSAP 的具体画面、元素与出现顺序","seconds":6}}],"kuaizi_shots":[{{"source_sentence":"原文连续片段","summary":"忠实压缩句","anchor":"1–15字单一可视机制或物象","style":"medical3d"}}]}}。
code_shots 只选择代码图形确有表达价值的段落：步骤、前后或并列对比、时间变化、原文有依据的数量关系等。选最少的必要镜头，可为零。每个 visual_brief 必须按竖屏 9:16、1080×1920 说明具体构图、图形关系、动效顺序和短屏幕文字，足以直接制作；屏幕文字应直接取自对应原文，保留其条件、否定、数字及单位，不得添加原文没有的医学事实、数字或结论。绝对不要写 16:9、1920×1080 或横屏。seconds 为 2–30 的整数。
每个 source_quote/source_sentence 必须是正文中唯一可定位的连续原文，保留原字词、否定、条件、数字和标点；不同镜头的原文范围不能重叠，也不能重复同一片段。不要为了凑镜头数量选抽象泛谈、重复表达或没有可靠视觉映射的句子。
{"如有明确适合 3D 医疗机制或温暖写实空景的 AI 空镜，可选少量 kuaizi_shots；它们只做候选计划，不与代码镜头重叠。写实画面可选无人物的器械、检查单或环境空景。style 仅 medical3d 或 warmReal。summary 忠实压缩成一个完整句子，可有一个句末标点，小数点保留；anchor 为 1–15 字单一具体可视物象或机制，不含标点或空白。可为零。" if mixed else "本次仅做代码动效，kuaizi_shots 必须为空数组。"}
全文如下：
{source}
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(Path(os.environ.get("DSH_WORKER_PS1", MODULE.parent / "tools" / "dsh-worker.ps1"))), "--stdin"],
        input=prompt.encode("utf-8"), stdout=subprocess.PIPE, check=True, timeout=900,
    )
    reply = result.stdout.decode("utf-8-sig").strip()
    match = re.fullmatch(r"(?:```(?:json)?\s*)?(\{.*\})(?:\s*```)?", reply, re.DOTALL | re.IGNORECASE)
    if not match:
        raise ValueError("DSH 未返回单个 JSON 对象，未保存计划")
    return parse_json(match[1])


def validate_plan(raw, source, mixed):
    if not isinstance(raw, dict) or not isinstance(raw.get("code_shots"), list) or not isinstance(raw.get("kuaizi_shots"), list):
        raise ValueError("分镜计划缺少 code_shots 或 kuaizi_shots 数组")
    if not mixed and raw["kuaizi_shots"]:
        raise ValueError("未指定 --mixed 时不能规划 AI 空镜")
    intervals = []
    codes, ai = [], []
    for index, shot in enumerate(raw["code_shots"], 1):
        if not isinstance(shot, dict):
            raise ValueError("代码镜头格式错误")
        quote, brief, seconds = (shot.get(key) for key in ("source_quote", "visual_brief", "seconds"))
        if not isinstance(brief, str) or len(brief.strip()) < 20:
            raise ValueError(f"代码镜头 {index} 缺少可执行视觉说明")
        if re.search(r"16\s*[:：/]\s*9|1920\s*[×xX*]\s*1080|横屏", brief):
            raise ValueError(f"代码镜头 {index} 视觉说明误写横屏，应为 9:16、1080×1920")
        if type(seconds) is not int or not 2 <= seconds <= 30:
            raise ValueError(f"代码镜头 {index} 时长应为 2–30 秒整数")
        start, end = locate(source, quote)
        intervals.append((start, end))
        codes.append({"id": f"code-{index:02d}", "source_quote": source[start:end], "start": start,
                      "end": end, "visual_brief": brief.strip(), "seconds": seconds})
    for index, shot in enumerate(raw["kuaizi_shots"], 1):
        if not isinstance(shot, dict):
            raise ValueError("AI 空镜格式错误")
        sentence, summary, anchor, style = (shot.get(key) for key in ("source_sentence", "summary", "anchor", "style"))
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError(f"AI 空镜 {index} 缺少 summary")
        summary = summary.strip()
        if summary[-1] in "。！？.!?;；":
            summary = summary[:-1].rstrip()
        if not summary or any(mark in summary for mark in "。！？；!?;") or any(
            char == "." and (position == 0 or position == len(summary) - 1 or
                             not summary[position - 1].isdigit() or not summary[position + 1].isdigit())
            for position, char in enumerate(summary)
        ):
            raise ValueError(f"AI 空镜 {index} summary 应为单句；仅小数点可在句中")
        if (not isinstance(anchor, str) or not 1 <= len(anchor) <= 15 or
                any(char.isspace() or unicodedata.category(char).startswith("P") for char in anchor)):
            raise ValueError(f"AI 空镜 {index} anchor 应为 1–15 字")
        if style not in ("medical3d", "warmReal"):
            raise ValueError(f"AI 空镜 {index} style 错误")
        start, end = locate(source, sentence)
        intervals.append((start, end))
        ai.append({"source_sentence": source[start:end], "summary": summary, "anchor": anchor.strip(),
                   "style": style, "start": start, "end": end})
    intervals.sort()
    if any(left[1] > right[0] for left, right in zip(intervals, intervals[1:])):
        raise ValueError("分镜引用原文区间重叠或重复")
    return codes, ai


def main():
    parser = argparse.ArgumentParser(description="从整期已定稿口播规划镜头并生成 OpenMotion MP4")
    parser.add_argument("manuscript", type=Path, help="整期已定稿正文 UTF-8 文件")
    parser.add_argument("output", type=Path, help="本期工作区输出目录")
    parser.add_argument("--plan-only", action="store_true", help="只保存分镜计划，不生成 MP4")
    parser.add_argument("--resume", action="store_true", help="读取已有 storyboard.json 继续生成")
    parser.add_argument("--mixed", action="store_true", help="额外规划筷子 AI 空镜候选，不调用筷子")
    args = parser.parse_args()
    source = args.manuscript.read_text(encoding="utf-8-sig").strip()
    if not source:
        parser.error("整稿为空")
    output = args.output.resolve()
    plan_path = output / "storyboard.json"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if args.resume:
        plan = parse_json(plan_path.read_text(encoding="utf-8"))
        if plan.get("source_sha256") != digest:
            raise ValueError("正文与已保存分镜计划不一致，不能续跑")
        mixed = bool(plan.get("mixed"))
        codes, ai = validate_plan(plan, source, mixed)
        if codes != plan["code_shots"] or ai != plan["kuaizi_shots"]:
            raise ValueError("计划引用位置或内容与原文不一致")
    else:
        if output.exists():
            parser.error("输出目录已存在；续跑请使用 --resume")
        raw = worker_plan(source, args.mixed)
        codes, ai = validate_plan(raw, source, args.mixed)
        output.mkdir(parents=True)
        plan = {"schema_version": 1, "source_sha256": digest, "mixed": args.mixed,
                "code_shots": codes, "kuaizi_shots": ai}
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(plan_path)
    if args.plan_only:
        return
    for shot in codes:
        target = output / shot["id"]
        request_path = output / f"{shot['id']}.request.json"
        request = {key: shot[key] for key in ("source_quote", "start", "end", "visual_brief", "seconds")}
        if request_path.exists():
            if parse_json(request_path.read_text(encoding="utf-8")) != request:
                raise ValueError(f"{shot['id']} 方案已变更；旧 HTML/MP4 不能续用，请在新输出目录重新规划")
        elif target.exists():
            raise ValueError(f"{shot['id']} 缺少镜头方案记录，不能确认旧产物；请在新输出目录重新规划")
        else:
            request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if (target / "motion.mp4").is_file():
            print(f"已完成：{target / 'motion.mp4'}")
            continue
        saved_html = target / "project" / "index.html"
        if saved_html.is_file():
            render_html(saved_html, target, shot["seconds"])
        else:
            html_path = output / f"{shot['id']}.html"
            if not html_path.is_file():
                html = generate_html(shot["source_quote"], shot["seconds"], shot["visual_brief"])
                html_path.write_text(html, encoding="utf-8")
            render_html(html_path, target, shot["seconds"])
        print(target / "motion.mp4")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
