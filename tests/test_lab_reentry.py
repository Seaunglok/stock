"""재진입 개선 실험(lab_reentry) — 비교 기준이 검증한 I3 와 같은지, 리셋이 하는 일이 적힌 일과 같은지."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_reentry as R  # noqa: E402


def test_i3_mode_equals_validated_i3_on_real_data():
    """★ 비교 기준이 어긋나면 측정이 무의미 — mode='I3' 는 lab_holdout.i3 와 자산 곡선이 같아야 한다."""
    import lab_holdout as H
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
    assert sim(R.i3r(k, ks, "069500", "153130", 6, 252, "I3")) == sim(H.i3(k, ks, "069500", "153130", 6, 252))


def _scenario():
    """상승 200일 → 15% 급락(엔진 이탈) → 횡보 30일 → 강한 상승(20일 고점 돌파 = 재진입)."""
    px, p = [], 100.0
    for _ in range(200):
        p *= 1.003
        px.append(p)
    for _ in range(10):
        p *= 0.984
        px.append(p)
    for _ in range(30):
        px.append(p)
    for _ in range(40):
        p *= 1.01
        px.append(p)
    days = [(date(2020, 1, 1) + timedelta(days=i)).isoformat() for i in range(len(px))]
    bars = {d: {"open": v, "close": v} for d, v in zip(days, px)}
    kospi = {d: {"open": 1000 + i, "close": 1000 + i} for i, d in enumerate(days)}   # 늘 MA120 위
    return days, bars, kospi


def _weights(mode):
    days, bars, kospi = _scenario()
    t = R.i3r(bars, kospi, "A", "C", 6, 252, mode)
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


def test_reset_raises_weight_at_reentry():
    """★ I3 는 재진입 때 이탈 손실만큼 비중이 깎인다. R1 은 기준점을 다시 잡아 100%, R2 는 1년 최고치 −20%
    상한이 걸려 그 사이(이 시나리오는 자산이 최고치보다 ~9% 아래 → 6×(0.91−0.80)/0.91 ≈ 71%)."""
    i3, r1, r2 = _weights("I3"), _weights("R1"), _weights("R2")
    reentry = [d for d, w in i3.items() if w > 0 and d > min(d for d, x in i3.items() if x == 0)][0]
    assert i3[reentry] < r2[reentry] < r1[reentry] == pytest.approx(1.0)
    assert i3[reentry] < 0.6 and r2[reentry] > 0.65


def test_r2_never_risks_below_cap_of_year_peak():
    """★ R2 의 바닥은 1년 최고치 × (1 − CAP_DD) 아래로 내려가지 않는다 — 자산이 그 선에 닿으면 비중 0."""
    import lab_dd_control as I
    days, bars, kospi = _scenario()
    t = R.i3r(bars, kospi, "A", "C", 6, 252, "R2")
    navs = [100.0] * 200 + [79.0]                     # 1년 최고치 100 → 79 (CAP 20% 아래)
    w = None
    for i, (d, nav) in enumerate(zip(days, navs)):
        r = t(i, d, nav)
        if r is not None:
            w = r.get("A", 0.0)
    assert w == 0.0
    assert I is not None
