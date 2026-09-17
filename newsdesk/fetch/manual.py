"""手工补录的媒体报道（L2）：只存标题 / URL / 时间 / 转载关系。

用于 RSS 已经滚出窗口、但调研时确认存在的报道。文件格式见 config/manual_documents.yaml。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from ..normalize import canonical_url

ROOT = Path(__file__).resolve().parents[2]


def _iso(v):
    """YAML 会把时间解析成 datetime，统一转回 ISO 字符串。"""
    return v.isoformat() if hasattr(v, "isoformat") else v


def fetch(db, source: dict) -> int:
    data = yaml.safe_load((ROOT / source["url"]).read_text(encoding="utf-8"))
    for s in data.get("sources", []):
        db.upsert_source({"tier": "L2", "fetch_method": "manual_ref", "display_policy": "title_only",
                          "url": None, "homepage": None, **s})
    new = 0
    for d in data.get("documents", []):
        meta = {k: str(d[k]) for k in ("reprint_of", "author", "note", "event_date") if d.get(k)}
        meta["manual"] = True
        _, created = db.insert_document(
            source_id=d["source_id"], url=d["url"] if "#" in d["url"] else canonical_url(d["url"]), title=d["title"],
            published_at=_iso(d.get("published_at")), lang=d.get("lang"), doc_type="media",
            body_stored=False, meta=meta,
        )
        new += created
    return new
