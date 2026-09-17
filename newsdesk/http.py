"""抓取公共层：遵守 robots.txt、按域名节流、统一 UA。"""
from __future__ import annotations

import logging
import time
import urllib.robotparser
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (compatible; newsdesk/0.1; personal news digest; +https://github.com/derek2035/newsdesk)"
MIN_INTERVAL = 2.0  # 同一域名两次请求至少间隔秒数

_client: httpx.Client | None = None
_last_hit: dict[str, float] = {}
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


class RobotsDisallowed(Exception):
    pass


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True)
    return _client


def _robots_for(url: str) -> urllib.robotparser.RobotFileParser | None:
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = client().get(base + "/robots.txt")
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
                _robots[base] = rp
            else:
                _robots[base] = None  # 无 robots.txt 视为允许
        except httpx.HTTPError:
            _robots[base] = None
    return _robots[base]


def _throttle(url: str) -> None:
    host = urlsplit(url).netloc
    wait = MIN_INTERVAL - (time.monotonic() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.monotonic()


def get(url: str, **kw) -> httpx.Response:
    rp = _robots_for(url)
    if rp is not None and not rp.can_fetch(UA, url):
        raise RobotsDisallowed(url)
    _throttle(url)
    r = client().get(url, **kw)
    r.raise_for_status()
    return r


def post_json(url: str, payload: dict) -> dict:
    _throttle(url)
    r = client().post(url, json=payload)
    r.raise_for_status()
    return r.json()
