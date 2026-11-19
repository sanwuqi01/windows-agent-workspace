"""按原句把五段计划对齐到最终字幕时码。

规则（与任务单一致）：
- **不按总时长五等分**：每段边界来自「该段起句所在字幕卡的开始时刻」；
- **不沿用原素材时间**：只认最终成片字幕（SRT 或剪映草稿字幕轨）；
- 五段必须首尾相接：`第 i 段结束 = 第 i+1 段开始`，第 1 段从 0 开始，第 5 段结束于成片时长；
- 命中多次（重复句）/一条都命中不了（删句/改词）/顺序越界时，**不写盘**，
  而是把候选字幕段列出来等人工确认；确认方式二选一：
    1. 在 chapters.json 该段加 `"resolved": {"start_cue": 12, "end_cue": 15}`（SRT 序号）；
    2. 直接写死 `"start": 3.2, "end": 9.8` 并加 `"confirmed": true`。
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

from .model import Chapter, Plan
from .subtitles import Cue
from .util import fmt_s, norm_for_match

MIN_NGRAM = 5  # 部分匹配时最短可比对长度（少于这个长度就不敢定位）
GAP_WARN = 0.6  # 段末句结束到下一段起点超过这个秒数就给提示（时间已并入上一段）
ORDER_TOL = 0.05


@dataclass
class Locate:
    mode: str  # exact | trimmed_end | trimmed_start | none
    hits: list[int] = field(default_factory=list)
    used: str = ""

    @property
    def ok(self) -> bool:
        return self.mode != "none" and bool(self.hits)


@dataclass
class AlignResult:
    chapters: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    duration: float
    meta: dict[str, Any]

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def times(self) -> list[dict[str, Any]]:
        return self.chapters

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "ok" if self.ok else "needs_review",
            "duration": round(self.duration, 3),
            "chapters": self.chapters,
            "issues": self.issues,
            "warnings": self.warnings,
            "meta": self.meta,
        }


def _find_all(stream: str, sub: str, lo: int, hi: int) -> list[int]:
    if not sub:
        return []
    hits: list[int] = []
    i = stream.find(sub, lo)
    while i >= 0 and i + len(sub) <= hi:
        hits.append(i)
        i = stream.find(sub, i + 1)
    return hits


def locate(stream: str, anchor: str, *, side: str, lo: int, hi: int) -> Locate:
    """在 [lo, hi) 范围内定位整句；不行再按前缀（起句）/后缀（止句）逐字缩短。"""
    target = norm_for_match(anchor)
    if not target:
        return Locate("none")
    hits = _find_all(stream, target, lo, hi)
    if hits:
        return Locate("exact", hits, target)
    max_cut = len(target) - MIN_NGRAM
    for cut in range(1, max_cut + 1):
        sub = target[: len(target) - cut] if side == "start" else target[cut:]
        hits = _find_all(stream, sub, lo, hi)
        if hits:
            return Locate("trimmed_end" if side == "start" else "trimmed_start", hits, sub)
    return Locate("none")


def _candidates(anchor_norm: str, cues: list[Cue], limit: int = 3) -> list[dict[str, Any]]:
    """not_found 时给出最像的字幕卡，供人工挑选。"""
    scored: list[tuple[float, Cue]] = []
    for cue in cues:
        ratio = difflib.SequenceMatcher(None, anchor_norm, norm_for_match(cue.text)).ratio()
        scored.append((ratio, cue))
    scored.sort(key=lambda item: item[0], reverse=True)
    out = []
    for ratio, cue in scored[:limit]:
        out.append(
            {
                "cue": cue.index,
                "start": round(cue.start, 3),
                "end": round(cue.end, 3),
                "text": cue.text,
                "similarity": round(ratio, 3),
            }
        )
    return out


def _cue_candidates(cue_list: list[Cue]) -> list[dict[str, Any]]:
    return [
        {"cue": c.index, "start": round(c.start, 3), "end": round(c.end, 3), "text": c.text}
        for c in cue_list
    ]


def align_plan(
    plan: Plan,
    cues: list[Cue],
    *,
    duration: float | None = None,
    strict: bool = False,
) -> AlignResult:
    """把 plan 的五段对齐到 cues 的时间轴，返回结果（不写盘）。"""
    if not cues:
        raise ValueError("cues 为空")

    total = float(duration) if duration is not None else plan.declared_duration
    if total is None:
        total = cues[-1].end
    if total <= 0:
        raise ValueError("成片时长必须为正")
    if total > cues[-1].end + 0.05:
        # 允许尾部有静音/黑场，但明显超过最后一条字幕就需要提醒
        pass

    stream_parts: list[str] = []
    cue_of: list[int] = []
    for pos, cue in enumerate(cues):
        norm = norm_for_match(cue.text)
        stream_parts.append(norm)
        cue_of.extend([pos] * len(norm))
    stream = "".join(stream_parts)

    cue_by_index = {c.index: pos for pos, c in enumerate(cues)}

    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    raw_chapters: list[dict[str, Any]] = []

    cursor = 0
    prev_anchor_end = 0.0

    for chapter in plan.chapters:
        record: dict[str, Any] = {
            "index": chapter.index,
            "title": chapter.title,
            "start": None,
            "end": None,
            "anchor_start_time": None,
            "anchor_end_time": None,
            "start_cue": None,
            "end_cue": None,
        }
        anchor = chapter.anchor

        # ---- 已显式确认的时间（剪辑改时长/人工钉边界时用）--------------------
        if chapter.start is not None and chapter.end is not None and chapter.confirmed:
            record.update(
                {
                    "start": round(chapter.start, 3),
                    "end": round(chapter.end, 3),
                    "anchor_start_time": round(chapter.start, 3),
                    "anchor_end_time": round(chapter.end, 3),
                    "alignment": {"mode": "confirmed", "note": "chapters.json 显式写死并 confirmed=true"},
                }
            )
            prev_anchor_end = chapter.end
            raw_chapters.append(record)
            continue

        if anchor is None:
            issues.append(
                {
                    "chapter": chapter.index,
                    "kind": "missing_anchor",
                    "message": f"第 {chapter.index} 段既没有 anchor 也没有 confirmed 时码",
                    "candidates": [],
                }
            )
            raw_chapters.append(record)
            continue

        start_anchor_norm = norm_for_match(anchor.start_sentence)
        end_anchor_norm = norm_for_match(anchor.end_sentence)

        # ---- 起句 -----------------------------------------------------------
        start_hit: int | None = None
        used_resolved = False
        if chapter.resolved and isinstance(chapter.resolved.get("start_cue"), int):
            cue_idx = chapter.resolved["start_cue"]
            if cue_idx not in cue_by_index:
                issues.append(
                    {
                        "chapter": chapter.index,
                        "kind": "bad_override",
                        "message": f"resolved.start_cue={cue_idx} 不在字幕里（共 {len(cues)} 条）",
                        "candidates": _cue_candidates(cues[:5]),
                    }
                )
            else:
                pos = cue_by_index[cue_idx]
                start_hit = sum(len(p) for p in stream_parts[:pos])
                record["alignment"] = {"start": {"mode": "resolved_cue", "cue": cue_idx}}
                used_resolved = True

        if start_hit is None and not used_resolved:
            loc = locate(stream, start_anchor_norm, side="start", lo=cursor, hi=len(stream))
            if not loc.ok:
                issues.append(
                    {
                        "chapter": chapter.index,
                        "kind": "not_found",
                        "message": (
                            f"第 {chapter.index} 段起句在最终字幕里找不到：「{anchor.start_sentence}」"
                            "（删句或改词？请确认后写 resolved.start_cue 或 confirmed 时码）"
                        ),
                        "candidates": _candidates(start_anchor_norm, cues),
                    }
                )
                raw_chapters.append(record)
                continue
            if len(loc.hits) > 1:
                cand_cues = [cues[cue_of[h]] for h in loc.hits]
                issues.append(
                    {
                        "chapter": chapter.index,
                        "kind": "ambiguous",
                        "message": (
                            f"第 {chapter.index} 段起句在字幕里命中 {len(loc.hits)} 次，"
                            f"无法确定边界：「{anchor.start_sentence}」"
                        ),
                        "candidates": _cue_candidates(cand_cues),
                    }
                )
                raw_chapters.append(record)
                continue
            start_hit = loc.hits[0]
            record["alignment"] = {"start": {"mode": loc.mode, "used": loc.used}}
            if loc.mode != "exact":
                warnings.append(
                    {
                        "chapter": chapter.index,
                        "kind": "fuzzy_start",
                        "message": (
                            f"第 {chapter.index} 段起句只部分匹配到字幕（用「{loc.used}」定位，"
                            f"原文：「{anchor.start_sentence}」）"
                        ),
                    }
                )

        start_cue_pos = cue_of[start_hit]
        start_time = cues[start_cue_pos].start
        record["start_cue"] = cues[start_cue_pos].index
        record["anchor_start_time"] = round(start_time, 3)

        # ---- 止句 -----------------------------------------------------------
        end_hit: int | None = None
        end_len = len(end_anchor_norm)
        if chapter.resolved and isinstance(chapter.resolved.get("end_cue"), int):
            cue_idx = chapter.resolved["end_cue"]
            if cue_idx not in cue_by_index:
                issues.append(
                    {
                        "chapter": chapter.index,
                        "kind": "bad_override",
                        "message": f"resolved.end_cue={cue_idx} 不在字幕里（共 {len(cues)} 条）",
                        "candidates": _cue_candidates(cues[:5]),
                    }
                )
                raw_chapters.append(record)
                continue
            pos = cue_by_index[cue_idx]
            end_hit = sum(len(p) for p in stream_parts[: pos + 1]) - 1
            end_len = 1
            record.setdefault("alignment", {})["end"] = {"mode": "resolved_cue", "cue": cue_idx}

        if end_hit is None:
            loc = locate(stream, end_anchor_norm, side="end", lo=start_hit, hi=len(stream))
            if not loc.ok:
                issues.append(
                    {
                        "chapter": chapter.index,
                        "kind": "not_found",
                        "message": (
                            f"第 {chapter.index} 段止句在最终字幕里找不到：「{anchor.end_sentence}」"
                            "（删句或改词？请确认后写 resolved.end_cue 或 confirmed 时码）"
                        ),
                        "candidates": _candidates(end_anchor_norm, cues),
                    }
                )
                raw_chapters.append(record)
                continue
            if len(loc.hits) > 1:
                cand_cues = [cues[cue_of[h]] for h in loc.hits]
                issues.append(
                    {
                        "chapter": chapter.index,
                        "kind": "ambiguous",
                        "message": (
                            f"第 {chapter.index} 段止句在字幕里命中 {len(loc.hits)} 次，"
                            f"无法确定边界：「{anchor.end_sentence}」"
                        ),
                        "candidates": _cue_candidates(cand_cues),
                    }
                )
                raw_chapters.append(record)
                continue
            end_hit = loc.hits[0]
            end_len = len(loc.used)
            record.setdefault("alignment", {})["end"] = {"mode": loc.mode, "used": loc.used}
            if loc.mode != "exact":
                warnings.append(
                    {
                        "chapter": chapter.index,
                        "kind": "fuzzy_end",
                        "message": (
                            f"第 {chapter.index} 段止句只部分匹配到字幕（用「{loc.used}」定位，"
                            f"原文：「{anchor.end_sentence}」）"
                        ),
                    }
                )

        end_char = end_hit + end_len - 1
        end_cue_pos = cue_of[min(end_char, len(cue_of) - 1)]
        end_time = cues[end_cue_pos].end
        record["end_cue"] = cues[end_cue_pos].index
        record["anchor_end_time"] = round(end_time, 3)

        if end_time <= start_time:
            issues.append(
                {
                    "chapter": chapter.index,
                    "kind": "order",
                    "message": (
                        f"第 {chapter.index} 段止句 {fmt_s(end_time)}s 不晚于起句 {fmt_s(start_time)}s"
                    ),
                    "candidates": _cue_candidates(cues[start_cue_pos : end_cue_pos + 2]),
                }
            )
            raw_chapters.append(record)
            continue
        if start_time < prev_anchor_end - ORDER_TOL:
            issues.append(
                {
                    "chapter": chapter.index,
                    "kind": "order",
                    "message": (
                        f"第 {chapter.index} 段起点 {fmt_s(start_time)}s 早于上一段末句 "
                        f"{fmt_s(prev_anchor_end)}s，段落顺序与字幕不一致"
                    ),
                    "candidates": _cue_candidates(cues[start_cue_pos : start_cue_pos + 2]),
                }
            )
            raw_chapters.append(record)
            continue

        prev_anchor_end = end_time
        cursor = end_char + 1
        raw_chapters.append(record)

    # ---- 连续化：第 i 段结束 = 第 i+1 段开始 -------------------------------
    if not issues:
        starts = [0.0] + [float(r["anchor_start_time"]) for r in raw_chapters[1:]]
        bounds = starts + [total]
        for i, record in enumerate(raw_chapters):
            record["start"] = round(bounds[i], 3)
            record["end"] = round(bounds[i + 1], 3)
            anchor_end = float(record["anchor_end_time"])
            if i < len(raw_chapters) - 1 and anchor_end > bounds[i + 1] + ORDER_TOL:
                issues.append(
                    {
                        "chapter": record["index"],
                        "kind": "overlap",
                        "message": (
                            f"第 {record['index']} 段末句结束于 {fmt_s(anchor_end)}s，"
                            f"晚于下一段起点 {fmt_s(bounds[i + 1])}s，两段重叠"
                        ),
                        "candidates": [],
                    }
                )
            gap = bounds[i + 1] - anchor_end
            if gap > GAP_WARN:
                warnings.append(
                    {
                        "chapter": record["index"],
                        "kind": "gap",
                        "message": (
                            f"第 {record['index']} 段末句 {fmt_s(anchor_end)}s 到本段结束 "
                            f"{fmt_s(bounds[i + 1])}s 有 {fmt_s(gap)}s 间隔，已并入本段填充"
                        ),
                    }
                )
        first_start = float(raw_chapters[0]["anchor_start_time"])
        if first_start > ORDER_TOL:
            warnings.append(
                {
                    "chapter": 1,
                    "kind": "lead_in",
                    "message": (
                        f"第 1 段首句起于 {fmt_s(first_start)}s，前面 {fmt_s(first_start)}s "
                        "（片头/开场）已并入第 1 段"
                    ),
                }
            )
        last_end = float(raw_chapters[-1]["anchor_end_time"])
        if total - last_end > ORDER_TOL:
            warnings.append(
                {
                    "chapter": len(raw_chapters),
                    "kind": "tail",
                    "message": (
                        f"第 5 段末句止于 {fmt_s(last_end)}s，到成片结束 {fmt_s(total)}s 的 "
                        f"{fmt_s(total - last_end)}s 已并入第 5 段（保证末帧全满）"
                    ),
                }
            )

    if strict:
        upgraded = [w for w in warnings if w["kind"] in ("fuzzy_start", "fuzzy_end")]
        if upgraded:
            issues.extend({**w, "kind": "strict_" + w["kind"]} for w in upgraded)

    meta = {
        "cue_count": len(cues),
        "cue_duration": round(cues[-1].end, 3),
        "duration": round(total, 3),
        "strict": strict,
        "summary": {
            "exact": sum(
                1
                for r in raw_chapters
                if (r.get("alignment", {}).get("start", {}).get("mode") == "exact")
                and (r.get("alignment", {}).get("end", {}).get("mode") == "exact")
            ),
            "chapters": len(raw_chapters),
        },
    }
    return AlignResult(chapters=raw_chapters, issues=issues, warnings=warnings, duration=total, meta=meta)


def format_report(result: AlignResult) -> str:
    """人读报告。"""
    lines: list[str] = []
    lines.append(f"成片时长 {fmt_s(result.duration)}s；字幕 {result.meta['cue_count']} 条，"
                 f"末条止于 {fmt_s(result.meta['cue_duration'])}s")
    lines.append("")
    lines.append("段 | 标题 | 起(s) | 止(s) | 时长(s) | 起卡 | 止卡 | 锚点")
    for record in result.chapters:
        alignment = record.get("alignment") or {}
        start_mode = (alignment.get("start") or {}).get("mode", "-")
        end_mode = (alignment.get("end") or {}).get("mode", "-")
        start = "-" if record["start"] is None else fmt_s(record["start"])
        end = "-" if record["end"] is None else fmt_s(record["end"])
        dur = "-"
        if record["start"] is not None and record["end"] is not None:
            dur = fmt_s(record["end"] - record["start"])
        lines.append(
            f"{record['index']} | {record['title']} | {start} | {end} | {dur} | "
            f"{record['start_cue']} | {record['end_cue']} | {start_mode}/{end_mode}"
        )
    if result.warnings:
        lines.append("")
        lines.append("提示：")
        lines.extend(f"  - {w['message']}" for w in result.warnings)
    if result.issues:
        lines.append("")
        lines.append("待复核（未写盘）：")
        for issue in result.issues:
            lines.append(f"  [{issue['kind']}] {issue['message']}")
            for cand in issue.get("candidates") or []:
                sim = f"，相似度 {cand['similarity']}" if "similarity" in cand else ""
                lines.append(
                    f"      cue {cand['cue']}  {fmt_s(cand['start'])} → {fmt_s(cand['end'])}s"
                    f"{sim}  {cand['text']}"
                )
    return "\n".join(lines)
