"""Generate one editable OpenMotion insert from one approved narration excerpt."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


MODULE = Path(__file__).resolve().parent


def generate_html(source, seconds, visual_brief=None):
    worker = Path(os.environ.get("DSH_WORKER_PS1", MODULE.parent / "tools" / "dsh-worker.ps1"))
    example = (MODULE / "examples" / "visit-notes.html").read_text(encoding="utf-8")
    prompt = f"""根据以下一段医疗科普口播，编写一个竖屏无声插入镜头。只输出完整 HTML。
只使用原文已有的信息，保留否定、数量、条件和不确定性，不自行补充医学解释。
用形状、连线、顺序出现的标签或简图，具体表现这段话。屏幕文字少而清楚。
{f'本镜头已定视觉方案：{visual_brief}' if visual_brief else ''}
参考下面的 OpenMotion 文件契约：1080×1920，30fps，时长 {seconds} 秒，
一个 data-composition-id 根节点，window.__timelines 同名暂停 GSAP 时间线。
只引用 assets/gsap.min.js。CSS 字体统一使用 "Microsoft YaHei", sans-serif，本地字体声明由生成器提供。
所有构图、图形、样式与时间线内联。不要调用工具、访问网络、生成配音或媒体。
示例结构（按本次原文重新设计内容和时间线）：
{example}
待表现的口播原文：
{source}
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(worker), "--stdin"], input=prompt.encode("utf-8"),
        stdout=subprocess.PIPE, check=True, timeout=600,
    )
    reply = result.stdout.decode("utf-8-sig").strip()
    html = re.fullmatch(r"(?:```(?:html)?\s*)?(<!doctype html>.*?</html>)(?:\s*```)?",
                        reply, re.IGNORECASE | re.DOTALL)
    if not html:
        raise ValueError("DSH 未返回完整 HTML，未开始渲染。")
    # DSH sometimes emits either localized family name in a CSS fallback list.
    # HyperFrames verifies each name individually, even on Windows with YaHei installed.
    font_faces = """<style>
@font-face { font-family: "Microsoft YaHei"; src: local("Microsoft YaHei") }
@font-face { font-family: "微软雅黑"; src: local("Microsoft YaHei") }
</style>"""
    body, count = re.subn(r"</head\s*>", font_faces + "</head>", html[1], count=1, flags=re.IGNORECASE)
    if not count:
        raise ValueError("DSH 生成的 HTML 缺少 head 结束标签")
    return body


def render_html(html_path, output, seconds):
    node = Path.home() / ".dsh/dsh-runtimes/dsh-next-primary-runtime/dependencies/node/bin/node.exe"
    subprocess.run([str(node) if node.is_file() else "node", "--experimental-strip-types",
                    str(MODULE / "render.mjs"), str(html_path), str(output), str(seconds)], check=True)


def main():
    parser = argparse.ArgumentParser(description="用 DSH 把一段口播原文做成一个无声动效镜头")
    parser.add_argument("excerpt", type=Path, help="单个镜头的口播原文（UTF-8）")
    parser.add_argument("output", type=Path, help="新的输出目录")
    parser.add_argument("--seconds", type=int, choices=range(2, 31), default=6)
    args = parser.parse_args()
    source = args.excerpt.read_text(encoding="utf-8-sig").strip()
    if not source:
        parser.error("口播原文为空")
    output = args.output.resolve()
    if output.exists():
        parser.error("输出目录已存在")
    with tempfile.TemporaryDirectory() as work:
        shot = Path(work) / "index.html"
        shot.write_text(generate_html(source, args.seconds), encoding="utf-8")
        render_html(shot, output, args.seconds)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
