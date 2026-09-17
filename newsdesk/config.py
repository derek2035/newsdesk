from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("NEWSDESK_DB", ROOT / "data" / "newsdesk.db"))
SITE_DIR = Path(os.environ.get("NEWSDESK_SITE", ROOT / "site"))
LOG_DIR = ROOT / "logs"

SITE_TITLE = "newsdesk · 资讯解读"
SITE_BASE_URL = os.environ.get("NEWSDESK_BASE_URL", "https://derek2035.github.io/newsdesk/")
TIMEZONE = "Asia/Shanghai"  # 「今日」按这个时区切日

# 等级 → 模型（文档「各等级用什么」）；改这里就是改资源开关
GRADE_MODELS = {
    "A+": "claude-fable-5-1",
    "A": "claude-fable-5-1",
    "B": "claude-opus-5",
    "C": "claude-sonnet-5",
}
TRANSLATE_MODEL = "claude-haiku-4-5-20251001"
PROMPT_VERSION = "interp-v3"
MAX_INTERPRETATIONS_PER_RUN = int(os.environ.get("NEWSDESK_MAX_INTERP", "12"))


def load_sources() -> list[dict]:
    data = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    return [{"homepage": None, **s} for s in data["sources"]]
