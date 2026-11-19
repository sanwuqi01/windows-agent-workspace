"""字幕时码来源：SRT 解析/生成 + 剪映草稿 draft_content.json 字幕轨抽取。

对齐的输入只能是「最终成片的字幕时码」，所以这里额外提供草稿抽取：
剪映草稿里基础字幕轨的每个文字段都带 target_timerange（微秒），
这正是最终成片的时间轴，比原素材时码可靠。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError

_TS = re.compile(r"(?P<h>\d{1,3}):(?P<m>\d{1,2}):(?P<s>\d{1,2})[,.](?P<ms>\d{1,3})")
_US = 1_000_000.0


@dataclass(frozen=True)
class Cue:
    index: int
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return self.end - self.start


def parse_timestamp(token: str) -> float:
    m = _TS.search(token)
    if not m:
        raise ConfigError(f"无法解析时间码：{token!r}（应形如 00:00:01,500）")
    ms = m.group("ms")
    # 兼容两位毫秒写法 00:00:01,50
    ms_value = int(ms) * (10 ** (3 - len(ms)))
    return (
        int(m.group("h")) * 3600
        + int(m.group("m")) * 60
        + int(m.group("s"))
        + ms_value / 1000.0
    )


def format_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(content: str) -> list[Cue]:
    """解析 SRT。容忍 BOM、CRLF、多余空行、缺序号。"""
    text = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("\ufeff"):
        text = text[1:]
    blocks = re.split(r"\n\s*\n", text.strip())
    cues: list[Cue] = []
    for block in blocks:
        lines = block.split("\n")
        if not any("-->" in ln for ln in lines):
            continue
        pos = next(i for i, ln in enumerate(lines) if "-->" in ln)
        index = len(cues) + 1
        if pos > 0 and lines[0].strip().isdigit():
            index = int(lines[0].strip())
        left, right = lines[pos].split("-->", 1)
        start = parse_timestamp(left)
        end = parse_timestamp(right)
        body = "\n".join(lines[pos + 1 :]).strip()
        if end < start:
            raise ConfigError(f"第 {index} 条字幕结束早于开始：{left.strip()} --> {right.strip()}")
        cues.append(Cue(index=index, start=start, end=end, text=body))
    if not cues:
        raise ConfigError("SRT 里没有解析到任何字幕条目（检查是否用了 -->{ } 时间行）")
    for prev, cur in zip(cues, cues[1:]):
        if cur.start < prev.start - 1e-6:
            raise ConfigError(f"第 {cur.index} 条字幕开始时间早于上一条，SRT 未按时间排序")
    return cues


def format_srt(cues: list[Cue]) -> str:
    lines: list[str] = []
    for i, cue in enumerate(cues, start=1):
        lines.append(str(i))
        lines.append(f"{format_timestamp(cue.start)} --> {format_timestamp(cue.end)}")
        lines.append(cue.text)
        lines.append("")
    return "\n".join(lines)


def load_srt(path: str | Path) -> list[Cue]:
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"字幕文件不存在：{p}")
    return parse_srt(p.read_text(encoding="utf-8-sig"))


def _text_from_material(material: dict) -> str:
    """剪映文字素材的正文可能直接是字符串，也可能是含 text 字段的 JSON 串。"""
    content = material.get("content")
    if isinstance(content, str):
        stripped = content.strip()
        if stripped.startswith("{"):
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError:
                return stripped
            if isinstance(data, dict):
                for key in ("text", "content"):
                    value = data.get(key)
                    if isinstance(value, str):
                        return value
                return ""
            return stripped
        return stripped
    if isinstance(content, dict):
        value = content.get("text")
        return value if isinstance(value, str) else ""
    return ""


def cues_from_draft(
    path: str | Path,
    *,
    track_index: int | None = None,
    max_duration: float | None = None,
) -> tuple[list[Cue], dict]:
    """从剪映草稿 draft_content.json 抽取最终字幕轨，返回 (cues, meta)。

    取「段数最多的文字轨」作为基础字幕（重点词轨段数少，且可能把字从基础字幕里去掉）；
    也可用 track_index 显式指定文字轨序号（0 基，只数文字轨）。
    """
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"草稿文件不存在：{p}")
    head = p.read_bytes()[:16]
    if not head.lstrip().startswith(b"{"):
        raise ConfigError(
            f"草稿可能已被剪映加密（文件头不是 '{{'）：{p}\n"
            "请在剪映里先关闭该草稿，或改用源 overlay 草稿，不要把加密文件当 JSON 读"
        )
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"草稿 JSON 解析失败：{p}（{exc}）") from exc

    materials = (data.get("materials") or {}).get("texts") or []
    texts = {m.get("id"): m for m in materials if isinstance(m, dict)}
    text_tracks = [t for t in (data.get("tracks") or []) if t.get("type") == "text"]
    if not text_tracks:
        raise ConfigError("草稿里没有文字轨（tracks[].type == 'text'）")

    if track_index is None:
        track_no = max(range(len(text_tracks)), key=lambda i: len(text_tracks[i].get("segments") or []))
    else:
        if not 0 <= track_index < len(text_tracks):
            raise ConfigError(f"track_index={track_index} 越界，草稿里只有 {len(text_tracks)} 条文字轨")
        track_no = track_index
    track = text_tracks[track_no]

    cues: list[Cue] = []
    for segment in track.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        tr = segment.get("target_timerange") or {}
        try:
            start = float(tr.get("start", 0)) / _US
            duration = float(tr.get("duration", 0)) / _US
        except (TypeError, ValueError):
            continue
        body = _text_from_material(texts.get(segment.get("material_id"), {})).strip()
        if not body:
            continue
        end = start + duration
        if end <= start:
            continue
        cues.append(Cue(index=len(cues) + 1, start=round(start, 3), end=round(end, 3), text=body))

    cues.sort(key=lambda c: c.start)
    notes: list[str] = []
    if max_duration is not None:
        kept: list[Cue] = []
        for cue in cues:
            if cue.start >= max_duration - 1e-6:
                continue
            if cue.end > max_duration:
                notes.append(
                    f"第 {cue.index} 条字幕跨过截断点，已裁剪到 {max_duration:.3f}s：{cue.text[:20]}"
                )
                cue = Cue(index=cue.index, start=cue.start, end=max_duration, text=cue.text)
            kept.append(cue)
        cues = kept
    cues = [Cue(index=i, start=c.start, end=c.end, text=c.text) for i, c in enumerate(cues, start=1)]
    if not cues:
        raise ConfigError("草稿字幕轨里没有可用的非空字幕段")

    meta = {
        "draft": str(p),
        "draft_name": data.get("name"),
        "text_track_count": len(text_tracks),
        "track_index": track_no,
        "cue_count": len(cues),
        "duration": round(cues[-1].end, 3),
        "notes": notes,
    }
    return cues, meta
