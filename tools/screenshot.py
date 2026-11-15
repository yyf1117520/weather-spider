# -*- coding: utf-8 -*-
"""
tools/screenshot.py —— HTML 页面截图工具
====================================================================
用系统自带的 Microsoft Edge（Chromium 内核）以 headless 模式渲染本地 HTML
并截图，再用 Pillow 自动裁掉底部空白。

为什么这么做：
    * 不依赖额外安装 Playwright / Selenium 与浏览器二进制；
    * ``--virtual-time-budget`` 会让 ECharts 的入场动画"快进"完成，
      保证截到的图是最终态而不是动画中间帧；
    * 自动裁剪让不同长度的看板都有合适的图片高度，报告排版更整齐。

用法::

    python tools/screenshot.py 可视化看板.html docs/screenshots/看板全图.png
    python tools/screenshot.py 可视化看板.html out.png --width 1600 --height 4200
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_browser() -> str:
    for path in EDGE_CANDIDATES:
        if Path(path).exists():
            return path
    raise FileNotFoundError("未找到 Edge / Chrome，请手动指定浏览器路径")


def shoot(html: str | Path, out: str | Path, width: int = 1560,
          height: int = 4200, budget_ms: int = 9000,
          crop: bool = True, bg: tuple[int, int, int] = (244, 246, 250)) -> Path:
    """渲染 HTML 并截图，返回图片路径。"""
    html_path = Path(html).resolve()
    out_path = Path(out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not html_path.exists():
        raise FileNotFoundError(html_path)

    browser = find_browser()
    url = "file:///" + str(html_path).replace("\\", "/")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_png = Path(tmp) / "shot.png"
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-sandbox",
            "--force-device-scale-factor=1.5",     # 1.5 倍缩放，报告印刷更清晰
            "--allow-file-access-from-files",
            f"--window-size={width},{height}",
            f"--virtual-time-budget={budget_ms}",
            f"--screenshot={tmp_png}",
            url,
        ]
        subprocess.run(cmd, check=False, timeout=120,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Edge 偶尔写完文件后会延迟一点，重试等待
        for _ in range(20):
            if tmp_png.exists() and tmp_png.stat().st_size > 1000:
                break
            time.sleep(0.25)
        if not tmp_png.exists():
            raise RuntimeError("截图失败：浏览器未生成文件")

        if crop:
            from PIL import Image
            img = Image.open(tmp_png).convert("RGB")
            cropped = _crop_bottom(img, bg)
            cropped.save(out_path)
        else:
            import shutil
            shutil.copyfile(tmp_png, out_path)

    return out_path


def _crop_bottom(img, bg, pad: int = 24):
    """裁掉底部与背景色一致的空白行。"""
    from PIL import Image
    w, h = img.size
    px = img.load()
    last = h - 1
    while last > 0:
        row = [px[x, last] for x in range(0, w, 7)]   # 抽样判断，速度快
        if any(abs(c[0] - bg[0]) > 6 or abs(c[1] - bg[1]) > 6 or abs(c[2] - bg[2]) > 6
               for c in row):
            break
        last -= 1
    bottom = min(h, last + pad)
    if bottom < 200:      # 异常保护：不要把图裁没了
        bottom = h
    return img.crop((0, 0, w, bottom))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="HTML 页面截图工具")
    p.add_argument("html")
    p.add_argument("out")
    p.add_argument("--width", type=int, default=1560)
    p.add_argument("--height", type=int, default=4200)
    p.add_argument("--budget", type=int, default=9000)
    p.add_argument("--no-crop", action="store_true")
    a = p.parse_args(argv)
    path = shoot(a.html, a.out, a.width, a.height, a.budget, not a.no_crop)
    print(f"OK -> {path} ({path.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
