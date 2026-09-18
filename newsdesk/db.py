"""SQLite 存储：文档里的 9 张核心表 + generation_log。

原则：
- 所有事件的原始数据全存（分级可纠错的前提）
- L2 媒体文档 body_stored 恒为 0，只有标题 / URL / 时间
- 每次生成都写 generation_log，从第一天就有审计轨迹
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS source (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  tier TEXT NOT NULL,
  lang TEXT NOT NULL,
  fetch_method TEXT NOT NULL,
  display_policy TEXT NOT NULL,
  url TEXT,
  homepage TEXT
);
CREATE TABLE IF NOT EXISTS document (
  id INTEGER PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES source(id),
  url TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  published_at TEXT,
  fetched_at TEXT NOT NULL,
  simhash TEXT,
  body_stored INTEGER NOT NULL DEFAULT 0,
  lang TEXT,
  doc_type TEXT,
  meta TEXT
);
CREATE INDEX IF NOT EXISTS idx_document_published ON document(published_at);
CREATE TABLE IF NOT EXISTS passage (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES document(id),
  ordinal INTEGER NOT NULL,
  label TEXT NOT NULL,
  text TEXT NOT NULL,
  embedding BLOB,
  UNIQUE(document_id, ordinal)
);
CREATE TABLE IF NOT EXISTS event (
  id INTEGER PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  first_seen TEXT NOT NULL,
  canonical_title TEXT NOT NULL,
  title_zh TEXT,
  title_is_mt INTEGER NOT NULL DEFAULT 0,
  event_type TEXT NOT NULL,
  grade TEXT NOT NULL,
  graded_at TEXT NOT NULL,
  credibility_tier TEXT NOT NULL,
  one_line_fact TEXT,
  primary_document_id INTEGER REFERENCES document(id),
  meta TEXT
);
CREATE TABLE IF NOT EXISTS event_scope (
  event_id INTEGER PRIMARY KEY REFERENCES event(id),
  population REAL,
  industries INTEGER,
  econ_scale REAL,
  duration_months REAL,
  duration_is_estimate INTEGER NOT NULL DEFAULT 1,
  score REAL,
  notes TEXT
);
CREATE TABLE IF NOT EXISTS event_member (
  event_id INTEGER NOT NULL REFERENCES event(id),
  document_id INTEGER NOT NULL REFERENCES document(id),
  role TEXT NOT NULL,          -- primary | prior | related | media
  similarity REAL,
  is_reprint INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(event_id, document_id)
);
CREATE TABLE IF NOT EXISTS interpretation (
  id INTEGER PRIMARY KEY,
  event_id INTEGER NOT NULL REFERENCES event(id),
  model_name TEXT NOT NULL,
  model_version TEXT,
  prompt_version TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  author TEXT,
  status TEXT NOT NULL,        -- ok | manual | discarded
  sections TEXT,               -- JSON: what / changed / magnitude / divergence
  stats TEXT
);
CREATE TABLE IF NOT EXISTS claim (
  id INTEGER PRIMARY KEY,
  interpretation_id INTEGER NOT NULL REFERENCES interpretation(id),
  ordinal INTEGER NOT NULL,
  section TEXT NOT NULL,
  text TEXT NOT NULL,
  evidence_level TEXT NOT NULL, -- E1 | E2 | R（推演）
  formula TEXT,
  extra TEXT,                   -- 推演用：trigger / watch / horizon / counter
  status TEXT NOT NULL DEFAULT 'ok'
);
CREATE TABLE IF NOT EXISTS citation (
  id INTEGER PRIMARY KEY,
  claim_id INTEGER NOT NULL REFERENCES claim(id),
  passage_id INTEGER REFERENCES passage(id),     -- 官方原文段落
  document_id INTEGER REFERENCES document(id),   -- 或媒体标题（只存标题，没有段落）
  char_start INTEGER,
  char_end INTEGER,
  quote TEXT,
  quote_hash TEXT
);
CREATE TABLE IF NOT EXISTS generation_log (
  id INTEGER PRIMARY KEY,
  event_id INTEGER REFERENCES event(id),
  model_name TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  ok INTEGER NOT NULL DEFAULT 0,
  claims_total INTEGER,
  claims_kept INTEGER,
  drop_reasons TEXT,
  raw_output TEXT,
  cost_usd REAL,
  error TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class DB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=60)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        cols = {r["name"] for r in self.q("PRAGMA table_info(claim)")}
        if "extra" not in cols:
            self.conn.execute("ALTER TABLE claim ADD COLUMN extra TEXT")
            self.commit()

    # ---- generic helpers -------------------------------------------------
    def q(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, tuple(params)).fetchall()

    def one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, tuple(params)).fetchone()

    def commit(self) -> None:
        self.conn.commit()

    # ---- source ----------------------------------------------------------
    def upsert_source(self, s: dict) -> None:
        self.conn.execute(
            """INSERT INTO source(id,name,tier,lang,fetch_method,display_policy,url,homepage)
               VALUES(:id,:name,:tier,:lang,:fetch_method,:display_policy,:url,:homepage)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, tier=excluded.tier,
                 lang=excluded.lang, fetch_method=excluded.fetch_method,
                 display_policy=excluded.display_policy, url=excluded.url, homepage=excluded.homepage""",
            {"homepage": None, **s},
        )

    # ---- document / passage ---------------------------------------------
    def get_document_by_url(self, url: str) -> sqlite3.Row | None:
        return self.one("SELECT * FROM document WHERE url=?", (url,))

    def insert_document(self, *, source_id: str, url: str, title: str, published_at: str | None,
                        lang: str | None = None, doc_type: str | None = None,
                        body_stored: bool = False, meta: dict | None = None) -> tuple[int, bool]:
        """返回 (document_id, created)。同 URL 已存在时不覆盖。"""
        row = self.get_document_by_url(url)
        if row:
            return row["id"], False
        cur = self.conn.execute(
            """INSERT INTO document(source_id,url,title,published_at,fetched_at,body_stored,lang,doc_type,meta)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (source_id, url, title, published_at, now_iso(), int(body_stored), lang, doc_type,
             json.dumps(meta, ensure_ascii=False) if meta else None),
        )
        return cur.lastrowid, True

    def replace_passages(self, document_id: int, passages: list[tuple[str, str]]) -> None:
        """passages: [(label, text)]。只对 L1 调用。"""
        self.conn.execute("DELETE FROM passage WHERE document_id=?", (document_id,))
        self.conn.executemany(
            "INSERT INTO passage(document_id,ordinal,label,text) VALUES(?,?,?,?)",
            [(document_id, i, label, text) for i, (label, text) in enumerate(passages)],
        )
        self.conn.execute("UPDATE document SET body_stored=1 WHERE id=?", (document_id,))

    def passages_for(self, document_id: int) -> list[sqlite3.Row]:
        return self.q("SELECT * FROM passage WHERE document_id=? ORDER BY ordinal", (document_id,))

    # ---- event -----------------------------------------------------------
    GRADE_ORDER = {"below": -1, "C": 0, "B": 1, "A": 2, "A+": 3}

    def get_event_by_slug(self, slug: str) -> sqlite3.Row | None:
        return self.one("SELECT * FROM event WHERE slug=?", (slug,))

    def upsert_event(self, *, slug: str, canonical_title: str, event_type: str, grade: str,
                     credibility_tier: str, primary_document_id: int | None, first_seen: str,
                     title_zh: str | None = None, title_is_mt: bool = False,
                     one_line_fact: str | None = None, meta: dict | None = None) -> int:
        """等级只升不降。"""
        row = self.get_event_by_slug(slug)
        if row:
            new_grade = grade if self.GRADE_ORDER[grade] > self.GRADE_ORDER[row["grade"]] else row["grade"]
            self.conn.execute(
                """UPDATE event SET canonical_title=?, title_zh=COALESCE(?,title_zh), title_is_mt=?,
                   grade=?, graded_at=CASE WHEN grade<>? THEN ? ELSE graded_at END,
                   credibility_tier=?, one_line_fact=COALESCE(?,one_line_fact), meta=COALESCE(?,meta)
                   WHERE id=?""",
                (canonical_title, title_zh, int(title_is_mt), new_grade, new_grade, now_iso(),
                 credibility_tier, one_line_fact,
                 json.dumps(meta, ensure_ascii=False) if meta else None, row["id"]),
            )
            return row["id"]
        cur = self.conn.execute(
            """INSERT INTO event(slug,first_seen,canonical_title,title_zh,title_is_mt,event_type,grade,graded_at,
                                 credibility_tier,one_line_fact,primary_document_id,meta)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (slug, first_seen, canonical_title, title_zh, int(title_is_mt), event_type, grade, now_iso(),
             credibility_tier, one_line_fact, primary_document_id,
             json.dumps(meta, ensure_ascii=False) if meta else None),
        )
        return cur.lastrowid

    def set_scope(self, event_id: int, *, population, industries, econ_scale, duration_months,
                  duration_is_estimate: bool, score, notes: dict | None = None) -> None:
        self.conn.execute(
            """INSERT INTO event_scope(event_id,population,industries,econ_scale,duration_months,
                                       duration_is_estimate,score,notes)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(event_id) DO UPDATE SET population=excluded.population,
                 industries=excluded.industries, econ_scale=excluded.econ_scale,
                 duration_months=excluded.duration_months, duration_is_estimate=excluded.duration_is_estimate,
                 score=excluded.score, notes=excluded.notes""",
            (event_id, population, industries, econ_scale, duration_months, int(duration_is_estimate), score,
             json.dumps(notes, ensure_ascii=False) if notes else None),
        )

    def add_member(self, event_id: int, document_id: int, role: str, similarity: float | None = None,
                   is_reprint: bool = False) -> None:
        self.conn.execute(
            """INSERT INTO event_member(event_id,document_id,role,similarity,is_reprint) VALUES(?,?,?,?,?)
               ON CONFLICT(event_id,document_id) DO UPDATE SET role=excluded.role,
                 similarity=excluded.similarity, is_reprint=excluded.is_reprint""",
            (event_id, document_id, role, similarity, int(is_reprint)),
        )

    # ---- interpretation / claims ----------------------------------------
    def has_interpretation(self, event_id: int) -> bool:
        return self.one("SELECT 1 FROM interpretation WHERE event_id=? AND status IN ('ok','manual')",
                        (event_id,)) is not None

    def add_interpretation(self, *, event_id: int, model_name: str, model_version: str | None,
                           prompt_version: str, author: str | None, status: str,
                           sections: dict, stats: dict | None = None, generated_at: str | None = None) -> int:
        cur = self.conn.execute(
            """INSERT INTO interpretation(event_id,model_name,model_version,prompt_version,generated_at,
                                          author,status,sections,stats)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (event_id, model_name, model_version, prompt_version, generated_at or now_iso(), author, status,
             json.dumps(sections, ensure_ascii=False), json.dumps(stats, ensure_ascii=False) if stats else None),
        )
        return cur.lastrowid

    def add_claim(self, *, interpretation_id: int, ordinal: int, section: str, text: str,
                  evidence_level: str, formula: str | None,
                  citations: list[dict], extra: dict | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO claim(interpretation_id,ordinal,section,text,evidence_level,formula,extra)"
            " VALUES(?,?,?,?,?,?,?)",
            (interpretation_id, ordinal, section, text, evidence_level, formula,
             json.dumps(extra, ensure_ascii=False) if extra else None),
        )
        cid = cur.lastrowid
        self.conn.executemany(
            "INSERT INTO citation(claim_id,passage_id,document_id,char_start,char_end,quote,quote_hash)"
            " VALUES(?,?,?,?,?,?,?)",
            [(cid, c.get("passage_id"), c.get("document_id"), c.get("char_start"), c.get("char_end"), c.get("quote"),
              c.get("quote_hash"))
             for c in citations],
        )
        return cid

    def log_generation(self, **kw) -> int:
        cols = ["event_id", "model_name", "prompt_version", "input_hash", "started_at", "finished_at", "ok",
                "claims_total", "claims_kept", "drop_reasons", "raw_output", "cost_usd", "error"]
        vals = [kw.get(c) for c in cols]
        if isinstance(vals[9], (dict, list)):
            vals[9] = json.dumps(vals[9], ensure_ascii=False)
        cur = self.conn.execute(
            f"INSERT INTO generation_log({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)
        return cur.lastrowid
