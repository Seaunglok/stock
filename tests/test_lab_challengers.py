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


def _reentry_on_same_navs(kospi, spec, regime_ma=None):
    """I3 로 굴린 같은 자산 경로를 두 판단에 똑같이 넣고, I3 의 첫 재진입일 목표 비중을 비교한다
    (자산 경로가 같아야 쿠션이 같아 배수만의 효과가 보인다)."""
    days, bars, _ = TR._scenario()
    extra = {} if regime_ma is None else {"regime_ma": regime_ma}
    base = C.i3x(bars, kospi, "A", "C", 6, 252, reset="none", **extra)
    nav, w, prev, navs, ws = 100.0, 1.0, None, [], []
    for i, d in enumerate(days):
        if prev is not None:
            nav *= 1 + w * (bars[d]["close"] / bars[prev]["close"] - 1)
        navs.append(nav)
        r = base(i, d, nav)
        if r is not None:
            w = r.get("A", 0.0)
        ws.append(w)
        prev = d
    k = next(i for i in range(1, len(days)) if ws[i - 1] == 0.0 and ws[i] > 0)
    t = C.i3x(bars, kospi, "A", "C", 6, 252, **spec, **extra)
    got = None
    for i, d in enumerate(days[:k + 1]):
        r = t(i, d, navs[i])
        if r is not None:
            got = r.get("A", 0.0)
    return got, ws[k]


def test_trend_multiplier_scales_budget_only_by_long_trend():
    """★ 6세대 장치 — 장기선이 오르면 배수 m_up(재진입 비중 = I3 × 8/6, 상한 1), 내려가면 I3 그대로(T6a)·
    m_down(T6c, I3 × 4/6). 배수만 바뀌고 엔진·바닥선은 그대로여야 한다."""
    days, _, _ = TR._scenario()
    up = {d: {"open": 1000 + i, "close": 1000 + i} for i, d in enumerate(days)}
    down = {d: {"open": (3000 - i if i < 240 else 2760 + (i - 240)),
                "close": (3000 - i if i < 240 else 2760 + (i - 240))} for i, d in enumerate(days)}
    short = {"m_trend_ma": 50, "m_trend_lag": 10}                 # 시나리오가 짧아 250 대신 50 — 장치만 시험
    t6a, base = _reentry_on_same_navs(up, {"reset": "none", "m_up": 8, **short})
    assert base < 0.75 and t6a == pytest.approx(min(1.0, base * 8 / 6))
    t6a_dn, base_dn = _reentry_on_same_navs(down, {"reset": "none", "m_up": 8, **short}, regime_ma=5)
    assert t6a_dn == pytest.approx(base_dn) and base_dn > 0
    t6c_dn, _ = _reentry_on_same_navs(down, {"reset": "none", "m_up": 8, "m_down": 4, **short}, regime_ma=5)
    assert t6c_dn == pytest.approx(base_dn * 4 / 6)


def _vol_world(first: float, last: float, switch: int = 380, n: int = 400):
    """KOSPI 일간 수익률이 ±first 로 흔들리다 switch 일부터 ±last. 자산은 꾸준히 올라 엔진은 계속 보유."""
    days = [f"{2020 + i // 336}-{1 + (i % 336) // 28:02d}-{1 + i % 28:02d}" for i in range(n)]
    rets = [0.0] + [(1 if j % 2 else -1) * (first if j < switch else last) for j in range(1, n)]
    cl, c = [], 1000.0
    for r in rets:
        c *= 1 + r
        cl.append(c)
    kospi = {d: {"open": v, "close": v} for d, v in zip(days, cl)}
    bars = {d: {"open": 100.0 + i, "close": 100.0 + i} for i, d in enumerate(days)}
    return days, bars, kospi, rets


def _weight_after_drop(world, drop_day: int, spec: dict) -> float:
    """drop_day 에 계좌가 1년 최고치의 90% 로 떨어졌을 때의 목표 비중(그 전엔 최고치 그대로)."""
    days, bars, kospi, _ = world
    t = C.i3x(bars, kospi, "A", "C", 6, 252, **spec)
    w = None
    for i, d in enumerate(days[:drop_day + 1]):
        r = t(i, d, 100.0 if i < drop_day else 90.0)
        if r is not None:
            w = r.get("A", 0.0)
    return w


def test_vol_brake_only_cuts_the_multiplier_when_short_vol_exceeds_long():
    """★ 7세대 장치 — σ20 > σ252 면 배수 × σ252/σ20(하한 m_min), 조용하거나 흔들림이 가라앉으면 그대로(늘리지 않는다).
    기댓값은 statistics.pstdev 로 따로 계산한다."""
    import statistics as stt
    brake = {"reset": "none", "vol_short": 20, "vol_long": 252, "m_min": 2}
    plain = {"reset": "none"}
    cushion = (90.0 - 0.82 * 100.0) / 90.0
    k = 395
    calm = _vol_world(0.005, 0.005)
    assert _weight_after_drop(calm, k, brake) == pytest.approx(_weight_after_drop(calm, k, plain)) == pytest.approx(6 * cushion)
    settled = _vol_world(0.02, 0.005)                          # 흔들리다 가라앉음 — σ20 < σ252 → 늘리지 않는다
    assert _weight_after_drop(settled, k, brake) == pytest.approx(6 * cushion)
    spike = _vol_world(0.005, 0.02)                            # 조용하다 흔들림 — 비율만큼 줄인다
    rets = spike[3]
    ratio = stt.pstdev(rets[k - 251:k + 1]) / stt.pstdev(rets[k - 19:k + 1])
    assert 2 / 6 < ratio < 1
    assert _weight_after_drop(spike, k, brake) == pytest.approx(6 * ratio * cushion)
    big = _vol_world(0.005, 0.06)                              # 아주 크게 흔들림 — 하한 2
    assert _weight_after_drop(big, k, brake) == pytest.approx(2 * cushion)


def test_gen7_specs_are_the_declared_numbers():
    """7세대 선언(lab_gen7) — 20 = 엔진 n, 252 = L, 하한 2 = I2 격자 최솟값. V7a 는 T6c 그대로 + 브레이크."""
    import lab_dd_control as I
    import lab_gen6 as G6
    import lab_gen7 as G7
    import lab_holdout as H
    assert G7.BRAKE == {"vol_short": 20, "vol_long": H.I3_DEFAULT[1], "m_min": min(I.I2_GRID)}
    assert {k: v for k, v in G7.SPECS7["V7a"].items() if k in G6.SPECS6["T6c"]} == G6.SPECS6["T6c"]


def test_gen6_specs_are_the_declared_numbers():
    """6세대 선언(lab_gen6) — 숫자는 I3 격자 끝값(8·4)과 R6 장기 추세(250·20), 새 숫자 없음. T6b 는 R6 그대로 + 배수."""
    import lab_gen6 as G6
    import lab_holdout as H
    assert {m for m, _ in H.I3_GRID} >= {G6.M_UP, G6.M_DOWN_C, H.I3_DEFAULT[0]}
    assert G6.TREND == {"m_trend_ma": C.SPECS["R6"]["reset_trend_ma"], "m_trend_lag": C.SPECS["R6"]["reset_trend_lag"]}
    assert {k: v for k, v in G6.SPECS6["T6b"].items() if k in C.SPECS["R6"]} == C.SPECS["R6"]


def test_once_per_year_reset_refuses_second_forgiveness():
    """★ R3 장치 — 252일 안의 두 번째 재진입은 리셋하지 않는다(연속 휩쏘 차단). 첫 재진입은 R1 과 같다."""
    once, always = _reentry_weights(C.SPECS["R3"]), _reentry_weights(C.SPECS["R1"])
    assert len(once) == len(always) == 2
    assert once[0] == pytest.approx(always[0]) == pytest.approx(1.0)
    assert once[1] < always[1] == pytest.approx(1.0)
