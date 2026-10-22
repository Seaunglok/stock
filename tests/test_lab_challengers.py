"""도전자 2세대(lab_challengers.i3x) — 일반형이 부모(I3·R1)를 정확히 재현하는지, 새 장치가 적힌 대로 도는지."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_challengers as C  # noqa: E402
import test_lab_reentry as TR  # noqa: E402


@pytest.fixture(scope="module")
def real():
    import strategy_lab as L
    cache = _ROOT / "docs_cache" / "lab"
    if not (cache / "069500_2026-08-24.json").exists():
        pytest.skip("검증 캐시 없음")
    k = L.load_bars("069500", "2014-01-01", L.FULL[1])
    c = L.load_bars("153130", "2014-01-01", L.FULL[1])
    ks = L.load_bars("^KS11", "1996-01-01", L.FULL[1])
    dates = [d for d in L.calendar(k, *L.FULL) if d in c]

    def sim(t):
        return L.simulate({"069500": L.Asset("069500", k), "153130": L.Asset("153130", c)}, dates, t,
                          3_640_000.0, pass_nav=True).curve
    return k, c, ks, sim


def test_general_form_reproduces_parents_on_real_data(real):
    """★ 일반형 i3x 가 부모를 그대로 재현해야 2세대 비교가 공정하다 — I3(검증)·R1(8차)과 자산 곡선 동일."""
    import lab_holdout as H
    import lab_reentry as R
    k, c, ks, sim = real
    assert sim(C.i3x(k, ks, "069500", "153130", 6, 252, **C.SPECS["I3"])) == sim(H.i3(k, ks, "069500", "153130", 6, 252))
    assert sim(C.i3x(k, ks, "069500", "153130", 6, 252, **C.SPECS["R1"])) == sim(
        R.i3r(k, ks, "069500", "153130", 6, 252, "R1"))


def _drive(spec, navs_fn=None):
    days, bars, kospi = TR._scenario()
    t = C.i3x(bars, kospi, "A", "C", 6, 252, **spec)
    nav, w, prev, out = 100.0, 1.0, None, {}
    for i, d in enumerate(days):
        if prev is not None:
            nav *= 1 + w * (bars[d]["close"] / bars[prev]["close"] - 1)
        r = t(i, d, nav)
        if r is not None:
            w = r.get("A", 0.0)
            out[d] = w
        prev = d
    return out


def test_tight_exit_only_in_first_days_after_reentry():
    """R4 장치 — 재진입 직후엔 −5% 에 나가고, 처음 보유(시작)엔 적용하지 않는다."""
    import lab_dd_control as I
    days = [f"2020-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(140)]
    px = [100 + i for i in range(60)] + [159 * 0.85] * 20 + [200 + i for i in range(30)] + [229 * 0.94] * 30
    bars = {d: {"open": p, "close": p} for d, p in zip(days, px)}
    kospi = {d: {"open": 1000 + i, "close": 1000 + i} for i, d in enumerate(days)}
    t = C.i3x(bars, kospi, "A", "C", 6, 252, reset="always", tight_x=5.0, tight_days=60, regime_ma=5)
    sig = {}
    for i, d in enumerate(days):
        r = t(i, d, 100.0)
        if r is not None:
            sig[d] = r.get("A", 0.0)
    exits = [d for d, w in sig.items() if w == 0.0]
    assert exits[0] == days[60]                              # 시작 보유는 −10% 기준(−15% 하락에서 이탈)
    assert len(exits) >= 2 and exits[1] == days[110]         # 재진입 뒤 −6% 하락 → −5% 기준으로 이탈
    assert I is not None


def _two_cycles():
    """상승 → 급락(이탈) → 반등(재진입 1) → 다시 급락(이탈) → 반등(재진입 2) — 252일 안에 재진입 두 번."""
    px, p = [], 100.0
    for seg, step, n in (("up", 1.003, 200), ("dn", 0.984, 10), ("flat", 1.0, 30), ("up", 1.01, 30),
                         ("dn", 0.984, 10), ("flat", 1.0, 30), ("up", 1.01, 40)):
        for _ in range(n):
            p *= step
            px.append(p)
    days = [f"{2020 + i // 336}-{1 + (i % 336) // 28:02d}-{1 + i % 28:02d}" for i in range(len(px))]
    bars = {d: {"open": v, "close": v} for d, v in zip(days, px)}
    kospi = {d: {"open": 1000 + i, "close": 1000 + i} for i, d in enumerate(days)}
    return days, bars, kospi


def _reentry_weights(spec):
    days, bars, kospi = _two_cycles()
    t = C.i3x(bars, kospi, "A", "C", 6, 252, **spec)
    nav, w, prev, seen_zero, out = 100.0, 1.0, None, False, []
    for i, d in enumerate(days):
        if prev is not None:
            nav *= 1 + w * (bars[d]["close"] / bars[prev]["close"] - 1)
        r = t(i, d, nav)
        if r is not None:
            nw = r.get("A", 0.0)
            if seen_zero and nw > 0 and w == 0.0:
                out.append(nw)                               # 재진입한 날의 목표 비중
            seen_zero = seen_zero or nw == 0.0
            w = nw
        prev = d
    return out


def test_trend_condition_refuses_reset_in_long_downtrend():
    """★ R6·R7 장치 — KOSPI 250일선이 내려가는 장에선 리셋하지 않는다(올라가면 R1 과 같다)."""
    days, bars, _ = TR._scenario()
    up = {d: {"open": 1000 + i, "close": 1000 + i} for i, d in enumerate(days)}
    def kd(i):                                      # 240일 하락 뒤 완만한 반등 — 단기선 위(재진입 가능),
        return 3000 - i if i < 240 else 2760 + (i - 240)   # 장기선(50일)은 아직 내려가는 중
    down = {d: {"open": kd(i), "close": kd(i)} for i, d in enumerate(days)}

    def reentry_w(kospi, spec):
        t = C.i3x(bars, kospi, "A", "C", 6, 252, **spec)
        nav, w, prev, seen0, got = 100.0, 1.0, None, False, None
        for i, d in enumerate(days):
            if prev is not None:
                nav *= 1 + w * (bars[d]["close"] / bars[prev]["close"] - 1)
            r = t(i, d, nav)
            if r is not None:
                nw = r.get("A", 0.0)
                if seen0 and nw > 0 and w == 0.0 and got is None:
                    got = nw
                seen0 = seen0 or nw == 0.0
                w = nw
            prev = d
        return got
    short = {"reset_trend_ma": 50, "reset_trend_lag": 10}       # 시나리오가 짧아 250 대신 50 으로 장치만 시험
    assert reentry_w(up, {"reset": "always", **short}) == pytest.approx(1.0)
    w_down = reentry_w(down, {"reset": "always", "regime_ma": 5, **short})
    w_i3 = reentry_w(down, {"reset": "none", "regime_ma": 5})
    assert w_down is not None and w_down == pytest.approx(w_i3) and w_down < 0.9


def test_once_per_year_reset_refuses_second_forgiveness():
    """★ R3 장치 — 252일 안의 두 번째 재진입은 리셋하지 않는다(연속 휩쏘 차단). 첫 재진입은 R1 과 같다."""
    once, always = _reentry_weights(C.SPECS["R3"]), _reentry_weights(C.SPECS["R1"])
    assert len(once) == len(always) == 2
    assert once[0] == pytest.approx(always[0]) == pytest.approx(1.0)
    assert once[1] < always[1] == pytest.approx(1.0)
