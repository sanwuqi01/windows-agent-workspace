"""五段梗概的语义质量校验（复用 video-subtitle-outline 的口径）。

**这里刻意不生成任何标题**：语义提炼由 Agent 读完整文案完成；工具只做「不许偷懒」的
校验，把固定模板、占位符、凑字数、编造原文的写法挡在门外：

- 恰好五段，段序与播放顺序一致（由 chapters.json 的 index 保证）；
- 每段标题 ≤ 8 字、互不相同、不是「第一段 / 标题1 / 待定」这类占位；
- 每段必须保存原文起止句，且**起止句必须真的出现在打标文案原文里**（归一化后子串匹配），
  杜绝「用固定模板硬凑」；
- 五段合起来要覆盖原文的主体区间，且顺序递增、不重叠。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .util import norm_for_match

MAX_TITLE_CHARS = 8
CHAPTER_COUNT = 5

# 占位/模板标题：命中即判不合格
PLACEHOLDER_PATTERNS = (
    re.compile(r"^第[一二三四五六七八九十\d]{1,3}[段章节部分]$"),
    re.compile(r"^段[一二三四五六七八九十\d]{1,2}$"),
    re.compile(r"^(标题|title|字幕?条?|chapter|seg(ment)?)\s*[一二三四五六七八九十\d]*$", re.I),
    re.compile(r"^(待定|待补|待填|占位|空|无|todo|tbd|na|n/?a)$", re.I),
    re.compile(r"^(x{2,}|×{2,}|\?{2,}|\.{3,}|…+)$"),
    re.compile(r"^[一二三四五]?[、.．]?\s*同上?$"),
    re.compile(r"^(内容|正文|文案)\s*[一二三四五\d]*$"),
)


def title_problems(title: str, *, max_chars: int = MAX_TITLE_CHARS) -> list[str]:
    """单段标题的问题列表（空列表表示合格）。"""
    problems: list[str] = []
    if not isinstance(title, str):
        return ["标题必须是字符串"]
    text = title.strip()
    if not text:
        return ["标题为空"]
    if len(text) > max_chars:
        problems.append(f"标题「{text}」{len(text)} 字，超过 {max_chars} 字上限")
    for pattern in PLACEHOLDER_PATTERNS:
        if pattern.match(text):
            problems.append(f"标题「{text}」像占位/模板标题，请按内容重新提炼")
            break
    if re.search(r"[。！？!?，,、；;：:\n\t]", text):
        problems.append(f"标题「{text}」含句读标点，五段梗概应为短句")
    return problems


def duplicate_problems(titles: list[str]) -> list[str]:
    """标题重复检查。"""
    seen: dict[str, int] = {}
    problems: list[str] = []
    for i, t in enumerate(titles, start=1):
        key = norm_for_match(t)
        if not key:
            continue
        if key in seen:
            problems.append(f"第 {seen[key]} 段与第 {i} 段标题重复：「{t}」")
        else:
            seen[key] = i
    return problems


def uniformity_problems(titles: list[str]) -> list[str]:
    """整批标题若首字全同或字数全同，多半是模板硬凑，给出提示。"""
    problems: list[str] = []
    stripped = [t.strip() for t in titles if t.strip()]
    if len(stripped) < CHAPTER_COUNT:
        return problems
    if len({t[0] for t in stripped}) == 1:
        problems.append("五段标题首字全相同，疑似模板化，请按各段内容分别提炼")
    if len({len(t) for t in stripped}) == 1 and len(stripped[0]) <= 3:
        problems.append("五段标题字数全相同且极短，疑似凑数，请按内容分别提炼")
    return problems


@dataclass
class AnchorReport:
    """一段锚点在原文中的落位情况。"""

    index: int
    start_sentence: str
    end_sentence: str
    start_ok: bool
    end_ok: bool
    start_char: int
    end_char: int
    problems: list[str]


@dataclass
class OutlineReport:
    anchors: list[AnchorReport]
    coverage: dict[str, float]
    problems: list[str]

    @property
    def ok(self) -> bool:
        return not self.problems


def verify_anchors(plan, transcript: str) -> OutlineReport:
    """检查每段起止句是否真的出现在原文里，并给出覆盖度。

    `plan` 为 model.Plan。原文归一化后逐段查找；顺序必须递增且不重叠，否则说明
    段落划分和原文顺序对不上。
    """
    text = norm_for_match(transcript)
    anchors: list[AnchorReport] = []
    problems: list[str] = []
    cursor = 0
    spans: list[tuple[int, int]] = []

    for chapter in plan.chapters:
        anchor = chapter.anchor
        if anchor is None:
            problems.append(f"第 {chapter.index} 段缺少 anchor.start_sentence / end_sentence")
            continue
        start_norm = norm_for_match(anchor.start_sentence)
        end_norm = norm_for_match(anchor.end_sentence)
        item_problems: list[str] = []

        if len(start_norm) < 4:
            item_problems.append(f"第 {chapter.index} 段起句过短（{len(start_norm)} 字），无法唯一定位")

        start_at = text.find(start_norm, cursor) if start_norm else -1
        if start_at < 0 and start_norm:
            anywhere = text.find(start_norm)
            if anywhere >= 0:
                item_problems.append(
                    f"第 {chapter.index} 段起句出现在原文 {anywhere} 处，但早于上一段末尾（顺序错乱）"
                )
            else:
                item_problems.append(f"第 {chapter.index} 段起句未出现在原文里：「{anchor.start_sentence}」")

        end_at = -1
        if end_norm and start_at >= 0:
            end_at = text.find(end_norm, start_at)
            if end_at < 0:
                item_problems.append(f"第 {chapter.index} 段止句未出现在原文该段范围内：「{anchor.end_sentence}」")
            elif end_at < start_at:
                item_problems.append(f"第 {chapter.index} 段止句早于起句，顺序反了")

        if start_at >= 0 and end_at >= 0:
            spans.append((start_at, end_at + len(end_norm)))
            cursor = end_at + len(end_norm)

        anchors.append(
            AnchorReport(
                index=chapter.index,
                start_sentence=anchor.start_sentence,
                end_sentence=anchor.end_sentence,
                start_ok=start_at >= 0,
                end_ok=end_at >= 0,
                start_char=start_at,
                end_char=end_at,
                problems=item_problems,
            )
        )
        problems.extend(item_problems)

    coverage: dict[str, float] = {}
    total = len(text) or 1
    for report in anchors:
        if report.start_char >= 0 and report.end_char >= 0:
            span = report.end_char - report.start_char
            coverage[f"第{report.index}段"] = round(span / total, 3)
    if spans and text:
        gaps = []
        prev_end = 0
        for start, end in spans:
            if start > prev_end:
                gaps.append(start - prev_end)
            prev_end = max(prev_end, end)
        trailing = len(text) - prev_end
        if trailing > 0:
            gaps.append(trailing)
        uncovered = sum(gaps) / total
        if uncovered > 0.45:
            problems.append(
                f"五段起止句只覆盖原文 {1 - uncovered:.0%}，缺口 {uncovered:.0%}，请检查是否漏段"
            )
        for report in anchors:
            ratio = coverage.get(f"第{report.index}段")
            if ratio is not None and ratio < 0.03:
                problems.append(f"第 {report.index} 段只覆盖原文 {ratio:.1%}，段落划分可能过短")
            if ratio is not None and ratio > 0.60:
                problems.append(f"第 {report.index} 段覆盖原文 {ratio:.1%}，段落划分可能过粗")

    return OutlineReport(anchors=anchors, coverage=coverage, problems=problems)
