"""中文官方源（L1）：国家统计局「最新发布」、中国政府网「最新政策」。

两站 robots.txt 均允许抓取。每次只取近 LOOKBACK_DAYS 天、最多 MAX_ITEMS 条，控制请求量。
"""
from __future__ import annotations

import html as htmllib
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin

import trafilatura

from .. import http
from ..normalize import canonical_url

LOOKBACK_DAYS = 14
MAX_ITEMS = 15
MAX_PASSAGES = 120
CST = timezone(timedelta(hours=8))


def _clean(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", "", fragment)
    text = htmllib.unescape(text).replace("\xa0", " ").replace("　", " ")
    return re.sub(r"\s+", " ", text).strip()


def _recent(d: date) -> bool:
    return d >= datetime.now(CST).date() - timedelta(days=LOOKBACK_DAYS)


# ---- 国家统计局 ----------------------------------------------------------
def parse_stats_list(page_html: str, base_url: str) -> list[dict]:
    seen, items = set(), []
    for m in re.finditer(r'<a[^>]+href="([^"]*t\d{8}_\d+\.html)"[^>]*>(.*?)</a>', page_html, flags=re.S):
        href, title = m.group(1), _clean(m.group(2))
        url = urljoin(base_url, href)
        if len(title) < 6 or url in seen:
            continue
        seen.add(url)
        d = re.search(r"t(\d{8})_", url).group(1)
        items.append({"url": url, "title": title, "date": datetime.strptime(d, "%Y%m%d").date()})
    return items


def extract_stats(page_html: str) -> list[str]:
    text = trafilatura.extract(page_html, include_tables=True, include_comments=False,
                               favor_precision=True, deduplicate=True) or ""
    lines = []
    for x in text.split("\n"):
        x = re.sub(r"\s*\|\s*(\|\s*)+", " | ", x).strip(" |").strip()
        if len(x) >= 4:
            lines.append(x)
    return lines[:MAX_PASSAGES]


def fetch_stats(db, source: dict) -> int:
    items = parse_stats_list(http.get(source["url"]).text, source["url"])
    items = [i for i in items if _recent(i["date"])][:MAX_ITEMS]
    new = 0
    for it in items:
        url = canonical_url(it["url"])
        existing = db.get_document_by_url(url)
        if existing and db.passages_for(existing["id"]):
            continue
        page = http.get(url)
        page.encoding = "utf-8"
        m = re.search(r'<meta name="PubDate" content="([^"]+)"', page.text)
        published = (datetime.strptime(m.group(1), "%Y/%m/%d %H:%M").replace(tzinfo=CST).isoformat()
                     if m else datetime.combine(it["date"], datetime.min.time(), CST).isoformat())
        paras = extract_stats(page.text)
        if not paras:
            continue
        doc_id, created = db.insert_document(source_id=source["id"], url=url, title=it["title"],
                                             published_at=published, lang="zh", doc_type="stats_release",
                                             body_stored=True)
        db.replace_passages(doc_id, [("¶%d" % (i + 1), p) for i, p in enumerate(paras)])
        new += created
    return new


# ---- 中国政府网 ----------------------------------------------------------
def extract_govcn(page_html: str) -> list[str]:
    i = page_html.find('id="UCAP-CONTENT"')
    if i < 0:
        return []
    end_candidates = [page_html.find(m, i) for m in ('id="pagination"', 'class="jiedu-blk', "<!--微信分享图功能-->")]
    end_candidates = [e for e in end_candidates if e > 0]
    seg = page_html[i: min(end_candidates) if end_candidates else i + 200_000]
    seg = re.sub(r"<(script|style)\b.*?</\1>", "", seg, flags=re.S | re.I)
    paras = [_clean(p) for p in re.findall(r"<p\b[^>]*>(.*?)</p>", seg, flags=re.S | re.I)]
    return [p for p in paras if p][:MAX_PASSAGES]


def fetch_govcn(db, source: dict) -> int:
    r = http.get(source["url"])
    r.encoding = "utf-8"
    items = []
    for x in r.json():
        try:
            d = datetime.strptime(x["DOCRELPUBTIME"][:10], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        if _recent(d):
            items.append({"url": x["URL"], "title": x["TITLE"].strip(), "date": d})
    new = 0
    for it in items[:MAX_ITEMS]:
        url = canonical_url(it["url"])
        existing = db.get_document_by_url(url)
        if existing and db.passages_for(existing["id"]):
            continue
        page = http.get(url)
        page.encoding = "utf-8"
        m = re.search(r'<meta name="firstpublishedtime" content="(\d{4}-\d{2}-\d{2})-(\d{2}:\d{2}):\d{2}"', page.text)
        published = (datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M").replace(tzinfo=CST).isoformat()
                     if m else datetime.combine(it["date"], datetime.min.time(), CST).isoformat())
        paras = extract_govcn(page.text)
        if not paras:
            continue
        doc_id, created = db.insert_document(source_id=source["id"], url=url, title=it["title"],
                                             published_at=published, lang="zh", doc_type="policy_doc",
                                             body_stored=True)
        db.replace_passages(doc_id, [("¶%d" % (i + 1), p) for i, p in enumerate(paras)])
        new += created
    return new
