"""抓取器 golden file 测试：历史页面快照 → 期望解析结果。

页面改版导致解析失效时，修完解析器跑这组测试：字段齐、值对得上才算修好。
更新快照：把新页面存进 tests/golden/<源>/，人工核对解析结果后再更新 .expected.json。
"""
import json
from pathlib import Path

import pytest

from newsdesk.fetch import cn_gov, fed

G = Path(__file__).parent / "golden"


def _expected(name):
    return json.loads((G / name).read_text(encoding="utf-8"))


def _html(name):
    return (G / name).read_text(encoding="utf-8")


def test_fed_statement():
    html = _html("fed/statement_20260916.html")
    exp = _expected("fed/statement_20260916.expected.json")
    assert fed.extract_vote(html) == exp["vote"]
    paras = fed.extract_paragraphs(html)
    assert paras == exp["paragraphs"]
    assert any("3-3/4 to 4 percent" in p for p in paras)
    assert not any(p.startswith("For media inquiries") for p in paras)


def test_fed_implementation_note():
    lines = fed.extract_impl_note(_html("fed/impl_note_20260916.html"))
    assert lines == _expected("fed/impl_note_20260916.expected.json")
    assert any("3.90 percent" in x for x in lines)
    assert not any("Official websites use .gov" in x for x in lines)  # 不混入导航


def test_fed_sep_table():
    texts = [t for _, t in fed.extract_sep(_html("fed/sep_table_20260916.html"))]
    assert texts == _expected("fed/sep_table_20260916.expected.json")
    assert "SEP Federal funds rate median projection: 2026 4.1, 2027 4.1, 2028 3.9, 2029 3.6, Longer run 3.2" in texts
    assert any(t.startswith("Dot plot, end of 2026") and "12 participants at 4.125" in t for t in texts)


def test_fed_classify():
    assert fed.classify("Federal Reserve issues FOMC statement") == "fomc_statement"
    assert fed.classify("Minutes of the Federal Open Market Committee, July 28–29, 2026") == "fomc_minutes"


def test_stats_release():
    lines = cn_gov.extract_stats(_html("stats_cn/release_20260915_1965308.html"))
    assert lines == _expected("stats_cn/release_20260915_1965308.expected.json")
    assert lines[0].startswith("8月份，规模以上工业增加值同比实际增长5.2%")


def test_stats_list():
    items = cn_gov.parse_stats_list(_html("stats_cn/list_zxfb.html"), "https://www.stats.gov.cn/sj/zxfb/")
    got = [{"url": i["url"], "title": i["title"], "date": i["date"].isoformat()} for i in items]
    assert got == _expected("stats_cn/list_zxfb.expected.json")
    assert len({i["url"] for i in items}) == len(items)  # 去重


def test_govcn_policy():
    paras = cn_gov.extract_govcn(_html("gov_cn/policy_7081356.html"))
    assert paras == _expected("gov_cn/policy_7081356.expected.json")
    assert "国办发〔2026〕26号" in paras
    assert not any("京ICP备" in p for p in paras)  # 不混入页脚


@pytest.mark.parametrize("name", ["gov_cn/ZUIXINZHENGCE.json"])
def test_govcn_list_json_shape(name):
    data = json.loads(_html(name))
    assert {"TITLE", "URL", "DOCRELPUBTIME"} <= set(data[0])
