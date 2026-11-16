"""뉴스·경제 지표 일지(market_features) — 실제 writer(시장 일지 save_section)로 쓴 일지에서 지표를 만들고,
판정일 전엔 결과를 보지 않는다."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import market_features as X  # noqa: E402
import market_journal as MJ  # noqa: E402


def _journal(jd: Path, day: str, sox: float = -3.4, prelim: float = -5475.0, close: bool = True):
    MJ.save_section(day, "morning", {
        "overseas": {"^SOX": {"date": "x", "close": 10146.3, "chg_pct": sox}, "^IXIC": {"close": 25136.3, "chg_pct": -0.91},
                     "^GSPC": {"close": 7561.7, "chg_pct": -0.4}, "^VIX": {"close": 19.3, "chg_pct": 3.2},
                     "^TNX": {"close": 5.15, "chg_pct": 1.0}, "USD/KRW": {"close": 1335.7, "chg_pct": 0.15}},
        "news": [{"title": "반도체 급락 우려", "link": "a"}, {"title": "코스피 반등 기대", "link": "b"},
                 {"title": "반도체 급락 우려", "link": "a"}],                  # 같은 링크는 한 번
        "topics": {"반도체": 3, "엔비디아": 2},
        "calendar": [{"date": day, "event": "옵션 만기"}, {"date": "2099-01-01", "event": "먼 일정"}]}, jd)
    if close:
        MJ.save_section(day, "close", {
            "news": [{"title": "외국인 매도에 하락", "link": "c"}, {"title": "중립 기사", "link": "d"}],
            "topics": {"반도체": 4}, "dart": [{"report_nm": "x"}],
            "flows_prelim": {"kospi": {"외국인": prelim, "기관": 21.0}}}, jd)


def test_features_from_real_journal_writer(tmp_path):
    jd = tmp_path / "j"
    _journal(jd, "2026-11-16")
    r = X.features_for("2026-11-16", jd)
    assert r["complete"] == 1 and r["sox_chg"] == -3.4 and r["vix"] == 19.3 and r["usdkrw"] == 1335.7
    assert r["news_n"] == 4 and (r["neg_n"], r["pos_n"]) == (2, 1) and r["neg_ratio"] == round(2 / 3, 4)
    assert r["prelim_foreign"] == -5475.0 and r["dart_n"] == 1 and r["events"] == "옵션 만기"
    assert r["t_반도체"] == 7 and r["t_엔비디아"] == 2 and r["t_관세"] == 0
    assert X.features_for("2026-11-17", jd) is None
    _journal(jd, "2026-11-18", close=False)
    assert X.features_for("2026-11-18", jd)["complete"] == 0                 # 장중 묶음이 없으면 표시


def test_update_writes_all_days_and_reads_back(tmp_path):
    jd, out = tmp_path / "j", tmp_path / "f.csv"
    for d in ("2026-11-13", "2026-11-16"):
        _journal(jd, d)
    assert X.update(jd, out) == 2 and X.update(jd, out) == 2                 # 다시 돌려도 같은 2행
    rows = X.load(out)
    assert [r["date"] for r in rows] == ["2026-11-13", "2026-11-16"] and rows[0]["sox_chg"] == "-3.4"


def _rows(n: int, neg=None, sox=None, pf=-1.0):
    return [{"date": f"2027-{1 + k // 28:02d}-{1 + k % 28:02d}", "neg_ratio": str(neg(k) if neg else 0.5),
             "sox_chg": str(sox(k) if sox else 0.0), "prelim_foreign": str(pf)} for k in range(n)]


def test_hypothesis_days():
    rows = _rows(30, sox=lambda k: 2.0 if k == 3 else (-2.5 if k == 4 else 1.9))
    assert X.n1_days(rows) == [(rows[3]["date"], 1), (rows[4]["date"], -1)]
    rows2 = _rows(30, neg=lambda k: 0.5 + (0.01 if k % 2 else -0.01) + (0.3 if k == 25 else 0))
    assert X.n2_days(rows2) == [rows2[25]["date"]]                          # 직전 20일이 차야 센다
    assert X.n3_days(rows2) == [rows2[25]["date"]]
    assert X.n3_days(_rows(30, neg=lambda k: 0.5 + (0.01 if k % 2 else -0.01) + (0.3 if k == 25 else 0), pf=10.0)) == []


def test_no_judgment_before_120_days_even_if_asked(tmp_path):
    """★ 일부러 깨뜨린다 — 판정을 요청해도 120거래일 전엔 결과를 계산하지 않고 '해당 날 수'만 보여 준다."""
    rows = _rows(X.JUDGE_DAYS - 1, sox=lambda k: 3.0)
    txt = X.report(rows, allow_judge=True)
    assert "판정 전" in txt and f"{X.JUDGE_DAYS - 1}/{X.JUDGE_DAYS}" in txt and "통과" not in txt


def test_judge_rules_on_synthetic_outcomes():
    rows = _rows(40, sox=lambda k: 3.0 if k % 2 == 0 else 0.0)
    days = [r["date"] for r in rows]
    kodex = {d: {"open": 100.0, "close": 101.0} for d in days}            # SOX 오른 날 장중 +1% → 이어짐
    kospi = {d: {"open": 100.0 + k, "close": 100.0 + k} for k, d in enumerate(days)}
    res = X.judge(rows, kodex, kospi, 0.00115)
    assert res["N1"]["n"] == 20 and res["N1"]["hit"] == 1.0 and res["N1"]["pass"] is True
    kodex_rev = {d: {"open": 100.0, "close": 99.0} for d in days}          # 반대로 가면 탈락
    assert X.judge(rows, kodex_rev, kospi, 0.00115)["N1"]["pass"] is False


def test_declared_numbers_and_batch_order():
    assert (X.SOX_MOVE, X.NEG_WIN, X.NEG_Z, X.H, X.JUDGE_DAYS, X.MIN_EVENTS) == (2.0, 20, 1.0, 5, 120, 15)
    assert (X.N1_HIT, X.N2_GAP_PCT, X.N2_HIT_GAIN_PP) == (0.60, 0.5, 10.0)
    txt = (_ROOT / "scripts" / "i3_decide.cmd").read_text(encoding="utf-8")
    i_j, i_f, i_n = txt.index("market_journal.py --phase close"), txt.index("market_features.py"), txt.index("i3_notion.cmd")
    assert i_j < i_f < i_n and txt.rstrip().endswith("exit /b %RC%")       # 지표 실패가 판단 실패로 보이지 않게
