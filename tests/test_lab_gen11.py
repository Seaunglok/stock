"""11세대 세 시장 I3(lab_gen11) — 합치기·장기 정렬·선언 상수·장부 (11-23, 측정 전)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_aggr_gen3 as G3  # noqa: E402
import lab_challengers as CH  # noqa: E402
import lab_gen11 as X  # noqa: E402
import lab_trials as T  # noqa: E402
import strategy_lab as L  # noqa: E402


def test_declaration_reuses_i3_engine_and_entry_rules():
    assert X.SLEEVES == {"069500": "^KS11", "219480": "219480", "132030": "132030"}
    assert X.LONG_PROXY == {"069500": "^KS11", "219480": "^GSPC", "132030": "GC=F"}
    assert X.LONG == ("2001-09-03", "2026-08-24") and X.REGISTER_ON == "2026-12-01"
    assert (X.EQUITY, X.CASH) == (3_640_000.0, "153130") and CH.SPECS["I3"] == {"reset": "none"}
    row = [r for r in T.TRIALS if r[3] == "scripts/lab_gen11.py"]
    assert len(row) == 1 and row[0][2] == 1 and row[0][0] == X.DECLARED_ON


def test_combine_n_matches_two_sleeve_combine():
    """두 몫이면 HH1 이 쓰는 lab_aggr_gen3.combine 과 같은 값(n 몫판이 같은 규칙인지)."""
    ds = ["2025-12-29", "2025-12-30", "2026-01-02", "2026-01-05"]
    a = L.SimResult(dates=ds, curve=[100.0, 110.0, 120.0, 118.0])
    b = L.SimResult(dates=ds, curve=[100.0, 95.0, 90.0, 93.0])
    two = G3.combine(a, b, X.SIDE_COST)
    n = X.combine_n([(a.dates, a.curve), (b.dates, b.curve)])
    assert n.dates == two.dates and n.curve == pytest.approx(two.curve)


def test_combine_n_rebalances_three_sleeves_each_year_with_cost():
    ds = ["2025-12-30", "2026-01-02", "2026-01-05"]
    c1, c2, c3 = [100.0, 130.0, 130.0], [100.0, 100.0, 100.0], [100.0, 70.0, 70.0]
    r = X.combine_n([(ds, c1), (ds, c2), (ds, c3)], side_cost=0.01)
    nav = 300.0                                                  # 새해 첫날 합 300 — 옮긴 금액 (30 + 0 + 30) / 2 = 30
    assert r.curve[0] == 300.0 and r.curve[1] == pytest.approx(nav - 2 * 0.01 * 30)
    assert r.curve[2] == pytest.approx(r.curve[1])               # 그 뒤 몫 값이 그대로면 합도 그대로
    r0 = X.combine_n([(ds, c1), (ds, c2), (ds, c3)], side_cost=0.0)
    assert r0.curve[1] == pytest.approx(300.0)


def test_combine_n_skips_days_missing_in_any_sleeve():
    r = X.combine_n([(["d1", "d2", "d3"], [1.0, 1.1, 1.2]), (["d1", "d3"], [1.0, 0.9])])
    assert r.dates == ["d1", "d3"]


def _bars(days, start=100.0, step=0.5):
    return {d: {"open": start + k * step, "close": start + k * step} for k, d in enumerate(days)}


def test_run_long_aligns_us_calendar_to_kospi_calendar():
    """미국 대용 지수는 한국 휴장일에도 열린다 — KOSPI 달력에 마지막 값으로 맞춰 합친다(빈 날이 0 이 되지 않는다)."""
    import datetime as dt
    kd, ud = [], []
    d = dt.date(2001, 9, 3)
    while len(kd) < 400:
        if d.weekday() < 5:
            ud.append(d.isoformat())
            if d.day % 7:                                        # 한국만 쉬는 날
                kd.append(d.isoformat())
        d += dt.timedelta(days=1)
    px = {"^KS11": _bars(kd), "^GSPC": _bars(ud, 50.0, 0.1), "GC=F": _bars(ud, 300.0, 0.2)}
    r = X.run_long(px, {"069500": kd, "219480": ud, "132030": ud})
    assert r.dates == kd and r.curve[0] == pytest.approx(3.0) and min(r.curve) > 2.5
