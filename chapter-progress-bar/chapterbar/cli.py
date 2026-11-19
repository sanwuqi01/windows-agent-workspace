"""一条命令入口：check / align / render / preview / srt-from-draft / demo。

命令行示例见 README.md；Agent 侧的语义工作流程见 AGENT.md。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import align as align_mod
from . import mp4, outline
from .errors import ChapterBarError, ConfigError, NeedsReview
from .model import (
    apply_times,
    load_plan,
    read_transcript,
    save_plan,
    times_summary,
    validate_plan,
)
from .render import BarRenderer, layout_title, load_font, missing_glyphs
from .style import load_style
from .subtitles import cues_from_draft, format_srt, load_srt
from .util import fmt_s

EXIT_OK = 0


def _print_plan_times(plan) -> None:
    for row in times_summary(plan):
        print(f"  {row['index']}  {row['title']}  {row['start']:.3f} → {row['end']:.3f}s")


# --------------------------------------------------------------------------
def cmd_check(args: argparse.Namespace) -> int:
    style = load_style(args.style) if args.style else None
    plan = validate_plan(load_plan(args.chapters), require_times=args.require_times)

    print(f"chapters：{plan.path}")
    print(f"  五段：{' / '.join(c.title for c in plan.chapters)}")
    print(f"  标题字数：{[len(c.title) for c in plan.chapters]}（上限 {outline.MAX_TITLE_CHARS}）")
    if plan.has_times:
        print("  时码：")
        _print_plan_times(plan)
    else:
        print("  时码：尚未生成（先跑 align）")

    if style:
        print(f"style：{style.source_path}")
        print(
            f"  {style.width}x{style.height} @{style.fps}fps；单格 {style.cell_width}x{style.bar_height}px；"
            f"字体 {style.font_path} {style.font_size}px"
        )
        print(
            f"  色号：background {style.background} / cell {style.cell} / progress {style.progress} / "
            f"text {style.text} / stroke {style.stroke}"
        )
        # 排版预检：字体缺字、标题排不进两行都会在这里直接报错
        font = load_font(style.font_path, style.font_size)
        missing = []
        for chapter in plan.chapters:
            missing.extend(missing_glyphs(font, chapter.title, style.font_size))
            lines = layout_title(style, font, chapter.title, chapter.index)
            print(f"  排版：第{chapter.index}段「{chapter.title}」{len(lines)} 行 {lines}"
                  if len(lines) > 1 else
                  f"  排版：第{chapter.index}段「{chapter.title}」1 行")
        if missing:
            raise ConfigError(
                f"字体 {style.font_path} 缺少这些字的字形：{' '.join(dict.fromkeys(missing))}"
            )
        print("  排版：五段标题均可在两行内排入，字体无缺字")

    transcript_path = Path(args.transcript) if args.transcript else plan.transcript_path
    if transcript_path and transcript_path.is_file():
        report = outline.verify_anchors(plan, read_transcript(transcript_path))
        print(f"原文锚点核对：{transcript_path}")
        for item in report.anchors:
            flag = "OK" if item.start_ok and item.end_ok else "问题"
            print(f"  第{item.index}段 [{flag}] 起句 {item.start_char} / 止句 {item.end_char}")
        if report.coverage:
            print(f"  覆盖度：{report.coverage}")
        if report.problems:
            for problem in report.problems:
                print(f"  ! {problem}")
            print("原文锚点核对：不通过")
            return ConfigError.exit_code
        print("原文锚点核对：通过")
    elif transcript_path:
        print(f"原文文件不存在，跳过锚点核对：{transcript_path}")

    if args.json:
        print(json.dumps({"ok": True, "times": times_summary(plan)}, ensure_ascii=False, indent=2))
    print("check：通过")
    return EXIT_OK


# --------------------------------------------------------------------------
def cmd_align(args: argparse.Namespace) -> int:
    plan = validate_plan(load_plan(args.chapters), require_times=False)
    srt_path = Path(args.srt) if args.srt else plan.subtitle_path
    if srt_path is None:
        raise ConfigError("没有字幕来源：--srt 或 chapters.source.subtitle 至少给一个")
    cues = load_srt(srt_path)
    duration = args.duration if args.duration is not None else plan.declared_duration

    result = align_mod.align_plan(plan, cues, duration=duration, strict=args.strict)
    print(f"字幕：{srt_path}（{len(cues)} 条）")
    print(align_mod.format_report(result))

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"对齐报告：{report_path}")

    if not result.ok:
        print("\nalign：需人工复核，未写盘。确认边界后二选一：")
        print("  1) 在该段写 \"resolved\": {\"start_cue\": 起卡序号, \"end_cue\": 止卡序号}")
        print("  2) 直接写 \"start\"/\"end\" 秒数并加 \"confirmed\": true")
        raise NeedsReview("对齐存在待复核项")

    apply_times(plan, result.times)
    if args.out_plan:
        target = save_plan(plan, args.out_plan)
        print(f"时码已写入新文件：{target}")
    if args.write:
        target = save_plan(plan, plan.path)
        print(f"时码已写回：{target}")
    if not args.write and not args.out_plan:
        print("\n（未写盘；加 --write 写回 chapters.json，或 --out-plan 另存）")
    print("align：通过")
    return EXIT_OK


# --------------------------------------------------------------------------
def _render_once(args, plan, style, out_path: Path, *, start: float, end: float) -> Path:
    renderer = BarRenderer(style, plan)
    end = min(end, renderer.duration)
    frames = renderer.frames_between(start, end)
    expected = max(0, min(renderer.frame_count, int(end * style.fps)) - max(0, int(start * style.fps)))
    out = mp4.encode(
        (frame for _, _, frame in frames),
        width=style.width,
        height=style.height,
        fps=style.fps,
        out_path=out_path,
        crf=args.crf,
        preset=args.preset,
        total_frames=expected,
    )
    duration = expected / style.fps
    info, problems = mp4.verify(
        out, width=style.width, height=style.height, fps=style.fps, duration=duration
    )
    print(f"输出：{out}")
    print(f"  ffprobe：{mp4.describe(info)}")
    if problems:
        for problem in problems:
            print(f"  ! {problem}")
        raise ChapterBarError("MP4 自检不通过：" + "；".join(problems))
    print(f"  自检：通过（尺寸 {style.width}x{style.height}、{style.fps}fps、"
          f"时长 {duration:.3f}s 误差 ≤1 帧、无音轨、h264/yuv420p）")
    return out


def cmd_render(args: argparse.Namespace) -> int:
    plan = validate_plan(load_plan(args.chapters), require_times=True)
    style = load_style(args.style)
    renderer = BarRenderer(style, plan)

    out_path = Path(args.out)
    if args.range:
        try:
            start_s, end_s = (float(x) for x in args.range.split(":"))
        except ValueError as exc:
            raise ConfigError(f"--range 需要 START:END 秒，当前 {args.range!r}") from exc
        if not 0 <= start_s < end_s:
            raise ConfigError(f"--range 需要 0 ≤ START < END，当前 {start_s} → {end_s}")
        if start_s >= renderer.duration:
            raise ConfigError(f"--range 起点 {start_s}s 超出成片时长 {renderer.duration:.3f}s")
    else:
        start_s, end_s = 0.0, renderer.duration

    if out_path.exists():
        if args.overwrite:
            out_path.unlink()
            print(f"已按 --overwrite 删除旧文件：{out_path}")
        else:
            raise ConfigError(f"目标文件已存在：{out_path}（不覆盖；换文件名或加 --overwrite）")

    mp4_path = _render_once(args, plan, style, out_path, start=start_s, end=end_s)

    if args.preview_at:
        times = [float(x) for x in args.preview_at.split(",") if x.strip()]
        out_dir = Path(args.preview_dir) if args.preview_dir else mp4_path.parent / (mp4_path.stem + "_preview")
        _save_previews(renderer, times, out_dir)
    print("render：通过")
    return EXIT_OK


def _save_previews(renderer: BarRenderer, times: list[float], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for seconds in times:
        frame_index, t = renderer.preview_time(seconds)
        image = renderer.render(t)
        path = out_dir / f"t_{seconds:07.3f}s_f{frame_index:05d}.png"
        image.save(path)
        saved.append(path)
        print(f"  预览 {seconds:.3f}s（帧 {frame_index}）→ {path}")
    return saved


def cmd_preview(args: argparse.Namespace) -> int:
    plan = validate_plan(load_plan(args.chapters), require_times=True)
    style = load_style(args.style)
    renderer = BarRenderer(style, plan)
    times = [float(x) for x in args.at.split(",") if x.strip()]
    if not times:
        raise ConfigError("--at 至少给一个时刻，如 0,4,9,16")
    out_dir = Path(args.out_dir)
    print(f"成片时长 {renderer.duration:.3f}s，{renderer.frame_count} 帧")
    _save_previews(renderer, times, out_dir)
    print("preview：通过")
    return EXIT_OK


# --------------------------------------------------------------------------
def cmd_srt_from_draft(args: argparse.Namespace) -> int:
    cues, meta = cues_from_draft(args.draft, track_index=args.track_index, max_duration=args.max_duration)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(format_srt(cues), encoding="utf-8")
    print(f"草稿：{meta['draft']}（{meta.get('draft_name')}）")
    print(f"  文字轨 {meta['text_track_count']} 条，取第 {meta['track_index']} 条（基础字幕）")
    print(f"  字幕 {meta['cue_count']} 条，末条止于 {meta['duration']:.3f}s")
    for note in meta["notes"]:
        print(f"  提示：{note}")
    print(f"SRT 已写出：{out}")
    return EXIT_OK


# --------------------------------------------------------------------------
def cmd_demo(args: argparse.Namespace) -> int:
    """五段不等长 2/4/3/5/2=16s 演示：对齐 → 全片渲染 → 短动画 → 预览图。"""
    root = Path(__file__).resolve().parent.parent
    demo_dir = root / "examples" / "demo16s"
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    plan_path = demo_dir / "chapters.json"
    style_path = demo_dir / "style.json"
    srt_path = demo_dir / "subs.srt"

    print("== 1/5 校验配置 ==")
    plan = validate_plan(load_plan(plan_path), require_times=False)
    style = load_style(style_path)
    print(f"  chapters {plan_path}")
    print(f"  style {style_path}（{style.width}x{style.height}@{style.fps}fps）")

    print("== 2/5 对齐最终字幕时码 ==")
    cues = load_srt(srt_path)
    result = align_mod.align_plan(plan, cues, duration=plan.declared_duration)
    print(align_mod.format_report(result))
    if not result.ok:
        raise NeedsReview("演示章节对齐存在待复核项，见上方报告")
    apply_times(plan, result.times)
    aligned_path = save_plan(plan, out_dir / "chapters.aligned.json")
    print(f"  对齐后 chapters：{aligned_path}")

    print("== 3/5 全片渲染 ==")
    full_path = out_dir / f"demo16s_{style.width}x{style.height}_{style.fps}fps.mp4"
    if full_path.exists():
        full_path.unlink()
    _render_once(args, plan, style, full_path, start=0.0, end=plan.chapters[-1].end)

    print("== 4/5 短动画（5→8s，跨越第2/3段切换）==")
    short_path = out_dir / "demo16s_short_5.00-8.00s.mp4"
    if short_path.exists():
        short_path.unlink()
    _render_once(args, plan, style, short_path, start=5.0, end=8.0)

    print("== 5/5 预览图（开始 / 段中 / 切换 / 末尾）==")
    renderer = BarRenderer(style, plan)
    _save_previews(renderer, [0.0, 1.2, 4.0, 6.0, 16.0], out_dir / "preview")

    print("\ndemo：通过")
    print(f"  源码目录：{root}")
    print(f"  产物目录：{out_dir}")
    return EXIT_OK


# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chapter_bar.py",
        description="五段章节进度条：align（对齐最终字幕时码）/ render（渲染窄条 MP4）/ preview（PNG 预览）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", help="校验 chapters.json / style.json / 原文锚点")
    p.add_argument("--chapters", required=True)
    p.add_argument("--style")
    p.add_argument("--transcript", help="覆盖 chapters.source.transcript 的原文路径")
    p.add_argument("--require-times", action="store_true", help="同时要求已有 start/end")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("align", help="按原句对齐到最终字幕时码")
    p.add_argument("--chapters", required=True)
    p.add_argument("--srt", help="最终字幕 SRT；缺省用 chapters.source.subtitle")
    p.add_argument("--duration", type=float, help="成片时长（秒）；缺省用 chapters.source.duration 或字幕末条")
    p.add_argument("--write", action="store_true", help="把时码写回 chapters.json")
    p.add_argument("--out-plan", help="把带时码的 chapters 另存到该路径")
    p.add_argument("--report", help="对齐报告 JSON 输出路径")
    p.add_argument("--strict", action="store_true", help="部分匹配也算待复核")
    p.set_defaults(func=cmd_align)

    p = sub.add_parser("render", help="渲染 MP4（全片或 --range 短动画）")
    p.add_argument("--chapters", required=True)
    p.add_argument("--style", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--range", help="短动画区间，形如 5:8（秒）")
    p.add_argument("--crf", type=int, default=18)
    p.add_argument("--preset", default="medium")
    p.add_argument("--overwrite", action="store_true", help="允许覆盖同名输出")
    p.add_argument("--preview-at", help="渲染同时导出这些时刻的 PNG，如 0,4,9,16")
    p.add_argument("--preview-dir")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("preview", help="指定时刻导出 PNG")
    p.add_argument("--chapters", required=True)
    p.add_argument("--style", required=True)
    p.add_argument("--at", required=True, help="逗号分隔的秒数，如 0,1.2,4,6,16")
    p.add_argument("--out-dir", required=True)
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("srt-from-draft", help="从剪映草稿 draft_content.json 抽出最终字幕轨为 SRT")
    p.add_argument("draft")
    p.add_argument("--out", required=True)
    p.add_argument("--track-index", type=int, help="文字轨序号（0 基）；缺省取段数最多的一条")
    p.add_argument("--max-duration", type=float, help="只取该时刻之前的字幕（合并草稿切片用）")
    p.set_defaults(func=cmd_srt_from_draft)

    p = sub.add_parser("demo", help="跑通 2/4/3/5/2=16s 不等长演示")
    p.add_argument("--out-dir", default="outputs/demo16s")
    p.add_argument("--crf", type=int, default=18)
    p.add_argument("--preset", default="medium")
    p.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ChapterBarError as exc:
        print(f"\n[退出码 {exc.exit_code}] {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:  # pragma: no cover
        print("\n已中断", file=sys.stderr)
        return 130
