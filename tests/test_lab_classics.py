"""고전 알고리즘(lab_classics) — 각 규칙이 출처에 적힌 대로 동작하는가 (손으로 계산한 값과 대조)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_classics as C  # noqa: E402
import strategy_lab as L  # noqa: E402


def _days(n):
    return [f"{2010 + i // 336}-{1 + (i % 336) // 28:02d}-{1 + i % 28:02d}" for i in range(n)]


def _bars(px):
    return {d: {"open": p, "high": p, "low": p, "close": p} for d, p in zip(_days(len(px)), px)}


def test_rsi_wilder_by_hand():
    r = C.rsi_wilder([1, 2, 3, 2, 1], 2)
    assert r[:2] == [None, None] and r[2] == 100.0 and r[3] == pytest.approx(50.0) and r[4] == pytest.approx(25.0)


def test_vbreak_buys_at_level_and_sells_next_open():
    d = _days(3)
    o = {d[0]: {"open": 100, "high": 110, "low": 90, "close": 105},
         d[1]: {"open": 100, "high": 112, "low": 99, "close": 111},      # 기준가 100+0.5×20=110 돌파
         d[2]: {"open": 115, "high": 116, "low": 114, "close": 115}}
    dd, vv, n, _ = C.vbreak_curve(o, None, d, 1000.0)
    bc, sc = L._side_cost(False, False), L._side_cost(False, True)
    assert n == 1
    assert vv[2] == pytest.approx(1000.0 * 115 * (1 - sc) / (110 * (1 + bc)))


def test_vbreak_no_breakout_keeps_cash_then_buys():
    d = _days(3)
    o = {d[0]: {"open": 100, "high": 110, "low": 90, "close": 105},
         d[1]: {"open": 120, "high": 121, "low": 119, "close": 120},      # 기준가 120+0.5×20=130 미도달 → 안 산다
         d[2]: {"open": 120, "high": 140, "low": 119, "close": 135}}      # 기준가 120+0.5×2=121 → 121 체결
    _, vv, n, _ = C.vbreak_curve(o, None, d, 1000.0)
    assert n == 1 and vv[1] == 1000.0


def test_turtle_enters_on_55_high_and_exits_on_20_low():
    px = [100.0] * 60 + [101.0] + [101.0] * 5 + [99.0]
    t = C.turtle(_bars(px), "A")
    sig = {i: t(i, d) for i, d in enumerate(_days(len(px)))}
    assert sig[60] == {"A": 1.0}                                   # 55일 최고(100) 돌파
    assert sig[66] == {}                                           # 20일 최저(100) 이탈


def test_golden_cross_and_bollinger():
    up = [100 + i * 0.5 for i in range(260)]
    g = C.golden_cross(_bars(up), "A")
    assert g(259, _days(260)[259]) == {"A": 1.0}
    px = [100.0 + (i % 2) for i in range(30)] + [80.0, 100.6]
    b = C.bollinger_mr(_bars(px), "A")
    out = [b(i, d) for i, d in enumerate(_days(len(px)))]
    assert out[30] == {"A": 1.0} and out[31] == {}                 # −2σ 아래 진입 → 20일선 위 청산


def test_tsmom_holds_only_positive_assets_equal_weight():
    n = 300
    ups = _bars([100 + i for i in range(n)])
    dns = _bars([400 - i for i in range(n)])
    ends = {_days(n)[-1]}
    t = C.tsmom({"U": ups, "D": dns}, ends)
    assert t(n - 1, _days(n)[-1]) == {"U": 0.5}                   # 꺼진 D 의 몫은 현금


def test_all_weather_weights_and_volmgd_cap():
    assert sum(C.AW_WEIGHTS.values()) == pytest.approx(1.0)
    t = C.all_weather({"q"})
    assert t(5, "q") == C.AW_WEIGHTS and t(5, "x") is None
    px = [100 * (1.01 if i % 2 else 0.99) ** (i % 3) for i in range(80)]
    days = _days(80)
    v = C.volmgd(_bars(px), "A", {days[30], days[60]})
    w1, w2 = v(30, days[30]), v(60, days[60])
    assert w1 == {"A": pytest.approx(1.0)} and 0 < w2["A"] <= 1.0   # 첫 달은 c = 자기 분산 → 1
