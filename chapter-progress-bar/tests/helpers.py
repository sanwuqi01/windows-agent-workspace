"""测试公共工具：临时 chapters/style 构造与断言辅助。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEMO_DIR = ROOT / "examples" / "demo16s"
FONT_PATH = "C:/Windows/Fonts/msyh.ttc"

DEFAULT_TITLES = ["早餐怎么吃", "蛋白质先吃", "主食粗细搭", "两个常见误区", "三句话记住"]
DEFAULT_ANCHORS = [
    ("早餐到底该怎么吃", "今天一次讲清"),
    ("第一件事是蛋白质", "鸡蛋牛奶都算"),
    ("第二步看主食", "别只吃白粥配咸菜"),
    ("误区一是空腹喝咖啡", "把水果当正餐"),
    ("记住这三句", "早餐就不难"),
]
DEFAULT_TIMES = [(0.0, 2.0), (2.0, 6.0), (6.0, 9.0), (9.0, 14.0), (14.0, 16.0)]


def chapters_payload(
    *,
    titles: list[str] | None = None,
    anchors: list[tuple[str, str]] | None = None,
    times: list[tuple[float, float]] | None = None,
    duration: float | None = 16.0,
    extra: dict | None = None,
) -> dict:
    titles = titles if titles is not None else DEFAULT_TITLES
    anchors = anchors if anchors is not None else [
        DEFAULT_ANCHORS[i % len(DEFAULT_ANCHORS)] for i in range(len(titles))
    ]
    times = times if times is not None else DEFAULT_TIMES[: len(titles)]
    chapters = []
    for i, title in enumerate(titles, start=1):
        item: dict = {
            "index": i,
            "title": title,
            "anchor": {"start_sentence": anchors[i - 1][0], "end_sentence": anchors[i - 1][1]},
        }
        if times is not None and i - 1 < len(times):
            item["start"] = times[i - 1][0]
            item["end"] = times[i - 1][1]
        chapters.append(item)
    payload = {
        "schema_version": 1,
        "title": "测试用",
        "source": {"duration": duration} if duration is not None else {},
        "chapters": chapters,
    }
    if extra:
        payload.update(extra)
    return payload


def style_payload(**overrides) -> dict:
    data = {
        "width": 1080,
        "height": 112,
        "fps": 30,
        "background": "#FFFFFF",
        "cell": "#FFFFFF",
        "progress": "#1E6FFF",
        "text": "#1B1B1B",
        "stroke": "#FFFFFF",
        "font": {"path": FONT_PATH},
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
    data.update(overrides)
    return data


def write_json(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
