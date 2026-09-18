"""命令行入口：python -m newsdesk <command>

  fetch       抓取所有源（--only fed,stats_cn）
  events      从 L1 文档生成 / 更新事件、范围打分、分级、挂媒体报道
  interpret   为还没有解读的事件生成解读并过三道闸门（--slug 指定事件）
  regate      闸门规则改进后，用库里存的模型原始输出重新过闸门（不调模型）
  build       生成静态站到 site/
  publish     把 site/ 推到 gh-pages（build 成功才推）
  run         fetch → events → interpret → build → publish（任何一步失败即停，不发布）
  stats       打印库里各表行数与闸门丢弃率
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from . import config
from .db import DB


def _db() -> DB:
    db = DB(config.DB_PATH)
    for s in config.load_sources():
        db.upsert_source(s)
    db.commit()
    return db


def cmd_fetch(args) -> int:
    from .fetch import fetch_all
    db = _db()
    only = set(args.only.split(",")) if args.only else None
    report = fetch_all(db, config.load_sources(), only)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    l1_failed = [k for k, v in report.items() if v["error"] and k in {"fed", "stats_cn", "gov_cn"}]
    return 1 if args.strict and l1_failed else 0


def cmd_events(args) -> int:
    from .events import build_events
    db = _db()
    n = build_events(db)
    db.commit()
    print(f"events upserted: {n}")
    return 0


AUTH_FLAG = config.LOG_DIR / "llm-auth-failed"
AUTH_PATTERNS = ("not logged in", "401", "unauthorized", "invalid api key", "authentication")


def cmd_interpret(args) -> int:
    from .interpret import interpret_pending
    db = _db()
    res = interpret_pending(db, slug=args.slug, limit=args.limit, force=args.force)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    # 模型调不通（本机 CLI 掉登录 / key 失效）时留个标记：定时任务据此弹通知，
    # 否则新事件会一直静默地停在「暂无解读」。
    failed = [r for r in res if not r.get("ok") and any(p in (r.get("error") or "").lower()
                                                        for p in AUTH_PATTERNS)]
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    if failed and len(failed) == len([r for r in res if not r.get("ok")]):
        AUTH_FLAG.write_text(failed[0].get("error", "")[:500], encoding="utf-8")
        logging.error("LLM 认证失败，%d 个事件没能生成解读：%s", len(failed), failed[0].get("error", "")[:120])
    elif res:
        AUTH_FLAG.unlink(missing_ok=True)
    return 0


def cmd_regate(args) -> int:
    from .interpret import regate
    db = _db()
    res = regate(db)
    print(json.dumps([{k: r[k] for k in ("slug", "before", "kept", "total")} for r in res], ensure_ascii=False, indent=2))
    return 0


def cmd_build(args) -> int:
    from .site.build import build_site
    db = _db()
    out = build_site(db, config.SITE_DIR)
    print(f"site built: {out}")
    return 0


def cmd_publish(args) -> int:
    from .publish import publish
    return publish(config.SITE_DIR, dry_run=args.dry_run)


def cmd_run(args) -> int:
    steps = [
        ("fetch", lambda: cmd_fetch(argparse.Namespace(only=None, strict=False))),
        ("events", lambda: cmd_events(args)),
        ("interpret", lambda: cmd_interpret(argparse.Namespace(slug=None, limit=config.MAX_INTERPRETATIONS_PER_RUN,
                                                               force=False))),
        ("build", lambda: cmd_build(args)),
    ]
    if not args.no_publish:
        steps.append(("publish", lambda: cmd_publish(argparse.Namespace(dry_run=False))))
    for name, fn in steps:
        logging.info("== step %s", name)
        try:
            rc = fn()
        except Exception:
            logging.exception("step %s crashed; stopping without publish", name)
            return 2
        if rc:
            logging.error("step %s failed rc=%s; stopping without publish", name, rc)
            return rc
    return 0


def cmd_stats(args) -> int:
    db = _db()
    for t in ["source", "document", "passage", "event", "event_member", "interpretation", "claim", "citation",
              "generation_log"]:
        print(f"{t:16} {db.one(f'SELECT COUNT(*) c FROM {t}')['c']}")
    row = db.one("SELECT SUM(claims_total) t, SUM(claims_kept) k FROM generation_log WHERE ok=1")
    if row and row["t"]:
        print(f"claims kept {row['k']}/{row['t']} = {row['k'] / row['t']:.0%}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="newsdesk")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--only")
    f.add_argument("--strict", action="store_true")
    f.set_defaults(fn=cmd_fetch)
    sub.add_parser("events").set_defaults(fn=cmd_events)
    i = sub.add_parser("interpret")
    i.add_argument("--slug")
    i.add_argument("--limit", type=int, default=config.MAX_INTERPRETATIONS_PER_RUN)
    i.add_argument("--force", action="store_true")
    i.set_defaults(fn=cmd_interpret)
    sub.add_parser("regate").set_defaults(fn=cmd_regate)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    pb = sub.add_parser("publish")
    pb.add_argument("--dry-run", action="store_true")
    pb.set_defaults(fn=cmd_publish)
    r = sub.add_parser("run")
    r.add_argument("--no-publish", action="store_true")
    r.set_defaults(fn=cmd_run)
    sub.add_parser("stats").set_defaults(fn=cmd_stats)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
