"""chapters.json：五段内容 + 时码的加载与结构校验。

chapters.json 只放「内容与时码」，样式一律在 style.json；两者互不影响——
因此只改样式不需要重新对齐，改了成片时长才需要重跑 align 再渲染。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import outline
from .errors import ConfigError

SCHEMA_VERSION = 1
TIME_TOLERANCE = 1e-3  # 秒；时码比较容差（三位小数）


@dataclass
class Anchor:
    start_sentence: str
    end_sentence: str


@dataclass
class Chapter:
    index: int
    title: str
    anchor: Anchor | None = None
    start: float | None = None
    end: float | None = None
    resolved: dict[str, Any] | None = None
    confirmed: bool = False
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def duration(self) -> float | None:
        if self.start is None or self.end is None:
            return None
        return self.end - self.start


@dataclass
class Plan:
    path: Path
    title: str
    source: dict[str, Any]
    chapters: list[Chapter]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    # ---- 路径与时长 -----------------------------------------------------
    def _source_path(self, key: str) -> Path | None:
        value = self.source.get(key)
        if not value:
            return None
        p = Path(str(value))
        if not p.is_absolute():
            p = self.path.parent / p
        return p

    @property
    def transcript_path(self) -> Path | None:
        return self._source_path("transcript")

    @property
    def subtitle_path(self) -> Path | None:
        return self._source_path("subtitle")

    @property
    def declared_duration(self) -> float | None:
        value = self.source.get("duration")
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"chapters.source.duration 必须是数字，当前 {value!r}")
        return float(value)

    @property
    def has_times(self) -> bool:
        return all(c.start is not None and c.end is not None for c in self.chapters)


def _as_float(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{field_name} 必须是数字（秒），当前 {value!r}")
    return float(value)


def load_plan(path: str | Path) -> Plan:
    """读取 chapters.json（只解析结构，不做语义校验）。"""
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"chapters 文件不存在：{p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"chapters 文件不是合法 JSON：{p}（{exc}）") from exc
    if not isinstance(raw, dict):
        raise ConfigError("chapters.json 顶层必须是对象")

    schema = raw.get("schema_version", SCHEMA_VERSION)
    if schema != SCHEMA_VERSION:
        raise ConfigError(f"chapters.schema_version 只支持 {SCHEMA_VERSION}，当前 {schema!r}")

    chapters_raw = raw.get("chapters")
    if not isinstance(chapters_raw, list):
        raise ConfigError("chapters.chapters 必须是数组")

    chapters: list[Chapter] = []
    for pos, item in enumerate(chapters_raw, start=1):
        if not isinstance(item, dict):
            raise ConfigError(f"chapters.chapters[{pos}] 必须是对象")
        index = item.get("index", pos)
        if isinstance(index, bool) or not isinstance(index, int):
            raise ConfigError(f"chapters.chapters[{pos}].index 必须是整数，当前 {index!r}")
        anchor_raw = item.get("anchor")
        anchor = None
        if anchor_raw is not None:
            if not isinstance(anchor_raw, dict):
                raise ConfigError(f"chapters.chapters[{pos}].anchor 必须是对象")
            anchor = Anchor(
                start_sentence=str(anchor_raw.get("start_sentence") or "").strip(),
                end_sentence=str(anchor_raw.get("end_sentence") or "").strip(),
            )
        chapters.append(
            Chapter(
                index=index,
                title=str(item.get("title") or "").strip(),
                anchor=anchor,
                start=_as_float(item.get("start"), f"chapters.chapters[{pos}].start"),
                end=_as_float(item.get("end"), f"chapters.chapters[{pos}].end"),
                resolved=item.get("resolved") if isinstance(item.get("resolved"), dict) else None,
                confirmed=bool(item.get("confirmed", False)),
                raw=dict(item),
            )
        )

    source = raw.get("source")
    if source is not None and not isinstance(source, dict):
        raise ConfigError("chapters.source 必须是对象")

    return Plan(
        path=p,
        title=str(raw.get("title") or "").strip(),
        source=dict(source or {}),
        chapters=chapters,
        raw=raw,
    )


def validate_plan(plan: Plan, *, require_times: bool) -> Plan:
    """结构校验。所有问题一次性列出，方便一次改完。

    require_times=True 时要求五段都有 start/end 且严格连续（render 用）；
    require_times=False 时允许只有 anchor（align 用）。
    """
    problems: list[str] = []
    chapters = plan.chapters

    if len(chapters) != outline.CHAPTER_COUNT:
        problems.append(
            f"必须恰好 {outline.CHAPTER_COUNT} 段，当前 {len(chapters)} 段"
            "（五段梗概口径来自 video-subtitle-outline，不做 4 段/6 段变体）"
        )

    expected_index = list(range(1, len(chapters) + 1))
    if [c.index for c in chapters] != expected_index:
        problems.append(f"index 必须按 1..{len(chapters)} 顺序排列，当前 {[c.index for c in chapters]}")

    for chapter in chapters:
        for msg in outline.title_problems(chapter.title):
            problems.append(f"第 {chapter.index} 段：{msg}")
        if chapter.anchor is None and not chapter.confirmed:
            problems.append(
                f"第 {chapter.index} 段缺少 anchor.start_sentence / end_sentence"
                "（必须保存原文起止句，或用 confirmed=true 显式确认边界）"
            )
        elif chapter.anchor is not None:
            if not chapter.anchor.start_sentence:
                problems.append(f"第 {chapter.index} 段 anchor.start_sentence 为空")
            if not chapter.anchor.end_sentence:
                problems.append(f"第 {chapter.index} 段 anchor.end_sentence 为空")

    problems.extend(outline.duplicate_problems([c.title for c in chapters]))
    problems.extend(outline.uniformity_problems([c.title for c in chapters]))

    if require_times:
        missing = [c.index for c in chapters if c.start is None or c.end is None]
        if missing:
            problems.append(
                f"第 {missing} 段缺少 start/end；请先跑 align 生成时码（改样式不需要重新对齐）"
            )
    else:
        partial = [c.index for c in chapters if (c.start is None) != (c.end is None)]
        if partial:
            problems.append(f"第 {partial} 段 start/end 只给了一个，必须成对出现")

    if all(c.start is not None and c.end is not None for c in chapters):
        problems.extend(_time_problems(plan))

    if problems:
        raise ConfigError("chapters.json 校验失败：\n- " + "\n- ".join(problems))
    return plan


def _time_problems(plan: Plan) -> list[str]:
    problems: list[str] = []
    chapters = plan.chapters
    for chapter in chapters:
        assert chapter.start is not None and chapter.end is not None
        if chapter.end - chapter.start <= 0:
            problems.append(
                f"第 {chapter.index} 段时长非正（{chapter.start:.3f} → {chapter.end:.3f}）"
            )
    if chapters:
        if abs(chapters[0].start) > TIME_TOLERANCE:
            problems.append(f"第 1 段必须从 0 开始，当前 {chapters[0].start:.3f}")
        for prev, cur in zip(chapters, chapters[1:]):
            assert prev.end is not None and cur.start is not None
            if abs(prev.end - cur.start) > TIME_TOLERANCE:
                problems.append(
                    f"第 {prev.index} 段结束 {prev.end:.3f} 与第 {cur.index} 段开始 "
                    f"{cur.start:.3f} 不连续（五段必须首尾相接）"
                )
    duration = plan.declared_duration
    if duration is not None and chapters:
        last_end = chapters[-1].end or 0.0
        if abs(last_end - duration) > TIME_TOLERANCE:
            problems.append(
                f"第 5 段结束 {last_end:.3f} 与成片时长 {duration:.3f} 不一致；"
                "剪辑改时长后必须重新 align 再渲染"
            )
    return problems


def times_summary(plan: Plan) -> list[dict[str, Any]]:
    return [
        {
            "index": c.index,
            "title": c.title,
            "start": round(c.start, 3) if c.start is not None else None,
            "end": round(c.end, 3) if c.end is not None else None,
            "duration": round(c.duration, 3) if c.duration is not None else None,
        }
        for c in plan.chapters
    ]


def apply_times(plan: Plan, times: list[dict[str, Any]]) -> Plan:
    """把对齐结果写回 Plan（内存），并把时码与对齐信息同步进 raw，供落盘。"""
    raw_chapters = plan.raw.get("chapters")
    assert isinstance(raw_chapters, list)
    for chapter, item in zip(plan.chapters, times):
        chapter.start = round(float(item["start"]), 3)
        chapter.end = round(float(item["end"]), 3)
        chapter.raw["start"] = chapter.start
        chapter.raw["end"] = chapter.end
        if "alignment" in item:
            chapter.raw["alignment"] = item["alignment"]
        for pos, raw_item in enumerate(raw_chapters):
            if isinstance(raw_item, dict) and raw_item.get("index", pos + 1) == chapter.index:
                raw_item.update(chapter.raw)
                break
    return plan


def save_plan(plan: Plan, path: str | Path | None = None) -> Path:
    """把 Plan（含时码）写回 chapters.json；写入前不覆盖别的文件。"""
    target = Path(path) if path else plan.path
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(plan.raw, ensure_ascii=False, indent=2) + "\n"
    target.write_text(text, encoding="utf-8")
    return target


def read_transcript(path: Path) -> str:
    """只读读取打标文案（md/txt）。业务文件一律不改。"""
    if not path.is_file():
        raise ConfigError(f"原文文件不存在：{path}")
    return path.read_text(encoding="utf-8-sig")
