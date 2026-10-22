"""AQR 팩터(lab_factors) — 저베타·퀄리티가 규칙대로 고르는지, 재무를 공시 전에 쓰지 않는지(합성 데이터)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_factors as F  # noqa: E402


def _days(n):
    return [f"{2010 + i // 336}-{1 + (i % 336) // 28:02d}-{1 + i % 28:02d}" for i in range(n)]


def test_beta_by_hand():
    rm = [0.01, -0.02, 0.015, -0.005] * 10
    assert F.beta([2 * x for x in rm], rm) == pytest.approx(2.0)
    assert F.beta([0.5 * x + 0.001 for x in rm], rm) == pytest.approx(0.5)


def test_bab_picks_lowest_beta():
    n = 300
    days = _days(n)
    mret = [0.01 * math.sin(i) for i in range(n)]
    kospi, lev = {}, 1000.0
    stocks = {"LOW": [100.0], "MID": [100.0], "HIGH": [100.0]}
    for i, d in enumerate(days):
        lev *= 1 + mret[i]
        kospi[d] = {"open": lev, "close": lev}
        if i:
            for name, b in (("LOW", 0.3), ("MID", 1.0), ("HIGH", 2.0)):
                stocks[name].append(stocks[name][-1] * (1 + b * mret[i]))
    bars = {c: {d: {"open": p, "close": p} for d, p in zip(days, px)} for c, px in stocks.items()}
    t = F.bab_target(bars, kospi, {days[-1]}, n_pick=1)
    assert t(0, days[0]) == {} and t(5, days[5]) is None
    assert t(n - 1, days[-1]) == {"LOW": 1.0}


def test_qmj_uses_only_filed_financials():
    """★ 공시일(avail) 당일·이전엔 그 재무를 쓰지 않는다 — 미래 정보 차단."""
    d0, d1 = "2016-03-31", "2016-04-01"
    bars = {c: {d0: {"close": 1.0}, d1: {"close": 1.0}} for c in ("A", "B")}
    good = {"equity": 100, "net_income": 30, "assets": 200, "op_income": 40, "liabilities": 50}
    bad = {"equity": 100, "net_income": 1, "assets": 200, "op_income": 2, "liabilities": 300}
    fund = {"A": {"2015": {**good, "avail": d0}}, "B": {"2015": {**bad, "avail": "2016-03-01"}}}
    assert set(F.quality_scores(bars, fund, d0)) == {"B"}            # A 는 공시 당일 — 아직 못 쓴다
    sc = F.quality_scores(bars, fund, d1)
    assert sc["A"] > sc["B"]
    t = F.qmj_target(bars, fund, {d1}, n_pick=1)
    assert t(1, d1) == {"A": 1.0}
