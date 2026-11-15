# -*- coding: utf-8 -*-
"""
spider/ui.py —— 终端输出美化层
====================================================================
目的：让"程序运行结果"本身就是一份可以直接截图进报告的成果。
实现要点：
  * 中文占 2 个字符宽，用 ``_disp_width`` 计算真实显示宽度，
    否则表格竖线会错位（这是很多人做终端表格时踩的坑）；
  * 自适应列宽 + 自动换行计算；
  * 在 Windows 上开启 ANSI 颜色与 UTF-8 代码页；
  * 提供 ``支持颜色 关闭`` 的降级开关，重定向到文件时不输出控制符。
"""

from __future__ import annotations

import os
import sys
import unicodedata

# ---------------------------------------------------------------------------
# 颜色
# ---------------------------------------------------------------------------
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GREY = "\033[90m"
    BG_BLUE = "\033[44m"
    BG_CYAN = "\033[46m"


_ENABLED = True


def enable_ansi() -> bool:
    """在 Windows 控制台开启 ANSI 转义支持；失败则关闭彩色输出。"""
    global _ENABLED
    if os.name != "nt":
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        # 同时尝试把代码页切到 UTF-8，避免中文乱码
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
        return True
    except Exception:  # noqa: BLE001
        _ENABLED = False
        return False


def set_color(enabled: bool) -> None:
    global _ENABLED
    _ENABLED = enabled


def colorize(text: str, *styles: str) -> str:
    """按顺序包裹样式；关闭颜色时原样返回。"""
    if not _ENABLED or not styles:
        return text
    return "".join(styles) + str(text) + C.RESET


# ---------------------------------------------------------------------------
# 显示宽度
# ---------------------------------------------------------------------------
def _char_width(ch: str) -> int:
    """东亚宽字符按 2 列算，其余按 1 列。"""
    if unicodedata.east_asian_width(ch) in ("W", "F", "A"):
        return 2
    return 1


def disp_width(text: str) -> int:
    """去掉 ANSI 转义后计算字符串的终端显示宽度。"""
    import re
    plain = re.sub(r"\033\[[0-9;]*m", "", str(text))
    return sum(_char_width(c) for c in plain)


def pad(text: str, width: int, align: str = "left") -> str:
    """按显示宽度补空格。"""
    text = str(text)
    gap = width - disp_width(text)
    if gap <= 0:
        return text
    if align == "right":
        return " " * gap + text
    if align == "center":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


# ---------------------------------------------------------------------------
# 组件
# ---------------------------------------------------------------------------
def banner(title: str, subtitle: str = "", width: int = 78, compact: bool = False) -> str:
    """打印带边框的标题；compact=True 时输出三行式紧凑标题。"""
    if compact:
        line = "═" * width
        lines = [
            colorize("╔" + line + "╗", C.CYAN),
            colorize("║", C.CYAN) + pad("  " + title, width) + colorize("║", C.CYAN),
            colorize("╚" + line + "╝", C.CYAN),
        ]
        if subtitle:
            lines.insert(2, colorize("║", C.CYAN) + pad("  " + subtitle, width)
                         + colorize("║", C.CYAN))
        return "\n".join(lines)

    lines = []
    lines.append(colorize("╔" + "═" * (width - 2) + "╗", C.CYAN))
    lines.append(colorize("║", C.CYAN) + pad("", width - 2) + colorize("║", C.CYAN))
    lines.append(colorize("║", C.CYAN) + pad("  " + title, width - 2) + colorize("║", C.CYAN))
    if subtitle:
        lines.append(colorize("║", C.CYAN) + pad("  " + subtitle, width - 2) + colorize("║", C.CYAN))
    lines.append(colorize("║", C.CYAN) + pad("", width - 2) + colorize("║", C.CYAN))
    lines.append(colorize("╚" + "═" * (width - 2) + "╝", C.CYAN))
    return "\n".join(lines)


def section(title: str, width: int = 78) -> str:
    """小节标题：左侧粗色块 + 标题 + 右侧横线。"""
    head = "▍" + title
    fill = width - disp_width(head) - 2
    return (colorize("▍", C.CYAN) + colorize(title, C.BOLD, C.WHITE)
            + colorize(" " + "─" * max(fill, 3), C.GREY))


def table(headers: list[str], rows: list[list[str]],
          aligns: list[str] | None = None, gap: int = 1) -> str:
    """渲染一张自适应宽度的终端表格（支持中文对齐）。"""
    aligns = aligns or ["left"] * len(headers)
    n = len(headers)
    widths = [disp_width(h) for h in headers]
    for row in rows:
        for i in range(n):
            cell = row[i] if i < len(row) else ""
            widths[i] = max(widths[i], disp_width(cell))

    sep = colorize("│", C.GREY)
    def line(cells, aligns):
        parts = []
        for i, cell in enumerate(cells):
            parts.append(" " + pad(cell, widths[i], aligns[i]) + " ")
        return sep.join(parts)

    out = []
    out.append(colorize("┌" + "┬".join("─" * (w + 2) for w in widths) + "┐", C.GREY))
    out.append(sep + line(headers, ["center"] * n) + sep)
    out.append(colorize("├" + "┼".join("─" * (w + 2) for w in widths) + "┤", C.GREY))
    for row in rows:
        cells = [row[i] if i < len(row) else "" for i in range(n)]
        out.append(sep + line(cells, aligns) + sep)
    out.append(colorize("└" + "┴".join("─" * (w + 2) for w in widths) + "┘", C.GREY))
    return "\n".join(out)


def progress_bar(done: int, total: int, width: int = 30, label: str = "") -> str:
    """一行式进度条。"""
    ratio = done / total if total else 0
    filled = int(width * ratio)
    bar = "█" * filled + "░" * (width - filled)
    pct = int(ratio * 100)
    text = f"{colorize(bar, C.GREEN)} {pct:3d}%  ({done}/{total})"
    if label:
        text += "  " + colorize(label, C.GREY)
    return text


def kv_line(key: str, value: str, key_width: int = 16) -> str:
    return colorize(pad(key, key_width), C.GREY) + " " + str(value)


def wrap_text(text: str, width: int = 96, indent: int = 0) -> list[str]:
    """按 **显示宽度** 折行（中文占 2 列），避免长结论句在窄终端里被硬切。

    与 ``textwrap`` 的区别：``textwrap`` 按字符数折行，一句中文会被算成
    一半宽度，导致行末留白很多；这里按东亚宽度计算，版式更紧凑。
    """
    text = str(text)
    if disp_width(text) <= width:
        return [text]
    lines: list[str] = []
    cur = ""
    cur_w = 0
    limit = width
    for ch in text:
        w = _char_width(ch)
        if cur_w + w > limit:
            lines.append(cur)
            cur = " " * indent + ch
            cur_w = indent + w
            limit = width
        else:
            cur += ch
            cur_w += w
    if cur.strip():
        lines.append(cur)
    return lines


def supports_color() -> bool:
    """判断当前 stdout 是否适合输出颜色（重定向到文件时关闭）。"""
    return bool(getattr(sys.stdout, "isatty", lambda: False)())
