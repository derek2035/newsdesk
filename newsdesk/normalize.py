"""URL 规范化、文本归一化、数字抽取。校验闸门和去重共用。"""
from __future__ import annotations

import re
import unicodedata
from fractions import Fraction
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid",
                   "ref", "spm", "from", "ncid", "cmpid", "srnd"}


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS]
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower(), path, urlencode(query), ""))


def norm_text(s: str) -> str:
    """全半角折叠、空白折叠、引号/破折号统一，用于逐字比对。"""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace("‑", "-").replace("−", "-")
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


# ---- 数字归一化 ----------------------------------------------------------
# 原文写法五花八门：3-3/4 to 4 percent、1/4 percentage point、3.75%、25 个基点、3.90 percent、
# 342,909、12 – 0 vote。统一成一组「可比数值」后再做回填比对。

# 前后只排除 ASCII 字母数字（中文紧贴数字很常见：增长5.2%、464.8万亿元）。
# 不识别负号：区间写法「3.75%-4%」「12–0」里的连字符不是负号。数字回填只比较绝对值。
_NUM_RE = re.compile(
    r"(?<![A-Za-z0-9_.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+-\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)(?![A-Za-z0-9_/])"
)


def _to_float(tok: str) -> float | None:
    tok = tok.replace(",", "")
    try:
        if re.fullmatch(r"\d+-\d+/\d+", tok):          # 3-3/4
            whole, frac = tok.split("-", 1)
            return int(whole) + float(Fraction(frac))
        if re.fullmatch(r"\d+/\d+", tok):               # 1/4
            return float(Fraction(tok))
        return float(tok)
    except (ValueError, ZeroDivisionError):
        return None


def extract_numbers(text: str) -> list[float]:
    """抽出文本里所有数值（已归一化为 float）。"""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2212]", "-", text)  # 各种连字符：3‑3/4（U+2011）
    out: list[float] = []
    for m in _NUM_RE.finditer(text):
        v = _to_float(m.group(1))
        if v is not None:
            out.append(v)
    return out


def number_variants(v: float) -> set[float]:
    """一个数值在原文里可能出现的等价形式：
    - 百分点 ↔ 基点：0.25 ↔ 25；1/4 percentage point 在原文里是 0.25，在中文解读里常写 25 个基点
    - 千分位、万 / 亿 单位换算不在此处做（原文与解读的单位需模型保持一致）
    """
    s = {v}
    if v != 0:
        s.add(round(v * 100, 6))   # 0.25 → 25（百分点 → 基点）
        s.add(round(v / 100, 6))   # 25 → 0.25
    return s


def numbers_supported(claim_text: str, passages_text: str, *, extra_allowed: set[float] | None = None
                      ) -> tuple[bool, list[float]]:
    """第三道闸门：claim 里每个数字都必须在被引段落里出现（允许 bp/百分点换算）。
    返回 (全部通过, 未找到的数字列表)。extra_allowed 用于 E2 公式算出的数值。"""
    have = set()
    for n in extract_numbers(passages_text):
        have |= number_variants(n)
    if extra_allowed:
        for n in extra_allowed:
            have |= number_variants(n)
    missing = []
    for n in extract_numbers(claim_text):
        # 年份、序数、日期这些小整数不当作数据数字校验
        if float(n).is_integer() and 1900 <= n <= 2100:
            continue
        if not (number_variants(n) & have):
            missing.append(n)
    return (not missing), missing
