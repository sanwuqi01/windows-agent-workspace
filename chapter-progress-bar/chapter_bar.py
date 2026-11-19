#!/usr/bin/env python
"""五段章节进度条 —— 一条命令入口。

用法（完整说明见 README.md / AGENT.md）：

    python chapter_bar.py check    --chapters examples/demo16s/chapters.json --style examples/demo16s/style.json
    python chapter_bar.py align    --chapters examples/demo16s/chapters.json --srt examples/demo16s/subs.srt
    python chapter_bar.py render   --chapters <aligned.json> --style style.json --out outputs/x.mp4
    python chapter_bar.py preview  --chapters <aligned.json> --style style.json --at 0,4,9,16 --out-dir outputs/p
    python chapter_bar.py demo

Windows 上也直接双击/调用 run.cmd，参数与上面一致。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chapterbar.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
