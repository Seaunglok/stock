"""공격형 트랙 1세대(lab_aggr 양방향 · lab_orb 단타) — 선언한 규칙이 적힌 대로 도는지. 합성 자료만 쓴다."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_aggr as A  # noqa: E402
import lab_orb as B  # noqa: E402


def _bars(closes: list[float], start_month: int = 1) -> dict:
    """영업일 대신 '달마다 21일' 합성 일봉 — 2010-01-01 부터."""
    out = {}
    for k, c in enumerate(closes):
        m, d = divmod(k, 21)
        y, mm = divmod(start_month - 1 + m, 12)
        out[f"{2010 + y}-{mm + 1:02d}-{d + 1:02d}"] = {"open": c, "close": c}
    return out


def test_declared_constants_match_operator_decisions():
    """운용자 결정(10-28): 정지선 −30% · 50만원 · 6개 후보 · 2배 인버스 제외 · 월 10% × 36 은 보고만."""
    assert A.AG_MAX_MDD_PCT == 30.0 and A.AG_EQUITY == 500_000.0 and B.B_MAX_MDD_PCT == 30.0
    assert A.SPECS == ("A1a", "A1b", "A2a", "A2b", "A3a", "A3b")
    assert "252670" in A.EXCLUDED and "252670" not in (*A.LONG.values(), A.INV1)
    assert A.ROLL_3Y == 756 and (A.A1_DEFAULT, A.A2_DEFAULT) == (10, 12)
    assert B.B_START > "2026-10-28"                 # 선언일 다음 날부터 — 선언 뒤에 온 데이터만 성적


def test_faber_and_tsmom_go_inverse_in_downtrend_and_long_in_uptrend():
    up = _bars([100 + k for k in range(21 * 14)])
    dn = _bars([500 - k for k in range(21 * 14)])
    for bars, want in ((up, "up"), (dn, "down")):
        ends = A.C.month_ends(sorted(bars))
        last = max(ends)
        assert A.faber_ls(bars, 10, ends)(0, last) == want
        assert A.tsmom_ls(bars, 12, ends)(0, last) == want
        assert A.faber_ls(bars, 10, ends)(0, min(ends)) == "flat"      # 자료 부족은 현금


def test_changed_only_emits_on_state_change():
    seq = iter(["up", "up", None, "down", "down", "flat"])
    t = A._changed_only(lambda i, d: next(seq), "L", "INV", "CASH")
    assert [t(i, "d") for i in range(6)] == [{"L": 1.0}, None, None, {"INV": 1.0}, None, {"CASH": 1.0}]


def test_engine_ls_inverse_only_when_out_and_kospi_below_ma120():
    """엔진 이탈(−10%) 뒤: KOSPI 가 120일선 아래면 인버스, 위면 현금 — 엔진은 reentry_confirmed 그대로."""
    closes = [100.0] * 130 + [100 - 2 * k for k in range(1, 11)]           # 마지막 10일 하락 → 이탈
    bars = _bars(closes)
    days = sorted(bars)
    st = A.engine_ls(bars, bars, 10, 20)
    states = [st(i, d) for i, d in enumerate(days)]
    assert states[0] == "up" and states[-1] == "down"
    hi = {d: {"open": 1e6, "close": 1e6} for d in days}                    # KOSPI 가 늘 120일선 위인 세계
    hi[days[-1]] = {"open": 2e6, "close": 2e6}
    st2 = A.engine_ls(bars, hi, 10, 20)
    assert [st2(i, d) for i, d in enumerate(days)][-1] == "flat"


def test_rolling_and_monthly_metrics():
    curve = [100.0, 110.0, 99.0, 120.0]
    assert round(A.rolling_min(curve, 2), 6) == round((99 / 100 - 1) * 100, 6)
    assert A.rolling_min(curve, 4) != A.rolling_min(curve, 4)               # 창보다 짧으면 nan
    assert A.dd_events([100, 60, 110, 70, 120], 30.0) == 2
    mr = A.monthly_returns(["2026-01-05", "2026-01-30", "2026-02-27"], [100.0, 110.0, 99.0])
    assert [round(x, 6) for x in mr] == [10.0, -10.0]


def _min(t: str, o, h, l, c) -> dict:
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": 1}


def _day(first5_up: bool, path: list[tuple[str, float, float, float, float]], close: float) -> list[dict]:
    o, c = (100.0, 101.0) if first5_up else (101.0, 100.0)
    bars = [_min(t, o, max(o, c), 99.5 if first5_up else 99.8, o) for t in B.OR_BARS[:-1]]
    bars.append(_min(B.OR_BARS[-1], o, max(o, c), 99.5 if first5_up else 99.8, c))
    bars += [_min(*p) for p in path]
    bars.append(_min(B.CLOSE_T, close, close, close, close))
    return bars


def test_orb_long_day_exits_at_close_with_paper_sizing_and_costs():
    sig = _day(True, [("0905", 101, 101.5, 100.5, 101.2)], 102.0)
    r = B.orb_day(sig, sig, sig)
    # 진입 101, 손절 99.5(첫 5분 저가) → R 1.49% → 크기 min(1, 1%/1.49%) ≈ 67%
    assert r["side"] == "long" and r["how"] == "종가" and r["stop"] == 99.5
    size = 0.01 / ((101 - 99.5) / 101)
    assert abs(r["ret"] - (size * (102 / 101 - 1) - size * 2 * B.SIDE_COST)) < 1e-12


def test_orb_stop_first_gap_and_down_day_buys_inverse():
    sig_dn = _day(False, [("0905", 100, 100, 99, 99.5)], 98.0)
    inv = _day(True, [("0905", 101, 101, 99.0, 99.2), ("0906", 99, 99, 98, 98.5)], 105.0)
    r = B.orb_day(sig_dn, sig_dn, inv)
    assert r["side"] == "inv" and r["how"] == "손절" and r["exit"] == 99.5   # 0905 봉 저가 99.0 ≤ 손절 99.5, 시가 101 은 위 → 손절가
    gap = _day(True, [("0905", 101, 101, 100.6, 100.8), ("0906", 98, 98.5, 97, 98)], 105.0)
    rg = B.orb_day(gap, gap, gap)
    assert rg["how"] == "손절" and rg["exit"] == 98                          # 갭으로 손절 아래 시작 → 그 시가


def test_orb_doji_skips_and_target_hits():
    flat = [_min(t, 100, 100.2, 99.8, 100) for t in B.OR_BARS] + [_min("0905", 100, 100, 100, 100),
                                                                   _min(B.CLOSE_T, 100, 100, 100, 100)]
    assert B.orb_day(flat, flat, flat)["side"] is None
    sig = _day(True, [("0905", 101, 101, 100.9, 101), ("0906", 101, 120, 101, 119)], 110.0)
    r = B.orb_day(sig, sig, sig)
    assert r["how"] == "익절" and r["exit"] == 101 + 10 * (101 - 99.5)
