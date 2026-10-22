"""장중 손절 S1(lab_intraday) — 새 시뮬레이터가 검증된 I3 를 1원까지 재현하는지, 장중 체결이 적힌 대로인지."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_intraday as LI  # noqa: E402
import strategy_lab as L  # noqa: E402


@pytest.fixture(scope="module")
def real():
    cache = _ROOT / "docs_cache" / "lab"
    if not (cache / "ohlc_069500_2026-10-21.json").exists() or not (cache / "153130_2026-10-21.json").exists():
        pytest.skip("캐시 없음")
    import lab_classics as C
    k = C.load_ohlc("069500", "2014-01-01", "2026-10-21")
    c = L.load_bars("153130", "2014-01-01", "2026-10-21")
    ks = L.load_bars("^KS11", "1996-01-01", "2026-08-24")
    dates = [d for d in L.calendar(k, *L.FULL) if d in c]
    return k, c, ks, dates


def test_new_simulator_reproduces_validated_i3_exactly(real):
    """★ 장중 손절을 끄면 strategy_lab.simulate(lab_holdout.i3) 와 자산곡선·매매 수가 같아야 S1 비교가 공정하다."""
    import lab_holdout as H
    k, c, ks, dates = real
    ref = L.simulate({"069500": L.Asset("069500", k), "153130": L.Asset("153130", c)}, dates,
                     H.i3(k, ks, "069500", "153130", *H.I3_DEFAULT), LI.EQUITY, pass_nav=True)
    mine, ev = LI.i3_sim(k, ks, dates, LI.EQUITY, c, intraday=False)
    assert mine.curve == ref.curve and mine.trades == ref.trades and not ev


def _ohlc(rows):
    days = [f"2020-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(len(rows))]
    return days, {d: {"open": o, "high": h, "low": lo, "close": c} for d, (o, h, lo, c) in zip(days, rows)}


def _kospi(days):
    return {d: {"open": 1000 + i, "close": 1000 + i} for i, d in enumerate(days)}


def test_intraday_stop_fills_at_level_or_gap_open():
    """손절선(최고 종가 100 × 0.9 = 90)에 장중 닿으면 90, 시가가 이미 아래면 시가."""
    rows = [(100, 100, 100, 100)] * 3 + [(99, 99, 89, 95)]                 # 저가 89 ≤ 90 → 90 체결
    days, o = _ohlc(rows)
    r, ev = LI.i3_sim(o, _kospi(days), days, 0.0, None, intraday=True, asset="A", regime_ma=2)
    assert ev and ev[0][0] == days[3] and "90" in ev[0][1] and "갭" not in ev[0][1]
    rows = [(100, 100, 100, 100)] * 3 + [(85, 86, 84, 85)]                 # 갭 하락 85 < 90 → 시가 85
    days, o = _ohlc(rows)
    r, ev = LI.i3_sim(o, _kospi(days), days, 0.0, None, intraday=True, asset="A", regime_ma=2)
    assert ev and "85" in ev[0][1] and "갭" in ev[0][1]


def test_close_based_i3_does_not_sell_on_intraday_touch():
    """같은 날(장중 89, 종가 95) — I3(종가 기준)는 팔지 않는다. 이것이 둘의 차이(흔들림에 털릴 위험)."""
    rows = [(100, 100, 100, 100)] * 3 + [(99, 99, 89, 95)]
    days, o = _ohlc(rows)
    _, ev = LI.i3_sim(o, _kospi(days), days, 0.0, None, intraday=False, asset="A", regime_ma=2)
    assert ev == []
