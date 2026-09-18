"""三道校验闸门。模型输出不能直接上线；不过关的 claim 整条丢弃，不降级展示。

① Schema：合法 JSON，section / evidence 取值合法，必填字段齐全
② 引用校验：每条引用的 quote 必须逐字（归一化空白、全半角、引号）出现在它声称的段落里；
   不过关的引用断开，失去全部引用的 claim 丢弃。
   （文档设计是本地 cross-encoder 蕴含判定；第 1 版用「逐字引文」替代，更严格但会漏掉意译型错误。）
③ 数字回填：claim 文本里的每个数字，必须在被引段落中出现（允许百分点↔基点换算），
   或者是 E2 公式的计算结果；E2 公式的每个操作数也必须来自被引段落，且算式成立。

推演（R，只能出现在「连锁反应 / 演化路径」）另外三条：
- 演化路径必须写出触发条件、观察指标、证伪信号，否则无法检验，丢弃
- 正文与各字段都不得含投资建议、买卖动作、价位目标或「必然」这类断言
- 正文里的数字照常回查；触发条件与时间窗本身是判断，不做数字回查
"""
from __future__ import annotations

import ast
import hashlib
import operator
import re
from dataclasses import dataclass, field

from .normalize import extract_numbers, norm_text, number_variants, numbers_supported

SECTIONS = ("what", "changed", "magnitude", "transmission", "scenario", "divergence")
EVIDENCE = ("E1", "E2", "R")           # R = 推演：由原文事实出发的机制推理，不是事实陈述
REASONING_SECTIONS = ("transmission", "scenario")
SCENARIO_FIELDS = ("trigger", "watch", "horizon", "counter")

# 推演可以讲机制，但不能变成投资建议或价位预测：命中即整条丢弃
FORBIDDEN = re.compile(r"(买入|卖出|加仓|减仓|抄底|建仓|做多|做空|建议投资|投资建议|推荐(关注|配置|买)|"
                       r"目标价|看涨到|看跌到|必然|一定会|稳赚|保本|包赚)")

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"])}
_WORDS = {w: i for i, w in enumerate(
    ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
     "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"])}
_CN_DIGITS = {"两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_CN_UNIT = "年个次倍位名人项条月天周季"
# 推演里的时滞与期限（「1–2 个交易日」「30 年期」「下一个季度」）是判断，不是数据，不回查出处
_TIMESPAN = re.compile(r"\d+(?:\s*[–—~-]\s*\d+)?\s*(?:个)?"
                       r"(?:交易日|工作日|天|日内|周|月|个月|季度|年期|年内|年|次会议|次议息会议|次|小时)")
FORMULA_CONSTANTS = {2.0, 100.0}  # 公式里允许的常数：求中点 ÷2、换算百分比 ×100


@dataclass
class GateReport:
    kept: list[dict] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)   # {claim, reason}
    schema_ok: bool = True
    schema_error: str | None = None

    @property
    def total(self) -> int:
        return len(self.kept) + len(self.dropped)


def quote_hash(q: str) -> str:
    return hashlib.sha1(norm_text(q).encode()).hexdigest()[:16]


def _implicit_numbers(text: str) -> set[float]:
    """原文里用英文单词 / 月份名写的数字：Eighteen participants、September 16。"""
    low = text.lower()
    out = {float(v) for w, v in _WORDS.items() if re.search(rf"\b{w}\b", low)}
    out |= {float(v) for w, v in _MONTHS.items() if re.search(rf"\b{w}\b", low)}
    return out


def _claim_numbers_with_cn(text: str) -> str:
    """把「三年」「两次」这类中文数字 + 量词转成阿拉伯数字，纳入数字回填校验。"""
    def rep(m):
        return f"{_CN_DIGITS[m.group(1)]}{m.group(2)}"
    return re.sub(rf"([两二三四五六七八九十])([{_CN_UNIT}])", rep, text)


# ---- ① schema -------------------------------------------------------------
def check_schema(obj) -> str | None:
    if not isinstance(obj, dict):
        return "top-level is not an object"
    claims = obj.get("claims")
    if not isinstance(claims, list):
        return "claims missing or not a list"
    for i, c in enumerate(claims):
        if not isinstance(c, dict):
            return f"claim {i} not an object"
        for k in ("section", "text", "evidence", "citations"):
            if k not in c:
                return f"claim {i} missing {k}"
        if c["section"] not in SECTIONS:
            return f"claim {i} bad section {c['section']!r}"
        if c["evidence"] not in EVIDENCE:
            return f"claim {i} bad evidence {c['evidence']!r}"
        if c["evidence"] == "R" and c["section"] not in REASONING_SECTIONS:
            return f"claim {i}: 推演（R）只能出现在连锁反应 / 演化路径里"
        if c["section"] in REASONING_SECTIONS and c["evidence"] != "R":
            return f"claim {i}: 连锁反应 / 演化路径必须标 R"
        if not isinstance(c["citations"], list):
            return f"claim {i} citations not a list"
    return None


# ---- E2 公式 ---------------------------------------------------------------
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand)
    raise ValueError("unsupported expression")


def check_formula(formula: str) -> tuple[bool, str, list[float], set[float]]:
    """「表达式 = 结果」，可以用分号写多段（4.1 - 3.8 = 0.3; 4.1 - 3.6 = 0.5）。
    返回 (全部成立, 原因, 操作数, 允许出现的结果数值及其四舍五入形式)。"""
    parts = [x for x in re.split(r"[;；]", formula) if x.strip()]
    if len(parts) > 1:
        operands: list[float] = []
        allowed: set[float] = set()
        for part in parts:
            ok, why, ops, vals = _check_one_formula(part)
            if not ok:
                return False, why, [], set()
            operands += ops
            allowed |= vals
        return True, "", operands, allowed
    return _check_one_formula(formula)


def _check_one_formula(formula: str) -> tuple[bool, str, list[float], set[float]]:
    f = formula.replace("×", "*").replace("÷", "/").replace("−", "-").replace("，", ",").replace(",", "")
    f = re.sub(r"%", "", f)
    if f.count("=") != 1:
        return False, "formula must be 'expr = result'", [], set()
    lhs, rhs = (x.strip() for x in f.split("="))
    if not re.fullmatch(r"[\d.\s+\-*/()]+", lhs) or not re.fullmatch(r"-?[\d.]+", rhs):
        return False, "formula has non-numeric tokens", [], set()
    try:
        value = _eval(ast.parse(lhs, mode="eval"))
    except (ValueError, SyntaxError, ZeroDivisionError) as e:
        return False, f"formula not evaluable: {e}", [], set()
    claimed = float(rhs)
    tol = max(abs(value) * 0.005, 0.005 * 10 ** (-len(rhs.split(".")[1]) if "." in rhs else 0) + 0.005)
    if abs(value - claimed) > max(tol, 0.051 if "." in rhs else 0.5):
        return False, f"formula wrong: {lhs} = {value:.4f}, not {claimed}", [], set()
    operands = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", lhs)]
    allowed = {claimed, round(value, 0), round(value, 1), round(value, 2)}
    return True, "", operands, allowed


# ---- 主入口 ----------------------------------------------------------------
def strip_doc_dates(text: str, doc_dates: set[str]) -> str:
    """结论里指代文件的日期（「7月声明」「2026年9月16日」）核对后剥掉，不参与数字回填。
    只剥和事件内某份文件发布日期对得上的写法；对不上的日期照常当数字校验。"""
    ymd = {tuple(int(x) for x in d.split("-")) for d in doc_dates}

    def rep(m):
        y = int(m.group(1)) if m.group(1) else None
        mo = int(m.group(2))
        d = int(m.group(3)) if m.group(3) else None
        for yy, mm, dd in ymd:
            if mm == mo and (y is None or y == yy) and (d is None or d == dd):
                return "〔日期〕"
        return m.group(0)
    return re.sub(r"(?:(\d{4})年)?(\d{1,2})月(?:(\d{1,2})日)?", rep, text)


def _sentence_with(text: str, value: float) -> str:
    """从段落里截出含这个数字的一句，用作自动补上的引用。"""
    parts = re.split(r"(?<=[。；;.])\s+|\n", text)
    for part in parts:
        if any(abs(n - value) < 1e-9 for n in extract_numbers(part)):
            return part.strip()[:200]
    return text[:200]


def _autolink(missing: list[float], passages: dict[str, str], used: set[str]) -> list[dict]:
    """结论用到的数字在别的段落里：自动把那一段补成引用，而不是丢掉整条。
    数字仍然只能来自本事件的官方原文，溯源链条不断。"""
    added, remaining = [], list(missing)
    for pid, text in passages.items():
        if not remaining or pid in used or not pid.startswith("P"):
            continue
        have = set()
        for n in extract_numbers(text) + list(_implicit_numbers(text)):
            have |= number_variants(n)
        hit = [m for m in remaining if number_variants(m) & have]
        if not hit:
            continue
        quote = _sentence_with(text, hit[0])
        if len(norm_text(quote)) < 4:
            continue
        pos = norm_text(text).find(norm_text(quote))
        added.append({"id": pid, "quote": quote, "norm_start": max(pos, 0),
                      "norm_end": max(pos, 0) + len(norm_text(quote)), "quote_hash": quote_hash(quote),
                      "auto": True})
        used.add(pid)
        remaining = [m for m in remaining if m not in hit]
    return added if not remaining else []


def run_gates(obj, passages: dict[str, str], doc_dates: set[str] | None = None) -> GateReport:
    """passages: {"P123": 原文段落, "M45": 媒体标题, ...}
    doc_dates: 事件内各文件的发布日期（YYYY-MM-DD）。"""
    rep = GateReport()
    err = check_schema(obj)
    if err:
        rep.schema_ok, rep.schema_error = False, err
        return rep

    for c in obj["claims"]:
        text = str(c.get("text", "")).strip()
        if not text:
            rep.dropped.append({"claim": c, "reason": "empty text"})
            continue
        if FORBIDDEN.search(text):
            rep.dropped.append({"claim": c, "reason": f"含投资建议 / 断言式措辞：{FORBIDDEN.search(text).group(0)}"})
            continue
        # ② 引用校验
        good_cites = []
        for cit in c["citations"]:
            if not isinstance(cit, dict):
                continue
            pid, quote = str(cit.get("id", "")), str(cit.get("quote", ""))
            src = passages.get(pid)
            if src is None or len(norm_text(quote)) < 4:
                continue
            nq, ns = norm_text(quote), norm_text(src)
            pos = ns.find(nq)
            if pos < 0:
                continue
            good_cites.append({"id": pid, "quote": quote, "norm_start": pos, "norm_end": pos + len(nq),
                               "quote_hash": quote_hash(quote)})
        if not good_cites:
            rep.dropped.append({"claim": c, "reason": "no citation quote found verbatim in cited passage"})
            continue

        # ③ 数字回填
        cited_text = "\n".join(passages[g["id"]] for g in good_cites)
        implicit = _implicit_numbers(cited_text)
        extra: set[float] = set(implicit)
        formula = (c.get("formula") or "").strip() or None
        if c["evidence"] == "E2":
            if not formula:
                rep.dropped.append({"claim": c, "reason": "E2 without formula"})
                continue
            ok, why, operands, allowed = check_formula(formula)
            if not ok:
                rep.dropped.append({"claim": c, "reason": why})
                continue
            have = set()
            for n in extract_numbers(cited_text) + list(implicit):
                have |= number_variants(n)
            missing_ops = [o for o in operands if o not in FORMULA_CONSTANTS and not (number_variants(o) & have)]
            if missing_ops:
                rep.dropped.append({"claim": c, "reason": f"formula operands not in cited passages: {missing_ops}"})
                continue
            extra |= allowed
        checked = text
        extra_fields = {k: str(c.get(k) or "").strip() for k in SCENARIO_FIELDS}
        if c["section"] in REASONING_SECTIONS:
            if c["section"] == "scenario" and not (extra_fields["trigger"] and extra_fields["watch"]
                                                   and extra_fields["counter"]):
                rep.dropped.append({"claim": c, "reason": "演化路径必须写出触发条件 / 观察指标 / 证伪信号"})
                continue
            if any(FORBIDDEN.search(v) for v in extra_fields.values()):
                rep.dropped.append({"claim": c, "reason": "触发条件 / 观察指标里含投资建议式措辞"})
                continue
            # 结论正文里的数据照样要有出处；时滞与期限是判断，不做回查
            checked = _TIMESPAN.sub("〔时长〕", text)
        ok, missing = numbers_supported(_claim_numbers_with_cn(strip_doc_dates(checked, doc_dates or set())),
                                        cited_text, extra_allowed=extra)
        if not ok:
            extra_cites = _autolink(missing, passages, {g["id"] for g in good_cites})
            if not extra_cites:
                rep.dropped.append({"claim": c, "reason": f"numbers not found in cited passages: {missing}"})
                continue
            good_cites += extra_cites
        rep.kept.append({"section": c["section"], "text": text, "evidence": c["evidence"],
                         "formula": formula if c["evidence"] == "E2" else None, "citations": good_cites,
                         "extra": {k: v for k, v in extra_fields.items() if v} or None})
    return rep
