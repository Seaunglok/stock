"""trend_mcp.signals 순수함수 회귀 테스트."""
from src.mcp_servers.trend_mcp.signals import (
    TrendConfig,
    classify_zone,
    entry_signal,
    fundamentals_bonus,
    is_big_bullish_candle,
    is_consolidation,
    leading_sectors,
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


# ── 실적 가점 (차수재시실 '실적') ────────────────────────────────────────────

def test_fundamentals_bonus_both_up():
    pts, det = fundamentals_bonus(12.0, 30.0, bonus=5.0)
    assert pts == 5.0 and "동반" in det["why"]


def test_fundamentals_bonus_op_only():
    pts, _ = fundamentals_bonus(-3.0, 10.0, bonus=5.0)
    assert pts == 2.5


def test_fundamentals_bonus_none_and_down():
    assert fundamentals_bonus(None, 10.0)[0] == 0.0      # 데이터 없음 → 가점 없음(veto 아님)
    assert fundamentals_bonus(5.0, None)[0] == 0.0
    assert fundamentals_bonus(-5.0, -10.0)[0] == 0.0


# ── 주도섹터 집단상승 (차수재시실 '시황') ─────────────────────────────────────

def _sec(name, chg, rising, falling, flat=0):
    return {"sector": name, "change_pct": chg, "rising": rising, "falling": falling, "flat": flat}


def test_leading_sectors_breadth_and_avg():
    rows = [
        _sec("철강", 1.32, rising=97, falling=16, flat=7),   # +1.32%, 상승 81% → 주도
        _sec("은행", 2.00, rising=5, falling=5),              # 상승 50% < 60% → 집단상승 아님
        _sec("화학", 0.25, rising=40, falling=10),            # 등락률 < 1.0% → 탈락
    ]
    leaders = leading_sectors(rows, min_avg_pct=1.0, min_breadth=0.6)
    assert [x["sector"] for x in leaders] == ["철강"]
    assert leaders[0]["breadth"] == 0.81 and leaders[0]["count"] == 120


def test_leading_sectors_min_count_and_topk():
    rows = [
        _sec("A", 5.0, rising=2, falling=0),                  # 구성 2 < 3 → 제외
        _sec("B", 3.0, rising=3, falling=0),
        _sec("C", 2.0, rising=3, falling=0),
        _sec("D", 4.0, rising=3, falling=0),
    ]
    leaders = leading_sectors(rows, min_count=3, top_k=2)
    assert [x["sector"] for x in leaders] == ["D", "B"]       # 등락률 내림차순 top 2


def test_leading_sectors_empty_and_nan():
    assert leading_sectors([]) == []
    assert leading_sectors([_sec("X", float("nan"), rising=10, falling=0)]) == []
