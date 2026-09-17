"""原子发布：把 site/ 整体提交到 gh-pages 分支并推送。

- 只有 build 成功产出完整 site/ 才会调用（cli run 里任何一步失败就不到这里）
- 用独立的临时 git worktree，不碰主分支工作区
- 发布前做完整性检查：index.html / archive.html / data/index.json / robots.txt 必须存在
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from . import config

log = logging.getLogger(__name__)
BRANCH = "gh-pages"
REQUIRED = ["index.html", "archive.html", "about.html", "data/index.json", "robots.txt"]


def _git(*args, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def publish(site_dir: Path, dry_run: bool = False) -> int:
    missing = [p for p in REQUIRED if not (site_dir / p).exists()]
    if missing:
        log.error("site incomplete, refusing to publish: missing %s", missing)
        return 1
    repo = config.ROOT
    if _git("remote", "get-url", "origin", cwd=repo, check=False).returncode != 0:
        log.error("no git remote 'origin'")
        return 1

    with tempfile.TemporaryDirectory(prefix="newsdesk-pages-") as tmp:
        wt = Path(tmp) / "pages"
        _git("fetch", "origin", BRANCH, cwd=repo, check=False)
        has_remote = _git("rev-parse", "--verify", f"origin/{BRANCH}", cwd=repo, check=False).returncode == 0
        if has_remote:
            _git("worktree", "add", "-B", BRANCH, str(wt), f"origin/{BRANCH}", cwd=repo)
        else:
            _git("worktree", "add", "--detach", str(wt), cwd=repo)
            _git("checkout", "--orphan", BRANCH, cwd=wt)
            _git("rm", "-rf", "--quiet", ".", cwd=wt, check=False)
        try:
            for child in wt.iterdir():
                if child.name == ".git":
                    continue
                shutil.rmtree(child) if child.is_dir() else child.unlink()
            shutil.copytree(site_dir, wt, dirs_exist_ok=True)
            _git("add", "-A", cwd=wt)
            if _git("diff", "--cached", "--quiet", cwd=wt, check=False).returncode == 0:
                log.info("site unchanged, nothing to publish")
                return 0
            msg = f"site: build {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            _git("commit", "-m", msg, cwd=wt)
            if dry_run:
                log.info("dry run: committed locally in temp worktree, not pushing")
                return 0
            r = _git("push", "origin", f"HEAD:{BRANCH}", cwd=wt, check=False)
            if r.returncode != 0:
                log.error("push failed: %s", r.stderr[-500:])
                return 1
            log.info("published to %s: %s", BRANCH, config.SITE_BASE_URL)
            return 0
        finally:
            _git("worktree", "remove", "--force", str(wt), cwd=repo, check=False)
            _git("worktree", "prune", cwd=repo, check=False)
