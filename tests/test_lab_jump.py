"""점프 모형 국면(lab_jump, ㉗) — 미래 자료 없음 · 낙폭 예산이 I3 와 같은 줄 · 동적 계획 · 장부 (11-20, 측정 전 · 합성 자료만)."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_dd_control as I  # noqa: E402
import lab_jump as J  # noqa: E402
import lab_reentry as R  # noqa: E402
import lab_trials as T  # noqa: E402
import strategy_lab as L  # noqa: E402


def days(n: int, start: str = "2010-01-04") -> list[str]:
    out, x = [], date.fromisoformat(start)
    while len(out) < n:
        if x.weekday() < 5:
            out.append(x.isoformat())
        x += timedelta(days=1)
    return out


def two_regime_bars(n: int = 900, seed: int = 0, start: str = "2010-01-04",
                    calm_ms=(0.0008, 0.008), storm_ms=(-0.0015, 0.025)) -> dict[str, dict]:
    """평온 ↔ 폭풍(평균·표준편차) 이 150일씩 번갈아 — 시가는 전일 종가 근처."""
    rng = np.random.default_rng(seed)
    out, c = {}, 100.0
    for k, d in enumerate(days(n, start)):
        calm = (k // 150) % 2 == 0
        r = rng.normal(*calm_ms) if calm else rng.normal(*storm_ms)
        o = c * (1 + rng.normal(0, 0.002))
        c = c * (1 + r)
        out[d] = {"open": o, "close": c}
    return out


def test_declared_constants_and_ledger():
    assert (J.LAM, J.LAM_GRID, J.HALFLIVES, J.WARMUP) == (50.0, (25.0, 50.0, 100.0), (5, 10, 21), 63)
    assert (J.REFIT, J.WIN_MIN, J.WIN_MAX, J.N_INIT, J.MAX_ITER) == (126, 1260, 2772, 10, 20)
    row = [r for r in T.TRIALS if r[3] == J.SOURCE]
    assert len(row) == 1 and row[0][2] == 2                   # J1·J2
    assert T.total_through(J.SOURCE) == 101


def test_ewm_halflife():
    x = np.array([0.0] + [1.0] * 30)
    assert J.ewm(x, 5)[5] == pytest.approx(0.5)              # 반감기 5일 → 5일 뒤 절반


def test_best_path_extremes():
    rng = np.random.default_rng(1)
    d0, d1 = rng.random(200).tolist(), rng.random(200).tolist()
    s, obj = J.best_path(d0, d1, 0.0)                          # 벌점 0 = 날마다 작은 쪽
    assert s == [0 if a <= b else 1 for a, b in zip(d0, d1)]
    assert obj == pytest.approx(sum(min(a, b) for a, b in zip(d0, d1)))
    s, _ = J.best_path(d0, d1, 1e9)                            # 벌점 무한 = 한 국면
    assert len(set(s)) == 1


def _fit_on(bars, lam):
    F, r = J.features([b["close"] for b in bars.values()])
    Z = (F[63:] - F[63:].mean(0)) / F[63:].std(0)
    _, _, s = J.fit(Z, lam, n_init=3)
    truth = np.array([((k + 63) // 150) % 2 == 0 for k in range(len(Z))], int)
    got = (s == J._bull_state(s, r[63:])).astype(int)
    return (got == truth).mean(), 1 + int((np.diff(s) != 0).sum())


def test_fit_recovers_clear_regimes():
    # 뚜렷한 두 국면(평온 0.5% · 폭풍 3%) — 틀리는 몫은 EWM 지연(전환 5번 × 약 15일 ≈ 9%) 정도
    acc, runs = _fit_on(two_regime_bars(900, calm_ms=(0.001, 0.005), storm_ms=(-0.004, 0.03)), 50.0)
    assert acc > 0.8 and runs <= 8                            # 실제 국면 6토막


def test_penalty_reduces_switching():
    # 잡음이 큰 자료(11-20 진단: λ 0 → 49토막 · 200 → 6토막) — 벌점이 클수록 덜 깜빡인다
    bars = two_regime_bars(900)
    runs = [_fit_on(bars, lam)[1] for lam in (0.0, 50.0, 200.0)]
    assert runs[0] > runs[1] > runs[2]


def _leaky_regimes(bars, lam, win_min, win_max, refit, n_init, warmup=63):
    """일부러 깨뜨린 판 — 구간 끝까지 보고 되짚은 경로(미래 자료). 시험이 이것을 잡아야 한다."""
    days_ = sorted(bars)
    F, r = J.features([bars[d]["close"] for d in days_])
    F, r, days_ = F[warmup:], r[warmup:], days_[warmup:]
    out = {}
    for t0 in range(win_min - 1, len(days_), refit):
        lo = max(0, t0 - win_max + 1)
        tr = F[lo:t0 + 1]
        mu, sd = tr.mean(0), tr.std(0)
        _, th, s = J.fit((tr - mu) / sd, lam, n_init)
        bull = J._bull_state(s, r[lo:t0 + 1])
        hi = min(len(days_), t0 + refit)
        D = J._costs((F[lo:hi] - mu) / sd, th)
        path, _ = J.best_path(D[:, 0].tolist(), D[:, 1].tolist(), lam)
        for k in range(t0 - lo, hi - lo):
            out[days_[lo + k]] = int(path[k] == bull)
    return out


def _crash_after(bars, cut_at):
    """cut_at 번째 날부터 20일 동안 하루 −8%, 그 뒤 멈춤 — 지난 날 국면이 바뀌면 미래를 본 것."""
    days_ = sorted(bars)
    out, c = dict(bars), bars[days_[cut_at - 1]]["close"]
    for k, d in enumerate(days_[cut_at:]):
        if k < 20:
            c *= 0.92
        out[d] = {"open": c, "close": c}
    return out


def test_regimes_use_no_future_data():
    bars = two_regime_bars(1000)
    kw = dict(win_min=300, win_max=600, refit=100, n_init=3)
    full = J.regimes(bars, 50.0, **kw)
    cut = sorted(bars)[:790]
    part = J.regimes({d: bars[d] for d in cut}, 50.0, **kw)
    assert part and all(full[d] == v for d, v in part.items())
    again = J.regimes(_crash_after(bars, 790), 50.0, **kw)
    assert all(again[d] == v for d, v in part.items())         # 미래 폭락이 지난 날을 바꾸지 않는다
    assert min(full) == sorted(bars)[63 + 299]                # 첫 신호 = 예열 + 최소 창
    # 같은 장면에서 누수 판은 걸린다(이 시험이 누수를 잡을 힘이 있다 — 11-20 확인 2일)
    lp = _leaky_regimes({d: bars[d] for d in cut}, 50.0, **kw)
    la = _leaky_regimes(_crash_after(bars, 790), 50.0, **kw)
    assert any(la[d] != v for d, v in lp.items())


def test_with_budget_equals_i3r():
    """같은 엔진이면 lab_reentry.i3r(mode I3) 와 같은 자산 곡선 — 실전==검증이 잠근 길과 한 줄."""
    k = two_regime_bars(700, seed=2)
    ks = two_regime_bars(700, seed=3)
    rng = np.random.default_rng(4)
    cash, c = {}, 100_000.0
    for d in sorted(k):
        c *= 1 + 0.00012 + rng.normal(0, 0.00005)
        cash[d] = {"open": c, "close": c}
    dates = sorted(k)
    assets = {"A": L.Asset("A", k), "C": L.Asset("C", cash)}
    ref = L.simulate(assets, dates, R.i3r(k, ks, "A", "C", 6, 252, "I3"), 3_640_000.0, pass_nav=True)
    got = L.simulate(assets, dates, J.with_budget(I.reentry_confirmed(k, ks, "A", 10, 20, "C"), "A", "C", 6, 252),
                     3_640_000.0, pass_nav=True)
    assert got.trades == ref.trades and got.trades > 0
    assert got.curve == ref.curve


def test_jm_engine_protocol():
    st = {"d1": 1, "d2": 1, "d3": 0, "d5": 1}
    t = J.jm_engine(st, "A", "C")
    assert t(0, "d1") == {"A": 1.0}
    assert t(1, "d2") is None
    assert t(2, "d3") == {"C": 1.0}
    assert t(3, "d4") is None                                  # 신호 없는 날은 그대로
    assert t(4, "d5") == {"A": 1.0}
    t2 = J.jm_engine(st, "IDX", None)
    t2(0, "d1")
    t2(1, "d2")
    assert t2(2, "d3") == {}                                   # 현금 없음 = 전부 매도
    t3 = J.jm_engine({"d9": 0}, "A", "C")
    assert t3(0, "d0") == {"A": 1.0} and t3(1, "d9") == {"C": 1.0}   # 신호 전엔 보유로 출발


def test_switches_count():
    st = {"a": 1, "b": 1, "c": 0, "d": 0, "e": 1}
    assert J.switches(st, ["a", "b", "c", "d", "e"]) == (2, pytest.approx(0.6))
