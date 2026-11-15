# -*- coding: utf-8 -*-
"""tools/finalize_shots.py —— 整理报告用截图（裁边、切片）"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"


def crop_left(src: Path, dst: Path, left: int = 12, bottom_trim: int = 0) -> None:
    img = Image.open(src).convert("RGB")
    w, h = img.size
    img.crop((left, 0, w, h - bottom_trim)).save(dst)
    print(f"{dst.name}: {img.size} -> {(w - left, h - bottom_trim)}")


def split(src: Path, outs: list[tuple[Path, int, int]]) -> None:
    img = Image.open(src).convert("RGB")
    w, h = img.size
    for path, y0, y1 in outs:
        img.crop((0, y0, w, min(y1, h))).save(path)
        print(f"{path.name}: y {y0}..{y1}")


if __name__ == "__main__":
    run = SHOTS / "_run6.png"
    if run.exists():
        # 去掉窗口左侧的一列"桌面残留"像素
        crop_left(run, SHOTS / "运行结果.png", left=14)
    else:
        print("WARN: _run6.png 不存在，跳过运行截图整理")

    full = SHOTS / "看板全图.png"
    if full.exists():
        img = Image.open(full)
        h = img.size[1]
        split(full, [
            (SHOTS / "看板_上.png", 0, int(h * 0.47)),
            (SHOTS / "看板_下.png", int(h * 0.47), h),
        ])
