# -*- coding: utf-8 -*-
"""
spider/logger.py —— 日志层
====================================================================
用标准库 logging 把"请求了几次、重试了几次、哪个城市失败了"记到文件里。
控制台只打印 WARNING 以上，避免刷屏影响表格观感；完整 DEBUG 信息进日志文件。
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

import config


def setup_logger(name: str = "weather", log_dir: str | Path | None = None,
                 level: int = logging.DEBUG, console: bool = True) -> logging.Logger:
    """创建（或复用）一个同时写文件与控制台的 logger。"""
    logger = logging.getLogger(name)
    if logger.handlers:            # 避免重复添加 handler
        return logger
    logger.setLevel(level)
    logger.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(threadName)-12s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # --- 文件 ---
    log_dir = Path(log_dir or config.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    filename = log_dir / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"
    fh = logging.FileHandler(filename, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # --- 控制台 ---
    if console:
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(logging.WARNING)   # 控制台只看告警
        ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(ch)

    logger.debug("日志文件：%s", filename)
    return logger
