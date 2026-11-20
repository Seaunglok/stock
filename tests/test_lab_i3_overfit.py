"""I3 과최적화 점검(lab_i3_overfit, ㉘) — 통계 함수가 알려진 값·극단 사례대로 움직이는지 (11-20, 측정 전 · 합성 자료만)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_i3_overfit as O  # noqa: E402
import lab_trials as T  # noqa: E402
import strategy_lab as L  # noqa: E402


def test_declared_constants():
    assert O.N_SELECT == 15                     # 연구소 1~5차 — I3 가 뽑힐 때까지
    assert O.N_NOW == T.total()
    assert O.I3_LABEL == "I3 m6·L252"
    assert (O.FULL, O.LONG, O.CSCV_S, O.SHIFT_MIN) == (("2015-07-28", "2026-08-24"), ("1998-01-02", "2026-08-24"), 16, 21)


def test_expected_max_close_to_order_statistic():
    # N(0,1) 100개 최대의 기댓값 2.508 — Bailey·López de Prado 근사
    assert O.expected_max_sr(1.0, 100) == pytest.approx(2.508, abs=0.05)
    assert O.expected_max_sr(1.0, 1000) > O.expected_max_sr(1.0, 100)
    with pytest.raises(ValueError):
        O.expected_max_sr(1.0, 1)


def test_psr_normal_case_is_plain_t():
    sr, t = 0.05, 1000
    assert O.psr_z(sr, t, 0.0, 3.0) == pytest.approx(sr * math.sqrt(t - 1) / math.sqrt(1 + sr * sr / 2))
    # 음의 왜도·두꺼운 꼬리는 z 를 깎는다
    assert O.psr_z(sr, t, -1.0, 10.0) < O.psr_z(sr, t, 0.0, 3.0)


def test_dsr_falls_as_trials_grow():
    a = O.dsr(0.05, 2000, 0.0, 3.0, 0.0004, 2)
    b = O.dsr(0.05, 2000, 0.0, 3.0, 0.0004, 100)
    assert 0 < b < a < 1


def test_min_trl_inverse_and_infinite():
    for d in O.JUDGE_DAYS:
        assert O.min_trl(O.sr_needed(d)) == pytest.approx(d, rel=1e-9)
    assert O.min_trl(0.0) == math.inf
    # 연 샤프 0.5 를 말하려면 10년 넘게 — ㉔ 의 핵심 숫자
    assert O.min_trl(0.5 / math.sqrt(252)) / 252 > 10


def test_moments_normal_sample():
    x = np.random.default_rng(0).normal(0.001, 0.01, 200_000)
    sr, g3, g4 = O.moments(x)
    assert sr == pytest.approx(0.1, abs=0.01)
    assert g3 == pytest.approx(0.0, abs=0.05)
    assert g4 == pytest.approx(3.0, abs=0.1)


def test_memmel_symmetric_and_sign():
    rng = np.random.default_rng(1)
    x = rng.normal(0.0008, 0.01, 3000)
    y = 0.6 * x + rng.normal(-0.0003, 0.008, 3000)
    assert O.memmel_z(x, y) == pytest.approx(-O.memmel_z(y, x))
    assert O.memmel_z(x, y) > 2.0                           # 샤프가 분명히 높은 쪽


def _toy(t=800, seed=2):
    rng = np.random.default_rng(seed)
    a_on, a_in = rng.normal(0, 0.004, t), rng.normal(0.0003, 0.01, t)
    a_on[0] = a_in[0] = 0.0
    z = np.zeros(t)
    return (a_on, a_in), (z, z), np.array([t // 2, t - 1])


def test_recon_full_exposure_is_buy_and_hold():
    a, c, _ = _toy()
    r = O.recon(np.ones((1, len(a[0]))), a, c)[0]
    want = (1 + a[0]) * (1 + a[1]) - 1
    assert r[0] == 0.0
    assert r[1] == pytest.approx(a[1][1])                 # 첫날 밤사이는 아직 현금
    assert np.allclose(r[2:], want[2:])


def test_path_stats_matches_strategy_lab_metrics():
    a, c, _ = _toy()
    t = len(a[0])
    dates = [f"{2000 + k // 250}-{1 + (k % 250) // 21:02d}-{1 + k % 21:02d}" for k in range(t)]
    ye = O.year_ends(dates)
    r = O.recon(np.full((1, t), 0.7), a, c)
    st = O.path_stats(r, ye)
    curve = list(np.cumprod(1 + r[0]))
    m = L.metrics(dates, curve)
    assert st["mdd"][0] == pytest.approx(m["mdd"])
    assert st["cagr"][0] == pytest.approx(m["cagr"])
    assert st["worst"][0] == pytest.approx(m["worst_year"])


def test_timing_constant_exposure_has_no_timing():
    a, c, ye = _toy()
    out = O.timing_test(np.full(len(a[0]), 0.5), a, c, ye)
    assert out["p_mdd"] == pytest.approx(1.0)              # 모든 이동이 같은 경로
    assert out["exposure"] == pytest.approx(0.5)


def test_timing_perfect_foresight_is_significant():
    a, c, ye = _toy()
    e = np.roll((a[1] > 0).astype(float), -1)              # 장중 비중 e_{t−1} = 오늘 장중이 오를 때만 1
    out = O.timing_test(e, a, c, ye)
    assert out["p_mdd"] < 0.01 and out["p_cagr"] < 0.01


def test_pbo_noise_is_coin_flip_and_dominant_is_zero():
    rng = np.random.default_rng(3)
    noise = rng.normal(0, 0.01, (12, 1600))
    assert 0.2 < O.cscv(noise, 8, "sharpe")["pbo"] < 0.8
    strong = noise.copy()
    strong[0] += 0.003
    for metric in ("sharpe", "mar"):
        res = O.cscv(strong, 8, metric)
        assert res["pbo"] < 0.05 and (res["best"] == 0).mean() > 0.95
        assert res["combos"] == 70                          # C(8,4)


def test_tracked_records_last_weight():
    calls = iter([{"A": 1.0}, None, {"C": 1.0}, {"A": 0.4, "C": 0.6}])
    t = O.tracked(lambda i, d, *nav: next(calls), "A")
    for k in range(4):
        t(k, f"d{k}", 1.0)
    assert t.hist == [1.0, 1.0, 0.0, 0.4]
