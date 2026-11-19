"""FFmpeg 管道编码 + ffprobe 自检。

产物要求：窄条不透明 H.264 / yuv420p / 无音轨；不带遮挡口播的整幅黑底。
所以编码参数固定 `-an`（无音轨）、`-pix_fmt yuv420p`，并且渲染出来就是条带本身，
不做任何背景垫片。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator

from PIL import Image

from .errors import DependencyError, RenderError

FRAME_TOLERANCE = 1  # 时长误差容忍：1 帧


def ffmpeg_bin() -> str:
    env = os.environ.get("CHAPTERBAR_FFMPEG")
    if env:
        if not Path(env).is_file():
            raise DependencyError(f"CHAPTERBAR_FFMPEG 指向的文件不存在：{env}")
        return env
    found = shutil.which("ffmpeg")
    if not found:
        raise DependencyError(
            "找不到 ffmpeg；请装 FFmpeg 并加入 PATH，或设环境变量 CHAPTERBAR_FFMPEG 指向可执行文件"
        )
    return found


def ffprobe_bin() -> str:
    env = os.environ.get("CHAPTERBAR_FFPROBE")
    if env:
        if not Path(env).is_file():
            raise DependencyError(f"CHAPTERBAR_FFPROBE 指向的文件不存在：{env}")
        return env
    sibling = Path(ffmpeg_bin()).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if sibling.is_file():
        return str(sibling)
    found = shutil.which("ffprobe")
    if not found:
        raise DependencyError("找不到 ffprobe；请装 FFmpeg 或设 CHAPTERBAR_FFPROBE")
    return found


def encode(
    frames: Iterator[Image.Image],
    *,
    width: int,
    height: int,
    fps: int,
    out_path: str | Path,
    crf: int = 18,
    preset: str = "medium",
    total_frames: int | None = None,
) -> Path:
    """把 RGB 帧逐帧写进 ffmpeg stdin，编码成无音轨 MP4。"""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise RenderError(f"目标文件已存在，不覆盖：{out}（换新文件名或显式 --overwrite）")
    err_file = tempfile.TemporaryFile()

    cmd = [
        ffmpeg_bin(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-movflags",
        "+faststart",
        str(out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err_file)
    assert proc.stdin is not None
    written = 0
    pipe_broken = False
    failure: BaseException | None = None
    try:
        for frame in frames:
            if frame.size != (width, height):
                raise RenderError(f"帧尺寸 {frame.size} 与配置 {width}x{height} 不一致")
            proc.stdin.write(frame.convert("RGB").tobytes())
            written += 1
    except BrokenPipeError:
        pipe_broken = True
    except BaseException as exc:  # 任何异常都要先收尾，否则 ffmpeg 还等 stdin，管道会死锁
        failure = exc
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        returncode = proc.wait()
        err_file.seek(0)
        stderr_text = err_file.read().decode("utf-8", "replace")
        err_file.close()

    if failure is not None:
        raise failure
    if pipe_broken:
        raise RenderError(f"ffmpeg 提前退出：\n{stderr_text[:1500]}")
    if returncode != 0:
        raise RenderError(f"ffmpeg 编码失败（退出码 {returncode}）：\n{stderr_text[:1500]}")
    if total_frames is not None and written != total_frames:
        raise RenderError(f"写入帧数 {written} 与预期 {total_frames} 不一致")
    return out


def probe(path: str | Path) -> dict:
    """ffprobe -show_streams -show_format，返回精简字典。"""
    p = Path(path)
    if not p.is_file():
        raise RenderError(f"待检测文件不存在：{p}")
    cmd = [
        ffprobe_bin(),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(p),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RenderError(f"ffprobe 失败：{result.stderr.strip()[:800]}")
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    fmt = data.get("format") or {}
    duration = None
    if fmt.get("duration"):
        duration = float(fmt["duration"])
    elif video and video.get("duration"):
        duration = float(video["duration"])
    fps = None
    if video and video.get("avg_frame_rate"):
        num, _, den = video["avg_frame_rate"].partition("/")
        try:
            fps = float(num) / float(den or 1)
        except (TypeError, ZeroDivisionError):
            fps = None
    return {
        "path": str(p),
        "size_bytes": p.stat().st_size,
        "width": int(video["width"]) if video else None,
        "height": int(video["height"]) if video else None,
        "codec": video.get("codec_name") if video else None,
        "pix_fmt": video.get("pix_fmt") if video else None,
        "fps": fps,
        "r_frame_rate": video.get("r_frame_rate") if video else None,
        "nb_frames": int(video["nb_frames"]) if video and video.get("nb_frames") else None,
        "duration": duration,
        "has_audio": bool(audio),
        "audio_streams": len(audio),
    }


def verify(
    path: str | Path,
    *,
    width: int,
    height: int,
    fps: int,
    duration: float,
    tolerance_frames: int = FRAME_TOLERANCE,
) -> tuple[dict, list[str]]:
    """按任务单验收项检查：尺寸、帧率、时长（≤1 帧误差）、无音轨、H.264/yuv420p。"""
    info = probe(path)
    problems: list[str] = []
    if info["width"] != width or info["height"] != height:
        problems.append(f"尺寸不符：期望 {width}x{height}，实际 {info['width']}x{info['height']}")
    if info["fps"] is None or abs(float(info["fps"]) - fps) > 0.01:
        problems.append(f"帧率不符：期望 {fps}，实际 {info['fps']}")
    actual = info["duration"]
    limit = tolerance_frames / float(fps) + 1e-3
    if actual is None:
        problems.append("读不到时长")
    elif abs(float(actual) - duration) > limit:
        problems.append(
            f"时长不符：期望 {duration:.3f}s，实际 {float(actual):.3f}s，"
            f"误差 {abs(float(actual) - duration) * 1000:.1f}ms > {tolerance_frames} 帧"
        )
    if info["has_audio"]:
        problems.append(f"不应有音轨，实际有 {info['audio_streams']} 条")
    if info["codec"] != "h264":
        problems.append(f"编码不是 H.264：{info['codec']}")
    if info["pix_fmt"] != "yuv420p":
        problems.append(f"像素格式不是 yuv420p：{info['pix_fmt']}")
    return info, problems


def describe(info: dict) -> str:
    return (
        f"{info['width']}x{info['height']}  {info['codec']}/{info['pix_fmt']}  "
        f"{info['fps']:.3f}fps  {float(info['duration'] or 0):.3f}s  "
        f"音轨 {info['audio_streams']} 条  {info['size_bytes'] / 1024:.0f} KB"
    )
