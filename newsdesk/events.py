"""事件生成（第 1 版无聚类）：每个 L1 文档 = 一个事件。

- 附属文件（执行说明、经济预测表）挂到同日 FOMC 声明事件下，role=related
- 同类上一份文件挂为 role=prior（给「变了什么」做 diff）
- 媒体报道按关键词 + 时间窗挂为 role=media，并做转载判定（署名 / 标题逐字一致）
- 所有 L1 源都是官方原文 → 可信度「已确认」
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from . import resolvers
from .normalize import norm_text

MEDIA_WINDOW_BEFORE = timedelta(hours=0)
MEDIA_WINDOW_AFTER = timedelta(days=3)


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _slug(doc) -> str:
    src = doc["source_id"]
    tail = re.sub(r"[^A-Za-z0-9]+", "-", doc["url"].rstrip("/").split("/")[-1].rsplit(".", 1)[0]).strip("-")
    day = (doc["published_at"] or doc["fetched_at"])[:10]
    return f"{day}-{src}-{tail}"[:80].lower()


def _prior_document(db, doc):
    """同类上一份文件。FOMC 声明：上一份声明；统计局：去掉数字后标题相同的上一期。"""
    if doc["doc_type"] == "fomc_statement":
        return db.one("""SELECT * FROM document WHERE doc_type='fomc_statement' AND published_at < ?
                         ORDER BY published_at DESC LIMIT 1""", (doc["published_at"],))
    if doc["doc_type"] == "stats_release":
        pattern = re.sub(r"[\d—\-.%]+", "", doc["title"])
        for row in db.q("""SELECT * FROM document WHERE doc_type='stats_release' AND published_at < ?
                           ORDER BY published_at DESC""", (doc["published_at"],)):
            if re.sub(r"[\d—\-.%]+", "", row["title"]) == pattern:
                return row
    return None


def _related_documents(db, doc):
    if doc["doc_type"] != "fomc_statement":
        return []
    meta = json.loads(doc["meta"] or "{}")
    d = meta.get("date")
    if not d:
        return []
    return db.q("""SELECT * FROM document WHERE source_id='fed'
                   AND doc_type IN ('fomc_impl_note','fomc_sep_table') AND json_extract(meta,'$.date')=?""", (d,))


def _media_matches(db, doc, keyword_groups: list[list[str]]):
    if not keyword_groups:
        return []
    t0 = _dt(doc["published_at"])
    rows = db.q("SELECT * FROM document WHERE doc_type='media'")
    out = []
    for r in rows:
        meta = json.loads(r["meta"] or "{}")
        t = _dt(r["published_at"])
        if t0 and t:
            if not (t0 - MEDIA_WINDOW_BEFORE <= t <= t0 + MEDIA_WINDOW_AFTER):
                continue
        elif t0 and meta.get("event_date"):
            # 补录报道没有可靠发布时间：用人工标注的事件日期判断
            if meta["event_date"] != t0.date().isoformat():
                continue
        else:
            continue
        title = r["title"].lower()
        if all(any(_kw_hit(k, title) for k in group) for group in keyword_groups):
            out.append(r)
    return out


def _kw_hit(keyword: str, title_lower: str) -> bool:
    if keyword == "<月份>":
        return re.search(r"\d{1,2}月", title_lower) is not None
    k = keyword.lower()
    if re.fullmatch(r"[a-z][a-z\- ]*", k):  # 英文词按词边界匹配，避免 fed 命中 federal/fedex
        return re.search(rf"\b{re.escape(k)}\b", title_lower) is not None
    return k in title_lower


def _mark_reprints(media_rows) -> dict[int, bool]:
    """转载判定：① 手工标注 reprint_of ② 标题归一化后逐字相同，较晚 / 非首个出现的算转载。"""
    by_url = {r["url"]: r for r in media_rows}
    reprint: dict[int, bool] = {}
    seen_titles: dict[str, int] = {}
    ordered = sorted(media_rows, key=lambda r: (r["published_at"] or "9999", r["id"]))
    for r in ordered:
        meta = json.loads(r["meta"] or "{}")
        if meta.get("reprint_of") and meta["reprint_of"] in by_url:
            reprint[r["id"]] = True
            continue
        key = norm_text(r["title"])
        if key in seen_titles and seen_titles[key] != r["id"]:
            reprint[r["id"]] = True
        else:
            seen_titles.setdefault(key, r["id"])
            reprint[r["id"]] = False
    return reprint


def build_events(db) -> int:
    docs = db.q("""SELECT d.* FROM document d JOIN source s ON s.id=d.source_id
                   WHERE s.tier='L1' AND d.body_stored=1 ORDER BY d.published_at""")
    n = 0
    for doc in docs:
        passages = [p["text"] for p in db.passages_for(doc["id"])]
        res = resolvers.resolve(doc["doc_type"], doc["title"], passages)
        if res is None:
            continue
        first_seen = doc["published_at"] or doc["fetched_at"]
        event_id = db.upsert_event(
            slug=_slug(doc), canonical_title=res.title, event_type=res.event_type, grade=res.grade,
            credibility_tier="confirmed", primary_document_id=doc["id"], first_seen=first_seen,
            meta={"source_title": doc["title"]},
        )
        db.set_scope(event_id, population=res.population, industries=res.industries, econ_scale=res.econ_scale,
                     duration_months=res.duration_months, duration_is_estimate=res.duration_is_estimate,
                     score=res.score, notes=res.notes)
        db.add_member(event_id, doc["id"], "primary")
        prior = _prior_document(db, doc)
        if prior:
            db.add_member(event_id, prior["id"], "prior")
        for rel in _related_documents(db, doc):
            db.add_member(event_id, rel["id"], "related")
        media = _media_matches(db, doc, res.media_keywords)
        reprints = _mark_reprints(media)
        for m in media:
            db.add_member(event_id, m["id"], "media", is_reprint=reprints.get(m["id"], False))
        n += 1
    return n
