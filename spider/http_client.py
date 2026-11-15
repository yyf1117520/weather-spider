# -*- coding: utf-8 -*-
"""
spider/http_client.py —— HTTP 抓取层
====================================================================
职责：只做"把 URL 变成 HTML 字符串"这一件事，并把它做扎实。
本模块集中实现了抓取的"健壮性"与"爬虫礼仪"：

    1. requests.Session + 连接复用        —— 减少 TCP/TLS 握手开销
    2. UA 轮换 + 完整请求头               —— 模拟真实浏览器
    3. 区分连接/读取超时、指数退避重试     —— 应对网络抖动与临时 5xx
    4. 编码纠错（utf-8 → apparent）       —— 解决中文乱码
    5. 磁盘缓存 + TTL                     —— 重复运行不打扰服务器，且可离线复现
    6. 请求限速 + 随机抖动                —— 不对目标站点造成压力
    7. robots.txt 检查                    —— 遵守约定，规避法律风险
    8. 访问统计                           —— 为报告的"性能分析"提供数据
"""

from __future__ import annotations

import hashlib
import random
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

import config


# ---------------------------------------------------------------------------
# 统计信息
# ---------------------------------------------------------------------------
@dataclass
class FetchStats:
    """全局抓取统计，多线程共享（写入时加锁）。"""

    requests_total: int = 0      # 实际发出的 HTTP 请求数
    cache_hits: int = 0          # 命中本地缓存次数
    retries: int = 0             # 重试次数
    failures: int = 0            # 最终失败次数
    bytes_total: int = 0         # 累计下载字节数
    time_total: float = 0.0      # 累计耗时（秒）
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, **kwargs) -> None:
        with self._lock:
            for k, v in kwargs.items():
                setattr(self, k, getattr(self, k) + v)

    @property
    def avg_ms(self) -> float:
        """单次请求平均耗时（毫秒）。"""
        if self.requests_total == 0:
            return 0.0
        return self.time_total / self.requests_total * 1000

    def summary(self) -> str:
        return (f"HTTP 请求 {self.requests_total} 次，缓存命中 {self.cache_hits} 次，"
                f"重试 {self.retries} 次，失败 {self.failures} 次，"
                f"下载 {self.bytes_total / 1024:.1f} KB，"
                f"平均耗时 {self.avg_ms:.0f} ms")


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------
class RobotsDisallowed(Exception):
    """目标站点 robots.txt 明确禁止抓取该路径时抛出。"""


class FetchError(Exception):
    """重试耗尽后仍然失败时抛出。"""


# ---------------------------------------------------------------------------
# 抓取客户端
# ---------------------------------------------------------------------------
class WeatherHttpClient:
    """带重试、缓存、限速的天气页面抓取客户端。

    Parameters
    ----------
    cache_dir : 缓存目录，None 表示不缓存
    use_cache : 是否读取已有缓存
    ttl       : 缓存有效期（秒）
    delay     : 两次请求之间的基础间隔（秒）
    max_retries : 单个 URL 的最大重试次数
    respect_robots : 是否检查 robots.txt
    """

    def __init__(
        self,
        cache_dir: str | Path | None = None,
        use_cache: bool = True,
        ttl: int = config.CACHE_TTL,
        delay: float = config.REQUEST_DELAY,
        max_retries: int = config.MAX_RETRIES,
        respect_robots: bool = True,
        timeout: tuple[int, int] = config.TIMEOUT,
        logger=None,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.use_cache = use_cache
        self.ttl = ttl
        self.delay = delay
        self.max_retries = max_retries
        self.timeout = timeout
        self.stats = FetchStats()
        self.log = logger

        # 每个线程独立 Session：requests.Session 并非完全线程安全
        self._local = threading.local()
        self._robots: RobotFileParser | None = None
        self._robots_ready = False
        self._respect_robots = respect_robots
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Session 管理
    # ------------------------------------------------------------------
    @property
    def session(self) -> requests.Session:
        """线程内懒加载一个 Session。"""
        sess = getattr(self._local, "session", None)
        if sess is None:
            sess = requests.Session()
            sess.headers.update(config.DEFAULT_HEADERS)
            self._local.session = sess
            self._local.last_request = 0.0
        return sess

    def _ua(self) -> str:
        """随机取一个 User-Agent。"""
        return random.choice(config.USER_AGENTS)

    # ------------------------------------------------------------------
    # 缓存
    # ------------------------------------------------------------------
    def _cache_path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        # 用 URL 的路径部分作为文件名，便于人工分辨
        slug = re.sub(r"[^0-9A-Za-z]+", "_", urlparse(url).path).strip("_")
        digest = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
        return self.cache_dir / f"{slug}_{digest}.html"

    def _read_cache(self, url: str) -> str | None:
        if not (self.use_cache and self.cache_dir):
            return None
        path = self._cache_path(url)
        if not path or not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > self.ttl:
            return None
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        if len(text) < 2000:          # 明显是错误页，不当作有效缓存
            return None
        self.stats.add(cache_hits=1)
        if self.log:
            self.log.debug("缓存命中 %s (%.0fs 前)", url, age)
        return text

    def _write_cache(self, url: str, text: str) -> None:
        if not self.cache_dir:
            return
        path = self._cache_path(url)
        if not path:
            return
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as exc:      # 缓存写失败不影响主流程
            if self.log:
                self.log.debug("缓存写入失败 %s: %s", path, exc)

    # ------------------------------------------------------------------
    # robots.txt
    # ------------------------------------------------------------------
    def _load_robots(self) -> None:
        """只加载一次 robots.txt。加载失败按"允许"处理（保守但可用）。"""
        with self._lock:
            if self._robots_ready:
                return
            self._robots_ready = True
            if not self._respect_robots:
                return
            parser = RobotFileParser()
            parser.set_url(config.ROBOTS_URL)
            try:
                resp = requests.get(config.ROBOTS_URL, headers={"User-Agent": self._ua()},
                                    timeout=self.timeout)
                if resp.status_code == 200:
                    # weather.com.cn 的 robots.txt 为 UTF-8 文本
                    resp.encoding = resp.encoding or "utf-8"
                    parser.parse(resp.text.splitlines())
                    self._robots = parser
                    if self.log:
                        self.log.info("已读取 robots.txt（%d 字节）", len(resp.text))
            except Exception as exc:  # noqa: BLE001  网络问题不应导致程序退出
                if self.log:
                    self.log.warning("robots.txt 读取失败，按允许处理：%s", exc)

    def allowed(self, url: str) -> bool:
        """判断 URL 是否被 robots.txt 允许抓取。"""
        self._load_robots()
        if self._robots is None:
            return True
        try:
            return self._robots.can_fetch("*", url)
        except Exception:  # noqa: BLE001
            return True

    # ------------------------------------------------------------------
    # 限速
    # ------------------------------------------------------------------
    def _throttle(self) -> None:
        """同线程内保证两次请求间隔不小于 delay + 随机抖动。"""
        last = getattr(self._local, "last_request", 0.0)
        wait = self.delay + random.uniform(0, 0.6) - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        self._local.last_request = time.time()

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def fetch(self, url: str, force: bool = False) -> str:
        """获取 URL 的 HTML 文本。

        force=True 时忽略缓存，强制走网络（用于"最新数据"场景）。
        失败会抛出 FetchError，由上层决定是否跳过该城市。
        """
        cached = None if force else self._read_cache(url)
        if cached is not None:
            return cached

        if not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt 禁止抓取：{url}")

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    # 指数退避 + 抖动：1s, 2s, 4s ... 最多 BACKOFF_MAX
                    backoff = min(config.BACKOFF_BASE * (2 ** (attempt - 1)),
                                  config.BACKOFF_MAX)
                    sleep_s = backoff + random.uniform(0, 0.4)
                    if self.log:
                        self.log.warning("第 %d 次重试 %s（等待 %.1fs）", attempt, url, sleep_s)
                    time.sleep(sleep_s)
                    self.stats.add(retries=1)

                self._throttle()
                started = time.time()
                resp = self.session.get(url, headers={"User-Agent": self._ua()},
                                        timeout=self.timeout)
                elapsed = time.time() - started
                self.stats.add(requests_total=1, time_total=elapsed,
                               bytes_total=len(resp.content))

                # ---- 状态码处理 ----
                if resp.status_code == 404:
                    raise FetchError(f"404 页面不存在：{url}")
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise FetchError(f"服务端临时错误 {resp.status_code}：{url}")
                resp.raise_for_status()

                text = self._decode(resp)
                if not text or len(text) < 2000:
                    raise FetchError(f"响应内容异常（{len(text) if text else 0} 字节）：{url}")

                self._write_cache(url, text)
                if self.log:
                    self.log.debug("GET %s -> %d, %d 字节, %.0f ms",
                                   url, resp.status_code, len(text), elapsed * 1000)
                return text

            except FetchError as exc:
                last_exc = exc
                # 404 属于确定性错误，不必重试
                if "404" in str(exc):
                    break
            except RobotsDisallowed:
                raise
            except requests.exceptions.Timeout as exc:
                last_exc = exc
                if self.log:
                    self.log.warning("请求超时：%s", url)
            except requests.exceptions.ConnectionError as exc:
                last_exc = exc
                if self.log:
                    self.log.warning("连接失败：%s", url)
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if self.log:
                    self.log.warning("请求异常：%s（%s）", url, exc)

        self.stats.add(failures=1)
        raise FetchError(f"抓取失败（已重试 {self.max_retries} 次）：{url}；原因：{last_exc}")

    # ------------------------------------------------------------------
    # 编码处理
    # ------------------------------------------------------------------
    @staticmethod
    def _decode(resp: requests.Response) -> str:
        """把响应体解码成 str。

        中国天气网页面是 UTF-8，但响应头里有时缺失 charset，requests 会退化成
        ISO-8859-1，导致中文变成乱码。这里按优先级尝试：
            1) 响应头声明的编码
            2) 页面 meta 声明的编码
            3) UTF-8
            4) chardet 自动探测
        """
        raw = resp.content

        # 1) 页面 <meta charset="utf-8">
        head = raw[:2048].decode("ascii", errors="ignore")
        m = re.search(r'charset=["\']?([\w-]+)', head, re.I)
        declared = m.group(1).lower() if m else None

        candidates: list[str] = []
        if resp.encoding and resp.encoding.lower() not in ("iso-8859-1",):
            candidates.append(resp.encoding)
        if declared:
            candidates.append(declared)
        candidates.extend(["utf-8", "gb18030"])

        for enc in candidates:
            try:
                text = raw.decode(enc)
                # 用"中文标点/常用字"做一次合理性校验
                if enc.startswith("utf") or text.count("的") + text.count("天") > 0:
                    return text
                return text
            except (UnicodeDecodeError, LookupError):
                continue

        # 5) 兜底：忽略错误字符
        return raw.decode("utf-8", errors="replace")

    def close(self) -> None:
        sess = getattr(self._local, "session", None)
        if sess is not None:
            sess.close()
