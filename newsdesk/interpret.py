"""解读流水线：带编号段落 → 模型 → 三道闸门 → 落库。

输入给模型的每一段都有 ID：
  P<passage_id>  官方原文段落（本次文件 / 上一版文件 / 附属文件）
  M<document_id> 媒体标题（只用于「各源差异」；媒体正文不入库也不给模型）
模型必须为每条结论给出 {id, quote}，quote 逐字取自该段。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone

from . import config, gates, llm
from .normalize import norm_text

log = logging.getLogger(__name__)

CONTEXT_CHARS = {"A+": 90_000, "A": 60_000, "B": 30_000, "C": 15_000}
MAX_MEDIA_TITLES = 30

SYSTEM_PROMPT = """你是一个财经资讯站的解读生成器。你不是评论员：只做有原文依据、可核对的陈述。

输入是一组带 ID 的段落：
- P 开头：官方原文（本次文件、上一版文件、附属文件），是唯一的事实依据
- M 开头：媒体报道标题，只能用于「各源差异」

输出一个 JSON 对象（不要任何其他文字），格式：
{
  "claims": [
    {
      "section": "what | changed | magnitude | divergence",
      "text": "一句中文结论",
      "evidence": "E1 | E2",
      "citations": [{"id": "P123", "quote": "从该段逐字复制的原文片段"}],
      "formula": "仅 E2 需要：只含数字与 + - * / ( ) 的算式 = 结果，例如 5.50 - 4.00 = 1.50"
    }
  ],
  "no_prior_version": true/false,
  "sources_consistent": true/false/null
}

四个 section 的含义（固定结构，不要自由发挥）：
1. what（发生了什么）：1 条，一句话事实，谁、做了什么、关键数字
2. changed（变了什么）：本次文件相对上一版文件的条文级改动：删了哪句、加了哪句、数字从多少变到多少。每条同时引用本次和上一版的段落。没有上一版文件时不输出这一节，并把 no_prior_version 设为 true
3. magnitude（量级锚定）：这个数字算大吗——占比、倍数、差值、与历史或预测值对比。只能用输入段落里的数字计算
4. divergence（各源差异）：对照媒体标题与官方原文，只指出与原文**矛盾**的地方（例如标题里的数字与原文不符、把原文没有的决定或措辞说成是原文的）。标题里补充了原文没提、但也不矛盾的背景（例如历史对比、市场反应、人物评价）不算差异。没有矛盾就不输出这一节，并把 sources_consistent 设为 true；没有媒体标题时设为 null

硬规则（违反的结论会被程序自动丢弃）：
- 每条结论至少 1 条引用；quote 必须是该 ID 段落里连续出现的原文，逐字复制，保留原文语言，不要翻译、不要改写、不要省略号拼接，长度 10～200 字符
- 结论里出现的每一个数字，都必须在所引段落中出现；百分点与基点可以换算（1/4 percentage point = 25 个基点，3-3/4 = 3.75）
- 由原文数字计算出来的结论标 E2，并给出 formula，formula 里的每个操作数都必须在所引段落中出现；直接来自原文的结论标 E1。差值、变化幅度（「上升 0.3 个百分点」「多 4 人」）、倍数、占比都是计算结果，必须标 E2
- 一条结论用到几个段落的数字，就把这几个段落都引上（例如「从 6 月的 3.8% 升到 4.1%」要同时引用两个预测值所在的段落）
- 可以用段落标题行里的文件日期指代文件（「7月声明」「9月16日」）
- 分数写法统一换成小数：3-3/4 写作 3.75%，1/4 个百分点写作 25 个基点
- 不预测、不评价好坏、不给投资建议、不写原文没有的背景知识（例如「这是若干年来首次」这类历史判断，除非段落里写了）
- 日期用阿拉伯数字（2026年9月16日）；数字保留原文精度
- 宁可少写，不要凑数：推不出来就不输出
"""


def _passage_block(db, doc, role_label: str, budget: int, used: int) -> tuple[list[str], dict[str, str], int]:
    lines, ids = [], {}
    head = f"\n## {role_label}：{doc['title']}（{doc['source_id']}，{(doc['published_at'] or '')[:10]}）"
    lines.append(head)
    for p in db.passages_for(doc["id"]):
        text = p["text"]
        if used + len(text) > budget:
            lines.append("（后续段落因长度限制省略）")
            break
        pid = f"P{p['id']}"
        ids[pid] = text
        lines.append(f"[{pid}] {text}")
        used += len(text) + len(pid) + 4
    return lines, ids, used


def build_input(db, event) -> tuple[str, dict[str, str], set[str]]:
    """返回 (prompt, {id: text}, 事件内各文件发布日期)"""
    budget = CONTEXT_CHARS.get(event["grade"], 15_000)
    members = db.q("""SELECT m.role, d.* FROM event_member m JOIN document d ON d.id=m.document_id
                      WHERE m.event_id=? ORDER BY CASE m.role WHEN 'primary' THEN 0 WHEN 'related' THEN 1
                      WHEN 'prior' THEN 2 ELSE 3 END, d.published_at""", (event["id"],))
    role_names = {"primary": "本次文件", "related": "本次附属文件", "prior": "上一版文件"}
    lines = [f"# 事件：{event['canonical_title']}"]
    ids: dict[str, str] = {}
    doc_dates: set[str] = set()
    used = 0
    for m in members:
        if m["role"] not in role_names:
            continue
        if m["published_at"]:
            doc_dates.add(m["published_at"][:10])
        block, bids, used = _passage_block(db, m, role_names[m["role"]], budget, used)
        lines += block
        ids.update(bids)
    if not any(m["role"] == "prior" for m in members):
        lines.append("\n（没有上一版文件）")
    media = [m for m in members if m["role"] == "media"]
    reprint = {r["document_id"]: r["is_reprint"] for r in
               db.q("SELECT document_id, is_reprint FROM event_member WHERE event_id=?", (event["id"],))}
    media = [m for m in media if not reprint.get(m["id"])][:MAX_MEDIA_TITLES]
    if media:
        lines.append("\n## 媒体报道标题")
        for m in media:
            mid = f"M{m['id']}"
            ids[mid] = m["title"]
            src = db.one("SELECT name FROM source WHERE id=?", (m["source_id"],))
            lines.append(f"[{mid}] {m['title']}（{src['name'] if src else m['source_id']}）")
    else:
        lines.append("\n（没有媒体报道标题）")
    return "\n".join(lines), ids, doc_dates


def _char_range(text: str, quote: str) -> tuple[int | None, int | None]:
    i = text.lower().find(quote.lower())
    if i >= 0:
        return i, i + len(quote)
    # 空白差异：退回按归一化位置近似
    nt, nq = norm_text(text), norm_text(quote)
    j = nt.find(nq)
    return (j, j + len(nq)) if j >= 0 else (None, None)


def interpret_event(db, event) -> dict:
    prompt, ids, doc_dates = build_input(db, event)
    model = config.GRADE_MODELS.get(event["grade"], config.GRADE_MODELS["C"])
    input_hash = _input_hash(prompt)
    started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    log.info("interpret %s grade=%s model=%s input=%d chars", event["slug"], event["grade"], model, len(prompt))
    try:
        res = llm.complete(model, SYSTEM_PROMPT, prompt)
    except llm.LLMError as e:
        db.log_generation(event_id=event["id"], model_name=model, prompt_version=config.PROMPT_VERSION,
                          input_hash=input_hash, started_at=started, finished_at=_now(), ok=0, error=str(e)[:2000])
        db.commit()
        return {"slug": event["slug"], "ok": False, "error": str(e)[:300]}

    try:
        obj = llm.parse_json(res.text)
    except (ValueError, json.JSONDecodeError) as e:
        obj, parse_err = None, str(e)
    else:
        parse_err = None
    report = gates.run_gates(obj, ids, doc_dates) if obj is not None else gates.GateReport(schema_ok=False,
                                                                                  schema_error=parse_err)
    drop_reasons = [{"text": d["claim"].get("text"), "reason": d["reason"]} for d in report.dropped]
    if not report.schema_ok:
        drop_reasons = [{"reason": f"schema: {report.schema_error}"}]
    db.log_generation(event_id=event["id"], model_name=res.model, prompt_version=config.PROMPT_VERSION,
                      input_hash=input_hash, started_at=started, finished_at=_now(), ok=int(report.schema_ok),
                      claims_total=report.total, claims_kept=len(report.kept), drop_reasons=drop_reasons,
                      raw_output=res.text[:50_000], cost_usd=res.cost_usd)
    if not report.schema_ok:
        db.commit()
        return {"slug": event["slug"], "ok": False, "error": f"schema: {report.schema_error}"}

    return _store(db, event, ids, obj, report, res.model, res.requested_model, res.backend, res.cost_usd)


def _store(db, event, ids, obj, report, model, requested_model, backend, cost_usd, generated_at=None) -> dict:
    drop_reasons = [{"text": d["claim"].get("text"), "reason": d["reason"]} for d in report.dropped]
    status = "ok" if report.kept else "discarded"
    interp_id = db.add_interpretation(
        event_id=event["id"], model_name=model, model_version=None, prompt_version=config.PROMPT_VERSION,
        author=None, status=status,
        sections={"no_prior_version": bool(obj.get("no_prior_version")),
                  "sources_consistent": obj.get("sources_consistent"),
                  "requested_model": requested_model, "backend": backend},
        stats={"claims_total": report.total, "claims_kept": len(report.kept), "cost_usd": cost_usd},
        generated_at=generated_at,
    )
    order = {s: i for i, s in enumerate(gates.SECTIONS)}
    for n, c in enumerate(sorted(report.kept, key=lambda c: order[c["section"]])):
        cites = []
        for g in c["citations"]:
            if g["id"].startswith("P"):
                pid = int(g["id"][1:])
                start, end = _char_range(ids[g["id"]], g["quote"])
                cites.append({"passage_id": pid, "document_id": None, "char_start": start, "char_end": end,
                              "quote": g["quote"], "quote_hash": g["quote_hash"]})
            else:
                cites.append({"passage_id": None, "document_id": int(g["id"][1:]), "char_start": None,
                              "char_end": None, "quote": g["quote"], "quote_hash": g["quote_hash"]})
        db.add_claim(interpretation_id=interp_id, ordinal=n, section=c["section"], text=c["text"],
                     evidence_level=c["evidence"], formula=c["formula"], citations=cites)
    db.commit()
    return {"slug": event["slug"], "ok": True, "model": model, "kept": len(report.kept), "total": report.total,
            "cost_usd": cost_usd, "dropped": drop_reasons}


def regate(db) -> list[dict]:
    """闸门规则改进后，对每个事件最近一次成功生成的原始输出重新过闸门并替换解读。不调用模型。
    只处理和当前提示词版本相同的输出（输入段落 ID 要能对上）。"""
    out = []
    logs = db.q("""SELECT g.* FROM generation_log g WHERE g.ok=1 AND g.raw_output IS NOT NULL AND g.prompt_version=?
                   AND g.id = (SELECT MAX(id) FROM generation_log g2 WHERE g2.event_id=g.event_id AND g2.ok=1
                               AND g2.prompt_version=?)""", (config.PROMPT_VERSION, config.PROMPT_VERSION))
    for g in logs:
        event = db.one("SELECT * FROM event WHERE id=?", (g["event_id"],))
        _, ids, doc_dates = build_input(db, event)
        obj = llm.parse_json(g["raw_output"])
        report = gates.run_gates(obj, ids, doc_dates)
        if not report.schema_ok:
            continue
        prev = db.one("""SELECT * FROM interpretation WHERE event_id=? ORDER BY generated_at DESC, id DESC LIMIT 1""",
                      (event["id"],))
        prev_meta = json.loads(prev["sections"] or "{}") if prev else {}
        prev_kept = json.loads(prev["stats"] or "{}").get("claims_kept") if prev else None
        if prev and prev_kept == len(report.kept):
            continue
        if prev:
            db.conn.execute("UPDATE interpretation SET status='superseded' WHERE event_id=? AND status IN ('ok','discarded')",
                            (event["id"],))
        db.conn.execute("UPDATE generation_log SET claims_kept=?, drop_reasons=? WHERE id=?",
                        (len(report.kept), json.dumps([{"text": d["claim"].get("text"), "reason": d["reason"]}
                                                       for d in report.dropped], ensure_ascii=False), g["id"]))
        r = _store(db, event, ids, obj, report, g["model_name"], prev_meta.get("requested_model", g["model_name"]),
                   prev_meta.get("backend", "claude_cli"), g["cost_usd"], generated_at=g["finished_at"])
        r["before"] = prev_kept
        out.append(r)
    return out


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _input_hash(prompt: str) -> str:
    return hashlib.sha256((config.PROMPT_VERSION + SYSTEM_PROMPT + prompt).encode()).hexdigest()[:24]


def _already_tried(db, event) -> bool:
    """同样的输入已经成功调用过模型（只是没有结论通过闸门）→ 不重复花钱，等输入变化再试。"""
    prompt, _, _ = build_input(db, event)
    return db.one("SELECT 1 FROM generation_log WHERE event_id=? AND input_hash=? AND ok=1",
                  (event["id"], _input_hash(prompt))) is not None


def interpret_pending(db, slug: str | None = None, limit: int = 12, force: bool = False) -> list[dict]:
    if slug:
        events = db.q("SELECT * FROM event WHERE slug=?", (slug,))
    else:
        # 等级高的先做；同级新的先做。未达 C 级只存不解读。
        events = db.q("""SELECT * FROM event WHERE grade <> 'below'
                         ORDER BY CASE grade WHEN 'A+' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END,
                                  first_seen DESC""")
    results = []
    for ev in events:
        if len(results) >= limit:
            break
        if not force and db.has_interpretation(ev["id"]):
            continue
        if not force and _already_tried(db, ev):
            continue
        results.append(interpret_event(db, ev))
    translate_titles(db)
    return results


# ---- 英文标题机器翻译 -------------------------------------------------------
TRANSLATE_SYSTEM = ("把给定的英文新闻标题翻译成简体中文，忠实、简洁、不加评论。"
                    "只输出 JSON 对象：键是输入里的 id（字符串），值是译文。")


def translate_titles(db, batch: int = 40) -> int:
    rows = db.q("""SELECT DISTINCT d.id, d.title, d.meta FROM document d
                   JOIN event_member m ON m.document_id=d.id JOIN event e ON e.id=m.event_id
                   WHERE e.grade <> 'below' AND d.lang='en'
                     AND (d.meta IS NULL OR json_extract(d.meta,'$.title_zh') IS NULL)""")
    done = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i: i + batch]
        payload = json.dumps({str(r["id"]): r["title"] for r in chunk}, ensure_ascii=False)
        try:
            res = llm.complete(config.TRANSLATE_MODEL, TRANSLATE_SYSTEM, payload, max_tokens=4000)
            out = llm.parse_json(res.text)
        except Exception as e:  # noqa: BLE001 — 翻译失败不影响主流程，页面只显示原文
            log.warning("title translation failed: %s", str(e)[:200])
            break
        for r in chunk:
            zh = out.get(str(r["id"]))
            if not zh or not re.search(r"[一-鿿]", zh):
                continue
            meta = json.loads(r["meta"] or "{}")
            meta.update(title_zh=zh.strip(), title_mt_model=res.model)
            db.conn.execute("UPDATE document SET meta=? WHERE id=?", (json.dumps(meta, ensure_ascii=False), r["id"]))
            done += 1
        db.commit()
    return done
