#!/bin/zsh -l
# launchd 入口：每 30 分钟跑一次。任何一步失败都不发布，站点停在上一个好版本。
# launchd 不继承登录 shell 的 PATH 与环境变量，这里全部显式设置。
set -u

ROOT="/Users/derek/code/newsdesk"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin"
export HOME="${HOME:-/Users/derek}"
export LANG="zh_CN.UTF-8"
# 以登录 shell 启动（见上面的 -l）：这样能读到你在 shell 配置里设置的 ANTHROPIC_* 凭据。
# 只清掉桌面端会话注入的临时变量，用户自己的凭据保留。
unset CLAUDE_CODE_SESSION_ID CLAUDE_CODE_CHILD_SESSION CLAUDE_CODE_ENTRYPOINT

mkdir -p "$ROOT/logs"
cd "$ROOT" || exit 1

# 上一轮还在跑（解读慢）就跳过这一轮，不叠加
LOCK="$ROOT/logs/run.pid"
if ! /usr/bin/shlock -f "$LOCK" -p $$; then
  echo "$(date '+%F %T') skipped: previous run still going (pid $(cat "$LOCK" 2>/dev/null))" >> "$ROOT/logs/skipped.log"
  exit 0
fi
trap 'rm -f "$LOCK"' EXIT

LOG="$ROOT/logs/run-$(date +%Y%m%d-%H%M%S).log"
{
  echo "== newsdesk run $(date)"
  "$ROOT/.venv/bin/python" -m newsdesk run
  RC=$?
  echo "== exit $RC $(date)"
  exit $RC
} >>"$LOG" 2>&1
RC=$?

if [ $RC -ne 0 ]; then
  /usr/bin/osascript -e "display notification \"流水线失败（exit $RC），站点未更新。日志：$LOG\" with title \"newsdesk\" sound name \"Basso\"" 2>/dev/null
fi

# 模型调不通（本机 claude 掉登录）：每天最多提醒一次，避免每半小时弹一次
FLAG="$ROOT/logs/llm-auth-failed"
NOTIFIED="$ROOT/logs/llm-auth-notified"
if [ -f "$FLAG" ]; then
  if [ ! -f "$NOTIFIED" ] || [ $(( $(date +%s) - $(stat -f %m "$NOTIFIED") )) -gt 86400 ]; then
    /usr/bin/osascript -e "display notification \"模型调用失败：本机 claude 未登录，新闻抓到了但没有解读。跑一次 claude 并 /login 即可\" with title \"newsdesk\" sound name \"Basso\"" 2>/dev/null
    touch "$NOTIFIED"
  fi
else
  rm -f "$NOTIFIED"
fi

# 数据库快照：内容有变且距上次快照超过 12 小时才提交，避免每半小时提交一次二进制文件
if [ $RC -eq 0 ] && ! git diff --quiet data/newsdesk.db 2>/dev/null; then
  LAST=$(git log -1 --format=%ct --grep="^data: snapshot" 2>/dev/null || echo 0)
  NOW=$(date +%s)
  if [ $((NOW - ${LAST:-0})) -gt 43200 ]; then
    git add data/newsdesk.db && git commit -q -m "data: snapshot $(date +%Y-%m-%d\ %H:%M)" && git push -q origin HEAD
  fi
fi

# 只保留最近 200 份运行日志
ls -1t "$ROOT"/logs/run-*.log 2>/dev/null | tail -n +201 | xargs rm -f 2>/dev/null
exit $RC
