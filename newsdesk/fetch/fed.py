"""美联储适配器（L1）。

RSS 发现 → 抓新闻稿页面 → 段落入 passage。
FOMC 声明额外抓：同日执行说明（...a1.htm）、经济预测表（fomcprojtabl<date>.htm）。
"""
from __future__ import annotations

import html as htmllib
import re
from datetime import datetime, timezone

import feedparser

from .. import http
from ..normalize import canonical_url

BASE = "https://www.federalreserve.gov"
STOP_MARKERS = ("For media inquiries", "Last Update:", "Implementation Note issued")


def classify(title: str) -> str:
    t = title.lower()
    if "issues fomc statement" in t:
        return "fomc_statement"
    if "economic projections" in t:
        return "fomc_sep_release"
    if t.startswith("minutes of the federal open market committee"):
        return "fomc_minutes"
    if "discount rate" in t:
        return "fed_discount_minutes"
    return "fed_other"


def _clean(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", "", fragment)
    text = htmllib.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def extract_paragraphs(page_html: str) -> list[str]:
    """新闻稿正文段落：从「For release at」之后到「For media inquiries」之前的 <p>。"""
    page_html = re.sub(r"<(script|style)\b.*?</\1>", "", page_html, flags=re.S | re.I)
    page_html = re.sub(r"<!--.*?-->", "", page_html, flags=re.S)
    paras = [_clean(p) for p in re.findall(r"<p\b[^>]*>(.*?)</p>", page_html, flags=re.S | re.I)]
    paras = [p for p in paras if p]
    start = next((i + 1 for i, p in enumerate(paras) if p.startswith("For release at")), 0)
    out = []
    for p in paras[start:]:
        if p.startswith(STOP_MARKERS):
            break
        out.append(p)
    return out


def html_lines(page_html: str) -> list[str]:
    """把页面按块级元素拆成行，保留原文顺序（<p> 与 <li> 混排的页面用）。"""
    page_html = re.sub(r"<(script|style|nav|header|footer)\b.*?</\1>", "", page_html, flags=re.S | re.I)
    page_html = re.sub(r"<!--.*?-->", "", page_html, flags=re.S)
    page_html = re.sub(r"</(p|li|tr|h\d|div|caption)>|<br\s*/?>", "\n", page_html, flags=re.I)
    lines = [_clean(x) for x in page_html.split("\n")]
    return [x for x in lines if x]


def extract_impl_note(page_html: str) -> list[str]:
    lines = html_lines(page_html)
    start = next((i for i, x in enumerate(lines) if x.startswith("The Federal Reserve has made the following")), 0)
    out = []
    for x in lines[start:]:
        if x.startswith(("This information will be updated", "More information regarding", "Last Update")):
            break
        out.append(x)
    return out


def extract_vote(page_html: str) -> str | None:
    m = re.search(r"The Federal Open Market Committee approved the following statement for release by a "
                  r"\d+\s*[–-]\s*\d+ vote", _clean(page_html))
    return m.group(0) if m else None


# ---- 经济预测（SEP）表 ----------------------------------------------------
def _rows(table_html: str) -> list[list[str]]:
    rows = []
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table_html, flags=re.S | re.I):
        cells = [_clean(c) for c in re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", tr, flags=re.S | re.I)]
        rows.append(cells)
    return rows


def extract_sep(page_html: str) -> list[tuple[str, str]]:
    """把 Table 1 的中值行与图 2 当年点阵分布转成可被引用的规范句子。"""
    out: list[tuple[str, str]] = []
    tables = re.findall(r"<table\b.*?</table>", page_html, flags=re.S | re.I)
    if not tables:
        return out
    # Table 1
    t1 = _rows(tables[0])
    header_years: list[str] = []
    for r in t1:
        if "2026" in " ".join(r) or re.search(r"20\d\d", " ".join(r)):
            yrs = [c for c in r if re.fullmatch(r"20\d\d|Longer run", c)]
            if len(yrs) >= 3:
                header_years = yrs[: len(yrs) // 3 if len(yrs) >= 9 else len(yrs)]
                break
    current = None
    for r in t1:
        if not r or not r[0]:
            continue
        name = r[0].rstrip("0123456789").strip()
        vals = r[1: 1 + len(header_years)] if header_years else r[1:6]
        if name == "June projection" or name.endswith("projection"):
            if current:
                label = f"SEP {current} ({name}) median"
                out.append(("SEP", f"{label}: " + ", ".join(
                    f"{y} {v if v else 'n/a'}" for y, v in zip(header_years, vals))))
            continue
        if name.startswith("Memo"):
            continue
        if any(re.fullmatch(r"-?\d+\.\d+", v) for v in vals):
            current = name
            out.append(("SEP", f"SEP {name} median projection: " + ", ".join(
                f"{y} {v if v else 'n/a'}" for y, v in zip(header_years, vals))))
    # 图 2 点阵：找含 "Midpoint of target range" 的表
    for tb in tables:
        if "Midpoint of target range" not in tb and "midpoint of target range" not in tb.lower():
            continue
        rows = _rows(tb)
        years = next((r[1:] for r in rows if len(r) > 2 and re.fullmatch(r"20\d\d", r[1] or "")), None)
        if not years:
            break
        dist: dict[str, list[str]] = {y: [] for y in years}
        for r in rows:
            if r and re.fullmatch(r"\d\.\d{3}", r[0] or ""):
                for y, c in zip(years, r[1:]):
                    if c.strip():
                        dist[y].append(f"{c.strip()} participants at {r[0]}")
        for y in years[:2]:
            if dist[y]:
                out.append(("SEP dot plot",
                            f"Dot plot, end of {y}, projected midpoint of the federal funds rate target range: "
                            + "; ".join(dist[y])))
        break
    # 参与人数
    notes = re.findall(r"\w+ participants submitted information in conjunction with the [A-Z][a-z]+ [\d–-]+, \d{4}, meeting",
                       _clean(page_html))
    if notes:
        out.append(("SEP note", notes[-1]))
    return out


# ---- 主流程 --------------------------------------------------------------
def _human_date(d: str) -> str:
    return datetime.strptime(d, "%Y%m%d").strftime("%B %-d, %Y")


def _pub(entry) -> str | None:
    t = entry.get("published_parsed")
    return datetime(*t[:6], tzinfo=timezone.utc).isoformat() if t else None


def _store_page(db, source, url, title, published_at, doc_type, passages, meta=None) -> tuple[int, bool]:
    doc_id, created = db.insert_document(
        source_id=source["id"], url=url, title=title, published_at=published_at, lang="en",
        doc_type=doc_type, body_stored=True, meta=meta,
    )
    if created or not db.passages_for(doc_id):
        db.replace_passages(doc_id, passages)
    return doc_id, created


def fetch(db, source: dict) -> int:
    feed = feedparser.parse(http.get(source["url"]).content)
    new = 0
    for e in feed.entries:
        url = canonical_url(e.link.strip())
        title = e.title.strip()
        doc_type = classify(title)
        existing = db.get_document_by_url(url)
        if existing and db.passages_for(existing["id"]):
            continue
        page = http.get(url).text
        paras = extract_paragraphs(page)
        vote = extract_vote(page) if doc_type == "fomc_statement" else None
        if vote:
            paras = [vote] + paras
        if doc_type == "fomc_minutes":
            paras = paras[:60]  # 纪要很长，第一版只取前 60 段
        passages = [("¶%d" % (i + 1), p) for i, p in enumerate(paras)]
        date = re.search(r"monetary(\d{8})", url)
        meta = {"date": date.group(1)} if date else None
        doc_id, created = _store_page(db, source, url, title, _pub(e), doc_type, passages, meta)
        new += created

        if doc_type == "fomc_statement" and date:
            d = date.group(1)
            impl_url = f"{BASE}/newsevents/pressreleases/monetary{d}a1.htm"
            try:
                impl = http.get(impl_url).text
                _store_page(db, source, impl_url, f"Implementation Note issued {_human_date(d)}", _pub(e),
                            "fomc_impl_note", [("¶%d" % (i + 1), p) for i, p in enumerate(extract_impl_note(impl))],
                            {"date": d, "parent": url})
            except Exception:  # noqa: BLE001 — 附属文件缺失不影响主文档
                pass
        if doc_type == "fomc_sep_release" and date:
            d = date.group(1)
            sep_url = f"{BASE}/monetarypolicy/fomcprojtabl{d}.htm"
            try:
                sep = http.get(sep_url).text
                _store_page(db, source, sep_url, f"Summary of Economic Projections, {_human_date(d)}", _pub(e),
                            "fomc_sep_table", extract_sep(sep), {"date": d, "parent": url})
            except Exception:  # noqa: BLE001
                pass
    return new
