"""RSS 发现 + 正文提取的官方源适配器（L1）：欧洲央行、英国央行这类有 RSS 的官方站。

RSS 只给标题和摘要，解读需要可引用的段落，所以逐篇抓正文页用 trafilatura 提取。
每次只处理近 LOOKBACK_DAYS 天、最多 MAX_ITEMS 篇。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import feedparser
import trafilatura

from .. import http
from ..normalize import canonical_url

LOOKBACK_DAYS = 7
MAX_ITEMS = 8
MAX_PASSAGES = 80


def _published(entry) -> str | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
    return None


def extract_article(page_html: str) -> list[str]:
    text = trafilatura.extract(page_html, include_tables=True, include_comments=False,
                               favor_precision=True, deduplicate=True) or ""
    out = []
    for line in text.split("\n"):
        line = re.sub(r"\s*\|\s*(\|\s*)+", " | ", line).strip(" |").strip()
        if len(line) >= 30 or (line and re.search(r"\d", line)):
            out.append(line)
    return out[:MAX_PASSAGES]


def fetch(db, source: dict) -> int:
    try:
        feed = feedparser.parse(http.get_if_modified(source["url"], db).content)
    except http.NotModified:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    new = 0
    for e in feed.entries[:40]:
        link, title = e.get("link"), (e.get("title") or "").strip()
        if not link or not title:
            continue
        published = _published(e)
        if published and datetime.fromisoformat(published) < cutoff:
            continue
        url = canonical_url(link)
        existing = db.get_document_by_url(url)
        if existing and db.passages_for(existing["id"]):
            continue
        if new >= MAX_ITEMS:
            break
        try:
            page = http.get(url)
        except Exception:  # noqa: BLE001 — 单篇抓不到不影响整源
            continue
        paras = extract_article(page.text)
        if len(paras) < 2:      # 正文提取不出来就不建事件，避免空卡片
            continue
        doc_id, created = db.insert_document(
            source_id=source["id"], url=url, title=title, published_at=published,
            lang=source["lang"], doc_type=source.get("doc_type", "official_release"), body_stored=True)
        db.replace_passages(doc_id, [("¶%d" % (i + 1), p) for i, p in enumerate(paras)])
        new += created
    return new
