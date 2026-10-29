"""공격형 2세대(lab_aggr_gen2) — 선언한 규칙이 적힌 대로 도는지. 합성 자료만 쓴다."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_aggr as A  # noqa: E402
import lab_aggr_gen2 as G  # noqa: E402


def test_declared_constants():
    """측정 전 선언: G1·G2 · 격자 m 3개 × f 3개 · 기본 (3, 30) 은 격자 가운데 · 잣대는 1세대 그대로."""
    assert G.SPECS == ("G1", "G2")
    assert G.GRID == tuple((m, f) for m in (2, 3, 4.5) for f in (25, 30, 35)) and len(G.GRID) == 9
    assert G.DEFAULT == (3, 30) and G.DEFAULT[0] == G.M_GRID[1] and G.DEFAULT[1] == G.F_GRID[1]
    assert (G.LOOKBACK, G.BAND) == (252, 0.10)
    assert (G.LEV2, G.CASH) == ("122630", "153130") and A.INV1 not in (G.LEV2, G.CASH)     # 인버스 없음
    assert (A.AG_MAX_MDD_PCT, A.AG_EXCESS_PP, A.ROLL_3Y) == (30.0, 5.0, 756)


def test_g1_engine_reads_signal_bars_and_holds_leverage():
    """엔진은 신호 종목(KODEX200)으로 판단하고, 드는 건 레버리지 — 레버리지 가격이 아니라 신호 종목이 −10% 면 이탈."""
    sig = {f"2020-01-{k + 1:02d}": {"open": c, "close": c} for k, c in enumerate([100, 101, 102, 90])}
    d = sorted(sig)
    t = G.make_target("G1", G.DEFAULT, sig, sig, "LEV", "CASH")
    out0 = t(0, d[0], 100.0)
    assert set(out0) == {"LEV", "CASH"} and abs(out0["LEV"] - 0.9) < 1e-9       # 3 × 쿠션 30% = 90%
    assert t(1, d[1], 100.0) is None and t(2, d[2], 100.0) is None              # 같은 비중 — 재조정 없음
    assert t(3, d[3], 100.0) == {"CASH": 1.0}                                   # 102 → 90 (−11.8%) 이탈


def test_g2_budget_cuts_as_nav_falls_and_recovers_when_window_rolls():
    t = G.budget_only("LEV", "CASH", 3, 30, lookback=3)
    o = t(0, "a", 100.0)
    assert abs(o["LEV"] - 0.9) < 1e-9 and abs(o["CASH"] - 0.1) < 1e-9
    assert abs(t(1, "b", 80.0)["LEV"] - 0.375) < 1e-9                         # 바닥 70 → 3 × 10/80
    assert t(2, "c", 70.0) == {"CASH": 1.0}                                     # 바닥에 닿으면 0
    assert abs(t(3, "d", 70.0)["LEV"] - 0.6) < 1e-9                             # 창(3일) 최고 80 → 바닥 56


def test_unknown_spec_raises():
    import pytest
    with pytest.raises(KeyError):
        G.make_target("G9", G.DEFAULT, {}, {}, "LEV", "CASH")
