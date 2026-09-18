"""范围解析器：event_type → 影响范围四维度 + 等级 + 中性标题。规则实现，不调模型。

score = log10(人口) + log10(持续月数) + log10(行业数) + log10(经济规模美元)
未知维度记为 None，不参与求和，并在页面上显示「未知」。

分级是资源开关（决定用哪个模型），不是重要性结论。阈值故意偏低：宁可多花几美元。
第 1 版按 event_type + 变化量判级；第 0 步发现纯 score 对同类事件几乎是常数（每次 FOMC
人口 / 行业 / GDP 都一样），所以美联储事件额外看「利率是否变动」。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .normalize import _to_float

# ---- 参考常量（来源写在旁边，更新时改这里） -------------------------------
US_POPULATION = 342_909_000          # FRED POPTHM，2026-07
US_GDP_USD = 32_486.066e9            # FRED GDP，2026Q2 年化名义值
CN_POPULATION = 1_404_890_000        # 国家统计局《2025 年国民经济和社会发展统计公报》：年末全国人口 140489 万人
CN_GDP_USD = 1_401_879e8 / 6.7080    # 同上：2025 年 GDP 1401879 亿元；按 FRED DEXCHUS 2026-09-11 汇率 6.7080 折美元
ALL_SECTORS = 11                     # GICS 一级行业数


@dataclass
class Resolution:
    event_type: str
    grade: str                     # A+ / A / B / C / below（未达 C 级：只存不解读）
    title: str                     # 系统生成的中性标题
    population: float | None = None
    industries: int | None = None
    econ_scale: float | None = None
    duration_months: float | None = None
    duration_is_estimate: bool = True
    notes: dict = field(default_factory=dict)
    media_keywords: list[list[str]] = field(default_factory=list)  # 每组内任一命中，组间全部命中

    @property
    def score(self) -> float | None:
        dims = [self.population, self.duration_months, self.industries, self.econ_scale]
        vals = [math.log10(v) for v in dims if v and v > 0]
        return round(sum(vals), 2) if vals else None


FED_KEYS = ["fed", "federal reserve", "fomc", "warsh", "美联储", "联储"]


# ---- 美联储 --------------------------------------------------------------
def parse_fomc_statement(passages: list[str]) -> dict:
    text = " ".join(passages).replace("‑", "-")
    out: dict = {}
    m = re.search(r"decided to (raise|lower|maintain) the target range for the federal funds rate"
                  r"(?: by ([\d/]+) percentage point)? (?:to|at) ([\d\-/]+) to ([\d\-/]+) percent", text)
    if m:
        action, step, lo, hi = m.groups()
        out.update(action=action, low=_to_float(lo), high=_to_float(hi),
                   step_bp=round(_to_float(step) * 100) if step else 0)
    v = re.search(r"by a (\d+)\s*[–-]\s*(\d+) vote", text)
    if v:
        out["vote"] = (int(v.group(1)), int(v.group(2)))
    return out


def resolve_fomc_statement(passages: list[str]) -> Resolution:
    p = parse_fomc_statement(passages)
    action = p.get("action")
    rng = f"{p['low']:.2f}%–{p['high']:.2f}%" if "low" in p else "未解析"
    if action == "raise":
        title, grade, duration = f"美联储上调联邦基金利率目标区间 {p['step_bp']} 个基点至 {rng}", "A", 12
    elif action == "lower":
        title, grade, duration = f"美联储下调联邦基金利率目标区间 {p['step_bp']} 个基点至 {rng}", "A", 12
    elif action == "maintain":
        title, grade, duration = f"美联储维持联邦基金利率目标区间在 {rng}", "B", 1.5
    else:
        title, grade, duration = "美联储发布 FOMC 声明", "B", 1.5
    return Resolution(
        event_type="central_bank_rate", grade=grade, title=title,
        population=US_POPULATION, industries=ALL_SECTORS, econ_scale=US_GDP_USD,
        duration_months=duration, duration_is_estimate=True,
        notes={"parsed": p,
               "population": "美国人口（FRED POPTHM 2026-07），只计直接影响，不计全球外溢",
               "industries": "利率影响全行业融资成本，按 GICS 11 个一级行业计",
               "econ_scale": "美国名义 GDP（FRED 2026Q2 年化）",
               "duration": "估计值：利率变动按 12 个月计；维持不变按到下次议息会议约 1.5 个月计"},
        media_keywords=[FED_KEYS, ["rate", "rates", "hike", "hikes", "raise", "raises", "raised", "cut",
                                   "利率", "加息", "降息", "基点", "decision", "statement", "声明"]],
    )


_EN_MONTHS = {m: i + 1 for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                               "September", "October", "November", "December"])}


def zh_meeting_date(s: str) -> str:
    """「July 28–29, 2026」→「2026年7月28–29日」；解析不了原样返回。"""
    m = re.fullmatch(r"([A-Z][a-z]+) (\d{1,2})\s*[–-]\s*(\d{1,2}), (\d{4})", s.strip())
    if m and m.group(1) in _EN_MONTHS:
        return f"{m.group(4)}年{_EN_MONTHS[m.group(1)]}月{m.group(2)}–{m.group(3)}日"
    return s


def resolve_fed_other(doc_type: str, title: str) -> Resolution:
    if doc_type == "fomc_minutes":
        return Resolution(event_type="central_bank_minutes", grade="C",
                          title="美联储公布 " + zh_meeting_date(
                              re.sub(r"^Minutes of the Federal Open Market Committee,\s*", "", title)) + " FOMC 会议纪要",
                          population=US_POPULATION, industries=ALL_SECTORS, econ_scale=US_GDP_USD,
                          duration_months=1.5,
                          notes={"duration": "估计值：纪要影响到下次会议"},
                          media_keywords=[FED_KEYS, ["minutes", "纪要"]])
    if doc_type == "fed_discount_minutes":
        return Resolution(event_type="central_bank_admin", grade="below", title="美联储公布贴现率会议纪要",
                          notes={"reason": "例行程序性文件"})
    return Resolution(event_type="central_bank_other", grade="C", title=f"美联储：{title}",
                      notes={"reason": "默认保守估计"})


# ---- 国家统计局 ----------------------------------------------------------
STATS_KEY_SERIES = {
    "国民经济运行": (["国民经济", "经济数据", "economy", "economic data"], "B"),
    "居民消费价格": (["居民消费价格", "CPI", "consumer price", "inflation", "通胀"], "B"),
    "工业生产者出厂价格": (["出厂价格", "PPI", "producer price", "factory-gate"], "B"),
    "国内生产总值": (["GDP", "国内生产总值", "经济增长"], "B"),
    "采购经理指数": (["PMI", "采购经理"], "B"),
    "规模以上工业增加值": (["工业增加值", "industrial output", "industrial production"], "C"),
    "社会消费品零售总额": (["社会消费品零售", "社零", "retail sales"], "C"),
    "固定资产投资": (["固定资产投资", "fixed-asset investment", "investment"], "C"),
    "房地产": (["房地产", "property", "real estate"], "C"),
    "商品住宅销售价格": (["房价", "home prices", "house prices", "新房"], "C"),
    "能源生产": (["能源生产", "发电量", "energy output", "power generation"], "C"),
}
CHINA_KEYS = ["china", "chinese", "beijing", "中国", "国家统计局", "统计局", "国内", "<月份>"]  # <月份> 匹配「8月」「1—8月」


def resolve_stats(title: str) -> Resolution:
    if "流通领域重要生产资料市场价格" in title:
        return Resolution(event_type="econ_data_release", grade="below", title=f"国家统计局：{title}",
                          notes={"reason": "旬度价格监测，例行发布"})
    for key, (kws, grade) in STATS_KEY_SERIES.items():
        if key in title:
            return Resolution(
                event_type="econ_data_release", grade=grade, title=f"国家统计局：{title}",
                population=CN_POPULATION, industries=ALL_SECTORS if grade == "B" else 3,
                econ_scale=CN_GDP_USD, duration_months=1,
                notes={"population": "中国人口（国家统计局 2025 年统计公报，年末 14.05 亿）",
                       "industries": "综合性数据按 11 个一级行业；分项数据保守按 3 个计",
                       "econ_scale": "中国 GDP（2025 年 140.19 万亿元，按 6.708 折美元）",
                       "duration": "估计值：影响到下一期数据发布，约 1 个月"},
                media_keywords=[CHINA_KEYS, kws])
    return Resolution(event_type="econ_data_release", grade="C", title=f"国家统计局：{title}",
                      population=CN_POPULATION, duration_months=1,
                      notes={"reason": "默认保守估计：行业与经济规模未知"})


# ---- 中国政府网政策文件 --------------------------------------------------
_POLICY_PREFIX = re.compile(r"^(中共中央办公厅\s*国务院办公厅(\s*中央军委办公厅)?|中共中央\s*国务院|国务院办公厅|国务院)"
                            r"(关于|印发)?")
_POLICY_SUFFIX = re.compile(r"(的通知|的意见|的决定|的批复|的函)$")


def policy_core(title: str) -> str:
    m = re.search(r"《(.+?)》", title)
    if m:
        return m.group(1)
    return _POLICY_SUFFIX.sub("", _POLICY_PREFIX.sub("", title)).strip()


def resolve_policy(title: str) -> Resolution:
    core = policy_core(title)
    major = bool(re.search(r"条例|规划|意见|决定|办法", title)) and bool(re.search(r"国务院|中共中央", title) or "条例" in title)
    key = core[:6] if len(core) >= 6 else core
    return Resolution(
        event_type="policy_document", grade="B" if major else "C", title=title,
        population=CN_POPULATION, industries=None, econ_scale=None, duration_months=None,
        notes={"reason": "第 1 版没有政策文件范围解析器：行业、经济规模、持续时间未知（保守）",
               "population": "全国性文件按中国人口计"},
        media_keywords=[[key]] if key else [],
    )


# ---- 财政部 / 统计局数据解读 / 外国央行 ------------------------------------
def resolve_stats_interpretation(title: str) -> Resolution:
    """统计局的解读与答记者问：官方对自家数据的说明，是解读的好参照系。"""
    return Resolution(event_type="econ_data_interpretation", grade="C", title=f"国家统计局：{title}",
                      population=CN_POPULATION, industries=ALL_SECTORS, econ_scale=CN_GDP_USD, duration_months=1,
                      notes={"population": "中国人口（国家统计局 2025 年统计公报，年末 14.05 亿）",
                             "econ_scale": "中国 GDP（2025 年 140.19 万亿元，按 6.708 折美元）",
                             "duration": "估计值：影响到下一期数据发布，约 1 个月"},
                      media_keywords=[CHINA_KEYS, ["解读", "统计局", "经济数据", "economy"]])


def resolve_fiscal(title: str) -> Resolution:
    """财政部财政新闻：国债发行、财政数据、会计准则等。"""
    major = bool(re.search(r"财政收支|预算|减税|降费|专项债|国债|转移支付|会计准则", title))
    return Resolution(event_type="fiscal_release", grade="C" if major else "below",
                      title=f"财政部：{title}",
                      population=CN_POPULATION if major else None,
                      industries=None, econ_scale=None, duration_months=None,
                      notes={"reason": "第 1 版没有财政事件范围解析器：行业、经济规模、持续时间未知（保守）"
                                       if major else "例行事务性发布"},
                      media_keywords=[CHINA_KEYS, ["财政", "国债", "预算", "减税", "fiscal", "treasury bond"]]
                      if major else [])


_FOREIGN_CB = {
    "ecb_release": ("欧洲央行", ["ecb", "european central bank", "euro zone", "eurozone", "欧洲央行", "欧元区"]),
    "boe_release": ("英国央行", ["boe", "bank of england", "英国央行", "英央行"]),
}


_CB_ROUTINE = re.compile(r"dates for \d{4}|appointments?\b|statistical notice|vacanc|agenda|"
                         r"minutes of the (securities|foreign exchange|money markets) |transcript of|"
                         r"list of|publication of|calendar", re.I)


def resolve_foreign_cb(doc_type: str, title: str) -> Resolution:
    name, keys = _FOREIGN_CB[doc_type]
    if _CB_ROUTINE.search(title):
        return Resolution(event_type="central_bank_admin", grade="below", title=f"{name}：{title}",
                          notes={"reason": "例行程序性发布"})
    decision = bool(re.search(r"monetary policy decision|monetary policy summary|interest rate|bank rate|"
                              r"asset purchase|policy decision|rate decision", title, re.I))
    return Resolution(
        event_type="central_bank_rate" if decision else "central_bank_other",
        grade="B" if decision else "C", title=f"{name}：{title}",
        population=None, industries=ALL_SECTORS if decision else None, econ_scale=None,
        duration_months=1.5 if decision else None,
        notes={"reason": f"第 1 版没有{name}的范围常量：人口与经济规模显示未知（不估算）",
               "duration": "估计值：影响到下次议息会议" if decision else ""},
        media_keywords=[keys, ["rate", "rates", "policy", "decision", "利率", "政策", "决议"]] if decision
        else [keys],
    )


def resolve(doc_type: str, title: str, passages: list[str]) -> Resolution | None:
    """返回 None 表示该文档不单独成事件（作为别的事件的附属文件）。"""
    if doc_type == "fomc_statement":
        return resolve_fomc_statement(passages)
    if doc_type in ("fomc_impl_note", "fomc_sep_release", "fomc_sep_table"):
        return None
    if doc_type in ("fomc_minutes", "fed_discount_minutes", "fed_other"):
        return resolve_fed_other(doc_type, title)
    if doc_type == "stats_release":
        return resolve_stats(title)
    if doc_type == "stats_interpretation":
        return resolve_stats_interpretation(title)
    if doc_type == "fiscal_release":
        return resolve_fiscal(title)
    if doc_type in _FOREIGN_CB:
        return resolve_foreign_cb(doc_type, title)
    if doc_type == "policy_doc":
        return resolve_policy(title)
    return None
