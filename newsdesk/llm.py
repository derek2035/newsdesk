"""LLM 调用：纯函数「给定输入，按 schema 返回 JSON」。

两个后端：
- anthropic：环境里有 ANTHROPIC_API_KEY 时用官方 SDK，temperature=0
- claude_cli：否则用本机 `claude -p`（订阅额度）。关掉工具、替换系统提示词、在空目录里跑，
  并剥掉上层会话注入的认证环境变量。CLI 不支持 temperature，靠 schema + 校验闸门兜底。

模型不可用（网关无通道 / 超时）时按 FALLBACKS 降级，调用方拿到的 model 是实际使用的模型。
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

FALLBACKS = {
    "claude-fable-5-1": ["claude-opus-5"],
    "claude-opus-5": ["claude-sonnet-5"],
    "claude-sonnet-5": ["claude-haiku-4-5-20251001"],
}
CLI_TIMEOUT = int(os.environ.get("NEWSDESK_LLM_TIMEOUT", "600"))
# 本会话（Claude Code 桌面端）注入的临时凭据不能给子进程用：它只对当前会话有效。
# 用户自己的凭据写在登录 shell 的配置里，launchd 与子进程都读不到，所以启动时从登录 shell 取一次。
_SESSION_ENV = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT",
                "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_HOST_SESSION_ID",
                "CLAUDE_CODE_EXECPATH", "CLAUDE_PID")
_CRED_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")
_login_creds: dict[str, str] | None = None


def login_shell_credentials() -> dict[str, str]:
    """从登录 shell 读取用户自己的 Anthropic 凭据（只读取，不落盘、不打印）。"""
    global _login_creds
    if _login_creds is not None:
        return _login_creds
    _login_creds = {}
    shell = os.environ.get("SHELL", "/bin/zsh")
    script = "; ".join(f'printf "%s\\n" "${{{v}:-}}"' for v in _CRED_VARS)
    try:
        proc = subprocess.run([shell, "-lc", script], capture_output=True, text=True, timeout=25)
        values = proc.stdout.split("\n")
        for name, value in zip(_CRED_VARS, values):
            if value.strip():
                _login_creds[name] = value.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    log.info("login shell credentials: %s", ", ".join(sorted(_login_creds)) or "（无，回退到本机 claude 登录态）")
    return _login_creds


def child_env() -> dict[str, str]:
    """给 `claude -p --bare` 用的环境。

    --bare 只认 ANTHROPIC_API_KEY（不读钥匙串、不弹自定义密钥确认），所以把用户的
    AUTH_TOKEN 也按 key 传入；网关地址取项目配置，配置没写才用环境里的。
    令牌只在进程内传递，不写文件、不记日志。
    """
    from . import config
    env = {k: v for k, v in os.environ.items() if k not in _SESSION_ENV}
    creds = login_shell_credentials()
    key = creds.get("ANTHROPIC_API_KEY") or creds.get("ANTHROPIC_AUTH_TOKEN")
    for v in _CRED_VARS:
        env.pop(v, None)
    if key:
        env["ANTHROPIC_API_KEY"] = key
    base = config.LLM_BASE_URL or creds.get("ANTHROPIC_BASE_URL")
    if base:
        env["ANTHROPIC_BASE_URL"] = base
    return env


UNAVAILABLE_TTL = 24 * 3600
_UNAVAILABLE_FILE = os.environ.get("NEWSDESK_UNAVAILABLE_FILE",
                                   os.path.join(os.path.dirname(__file__), "..", "data", "model_unavailable.json"))


def _load_unavailable() -> dict[str, float]:
    try:
        with open(_UNAVAILABLE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {m: t for m, t in data.items() if time.time() - t < UNAVAILABLE_TTL}
    except (OSError, ValueError):
        return {}


def _mark_unavailable(model: str) -> None:
    data = _load_unavailable()
    data[model] = time.time()
    try:
        with open(_UNAVAILABLE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


class LLMError(Exception):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    cost_usd: float | None
    backend: str
    requested_model: str


def backend() -> str:
    """NEWSDESK_LLM_BACKEND=anthropic 时走官方 SDK（可设 temperature=0）；默认走本机 claude -p。"""
    return "anthropic" if os.environ.get("NEWSDESK_LLM_BACKEND") == "anthropic" else "claude_cli"


def _call_anthropic(model: str, system: str, prompt: str, max_tokens: int) -> LLMResult:
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(model=model, max_tokens=max_tokens, temperature=0, system=system,
                                 messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    return LLMResult(text=text, model=msg.model, cost_usd=None, backend="anthropic", requested_model=model)


def _call_cli(model: str, system: str, prompt: str) -> LLMResult:
    env = child_env()
    # --bare：跳过 CLAUDE.md 发现、钩子、插件，认证严格走 ANTHROPIC_API_KEY —— 定时任务要的就是这种纯函数调用
    cmd = ["claude", "-p", prompt, "--model", model, "--output-format", "json", "--bare", "--tools", "",
           "--system-prompt", system, "--no-session-persistence"]
    with tempfile.TemporaryDirectory(prefix="newsdesk-llm-") as cwd:  # 空目录：不读任何 CLAUDE.md
        try:
            proc = subprocess.run(cmd, input="", capture_output=True, text=True, env=env, cwd=cwd,
                                  timeout=CLI_TIMEOUT)
        except subprocess.TimeoutExpired as e:
            raise LLMError(f"{model}: timeout after {CLI_TIMEOUT}s") from e
    try:
        d = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise LLMError(f"{model}: non-JSON CLI output: {proc.stdout[:300]} {proc.stderr[:300]}") from e
    if d.get("is_error"):
        raise LLMError(f"{model}: {d.get('result') or d.get('subtype')} {d.get('errors') or ''}")
    used = next(iter(d.get("modelUsage") or {}), model)
    return LLMResult(text=d.get("result") or "", model=used, cost_usd=d.get("total_cost_usd"),
                     backend="claude_cli", requested_model=model)


def complete(model: str, system: str, prompt: str, max_tokens: int = 8000) -> LLMResult:
    """按降级链调用，直到有一个模型成功。"""
    chain = [model] + FALLBACKS.get(model, [])
    errors = []
    for m in chain:
        if m in _load_unavailable() and m != chain[-1]:
            log.info("skip %s: marked unavailable within %dh", m, UNAVAILABLE_TTL // 3600)
            continue
        try:
            if backend() == "anthropic":
                res = _call_anthropic(m, system, prompt, max_tokens)
            else:
                res = _call_cli(m, system, prompt)
            res.requested_model = model
            return res
        except Exception as e:  # noqa: BLE001
            log.warning("LLM %s failed: %s", m, str(e)[:300])
            errors.append(str(e)[:300])
            if re.search(r"No available channel|not_found|model.*not.*(found|available)|timeout", str(e), re.I):
                _mark_unavailable(m)
    raise LLMError(" | ".join(errors))


def parse_json(text: str) -> dict:
    """模型偶尔包 ```json 围栏或前后带说明文字：取第一个 { 到最后一个 }。"""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < i:
        raise ValueError("no JSON object in model output")
    body = t[i: j + 1]
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        # 常见失误：中文里的引号「“十五五”」被写成未转义的 ASCII 双引号。
        # 只修复紧贴中文字符 / 书名号的引号，修不好就照常抛错，交给 schema 闸门丢弃。
        cjk = r"[\u4e00-\u9fff《》（）、，。：；0-9]"
        repaired = re.sub(rf'(?<={cjk})"(?={cjk})', '\\"', body)
        # 值末尾的中文引号：…严禁"一证多运"" → 前一个引号也要转义
        repaired = re.sub(rf'(?<={cjk})"(?=\s*"\s*[,}}\]])', '\\"', repaired)
        return json.loads(repaired)
