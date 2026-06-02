"""closing_bet exit_rules 순수함수 회귀 테스트 (#11 안전망)."""
from datetime import datetime

from src.mcp_servers.closing_bet_mcp.exit_rules import (
    classify_regime,
    evaluate_exit,
    evaluate_hold_exit,
    evaluate_market_filter,
    init_stop_price,
    ratchet_stop,
)


# ── (c) ATR 트레일 손절 ───────────────────────────────────────────────

def test_init_stop_price_atr_band():
    assert init_stop_price(1000, atr=10, atr_k=2.0, fallback_stop_pct=-2.0) == 980.0


def test_init_stop_price_fallback_when_no_atr():
    # ATR 0 → |fallback_stop_pct|% 밴드
    assert init_stop_price(1000, atr=0, atr_k=2.0, fallback_stop_pct=-2.0) == 980.0


def test_ratchet_stop_raises_on_new_peak():
    peak, stop = ratchet_stop(1000, peak_price=1000, stop_price=980,
                              current_price=1030, atr=10, atr_k=2.0, fallback_stop_pct=-2.0)
    assert peak == 1030
    assert stop == 1010  # 1030 - 2*10


def test_ratchet_stop_never_lowers():
    # 가격 하락해도 stop 은 내려가지 않음
    _, stop = ratchet_stop(1000, peak_price=1030, stop_price=1010,
                           current_price=1005, atr=10, atr_k=2.0, fallback_stop_pct=-2.0)
    assert stop == 1010


def test_evaluate_hold_exit_stop_breach():
    d = evaluate_hold_exit(1000, current_price=1005, stop_price=1010, aged_out=False)
    assert d.action == "SELL_ALL"


def test_evaluate_hold_exit_hold_when_above_stop_and_young():
    d = evaluate_hold_exit(1000, current_price=1020, stop_price=1010, aged_out=False)
    assert d.action == "HOLD"


def test_evaluate_hold_exit_time_exit_when_aged():
    d = evaluate_hold_exit(1000, current_price=1020, stop_price=1010, aged_out=True)
    assert d.action == "SELL_ALL"


# ── 시장 게이트 ───────────────────────────────────────────────────────

def test_market_filter_blocks_weak_today():
    assert evaluate_market_filter(-1.6)["ok"] is False


def test_market_filter_blocks_weak_5d():
    assert evaluate_market_filter(0.0, kospi_5d_pct=-3.5)["ok"] is False


def test_market_filter_ok():
    assert evaluate_market_filter(0.3, kospi_5d_pct=0.5)["ok"] is True


def test_classify_regime():
    assert classify_regime(-1.2, 0.5) == "weak"
    assert classify_regime(0.1, 0.50) == "neutral"
    assert classify_regime(0.8, 0.60) == "strong"


# ── (P1) 시간외 SELL_ALL 오버라이드 완화 ──────────────────────────────

def test_evaluate_exit_ah_dip_but_open_green_not_dumped():
    now = datetime.now().replace(hour=9, minute=2)
    d = evaluate_exit(1000, current_price=1010, after_hours_price=995, now=now)
    assert d.action != "SELL_ALL"   # 시초 회복 → 투매 금지


def test_evaluate_exit_ah_dip_and_open_weak_sells():
    now = datetime.now().replace(hour=9, minute=2)
    d = evaluate_exit(1000, current_price=998, after_hours_price=995, now=now)
    assert d.action == "SELL_ALL"
