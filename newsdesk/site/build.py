"""静态站生成：从 SQLite 物化出全部页面。没有后端，交互全靠页面内嵌 JSON + 原生 JS。

输出：
  index.html            今日流（按北京时间切日，最近 14 天）
  events/<slug>.html    事件卡
  archive.html          归档搜索（读 data/index.json，客户端筛选）
  about.html            方法说明
  data/index.json       归档索引
  robots.txt            全站 Disallow（第二道锁；页面另有 noindex）
"""
from __future__ import annotations

import json
import shutil
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .. import config

HERE = Path(__file__).parent
TZ = ZoneInfo(config.TIMEZONE)
GRADE_RANK = {"A+": 0, "A": 1, "B": 2, "C": 3, "below": 4}
SECTION_TITLES = {"what": "发生了什么", "changed": "变了什么", "magnitude": "量级锚定", "divergence": "各源差异"}
CRED_LABELS = {"confirmed": "已确认", "unconfirmed": "多方报道但未经官方确认", "doubtful": "来源存疑"}
TYPE_LABELS = {"central_bank_rate": "央行利率决议", "central_bank_minutes": "央行会议纪要",
               "central_bank_admin": "央行程序性文件", "central_bank_other": "央行其他",
               "econ_data_release": "经济数据发布", "policy_document": "政策文件"}


# ---- 格式化 ---------------------------------------------------------------
def _local(ts: str | None) -> datetime | None:
    if not ts:
        return None
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ)


def fmt_time(ts: str | None, with_date: bool = True) -> str:
    dt = _local(ts)
    if not dt:
        return "时间未知"
    return dt.strftime("%Y-%m-%d %H:%M" if with_date else "%H:%M")


def fmt_people(n: float | None) -> str:
    if not n:
        return "未知"
    return f"{n / 1e8:.2f} 亿" if n >= 1e8 else f"{n / 1e4:.0f} 万"


def fmt_usd(n: float | None) -> str:
    if not n:
        return "未知"
    if n >= 1e12:
        return f"{n / 1e12:.1f} 万亿美元"
    if n >= 1e8:
        return f"{n / 1e8:.0f} 亿美元"
    return f"{n:,.0f} 美元"


def fmt_months(n: float | None) -> str:
    if not n:
        return "未知"
    return f"约 {n:g} 个月"


# ---- 物化 -----------------------------------------------------------------
def _meta(row) -> dict:
    return json.loads(row["meta"] or "{}") if row["meta"] else {}


def materialize_event(db, ev) -> dict:
    scope = db.one("SELECT * FROM event_scope WHERE event_id=?", (ev["id"],))
    sources = {r["id"]: dict(r) for r in db.q("SELECT * FROM source")}
    members = db.q("""SELECT m.role, m.is_reprint, d.* FROM event_member m JOIN document d ON d.id=m.document_id
                      WHERE m.event_id=?""", (ev["id"],))

    def doc_view(m):
        meta = _meta(m)
        src = sources.get(m["source_id"], {})
        return {"id": m["id"], "title": m["title"], "title_zh": meta.get("title_zh"),
                "mt_model": meta.get("title_mt_model"), "url": m["url"].split("#")[0], "lang": m["lang"],
                "source": src.get("name", m["source_id"]), "tier": src.get("tier"), "role": m["role"],
                "published_at": m["published_at"], "time": fmt_time(m["published_at"]),
                "note": meta.get("note"), "reprint_of_source": None}

    official = [doc_view(m) for m in members if m["role"] in ("primary", "related", "prior")]
    role_order = {"primary": 0, "related": 1, "prior": 2}
    official.sort(key=lambda d: (role_order[d["role"]], d["published_at"] or ""))
    media_all = [(m, doc_view(m)) for m in members if m["role"] == "media"]
    media = sorted([v for m, v in media_all if not m["is_reprint"]], key=lambda d: d["published_at"] or "9999")
    reprints = sorted([v for m, v in media_all if m["is_reprint"]], key=lambda d: d["published_at"] or "9999")

    interp = db.one("""SELECT * FROM interpretation WHERE event_id=? AND status IN ('ok','manual')
                       ORDER BY generated_at DESC LIMIT 1""", (ev["id"],))
    interpretation = None
    cites: dict[str, dict] = {}
    if interp:
        sections = defaultdict(list)
        claims = db.q("SELECT * FROM claim WHERE interpretation_id=? ORDER BY ordinal", (interp["id"],))
        n = 0
        for c in claims:
            refs = []
            for cit in db.q("SELECT * FROM citation WHERE claim_id=?", (c["id"],)):
                n += 1
                key = f"c{n}"
                if cit["passage_id"]:
                    p = db.one("""SELECT p.*, d.title doc_title, d.url doc_url, d.source_id, d.published_at doc_time FROM passage p
                                  JOIN document d ON d.id=p.document_id WHERE p.id=?""", (cit["passage_id"],))
                    cites[key] = {"kind": "passage", "passage_id": p["id"], "text": p["text"], "quote": cit["quote"],
                                  "doc_title": p["doc_title"], "url": p["doc_url"],
                                  "source": sources.get(p["source_id"], {}).get("name", p["source_id"]),
                                  "label": p["label"], "date": fmt_time(p["doc_time"])[:10]}
                else:
                    d = db.one("SELECT * FROM document WHERE id=?", (cit["document_id"],))
                    cites[key] = {"kind": "headline", "text": d["title"], "quote": cit["quote"],
                                  "doc_title": d["title"], "url": d["url"].split("#")[0],
                                  "source": sources.get(d["source_id"], {}).get("name", d["source_id"]),
                                  "label": "标题", "date": fmt_time(d["published_at"])[:10]}
                refs.append({"key": key, "n": n})
            sections[c["section"]].append({"text": c["text"], "evidence": c["evidence_level"], "formula": c["formula"],
                                           "refs": refs})
        sec_meta = json.loads(interp["sections"] or "{}")
        stats = json.loads(interp["stats"] or "{}")
        interpretation = {
            "model": interp["model_name"], "requested_model": sec_meta.get("requested_model"),
            "backend": sec_meta.get("backend"), "generated_at": fmt_time(interp["generated_at"]),
            "prompt_version": interp["prompt_version"], "author": interp["author"],
            "sections": [{"key": k, "title": SECTION_TITLES[k], "claims": sections.get(k, [])}
                         for k in SECTION_TITLES],
            "no_prior_version": sec_meta.get("no_prior_version"),
            "sources_consistent": sec_meta.get("sources_consistent"),
            "claims_total": stats.get("claims_total"), "claims_kept": stats.get("claims_kept"),
        }
        whats = sections.get("what") or []
        interpretation["one_line"] = whats[0] if whats else None
        # 「发生了什么」如果只有这一句，就不再单列一节：它已经在页首
        if interpretation["one_line"] and len(whats) == 1:
            interpretation["sections"] = [s for s in interpretation["sections"] if s["key"] != "what"]

    # 被引用的段落 → 原文里高亮
    quotes_by_passage: dict[int, list[str]] = defaultdict(list)
    for c in cites.values():
        if c["kind"] == "passage":
            quotes_by_passage[c["passage_id"]].append(c["quote"])

    # 新闻内容：官方原文全文（L1 可全文展示），被引用处高亮
    def doc_full(m):
        view = doc_view(m)
        view["passages"] = [{"id": p["id"], "label": p["label"], "text": p["text"],
                             "quotes": quotes_by_passage.get(p["id"], [])}
                            for p in db.passages_for(m["id"])]
        view["cited_count"] = sum(1 for p in view["passages"] if p["quotes"])
        return view

    primary_doc = next((doc_full(m) for m in members if m["role"] == "primary"), None)
    other_docs = [doc_full(m) for m in members if m["role"] in ("related", "prior")]
    other_docs.sort(key=lambda d: (role_order[d["role"]], d["published_at"] or ""))

    notes = json.loads(scope["notes"] or "{}") if scope and scope["notes"] else {}
    return {
        "id": ev["id"], "slug": ev["slug"], "title": ev["canonical_title"], "grade": ev["grade"],
        "credibility": ev["credibility_tier"], "credibility_label": CRED_LABELS.get(ev["credibility_tier"], ""),
        "event_type": ev["event_type"], "event_type_label": TYPE_LABELS.get(ev["event_type"], ev["event_type"]),
        "first_seen": ev["first_seen"], "time": fmt_time(ev["first_seen"]),
        "date": (_local(ev["first_seen"]) or datetime.now(TZ)).date().isoformat(),
        "scope": {
            "population": fmt_people(scope["population"]) if scope else "未知",
            "industries": f"{scope['industries']} 个" if scope and scope["industries"] else "未知",
            "econ_scale": fmt_usd(scope["econ_scale"]) if scope else "未知",
            "duration": fmt_months(scope["duration_months"]) if scope else "未知",
            "duration_is_estimate": bool(scope and scope["duration_is_estimate"]),
            "score": scope["score"] if scope else None, "notes": notes,
        },
        "official": official, "media": media, "reprints": reprints,
        "sources_list": sorted({d["source"] for d in official + media}),
        "interpretation": interpretation, "cites": cites,
        "primary_doc": primary_doc, "other_docs": other_docs,
    }


# ---- 页面 -----------------------------------------------------------------
def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.globals.update(site_title=config.SITE_TITLE, section_titles=SECTION_TITLES)
    # <script type="application/json"> 里不能做 HTML 转义，只需防止提前闭合 </script>
    env.filters["json_script"] = lambda v: Markup(json.dumps(v, ensure_ascii=False).replace("<", "\\u003c"))
    # HTML 属性里交给自动转义处理
    env.filters["json_attr"] = lambda v: json.dumps(v, ensure_ascii=False)
    return env


def build_site(db, out_dir: Path) -> Path:
    tmp = out_dir.with_name(out_dir.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    (tmp / "events").mkdir(parents=True)
    (tmp / "data").mkdir()
    shutil.copytree(HERE / "static", tmp / "static")

    env = _env()
    built_at = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    events = [materialize_event(db, ev) for ev in db.q("SELECT * FROM event ORDER BY first_seen DESC")]

    for ev in events:
        if ev["grade"] == "below":
            continue
        html = env.get_template("event.html").render(ev=ev, root="../", built_at=built_at, page="event")
        (tmp / "events" / f"{ev['slug']}.html").write_text(html, encoding="utf-8")

    # 今日流：最近 14 天，按天分组；组内按时间倒序（第 1 版不做分级排序与「被低估」栏）
    today = datetime.now(TZ).date()
    days = []
    for i in range(14):
        d = (today - timedelta(days=i)).isoformat()
        day_events = [e for e in events if e["date"] == d]
        shown = [e for e in day_events if e["grade"] != "below"]
        below = [e for e in day_events if e["grade"] == "below"]
        if shown or below:
            days.append({"date": d, "is_today": i == 0, "events": shown, "below": below})
    (tmp / "index.html").write_text(
        env.get_template("index.html").render(days=days, root="", built_at=built_at, page="index"), encoding="utf-8")

    index = [{"slug": e["slug"], "title": e["title"], "grade": e["grade"], "type": e["event_type"],
              "type_label": e["event_type_label"], "date": e["date"], "time": e["time"],
              "sources": e["sources_list"],
              "primary_source": next((d["source"] for d in e["official"] if d["role"] == "primary"), ""),
              "media_count": len(e["media"]),
              "summary": e["interpretation"]["one_line"]["text"] if e["interpretation"] and
              e["interpretation"]["one_line"] else "",
              "has_interp": bool(e["interpretation"])} for e in events]
    (tmp / "data" / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    (tmp / "archive.html").write_text(
        env.get_template("archive.html").render(root="", built_at=built_at, page="archive",
                                                types=TYPE_LABELS), encoding="utf-8")
    stats = db.one("SELECT COALESCE(SUM(claims_total),0) t, COALESCE(SUM(claims_kept),0) k FROM generation_log WHERE ok=1")
    (tmp / "about.html").write_text(
        env.get_template("about.html").render(root="", built_at=built_at, page="about",
                                              sources=[dict(r) for r in db.q(
                                                  "SELECT * FROM source WHERE fetch_method<>'manual_ref' ORDER BY tier, id")],
                                              grade_models=config.GRADE_MODELS, gate_stats=stats),
        encoding="utf-8")
    (tmp / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    (tmp / ".nojekyll").write_text("", encoding="utf-8")

    # 原子替换：全部生成成功才换掉旧站
    if out_dir.exists():
        shutil.rmtree(out_dir)
    tmp.rename(out_dir)
    return out_dir
