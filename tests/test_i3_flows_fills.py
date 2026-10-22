"""입출금 보정(i3_flows)·체결 기록(i3_fills) — 출금이 손실로 보이지 않는지, 체결가를 바르게 읽는지."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import i3_core as K  # noqa: E402
import i3_fills as FL  # noqa: E402
import i3_flows as F  # noqa: E402

CODES = (K.BASE, K.CASH)


def _hold(q_base, p_base, q_cash, p_cash):
    out = []
    if q_base:
        out.append({"symbol": K.BASE, "qty": q_base, "cur": p_base})
    if q_cash:
        out.append({"symbol": K.CASH, "qty": q_cash, "cur": p_cash})
    return out


def test_no_flow_keeps_index_equal_to_nav():
    snap = F.snapshot(_hold(0, 0, 34, 105_900), 3_647_500, CODES)
    flow, how, _ = F.detect_flow(snap, _hold(0, 0, 34, 105_910), 3_647_840, traded_since=False)
    assert how == "none" and flow == 0
    idx, units = F.apply_flow(3_647_500, 1.0, 3_647_840, flow)
    assert idx == 3_647_840 and units == 1.0


def test_withdrawal_is_detected_and_not_seen_as_loss():
    """★ 일부러 깨뜨리기 — 50만원 출금(매매 없는 날): 자동 보정, 성과 지수는 시장 움직임만큼만 변한다."""
    snap = F.snapshot(_hold(0, 0, 34, 105_900), 3_647_500, CODES)
    nav_after = 3_647_500 + 34 * 10 - 500_000                      # 머니마켓 +10원, 50만원 출금
    flow, how, resid = F.detect_flow(snap, _hold(0, 0, 34, 105_910), nav_after, traded_since=False)
    assert how == "auto-withdrawal" and flow == pytest.approx(-500_000)
    idx, units = F.apply_flow(3_647_500, 1.0, nav_after, flow)
    assert idx == pytest.approx(3_647_840) and units < 1.0          # 지수는 출금과 무관
    assert K.budget_exposure([3_647_500, idx]) == 1.0                # 예산이 비중을 깎지 않는다


def test_gain_is_auto_deposit_unless_it_looks_like_a_distribution():
    """입금·SK이노 매도 대금 → 자동 입금. KODEX200 분배금 지급기(2·5·8·11월 초)에 평가액 3% 이하면 분배금(성과)."""
    snap = F.snapshot(_hold(40, 90_000, 0, 0), 3_640_000, CODES)
    flow, how, resid = F.detect_flow(snap, _hold(40, 90_000, 0, 0), 3_640_000 + 142_200, False, day="2026-10-27")
    assert how == "auto-deposit" and flow == pytest.approx(142_200)
    flow, how, _ = F.detect_flow(snap, _hold(40, 90_000, 0, 0), 3_640_000 + 50_000, False, day="2027-05-04")
    assert how == "distribution" and flow == 0                      # 5월 초 · 360만원의 1.4% → 분배금
    flow, how, _ = F.detect_flow(snap, _hold(40, 90_000, 0, 0), 3_640_000 + 500_000, False, day="2027-05-04")
    assert how == "auto-deposit"                                     # 3% 넘으면 분배금이 아니다
    flow, how, _ = F.detect_flow(snap, _hold(40, 90_000, 0, 0), 3_640_000 + 142_200, False, declared=142_200)
    assert how == "declared" and flow == 142_200                    # 운용자 기록이 있으면 그것만


def test_trade_day_uses_fills_to_detect_flows():
    """★ 매매가 있던 날도 체결 기록으로 계산 — 머니마켓 34주 팔고 KODEX200 40주 산 날 30만원 출금을 잡는다."""
    snap = F.snapshot(_hold(0, 0, 34, 105_900), 3_647_500, CODES)
    trades = [{"side": "sell", "code": K.CASH, "fill_qty": 34, "fill_price": 105_910.0},
              {"side": "buy", "code": K.BASE, "fill_qty": 40, "fill_price": 89_000.0}]
    after = F.apply_trades(snap, trades)
    hold_now = _hold(40, 89_500, 0, 0)
    nav_ok = after["cash"] + 40 * 89_500
    flow, how, _ = F.detect_flow(snap, hold_now, nav_ok, traded_since=True, trades=trades, day="2026-10-27")
    assert how == "none" and flow == 0                               # 매매만 있었다 — 입출금 없음
    flow, how, _ = F.detect_flow(snap, hold_now, nav_ok - 300_000, True, trades=trades, day="2026-10-27")
    assert how == "auto-withdrawal" and flow == pytest.approx(-300_000)


def test_trade_day_without_fills_skips_auto_detection_but_applies_declared():
    snap = F.snapshot(_hold(0, 0, 34, 105_900), 3_647_500, CODES)
    flow, how, _ = F.detect_flow(snap, _hold(39, 90_000, 0, 0), 3_100_000, traded_since=True, declared=-500_000)
    assert how == "skip-trade" and flow == -500_000
    unknown = [{"side": "buy", "code": K.BASE, "fill_qty": None, "fill_price": None}]
    _, how, _ = F.detect_flow(snap, _hold(39, 90_000, 0, 0), 3_100_000, True, trades=unknown)
    assert how == "skip-trade"                                       # 체결가를 모르면 추측하지 않는다


def test_small_noise_is_ignored_and_first_day():
    snap = F.snapshot(_hold(0, 0, 34, 105_900), 3_647_500, CODES)
    _, how, _ = F.detect_flow(snap, _hold(0, 0, 34, 105_900), 3_647_500 - 5_000, traded_since=False)
    assert how == "none"                                             # 5천원 < 1만원 한도
    assert F.apply_flow(None, None, 3_647_500, 0) == (3_647_500, 1.0)
    with pytest.raises(ValueError):
        F.apply_flow(100.0, 1.0, 50.0, 60.0)


PAYLOAD = {"success": True, "data": {"return_code": 0, "cntr": [
    {"stk_cd": "A488770", "io_tp_nm": "+매수", "ord_stt": "체결", "ord_tm": "090540", "ord_qty": "34",
     "cntr_qty": "34", "cntr_pric": "105912"},
    {"stk_cd": "A488770", "io_tp_nm": "+매수", "ord_stt": "취소", "ord_tm": "111500", "ord_qty": "1",
     "cntr_qty": "0", "cntr_pric": "0"},                            # 오늘 낮 시험 주문(취소) — 빼야 한다
    {"stk_cd": "A069500", "io_tp_nm": "-매도", "ord_stt": "체결", "ord_tm": "085000", "ord_qty": "10",
     "cntr_qty": "10", "cntr_pric": "88500"},
]}}


def test_parse_fills_buy_and_sell():
    assert FL.parse_fills(PAYLOAD, "488770", "매수", "085000") == (34, 34, 105912.0)
    assert FL.parse_fills(PAYLOAD, "069500", "매도", "084500") == (10, 10, 88500.0)
    assert FL.parse_fills({"success": False}, "488770", "매수") is None


def test_fill_record_slippage_sign():
    r = FL.fill_record("2026-10-23", "buy", "488770", 34, "지정가", 106_965, 105_905, (34, 34, 105_912.0))
    assert r["fill_price"] == 105_912.0 and r["slippage_bp"] == pytest.approx((105_912 / 105_905 - 1) * 1e4, abs=0.01)
    s = FL.fill_record("2026-10-23", "sell", "069500", 10, "시장가", None, 88_600, (10, 10, 88_500.0))
    assert s["slippage_bp"] > 0                                      # 기준보다 싸게 팔면 비용 +
