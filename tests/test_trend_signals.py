"""trend_mcp.signals 순수함수 회귀 테스트."""
from src.mcp_servers.trend_mcp.signals import (
    TrendConfig,
    classify_zone,
    entry_signal,
    is_big_bullish_candle,
    is_consolidation,
    ma_uptrend,
    moving_average,
    relative_strength,
    trend_exit,
    volume_surge_ok,
)


def _bar(o, h, l, c, v=1000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v, "value": c * v}


def _rising(n=130, start=100.0, end=130.0):
    out = []
    for i in range(n):
        c = start + (end - start) * i / (n - 1)
        out.append(_bar(c - 0.1, c + 0.1, c - 0.2, c))
    return out


# ── 지표 ──────────────────────────────────────────────────────────────────

def test_moving_average():
    assert moving_average([1, 2, 3, 4], 2) == 3.5
    assert moving_average([1, 2], 5) is None


def test_ma_uptrend():
    rising = [100 + i for i in range(60)]
    assert ma_uptrend(rising, 20, 20) is True
    falling = [100 - i for i in range(60)]
    assert ma_uptrend(falling, 20, 20) is False


def test_relative_strength():
    stock = [100 + i for i in range(61)]   # +60%
    kospi = [100] * 61                      # 0%
    assert relative_strength(stock, kospi, 60) > 0
    assert relative_strength(kospi, stock, 60) < 0


def test_big_bullish_candle():
    assert is_big_bullish_candle(_bar(100, 106, 99, 105), body_pct=4, wick_max=0.3) is True   # +5%, 짧은 위꼬리
    assert is_big_bullish_candle(_bar(100, 110, 99, 102), body_pct=4, wick_max=0.3) is False  # 위꼬리 김
    assert is_big_bullish_candle(_bar(100, 101, 98, 99), body_pct=4, wick_max=0.3) is False    # 음봉


def test_consolidation():
    box = [_bar(100, 101, 99, 100) for _ in range(21)]   # 저변동 박스
    assert is_consolidation(box, lookback=20, max_range_pct=15) is True
    wide = [_bar(100, 130, 80, 100) for _ in range(21)]   # 고변동
    assert is_consolidation(wide, lookback=20, max_range_pct=15) is False


def test_volume_surge():
    bars = [_bar(100, 101, 99, 100, v=1000) for _ in range(21)]
    bars[-1] = _bar(100, 101, 99, 100, v=2500)            # 2.5배
    assert volume_surge_ok(bars, mult=2.0) is True
    assert volume_surge_ok(bars, mult=3.0) is False


# ── 진입 신호 ───────────────────────────────────────────────────────────────

def test_entry_largecap_pass():
    ohlcv = _rising(130, 100, 130)        # 완만한 상승 → 정배열 + 눌림권
    kospi = [100.0] * 130                 # 코스피 횡보 → 종목 상대강도 +
    sig = entry_signal(ohlcv, kospi, TrendConfig(mode="largecap"))
    assert sig.passed is True, sig.gates
    # 손익비 1:3 — 목표폭 = 손절폭 × 3
    assert abs((sig.target - 130) - 3 * (130 - sig.stop)) < 0.5


def test_entry_largecap_fail_downtrend():
    ohlcv = _rising(130, 130, 100)        # 하락 추세 → price < MA
    kospi = [100.0] * 130
    sig = entry_signal(ohlcv, kospi, TrendConfig(mode="largecap"))
    assert sig.passed is False


def test_entry_insufficient_data():
    sig = entry_signal(_rising(30), [100.0] * 30, TrendConfig(mode="largecap"))
    assert sig.passed is False and "데이터 부족" in sig.reason


# ── 청산 신호 ───────────────────────────────────────────────────────────────

def test_trend_exit_stop():
    d = trend_exit(100, current_price=92, ma_support=95, stop_price=93)
    assert d["action"] == "SELL_ALL" and "이탈" in d["reason"]


def test_trend_exit_ma_break():
    d = trend_exit(100, current_price=94, ma_support=95, stop_price=80)  # stop 안 깨졌지만 MA 이탈
    assert d["action"] == "SELL_ALL"


def test_trend_exit_foreign():
    d = trend_exit(100, current_price=110, ma_support=95, stop_price=80,
                   foreign_net_5d=-5, use_foreign_exit=True)
    assert d["action"] == "SELL_ALL" and "외국인" in d["reason"]


def test_trend_exit_hold():
    d = trend_exit(100, current_price=110, ma_support=95, stop_price=90)
    assert d["action"] == "HOLD"


# ── JH ZONE ─────────────────────────────────────────────────────────────────

def test_zone_go():
    # 정배열(MA60>MA120) + 60일선 ±3% 지지 → GO
    assert classify_zone(102, ma60=100, ma120=90) == "GO"


def test_zone_watch_above_zone():
    # 추세 위지만 60일선에서 멀리(>3%) → 진입존 밖 WATCH
    assert classify_zone(120, ma60=100, ma120=90) == "WATCH"


def test_zone_caution_below_ma60():
    assert classify_zone(95, ma60=100, ma120=90) == "CAUTION"


def test_zone_stoploss_below_ma120():
    assert classify_zone(85, ma60=100, ma120=90) == "STOP_LOSS"


def test_zone_held_hold_and_stop():
    assert classify_zone(110, ma60=100, ma120=90, held=True, stop_price=95) == "HOLD"
    assert classify_zone(94, ma60=100, ma120=90, held=True, stop_price=95) == "STOP_LOSS"
