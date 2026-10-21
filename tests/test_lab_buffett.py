"""버핏식 후보 — 미래 정보 차단과 선언값 잠금 (2026-10-22)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_buffett as B  # noqa: E402
from dart_fundamentals import latest_as_of, parse_rows  # noqa: E402


def test_grids_are_declared():
    """★ 측정 전 선언(10-22)."""
    assert B.D_DEFAULT == (60, 12) and len(B.D_GRID) == 9
    assert B.E_DEFAULT == (10, 200) and len(B.E_GRID) == 12
    assert B.F_DEFAULT == (10, 15) and len(B.F_GRID) == 6
    assert B.FIN_SECTORS == {"금융", "증권", "보험"}


def test_fundamentals_not_usable_on_filing_day():
    """★ 공시 당일 종가 신호에 쓰면 미래 정보 — 다음 날부터."""
    fund = {"2019": {"avail": "2020-03-30", "equity": 1}, "2018": {"avail": "2019-03-29", "equity": 2}}
    assert latest_as_of(fund, "2020-03-30")["equity"] == 2
    assert latest_as_of(fund, "2020-03-31")["equity"] == 1
    assert latest_as_of(fund, "2019-03-29") is None


def test_parse_rows_prefers_consolidated_and_reads_filing_date():
    rows = [
        {"stock_code": "000001", "fs_div": "OFS", "account_nm": "자본총계", "thstrm_amount": "5", "rcept_no": "20200330000001"},
        {"stock_code": "000001", "fs_div": "CFS", "account_nm": "자본총계", "thstrm_amount": "1,000", "rcept_no": "20200330000001"},
        {"stock_code": "000001", "fs_div": "CFS", "account_nm": "당기순이익(손실)", "thstrm_amount": "100", "rcept_no": "20200330000001"},
        {"stock_code": "000001", "fs_div": "CFS", "account_nm": "당기순이익(손실)", "thstrm_amount": "999", "rcept_no": "20200330000001"},
    ]
    r = parse_rows(rows)["000001"]
    assert r["fs"] == "CFS" and r["equity"] == 1000 and r["net_income"] == 100
    assert r["avail"] == "2020-03-30"


def test_pct_rank_handles_ties_and_order():
    r = B.pct_rank({"a": 1.0, "b": 3.0, "c": 3.0, "d": 5.0})
    assert r["a"] == 0.0 and r["d"] == 1.0 and r["b"] == r["c"] == pytest.approx(0.5)


def test_period_ends_quarters_only():
    ds = ["2020-03-30", "2020-03-31", "2020-04-01", "2020-05-29", "2020-06-01", "2020-06-30", "2020-07-01"]
    assert B.period_ends(ds, (3, 6, 9, 12)) == {"2020-03-31", "2020-06-30"}
    assert "2020-05-29" in B.period_ends(ds)


def _px():
    days = [f"2020-{m:02d}-{d:02d}" for m in range(1, 13) for d in range(1, 29)]
    import math
    bars = {}
    for code, amp in (("S", 0.01), ("V", 0.03)):
        bars[code] = {d: {"open": 100.0, "close": 100.0 * (1 + amp * math.sin(i)), "value": 1e9}
                      for i, d in enumerate(days)}
    return B.Prices(bars), days


def test_prices_never_read_future():
    """★ 그날 이후 종가를 바꿔도 그날 변동성은 그대로."""
    px, days = _px()
    d = days[100]
    v = px.vol("S", d, 60)
    for dd in days[101:]:
        px.bars["S"][dd]["close"] = 1.0
    px2 = B.Prices(px.bars)
    assert px2.vol("S", d, 60) == pytest.approx(v)


def test_inverse_vol_gives_more_weight_to_calmer_asset():
    px, days = _px()
    w = B.inv_vol_weights(px, ("S", "V"), days[200], 60)
    assert w["S"] > w["V"] and sum(w.values()) == pytest.approx(1.0)


def test_strat_f_weights_never_exceed_one(monkeypatch):
    """F 는 레버리지를 쓰지 않는다 — 종목 + 방어 바스켓 비중 합 ≤ 1."""
    px, days = _px()
    monkeypatch.setattr(B, "buffett_pick", lambda *a, **k: ["S", "V"])
    monkeypatch.setattr(B, "inv_vol_weights", lambda px_, codes, d, n: {"G": 0.5, "T": 0.5})
    t = B.strat_f(px, {}, {}, {}, days, 10, 15)
    w = t(0, days[0])
    assert sum(w.values()) <= 1.0 + 1e-9
    assert w["S"] == pytest.approx(w["V"])
