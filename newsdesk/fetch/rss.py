"""通用 RSS 适配器（媒体，L2）：只存标题 / URL / 发布时间，不落正文。"""
from __future__ import annotations

from datetime import datetime, timezone

import feedparser

from .. import http
from ..normalize import canonical_url


def _published(entry) -> str | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
    return None


def fetch(db, source: dict) -> int:
    try:
        r = http.get_if_modified(source["url"], db)
    except http.NotModified:
        return 0
    feed = feedparser.parse(r.content)
    new = 0
    for e in feed.entries:
        link = e.get("link")
        title = (e.get("title") or "").strip()
        if not link or not title:
            continue
        _, created = db.insert_document(
            source_id=source["id"], url=canonical_url(link), title=title,
            published_at=_published(e), lang=source["lang"], doc_type="media", body_stored=False,
        )
        new += created
    return new
