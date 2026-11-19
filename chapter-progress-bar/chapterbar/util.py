"""纯函数小工具：文本归一化、时间格式化、数值校验。

归一化是「按原句定位」的基础：打标文案与字幕的标点、空格、全半角习惯不同，
只有去掉标点与空白后逐字比较，才能判断锚点句确实出现在字幕流里。
"""

from __future__ import annotations

import re

_WS = re.compile(r"\s+")


def collapse_ws(text: str) -> str:
    """把连续空白压成一个空格并去首尾空白。"""
    return _WS.sub(" ", text or "").strip()


def norm_for_match(text: str) -> str:
    """只保留字母/数字/汉字（`str.isalnum()` 对汉字为真），英文转小写。

    标点、空格、引号、破折号全部丢弃，因此「午餐？」与「午餐」被视为同一串。
    """
    return "".join(ch.lower() for ch in (text or "") if ch.isalnum())


def fmt_s(value: float) -> str:
    """秒 -> 三位小数字符串，用于报告与文件名。"""
    return f"{float(value):.3f}"


def is_even_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value % 2 == 0


def require_number(value: object, field: str) -> float:
    """把配置里的数值字段读成 float；bool 不算数字。"""
    from .errors import ConfigError

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{field} 必须是数字，当前为 {value!r}")
    return float(value)


def require_int(value: object, field: str) -> int:
    """把配置里的整数字段读成 int（接受 30.0 这类整值 float）。"""
    from .errors import ConfigError

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{field} 必须是整数，当前为 {value!r}")
    if isinstance(value, float) and not value.is_integer():
        raise ConfigError(f"{field} 必须是整数，当前为 {value!r}")
    return int(value)
