"""命令行级「失败条件」自检：非法时间 / 缺字体 / 超框 / 非五段 / 占位标题 / 对齐歧义 / 不覆盖已有文件。

单测已经覆盖这些分支；这个脚本再从**真实命令行入口**跑一遍，把退出码与报错原文打出来，
方便交付复核时一眼看到「确实会报错，而且报的是人话」。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
ENTRY = str(ROOT / "chapter_bar.py")
OUT = ROOT / "outputs" / "failcases"

BASE_STYLE = {
    "width": 1080,
    "height": 112,
    "fps": 30,
    "background": "#FFFFFF",
    "cell": "#FFFFFF",
    "progress": "#1E6FFF",
    "text": "#1B1B1B",
    "stroke": "#FFFFFF",
    "font": {"path": "C:/Windows/Fonts/msyh.ttc"},
    "font_size": 30,
    "padding": 8,
    "gap": 6,
    "line_gap": 4,
    "stroke_width": 2,
    "corner_radius": 4,
    "cell_border": "#D8DEE9",
    "cell_border_width": 1,
    "text_padding": 6,
    "letter_spacing": 0,
}

ANCHORS = [
    ("早餐到底该怎么吃", "今天一次讲清"),
    ("第一件事是蛋白质", "鸡蛋牛奶都算"),
    ("第二步看主食", "别只吃白粥配咸菜"),
    ("误区一是空腹喝咖啡", "把水果当正餐"),
    ("记住这三句", "早餐就不难"),
]
TITLES = ["早餐怎么吃", "蛋白质先吃", "主食粗细搭", "两个常见误区", "三句话记住"]
TIMES = [(0.0, 2.0), (2.0, 6.0), (6.0, 9.0), (9.0, 14.0), (14.0, 16.0)]


def chapters(titles=None, times=None, anchors=None) -> dict:
    titles = titles or TITLES
    anchors = anchors or ANCHORS
    times = times if times is not None else TIMES
    items = []
    for i, title in enumerate(titles, start=1):
        item = {
            "index": i,
            "title": title,
            "anchor": {
                "start_sentence": anchors[(i - 1) % len(anchors)][0],
                "end_sentence": anchors[(i - 1) % len(anchors)][1],
            },
        }
        if times and i - 1 < len(times):
            item["start"], item["end"] = times[i - 1]
        items.append(item)
    return {
        "schema_version": 1,
        "title": "失败条件自检",
        "source": {"duration": 16.0},
        "chapters": items,
    }


def write(name: str, data: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def run(label: str, args: list[str], expect: str) -> bool:
    proc = subprocess.run(
        [PY, ENTRY, *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    output = (proc.stderr or "") + (proc.stdout or "")
    ok = expect in output
    print(f"\n[{ '通过' if ok else '不符合预期' }] {label}")
    print(f"  命令: chapter_bar.py {' '.join(args)}")
    print(f"  退出码: {proc.returncode}")
    for line in output.strip().splitlines()[:6]:
        print(f"  | {line}")
    print(f"  期望命中: {expect!r} -> {'命中' if ok else '未命中'}")
    return ok


def main() -> int:
    style = write("style.json", BASE_STYLE)
    results: list[bool] = []

    # 1) 非法时间：中间断档（不连续）
    bad_time = chapters(times=[(0.0, 2.0), (3.0, 6.0), (6.0, 9.0), (9.0, 14.0), (14.0, 16.0)])
    results.append(
        run(
            "非法时间：五段断档不连续",
            ["check", "--chapters", str(write("chapters_gap.json", bad_time)), "--style", str(style), "--require-times"],
            "不连续",
        )
    )

    # 2) 非法时间：末段与成片时长不符
    bad_len = chapters(times=[(0.0, 2.0), (2.0, 6.0), (6.0, 9.0), (9.0, 14.0), (14.0, 15.0)])
    results.append(
        run(
            "非法时间：末段结束比成片时长短",
            ["check", "--chapters", str(write("chapters_len.json", bad_len)), "--style", str(style), "--require-times"],
            "与成片时长",
        )
    )

    # 3) 缺字体
    no_font = dict(BASE_STYLE)
    no_font["font"] = {"path": "C:/Windows/Fonts/no-such-cjk-font.ttf"}
    results.append(
        run(
            "缺字体：style.font.path 不存在",
            ["check", "--chapters", str(write("chapters_ok.json", chapters())), "--style", str(write("style_nofont.json", no_font))],
            "字体文件不存在",
        )
    )

    # 4) 文字超框
    overflow = chapters()
    overflow["chapters"][0]["title"] = "八个字的超长标题"
    wide_text = dict(BASE_STYLE)
    wide_text["text_padding"] = 60
    results.append(
        run(
            "标题超框：格宽放不下两行",
            [
                "check",
                "--chapters",
                str(write("chapters_overflow.json", overflow)),
                "--style",
                str(write("style_narrow.json", wide_text)),
                "--require-times",
            ],
            "超过 2 行",
        )
    )

    # 5) 非五段
    four = chapters(titles=TITLES[:4], times=TIMES[:4], anchors=ANCHORS[:4])
    results.append(
        run(
            "非法结构：只有四段",
            ["check", "--chapters", str(write("chapters_four.json", four)), "--style", str(style)],
            "必须恰好 5 段",
        )
    )

    # 6) 占位标题
    placeholder = chapters(titles=["第一段", "蛋白质先吃", "主食粗细搭", "两个常见误区", "三句话记住"])
    results.append(
        run(
            "模板伪装：占位标题",
            ["check", "--chapters", str(write("chapters_placeholder.json", placeholder)), "--style", str(style)],
            "占位",
        )
    )

    # 7) 对齐歧义（重复句）
    dup = chapters(times=[])
    dup["chapters"][1]["anchor"] = {"start_sentence": "第一步先喝水", "end_sentence": "第一步先喝水"}
    srt = OUT / "dup.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\n早餐到底该怎么吃？今天一次讲清。\n\n"
        "2\n00:00:02,000 --> 00:00:04,000\n第一步先喝水。\n\n"
        "3\n00:00:04,000 --> 00:00:06,000\n第一步先喝水。\n\n"
        "4\n00:00:06,000 --> 00:00:09,000\n第二步看主食，粗细搭配。\n\n"
        "5\n00:00:09,000 --> 00:00:14,000\n误区一是空腹喝咖啡，误区二是把水果当正餐。\n\n"
        "6\n00:00:14,000 --> 00:00:16,000\n记住这三句，早餐就不难。\n",
        encoding="utf-8",
    )
    results.append(
        run(
            "对齐歧义：同一句出现两次，要求人工确认边界",
            [
                "align",
                "--chapters",
                str(write("chapters_dup.json", dup)),
                "--srt",
                str(srt),
                "--write",
            ],
            "需人工复核，未写盘",
        )
    )

    # 8) 不覆盖已有输出
    existing = OUT / "existing.mp4"
    existing.write_bytes(b"not a real mp4")
    results.append(
        run(
            "不覆盖：目标文件已存在",
            [
                "render",
                "--chapters",
                str(write("chapters_ok2.json", chapters())),
                "--style",
                str(style),
                "--out",
                str(existing),
            ],
            "目标文件已存在",
        )
    )

    ok = all(results)
    print("\n==== 汇总 ====")
    print(f"失败条件自检：{sum(results)}/{len(results)} 项符合预期 -> {'全部通过' if ok else '有不符合项'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
