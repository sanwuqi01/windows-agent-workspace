"""统一异常定义。

每个异常带 exit_code，CLI 直接把它当作进程退出码返回，便于上层/CI 判断：
0 成功 / 2 输入或配置不合法 / 3 需人工复核 / 4 渲染或编码失败 / 5 运行依赖缺失。
"""

from __future__ import annotations


class ChapterBarError(Exception):
    """本工程所有可预期错误的基类。"""

    exit_code = 2


class ConfigError(ChapterBarError):
    """chapters.json / style.json / SRT 内容不合法。"""

    exit_code = 2


class NeedsReview(ChapterBarError):
    """对齐存在歧义、删句或越界，必须先人工确认边界。"""

    exit_code = 3


class RenderError(ChapterBarError):
    """渲染/编码/自检失败。"""

    exit_code = 4


class DependencyError(ChapterBarError):
    """缺少 FFmpeg / Pillow / 字体等运行依赖。"""

    exit_code = 5
