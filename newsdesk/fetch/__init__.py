"""源适配器。每个适配器 fetch(db, source) -> 新增文档数。

- L1（官方）：写 document + passage（全文段落，证据源）
- L2（媒体）：只写 document（标题 / URL / 时间），不落正文
"""
from __future__ import annotations

import logging

from . import cn_gov, fed, manual, rss, rss_article

log = logging.getLogger(__name__)

ADAPTERS = {
    "rss": rss.fetch,
    "fed_rss": fed.fetch,
    "stats_html": cn_gov.fetch_stats,
    "govcn_json": cn_gov.fetch_govcn,
    "mof_html": cn_gov.fetch_mof,
    "rss_article": rss_article.fetch,
    "manual": manual.fetch,
}


def fetch_all(db, sources: list[dict], only: set[str] | None = None) -> dict[str, dict]:
    """逐源抓取，单源失败不影响其他源。返回每源的 {new, error}。"""
    report: dict[str, dict] = {}
    for s in sources:
        if only and s["id"] not in only:
            continue
        fn = ADAPTERS.get(s["fetch_method"])
        if fn is None:
            continue
        try:
            n = fn(db, s)
            db.commit()
            report[s["id"]] = {"new": n, "error": None}
            log.info("fetch %-12s new=%d", s["id"], n)
        except Exception as e:  # noqa: BLE001 — 单源失败要记录而不是中断整次运行
            db.conn.rollback()
            report[s["id"]] = {"new": 0, "error": f"{type(e).__name__}: {e}"}
            log.warning("fetch %-12s FAILED: %s", s["id"], e)
    return report
