"""五段章节进度条（chapter-progress-bar）源码包。

模块划分：
- errors     : 统一异常与退出码
- util       : 文本归一化、时间格式化等纯函数
- style      : style.json 加载与校验（色号 / 字体 / 尺寸 / 间距）
- model      : chapters.json 加载与结构校验（恰好五段、标题 ≤8 字、时码连续）
- outline    : 五段梗概的语义质量校验（占位符、重复、原文起止句是否真实存在）
- subtitles  : SRT 解析 / 生成，以及从剪映草稿 draft_content.json 抽取最终字幕轨
- align      : 按原句把五段计划对齐到最终字幕时码，歧义/删句报告待复核候选
- render     : Pillow 逐帧渲染（五格等宽、蓝填充在文字下层、末帧全满）
- mp4        : FFmpeg 管道编码 + ffprobe 自检
- cli        : 一条命令入口
"""

__all__ = [
    "align",
    "cli",
    "errors",
    "model",
    "mp4",
    "outline",
    "render",
    "style",
    "subtitles",
    "util",
]

VERSION = "1.0.0"
