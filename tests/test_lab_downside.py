"""하락 예측 신호 판정대(lab_downside) — 선언한 규칙이 적힌 대로 도는지. 합성 자료만 쓴다."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_downside as D  # noqa: E402


def _bars(closes: list[float], start: int = 1) -> dict:
    """2020-01-01 부터 하루씩(달력 날짜면 충분 — 봉의 순서만 본다)."""
    import datetime as dt
    d0 = dt.date(2020, 1, 1)
    return {(d0 + dt.timedelta(days=start - 1 + k)).isoformat(): {"open": c, "close": c} for k, c in enumerate(closes)}


def test_declared_constants():
    """측정 전 선언: 7개 후보 · 격자 3개 · 기본값은 격자 가운데 · D2 +2%p · D3 20회 · D4 2/3."""
    assert tuple(D.CANDIDATES) == ("V1", "V2", "U1", "F1", "K1", "K2", "M1")
    for _, grid, default in D.CANDIDATES.values():
        assert len(grid) == 3 and default == grid[1]
    assert D.VOTERS == ("V1", "V2", "U1", "F1", "K1", "K2")
    assert (D.HIT_EDGE_PP, D.MIN_ENTRIES, D.GRID_PASS) == (2.0, 20, 2)
    assert (D.INV1, D.CASH, D.EQUITY) == ("114800", "153130", 500_000.0)


def test_signals_use_only_bars_up_to_the_day():
    """d 의 상태는 날짜 ≤ d 인 봉만 — 다음 날 봉을 바꿔도 d 의 상태는 그대로."""
    up = _bars([100 + k for k in range(30)])
    d = sorted(up)[24]
    for make in (lambda b: D._below_ma(b, 5), lambda b: D._level_above(b, 120),
                 lambda b: D._change_above(b, 5, 3.0), lambda b: D._vol_above(b, 20, 25)):
        before = make(up)(d)
        crashed = {**up, **{x: {"open": 1.0, "close": 1.0} for x in sorted(up)[25:]}}
        assert make(crashed)(d) == before
    assert D._below_ma(up, 5)(d) is False                  # 오르는 중 → 이평선 위
    assert D._below_ma(_bars([200 - k for k in range(30)]), 5)(d) is True
    assert D._below_ma(up, 50)(d) is None                  # 자료 부족
    assert D._level_above(up, 120)(d) is True and D._level_above(up, 130)(d) is False


def test_us_bar_of_same_date_is_used_and_holidays_carry_last_value():
    """미국·환율 d 일 봉은 한국 d+1 시가 전에 확정 → d 에 쓴다. 그 날 봉이 없으면 직전 봉."""
    vix = {"2020-01-02": {"open": 20, "close": 20}, "2020-01-03": {"open": 40, "close": 40}}
    f = D._level_above(vix, 30)
    assert f("2020-01-02") is False and f("2020-01-03") is True and f("2020-01-06") is True
    assert f("2020-01-01") is None


def test_volatility_and_change():
    flat = _bars([100.0] * 30)
    wild = _bars([100 * (1.05 if k % 2 else 0.95) for k in range(30)])
    d = sorted(flat)[-1]
    assert D._vol_above(flat, 20, 25)(d) is False and D._vol_above(wild, 20, 25)(d) is True
    jump = _bars([20.0] * 10 + [30.0])
    assert D._change_above(jump, 5, 30)(sorted(jump)[-1]) is True      # +50% > 30%
    assert D._change_above(jump, 5, 60)(sorted(jump)[-1]) is False


def test_vote_needs_k_of_six(monkeypatch):
    on = {"V1": True, "V2": True, "U1": False, "F1": False, "K1": True, "K2": None}
    real = D.down_fn

    def fake(code, p, px):
        if code == "M1":
            return real(code, p, px)
        return lambda d, v=on[code]: v
    monkeypatch.setattr(D, "down_fn", fake)
    assert real("M1", 3, {})("x") is None                  # 하나라도 자료 부족이면 판단 없음
    on["K2"] = False
    assert real("M1", 3, {})("x") is True and real("M1", 4, {})("x") is False


def test_short_timing_inverse_only_when_down_and_changed_only():
    st = {"a": None, "b": True, "c": True, "d": False}
    t = D.short_timing(st)
    assert t(0, "a") == {D.CASH: 1.0}                      # 자료 부족 → 현금
    assert t(1, "b") == {D.INV1: 1.0}
    assert t(2, "c") is None                               # 같은 상태 → 재조정 없음
    assert t(3, "d") == {D.CASH: 1.0}
    assert D.entries(st, ["a", "b", "c", "d"]) == 1


def test_hit_rates_next_open_to_following_open():
    base = _bars([100, 100, 90, 95, 80, 85])               # 시가=종가
    dates = sorted(base)
    st = {dates[0]: True, dates[1]: True, dates[2]: False, dates[3]: False}
    h = D.hit_rates(st, base, dates, dates[0], dates[-1])
    # d0: 100→90 하락 · d1: 90→95 상승 · d2: 95→80 하락 · d3: 80→85 상승
    assert h["base"] == 0.5 and h["hit"] == 0.5 and h["days"] == 2
    assert abs(h["worst_up"][0] - (95 / 90 - 1)) < 1e-12 and h["worst_up"][1] == dates[2]


def test_judge_requires_each_period():
    cash = {"박스권": {"cagr": 1.5}, "강세장": {"cagr": 2.0}}
    good = {"seg": {"박스권": {"cagr": 3.0}, "강세장": {"cagr": 2.5}},
            "hit": {"박스권": {"hit": 0.52, "base": 0.49}, "강세장": {"hit": 0.50, "base": 0.47}}, "entries": 25}
    assert all(ok for _, ok in D.judge(good, cash))
    weak = {**good, "seg": {"박스권": {"cagr": 3.0}, "강세장": {"cagr": 1.9}}}
    assert dict(D.judge(weak, cash))["D1"] is False
    miss = {**good, "hit": {"박스권": {"hit": 0.52, "base": 0.49}, "강세장": {"hit": 0.48, "base": 0.47}}}
    assert dict(D.judge(miss, cash))["D2"] is False
    assert dict(D.judge({**good, "entries": 19}, cash))["D3"] is False
