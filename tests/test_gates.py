"""校验闸门测试：用真实 FOMC 段落构造正反例。"""
from newsdesk import gates
from newsdesk.normalize import extract_numbers, numbers_supported

P = {
    "P1": "The Federal Open Market Committee approved the following statement for release by a 12 – 0 vote",
    "P2": "The Committee decided to raise the target range for the federal funds rate by 1/4 percentage point to "
          "3-3/4 to 4 percent, in support of the Federal Reserve's dual mandate.",
    "P3": "The Committee decided to maintain the target range for the federal funds rate at 3-1/2 to 3-3/4 percent, "
          "in support of the Federal Reserve's dual mandate.",
    "P4": "Dot plot, end of 2026, projected midpoint of the federal funds rate target range: 4 participants at 4.375; "
          "12 participants at 4.125; 2 participants at 3.875",
    "M9": "Fed raises interest rates for first time since 2023, defying Trump as inflation mounts",
}
DATES = {"2026-09-16", "2026-07-29"}


def claim(text, evidence="E1", cites=(("P2", "raise the target range for the federal funds rate"),), formula=None,
          section="what"):
    return {"section": section, "text": text, "evidence": evidence, "formula": formula,
            "citations": [{"id": i, "quote": q} for i, q in cites]}


def run(*claims):
    return gates.run_gates({"claims": list(claims)}, P, DATES)


def test_numbers_normalized_fractions_and_bp():
    assert extract_numbers("3-3/4 to 4 percent") == [3.75, 4.0]
    ok, _ = numbers_supported("上调 25 个基点至 3.75%–4.00%", P["P2"])
    assert ok


def test_schema_rejects_bad_evidence():
    rep = gates.run_gates({"claims": [claim("x", evidence="E3")]}, P)
    assert not rep.schema_ok


def test_quote_must_be_verbatim():
    rep = run(claim("美联储上调利率 25 个基点", cites=(("P2", "raised the target range sharply"),)))
    assert not rep.kept and "verbatim" in rep.dropped[0]["reason"]


def test_quote_in_wrong_passage_is_rejected():
    rep = run(claim("美联储上调利率 25 个基点", cites=(("P3", "raise the target range for the federal funds rate"),)))
    assert not rep.kept


def test_wrong_number_is_dropped():
    rep = run(claim("美联储上调利率 50 个基点至 3.75%–4.00%"))
    assert not rep.kept and "50" in rep.dropped[0]["reason"]


def test_correct_claim_kept():
    rep = run(claim("美联储于2026年9月16日将联邦基金利率目标区间上调 25 个基点至 3.75%–4.00%"))
    assert len(rep.kept) == 1


def test_document_date_ok_but_other_dates_checked():
    assert run(claim("7月声明维持利率不变，本次上调 25 个基点")).kept
    assert not run(claim("5月声明维持利率不变，本次上调 25 个基点")).kept


def test_cn_numeral_checked():
    rep = run(claim("三位委员主张上调 25 个基点"))
    assert not rep.kept


def test_e2_requires_formula_and_correct_math():
    cites = (("P4", "12 participants at 4.125"), ("P4", "4 participants at 4.375"))
    assert not run(claim("16 人预计年内再加息", evidence="E2", cites=cites)).kept                  # 无公式
    assert not run(claim("17 人预计年内再加息", evidence="E2", cites=cites, formula="12 + 4 = 17")).kept  # 算错
    assert run(claim("16 人预计年内再加息", evidence="E2", cites=cites, formula="12 + 4 = 16")).kept
    # 操作数不在原文里
    assert not run(claim("20 人", evidence="E2", cites=cites, formula="12 + 8 = 20")).kept


def test_headline_citation():
    rep = run(claim("NBC 标题称这是 2023 年以来首次加息", section="divergence",
                    cites=(("M9", "first time since 2023"),)))
    assert rep.kept


def test_mixed_batch_counts():
    rep = run(claim("上调 25 个基点"), claim("上调 50 个基点"))
    assert (len(rep.kept), len(rep.dropped)) == (1, 1)


def test_formula_constants_allowed():
    cites = (("P2", "3-3/4 to 4 percent"),)
    assert run(claim("新目标区间中点为 3.875%", evidence="E2", cites=cites, formula="(3.75 + 4) / 2 = 3.875")).kept


def test_unicode_hyphen_fraction():
    assert extract_numbers("3\u20111/2 to 3\u20113/4 percent") == [3.5, 3.75]


def test_parse_json_repairs_unescaped_cjk_quotes():
    from newsdesk.llm import parse_json
    raw = '```json\n{"claims": [{"text": "印发《服务和保障"十五五"规划》"}]}\n```'
    assert parse_json(raw)["claims"][0]["text"] == '印发《服务和保障"十五五"规划》'
