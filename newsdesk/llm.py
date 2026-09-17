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
_STRIP_ENV = ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION",
              "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
              "CLAUDE_CODE_HOST_SESSION_ID", "CLAUDE_CODE_EXECPATH", "CLAUDE_PID")
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
    return "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "claude_cli"


def _call_anthropic(model: str, system: str, prompt: str, max_tokens: int) -> LLMResult:
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(model=model, max_tokens=max_tokens, temperature=0, system=system,
                                 messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    return LLMResult(text=text, model=msg.model, cost_usd=None, backend="anthropic", requested_model=model)


def _call_cli(model: str, system: str, prompt: str) -> LLMResult:
    env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}
    cmd = ["claude", "-p", "--model", model, "--output-format", "json", "--tools", "",
           "--system-prompt", system, "--no-session-persistence"]
    with tempfile.TemporaryDirectory(prefix="newsdesk-llm-") as cwd:  # 空目录：不读任何 CLAUDE.md
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, env=env, cwd=cwd,
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
        return json.loads(repaired)
