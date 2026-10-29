"""공격형 3세대(lab_aggr_gen3) — 선언한 규칙이 적힌 대로 도는지. 합성 자료만 쓴다."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_aggr as A  # noqa: E402
import lab_aggr_gen2 as G2  # noqa: E402
import lab_aggr_gen3 as G3  # noqa: E402
import strategy_lab as L  # noqa: E402


def test_declared_constants():
    """측정 전 선언: HH1(미국 I3)·HH2(미국 보유) · 한국 절반 격자는 2세대 그대로 · 미국은 1배 133690 · 세금 15.4% 는 보고만."""
    assert G3.SPECS == ("HH1", "HH2") and G3.US_MODE == {"HH1": "i3", "HH2": "hold"}
    assert G3.GRID == G2.GRID and G3.DEFAULT == G2.DEFAULT == (3, 30)
    assert (G3.NDQ, G3.LEV2, G3.CASH) == ("133690", "122630", "153130") and A.INV1 not in (G3.NDQ, G3.LEV2)
    assert G3.US_TAX == 0.154 and abs(G3.SIDE_COST - 0.00115) < 1e-12


def _res(dates, curve, trades=0):
    return L.SimResult(dates=list(dates), curve=list(curve), trades=trades)


def test_combine_rebalances_on_first_day_of_year_and_charges_cost():
    days = ["2020-12-30", "2020-12-31", "2021-01-04", "2021-01-05"]
    a = _res(days, [50, 60, 60, 66], 2)
    b = _res(days, [50, 50, 40, 40], 3)
    r = G3.combine(a, b, side_cost=0.001)
    assert r.trades == 5 and r.dates == days
    assert r.curve[:2] == [100, 110]
    nav = 100 - 2 * 0.001 * 10                      # 새해 첫날: 60/40 → 50/50, 10 을 옮김
    assert abs(r.curve[2] - nav) < 1e-9
    assert abs(r.curve[3] - nav * (0.5 * 66 / 60 + 0.5 * 40 / 40)) < 1e-9


def test_combine_without_year_change_is_plain_sum():
    days = ["2021-03-02", "2021-03-03"]
    r = G3.combine(_res(days, [50, 55]), _res(days, [50, 45]))
    assert r.curve == [100, 100]


def test_us_hold_buys_once_and_unknown_mode_raises():
    t = G3.us_target("hold", {}, "US", None)
    assert t(0, "d0", 1.0) == {"US": 1.0} and t(1, "d1", 1.0) is None
    with pytest.raises(KeyError):
        G3.us_target("short", {}, "US", None)


def test_us_i3_uses_its_own_trend_not_kospi():
    """미국 절반의 엔진은 자기 가격으로 판단 — 나스닥이 최고 대비 −10% 면 이탈."""
    bars = {f"2020-01-{k + 1:02d}": {"open": c, "close": c} for k, c in enumerate([100, 105, 110, 98])}
    d = sorted(bars)
    t = G3.us_target("i3", bars, "US", "CASH")
    assert "US" in t(0, d[0], 100.0)
    t(1, d[1], 100.0)
    t(2, d[2], 100.0)
    assert t(3, d[3], 100.0) == {"CASH": 1.0}       # 110 → 98 (−10.9%)
