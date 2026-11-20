"""10세대 X10a 변동성 비례 이탈폭(lab_gen10, ㉕) — 선언 그대로인지: 평소엔 I3 엔진과 같다 · 넓히기만 · 고점 때만 다시 잡는다 (11-20)."""
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

import i3_core as K  # noqa: E402
import i3_shadow as S  # noqa: E402
import lab_dd_control as I  # noqa: E402
import lab_gen10 as G  # noqa: E402
import lab_trials as T  # noqa: E402


def days(n: int, start: str = "2015-01-05") -> list[str]:
    out, x = [], date.fromisoformat(start)
    while len(out) < n:
        if x.weekday() < 5:
            out.append(x.isoformat())
        x += timedelta(days=1)
    return out


def bars_from(rets, start: str = "2015-01-05") -> dict[str, dict]:
    out, c = {}, 100.0
    for d, r in zip(days(len(rets), start), rets):
        o = c
        c = c * (1 + r)
        out[d] = {"open": o, "close": c}
    return out


def test_declared_constants_and_registry():
    assert (G.X_BASE, G.SIGMA_N) == (K.ENGINE_X, K.ENGINE_N)              # I3 엔진 10% · 20일 그대로
    assert (G.SIGMA_REF, G.CAP_MULT, G.REGISTER_ON) == (0.156, 2.0, "2026-11-23")
    row = [r for r in T.TRIALS if r[3] == G.SOURCE]
    assert len(row) == 1 and row[0][2] == 1 and T.total_through(G.SOURCE) == 102
    m = next(x for x in S.MEMBERS if x.name == G.NAME)
    assert (m.family, m.registered) == (G.FAMILY, G.REGISTER_ON) and m.name not in S.INTAKE_EXCEPTIONS
    assert set(m.codes) == {K.BASE, K.CASH, S.KOSPI} and "11-20" in m.admitted
    assert S.CAPACITY == 30 and S.DISPLAY[G.NAME] == "변동성 비례 이탈폭(X10a)"


def test_exit_pct_widens_only_and_caps():
    calm = [100 * (1 + 0.001 * (-1) ** k) for k in range(40)]              # σ ≈ 1.6% 연 — 기준 아래
    assert G.exit_pct(calm, 39) == 10.0
    assert G.exit_pct(calm, 5) == 10.0                                       # 자료 모자라면 I3 그대로
    rng = np.random.default_rng(0)
    wild = list(100 * np.cumprod(1 + rng.normal(0, 0.06, 40)))             # 연 95% — 상한
    assert G.exit_pct(wild, 39) == 20.0
    mid = list(100 * np.cumprod(1 + rng.normal(0, 0.0147, 40)))            # 연 ~23% — 그 사이 비례
    s = G.sigma(mid, 39)
    assert G.exit_pct(mid, 39) == pytest.approx(10.0 * s / G.SIGMA_REF) and 10.0 < G.exit_pct(mid, 39) < 20.0


def test_same_as_i3_engine_when_volatility_is_normal():
    """평소 변동성(기준 아래)에선 날마다 lab_dd_control.reentry_confirmed 와 같은 비중 — 다른 건 이탈폭뿐."""
    rng = np.random.default_rng(1)
    rets = rng.normal(0.0004, 0.005, 900)                                   # 연 ~8% — σ20 이 15.6% 를 넘을 일이 없다
    rets[300:340] = -0.004                                                   # 이탈·재진입이 일어나게
    k, ks = bars_from(rets), bars_from(rng.normal(0.0004, 0.005, 900))
    a = G.vol_exit_engine(k, ks, "A", "C")
    b = I.reentry_confirmed(k, ks, "A", 10, 20, "C")
    outs = [(a(i, d), b(i, d)) for i, d in enumerate(sorted(k))]
    assert all(x == y for x, y in outs)
    assert sum(1 for x, _ in outs if x is not None) >= 3                   # 실제로 매매가 있었다


def test_high_volatility_peak_delays_exit_and_does_not_narrow_later():
    """새 고점 때 변동성이 높으면 −10% 에선 안 나가고, 하락 중 변동성이 가라앉아도 이탈선은 그대로(고점 때 값)."""
    up = [0.04, -0.03] * 30                                                  # +4%·−3% 번갈아 — 연 ~55%, 낙폭은 3%뿐
    up[-1] = 0.05                                                            # 마지막 날 새 고점
    down = [-0.0105] * 12 + [0.0] * 25                                       # −12% 뒤 멈춤 — σ20 이 0 으로 가라앉는다
    #   (11-20 일부러 깨뜨리기: 멈춤 없이 12일만이면 20일 창에 오르던 날이 남아 '날마다 다시 잡기' 결함을 못 잡았다)
    k = bars_from(up + down)
    ks = bars_from([0.001] * len(up + down))
    a = G.vol_exit_engine(k, ks, "A", "C")
    b = I.reentry_confirmed(k, ks, "A", 10, 20, "C")
    dl = sorted(k)
    ra = [a(i, d) for i, d in enumerate(dl)]
    rb = [b(i, d) for i, d in enumerate(dl)]
    assert any(r == {"C": 1.0} for r in rb[60:])                           # I3 는 −10% 에서 나갔다
    assert all(r is None for r in ra[60:])                                  # X10a 는 아직 보유
    assert a.state["x"] == 20.0                                              # 고점 때 잡은 넓은 이탈폭(상한)이 남아 있다
    # 같은 하락이 −20% 를 넘으면 그때는 나간다(상한이 있다)
    k2 = bars_from(up + [-0.0105] * 25)
    a2 = G.vol_exit_engine(k2, bars_from([0.001] * 85), "A", "C")
    assert any(a2(i, d) == {"C": 1.0} for i, d in enumerate(sorted(k2)))
