# -*- coding: utf-8 -*-
"""
tools/console_run.py —— 在"可控字体大小"的控制台里跑一次主程序
====================================================================
目的：为了让"程序运行结果"能在一屏内完整显示并被真实截图，
本脚本先用 Win32 的 ``SetCurrentConsoleFontEx`` 把当前控制台字体调小、
把窗口尺寸调大，然后再调用 ``main.main()``。

这样得到的截图是控制台的真实像素输出（不是后期拼的图片），
既能完整呈现整张表格，又保证中文字形正常。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Win32 控制台结构与 API
# ---------------------------------------------------------------------------
class COORD(ctypes.Structure):
    _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]


class CONSOLE_FONT_INFO_EX(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("nFont", wintypes.DWORD),
        ("dwFontSize", COORD),
        ("FontFamily", wintypes.UINT),
        ("FontWeight", wintypes.UINT),
        ("FaceName", wintypes.WCHAR * 32),
    ]


class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = [
        ("dwSize", COORD),
        ("dwCursorPosition", COORD),
        ("wAttributes", wintypes.WORD),
        ("srWindow", wintypes.SMALL_RECT),
        ("dwMaximumWindowSize", COORD),
    ]


def set_font(face: str = "Consolas", height: int = 12) -> bool:
    """设置控制台字体（高度以像素计）。"""
    try:
        k32 = ctypes.windll.kernel32
        handle = k32.GetStdHandle(-11)          # STD_OUTPUT_HANDLE
        if handle in (0, -1):
            return False
        info = CONSOLE_FONT_INFO_EX()
        info.cbSize = ctypes.sizeof(CONSOLE_FONT_INFO_EX)
        info.nFont = 0
        info.dwFontSize = COORD(0, height)      # 宽度 0 表示由高度自动推导
        info.FontFamily = 54                     # FF_MODERN | TMPF_TRUETYPE
        info.FontWeight = 400
        info.FaceName = face
        return bool(k32.SetCurrentConsoleFontEx(handle, False, ctypes.byref(info)))
    except Exception:  # noqa: BLE001
        return False


def set_window(cols: int, lines: int) -> bool:
    """设置控制台窗口与缓冲区尺寸。"""
    try:
        k32 = ctypes.windll.kernel32
        handle = k32.GetStdHandle(-11)
        # 先把缓冲区缩小，避免"缓冲区小于窗口"的报错
        small = COORD(cols, lines)
        k32.SetConsoleScreenBufferSize(handle, small)
        rect = wintypes.SMALL_RECT(0, 0, cols - 1, lines - 1)
        ok = bool(k32.SetConsoleWindowInfo(handle, True, ctypes.byref(rect)))
        k32.SetConsoleScreenBufferSize(handle, COORD(cols, lines))
        return ok
    except Exception:  # noqa: BLE001
        return False


def set_buffer(cols: int, lines: int) -> bool:
    """只放大缓冲区，窗口大小交给截图脚本用 SetWindowPos 拉大。"""
    try:
        k32 = ctypes.windll.kernel32
        handle = k32.GetStdHandle(-11)
        return bool(k32.SetConsoleScreenBufferSize(handle, COORD(cols, lines)))
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    # 关闭快速编辑模式，避免截图时出现"选择"造成的反色块
    try:
        k32 = ctypes.windll.kernel32
        handle = k32.GetStdHandle(-10)          # STD_INPUT_HANDLE
        mode = wintypes.DWORD()
        k32.GetConsoleMode(handle, ctypes.byref(mode))
        k32.SetConsoleMode(handle, mode.value & ~0x0040)   # 去掉 ENABLE_QUICK_EDIT
    except Exception:  # noqa: BLE001
        pass

    set_font("Consolas", 9)
    # 缓冲区给足，避免输出被丢弃；窗口大小由截图脚本用 SetWindowPos 决定
    set_buffer(240, 400)
    set_window(150, 70)

    import main as app
    argv = sys.argv[1:] or ["--charts"]
    code = app.main(argv)

    # 保留完整回滚缓冲区，截图脚本需要向上翻页回看前半段输出
    print()
    print(" — 运行结束，按回车键关闭窗口 —", flush=True)
    try:
        input()
    except EOFError:
        pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())


