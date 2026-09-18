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


class NotModified(Exception):
    """源自上次抓取以来没变（HTTP 304）。"""


def get_if_modified(url: str, db, **kw) -> httpx.Response:
    """带 ETag / Last-Modified 的条件请求：高频轮询列表页与 RSS 时对源客气些。
    源返回 304 时抛 NotModified，调用方直接跳过本轮。"""
    row = db.one("SELECT etag, last_modified FROM http_cache WHERE url=?", (url,))
    headers = dict(kw.pop("headers", {}) or {})
    if row and row["etag"]:
        headers["If-None-Match"] = row["etag"]
    if row and row["last_modified"]:
        headers["If-Modified-Since"] = row["last_modified"]

    rp = _robots_for(url)
    if rp is not None and not rp.can_fetch(UA, url):
        raise RobotsDisallowed(url)
    _throttle(url)
    r = client().get(url, headers=headers, **kw)
    if r.status_code == 304:
        db.conn.execute("UPDATE http_cache SET checked_at=? WHERE url=?", (_now(), url))
        db.commit()
        raise NotModified(url)
    r.raise_for_status()
    db.conn.execute("""INSERT INTO http_cache(url,etag,last_modified,checked_at) VALUES(?,?,?,?)
                       ON CONFLICT(url) DO UPDATE SET etag=excluded.etag,
                         last_modified=excluded.last_modified, checked_at=excluded.checked_at""",
                    (url, r.headers.get("ETag"), r.headers.get("Last-Modified"), _now()))
    db.commit()
    return r


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def post_json(url: str, payload: dict) -> dict:
    _throttle(url)
    r = client().post(url, json=payload)
    r.raise_for_status()
    return r.json()
