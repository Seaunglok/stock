"""trend_mcp.signals 순수함수 회귀 테스트."""
import pytest

from src.mcp_servers.trend_mcp.signals import (
    TrendConfig,
    atr,
    classify_zone,
    levels,
    entry_signal,
    exit_decision,
    foreign_net_signal,
    fundamentals_bonus,
    is_big_bullish_candle,
    is_consolidation,
    is_rising,
    leading_sectors,
    ma_uptrend,
    market_breadth,
    moving_average,
    position_size,
    relative_strength,
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

# 구 trend_exit() 의 4케이스를 exit_decision 으로 이관(2026-08-17 — trend_exit 제거).
# 프로덕션 호출부가 0곳인데 청산 우선순위를 별도로 구현하고 있어, 라이브 규칙이 바뀔 때
# 조용히 어긋나는 '세 번째 사다리'였다.
def test_exit_stop_breach():
    act, reason, _ = exit_decision(entry=100, cur=92, qty=10, target=130, stop=93,
                                   partial_done=True, ma_exit=95)
    assert act == "EXIT" and "트레일" in reason


def test_exit_ma_break_without_stop_breach():
    act, reason, _ = exit_decision(entry=100, cur=94, qty=10, target=130, stop=80,
                                   partial_done=True, ma_exit=95)
    assert act == "EXIT" and "MA" in reason


def test_exit_foreign_net_selling():
    act, reason, _ = exit_decision(entry=100, cur=110, qty=10, target=130, stop=80,
                                   partial_done=True, ma_exit=95,
                                   foreign_net=-5, use_foreign=True)
    assert act == "EXIT" and "외국인" in reason


def test_exit_hold_when_all_clear():
    act, _, _ = exit_decision(entry=100, cur=110, qty=10, target=130, stop=90,
                              partial_done=True, ma_exit=95)
    assert act is None


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


def test_market_breadth_strong():
    # 상승 600 / 하락 200 / 보합 100 = 600/900 ≈ 0.667 → 양호
    rows = [_sec("A", 1.5, rising=200, falling=80, flat=20),
            _sec("B", 2.0, rising=200, falling=70, flat=30),
            _sec("C", 1.0, rising=200, falling=50, flat=50)]
    b = market_breadth(rows)
    assert b is not None and 0.66 < b < 0.68


def test_market_breadth_weak():
    # 상승 150 / 하락 600 / 보합 50 = 150/800 ≈ 0.1875 → 약세
    rows = [_sec("A", -2.5, rising=50, falling=200, flat=20),
            _sec("B", -3.0, rising=50, falling=200, flat=20),
            _sec("C", -1.0, rising=50, falling=200, flat=10)]
    b = market_breadth(rows)
    assert b is not None and 0.18 < b < 0.20


def test_market_breadth_insufficient_sample():
    # 표본 < 50 → None (fail-open)
    rows = [_sec("A", 1.0, rising=10, falling=5, flat=0)]   # 15 종목만
    assert market_breadth(rows) is None
    assert market_breadth([]) is None


# ── 실행 결정(순수): 사이징 / 상승판정 / 청산분기 ───────────────────────────

def test_position_size_pct_equity():
    # 예탁 1억의 8% = 800만 / 215만원 = 3주
    assert position_size(2_150_000, mode="pct_equity", equity=100_000_000, cash=100_000_000, pct=8) == 3
    # 현금 한도: 현금 100만이면 0주(215만 못 삼)
    assert position_size(2_150_000, mode="pct_equity", equity=100_000_000, cash=1_000_000, pct=8) == 0


def test_position_size_fallback_and_fixed():
    # equity 조회 실패(0) → 고정금액 폴백 (최소 1주)
    assert position_size(2_150_000, mode="pct_equity", equity=0, invest_fixed=500_000) == 1
    # fixed 모드: 50만 / 17만 = 2주
    assert position_size(170_000, mode="fixed", invest_fixed=500_000) == 2
    assert position_size(0, mode="fixed") == 0


def test_position_size_risk_mode():
    # 예탁 1억, 리스크 1.5% = 150만. 손절폭 = 100,000-93,000 = 7,000 → 150만/7,000 = 214주
    # notional 상한(25%=2,500만/10만=250주)·현금 한도 내 → 214주
    assert position_size(100_000, mode="risk", equity=100_000_000, cash=100_000_000,
                         stop=93_000, risk_pct=1.5, max_notional_pct=25) == 214
    # 손절폭이 좁으면(1,000) 수량 폭증하지만 notional 상한(250주)에 걸림
    assert position_size(100_000, mode="risk", equity=100_000_000, cash=100_000_000,
                         stop=99_000, risk_pct=1.5, max_notional_pct=25) == 250
    # 현금 한도: 현금 1,000만이면 100주까지만
    assert position_size(100_000, mode="risk", equity=100_000_000, cash=10_000_000,
                         stop=93_000, risk_pct=1.5) == 100


def test_position_size_risk_fallback_to_notional():
    # risk 모드인데 손절폭 무효(stop=0) → notional 폴백 (pct 사용)
    assert position_size(100_000, mode="risk", equity=100_000_000, cash=100_000_000,
                         stop=0, pct=15) == 150
    # stop >= price (역전) → 폴백
    assert position_size(100_000, mode="risk", equity=100_000_000, cash=100_000_000,
                         stop=101_000, pct=15) == 150
    # equity 조회 실패(0) → 고정금액 폴백
    assert position_size(170_000, mode="risk", equity=0, stop=150_000, invest_fixed=500_000) == 2


def test_is_rising():
    assert is_rising(101, 100) is True          # 시가 위
    assert is_rising(99, 100) is False           # 시가 아래(하락중)
    assert is_rising(0, 100) is True             # 불명 → fail-open


def test_exit_decision_hard_stop_priority():
    a, r, q = exit_decision(entry=100, cur=90, qty=10, target=130, stop=85,
                            partial_done=False, hard_stop_pct=5)
    assert a == "EXIT" and "하드 손절" in r and q == 10


def test_exit_decision_partial_then_trail():
    a, r, q = exit_decision(entry=100, cur=131, qty=10, target=130, stop=95, partial_done=False, partial_pct=30)
    assert a == "PARTIAL" and q == 3
    a2, _, q2 = exit_decision(entry=100, cur=94, qty=10, target=130, stop=95, partial_done=True)
    assert a2 == "EXIT" and q2 == 10            # 트레일 이탈


def test_exit_decision_ma_and_foreign_only_when_passed():
    # ma_exit 미평가(None) → HOLD
    assert exit_decision(entry=100, cur=110, qty=5, target=130, stop=90, partial_done=True)[0] is None
    # MA 이탈
    assert exit_decision(entry=100, cur=110, qty=5, target=130, stop=90, partial_done=True,
                         ma_exit=115)[0] == "EXIT"
    # 외인 전환
    assert exit_decision(entry=100, cur=110, qty=5, target=130, stop=90, partial_done=True,
                         foreign_net=-3, use_foreign=True)[0] == "EXIT"


def test_exit_decision_partial_qty1_skipped():
    # qty=1 은 쪼갤 수 없음 — 부분익절 없이 트레일 지속 (전량 매도 → qty=0 좀비 방지)
    a, _, q = exit_decision(entry=100, cur=131, qty=1, target=130, stop=95,
                            partial_done=False, partial_pct=30)
    assert a is None and q == 0
    # qty=2~3 은 기존처럼 1주 부분익절 (잔여 ≥1 보장)
    a2, _, q2 = exit_decision(entry=100, cur=131, qty=2, target=130, stop=95,
                              partial_done=False, partial_pct=30)
    assert a2 == "PARTIAL" and q2 == 1
    a3, _, q3 = exit_decision(entry=100, cur=131, qty=3, target=130, stop=95,
                              partial_done=False, partial_pct=30)
    assert a3 == "PARTIAL" and q3 == 1


def test_exit_decision_aged_out():
    # 보유만기(시간청산) — 백테스트 max_hold 대응. 우선순위 최하위(트레일/MA 이후).
    a, r, q = exit_decision(entry=100, cur=110, qty=5, target=130, stop=90,
                            partial_done=True, aged_out=True)
    assert a == "EXIT" and "시간청산" in r and q == 5
    # 트레일 이탈이 시간청산보다 우선 (reason 으로 구분)
    a2, r2, _ = exit_decision(entry=100, cur=89, qty=5, target=130, stop=90,
                              partial_done=True, aged_out=True)
    assert a2 == "EXIT" and "트레일" in r2
    # 미만기(기본 False) → HOLD 유지
    assert exit_decision(entry=100, cur=110, qty=5, target=130, stop=90,
                         partial_done=True)[0] is None


# ─── foreign_net_signal (외인 수급 신호 — 완성일 기준 + 규모 임계값) ─────────

def _frow(dt, chg, vol=500_000):
    return {"dt": dt, "chg_qty": chg, "trde_qty": vol}


def test_foreign_signal_excludes_today_provisional():
    # 2026-07-15 삼성생명 오발동 재현: 당일 잠정치 포함 시 음수, 완성일 기준으론 판정 달라야 함.
    rows = [_frow("20260715", "-40000"),   # 당일 잠정(제외돼야 함)
            _frow("20260714", "-50,387"), _frow("20260713", "+104,276"),
            _frow("20260710", "-59,576"), _frow("20260709", "+3,315"),
            _frow("20260708", "+52,748")]
    # 완성일 5일합 = +50,376 (당일 잠정 -40,000 미포함), 임계 off 로 값 자체 확인
    assert foreign_net_signal(rows, "20260715", min_ratio=0) == 50376.0


def test_foreign_signal_noise_filtered_by_ratio():
    # 5일합 -2,372주 vs 평균거래량 500,000 → 0.5% 는 노이즈 → None (룰 미적용)
    rows = [_frow("20260714", "-50,387"), _frow("20260713", "+104,276"),
            _frow("20260710", "-59,576"), _frow("20260709", "+3,315"),
            _frow("20260708", "+0"),
            _frow("20260707", "0"), _frow("20260706", "0")]
    assert foreign_net_signal(rows, "20260715", min_ratio=0.2) is None
    # 임계 off(0) 면 부호 그대로 통과
    assert foreign_net_signal(rows, "20260715", min_ratio=0) == -2372.0


def test_foreign_signal_strong_selling_passes():
    # 강한 순매도(-650만주 vs avg vol 1,500만 = 43%) → 임계 0.2 통과, 음수 반환
    rows = [_frow("2026071%d" % d, "-1,300,000", 15_000_000) for d in range(0, 5)]  # 07-10~14 (완성일만)
    net = foreign_net_signal(rows, "20260715", min_ratio=0.2)
    assert net == -6_500_000


def test_foreign_signal_insufficient_or_bad_data():
    # 완성일 5개 미만 → None
    rows = [_frow("20260714", "-100")] * 3
    assert foreign_net_signal(rows, "20260715", min_ratio=0) is None
    # 빈/깨진 입력 → None
    assert foreign_net_signal([], "20260715") is None
    assert foreign_net_signal([{"dt": "20260714", "chg_qty": "??"}] * 6, "20260715") is None


# ─── 외인 청산 추세 확인 조건 (ma_trend) ─────────────────────────────────────

def _ex(**kw):
    base = dict(entry=100.0, cur=100.0, qty=10, target=200.0, stop=80.0,
                partial_done=True, use_foreign=True, foreign_net=-5000.0)
    base.update(kw)
    return exit_decision(**base)


def test_foreign_exit_blocked_when_trend_intact():
    # 외인 순매도지만 현재가가 MA60 위 → 추세 유지 → 청산 안 함 (07-31 4종 오청산 방지)
    act, reason, q = _ex(cur=100.0, ma_trend=95.0)
    assert act is None and q == 0


def test_foreign_exit_fires_when_trend_broken():
    # 외인 순매도 + MA60 이탈 동시 → 청산
    act, reason, q = _ex(cur=90.0, ma_trend=95.0)
    assert act == "EXIT" and "외국인" in reason and "MA60" in reason and q == 10


def test_foreign_exit_legacy_without_trend_ma():
    # ma_trend=None(추세조건 off) → 수급만으로 청산(구 동작 하위호환)
    act, reason, q = _ex(cur=100.0, ma_trend=None)
    assert act == "EXIT" and reason == "외국인 5일 순매도 전환"


def test_foreign_exit_trend_label_reflected():
    act, reason, _ = _ex(cur=90.0, ma_trend=95.0, trend_ma_label=20)
    assert "MA20" in reason


def test_foreign_net_positive_never_exits():
    # 순매수면 추세 무관하게 청산 안 함
    assert _ex(cur=90.0, ma_trend=95.0, foreign_net=5000.0)[0] is None


# ─── levels(): 손절/목표 단일 정본 (2026-08-17 — 8곳 복제 통합) ──────────────
def test_levels_keeps_rr_ratio():
    """손익비 1:rr 은 이 전략 기대값의 전부다 — 어떤 경로로 계산해도 유지돼야 한다."""
    cfg = TrendConfig(rr=3.0, atr_k=2.0, stop_pct=7.0)
    stop, target = levels(10000, cfg, atr_value=200)
    assert (target - 10000) / (10000 - stop) == pytest.approx(3.0)


def test_levels_atr_value_and_ohlcv_agree():
    """ATR 을 직접 넘기든 ohlcv 로 계산하든 같은 결과여야 한다(호출부마다 입력 형태가 다르다)."""
    cfg = TrendConfig()
    bars = _rising(40, 100.0, 120.0)
    a = atr(bars, cfg.atr_period)
    assert levels(120, cfg, ohlcv=bars) == levels(120, cfg, atr_value=a)


def test_levels_stop_ref_splits_stop_and_target():
    """계좌 보유분 편입: 손절은 현재가 기준 트레일, 목표는 평단 기준 1:3."""
    cfg = TrendConfig(rr=3.0)
    entry, cur = 10000, 12000
    stop, target = levels(entry, cfg, atr_value=200, stop_ref=cur)
    base_stop, base_target = levels(entry, cfg, atr_value=200)
    assert stop > base_stop, "손절이 현재가 기준으로 올라와야 편입 즉시 손절을 피한다"
    assert target == base_target, "목표는 평단 기준 1:3 을 유지해야 한다"


def test_levels_falls_back_to_stop_pct_without_atr():
    """ATR=0(데이터 부족)이면 고정 stop_pct 로 폴백 — 손절 없는 포지션이 생기면 안 된다."""
    cfg = TrendConfig(stop_pct=7.0)
    stop, _ = levels(10000, cfg, atr_value=0)
    assert stop == pytest.approx(9300.0)


def test_levels_target_above_entry():
    cfg = TrendConfig()
    stop, target = levels(50000, cfg, atr_value=1500)
    assert stop < 50000 < target
