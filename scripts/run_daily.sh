#!/bin/zsh
# launchd 入口：每天跑一次完整流水线。任何一步失败都不发布，站点停在上一个好版本。
# launchd 不继承登录 shell 的 PATH 与环境变量，这里全部显式设置。
set -u

ROOT="/Users/derek/code/newsdesk"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin"
export HOME="${HOME:-/Users/derek}"
export LANG="zh_CN.UTF-8"
# 不让上层会话的认证变量干扰 `claude -p`（它会用本机登录的订阅账号）
unset ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL CLAUDE_CODE_SESSION_ID CLAUDE_CODE_CHILD_SESSION

mkdir -p "$ROOT/logs"
LOG="$ROOT/logs/run-$(date +%Y%m%d-%H%M%S).log"
cd "$ROOT" || exit 1

{
  echo "== newsdesk run $(date)"
  "$ROOT/.venv/bin/python" -m newsdesk run
  RC=$?
  echo "== exit $RC $(date)"
  if [ $RC -eq 0 ]; then
    # 数据库随 git 备份（原始数据全存是分级可纠错的前提）
    git add data/newsdesk.db && git commit -q -m "data: daily snapshot $(date +%Y-%m-%d)" && git push -q origin HEAD 2>&1
  fi
  exit $RC
} >>"$LOG" 2>&1
RC=$?

if [ $RC -ne 0 ]; then
  /usr/bin/osascript -e "display notification \"流水线失败（exit $RC），站点未更新。日志：$LOG\" with title \"newsdesk\" sound name \"Basso\""
fi
# 只保留最近 30 份日志
ls -1t "$ROOT"/logs/run-*.log 2>/dev/null | tail -n +31 | xargs rm -f 2>/dev/null
exit $RC
