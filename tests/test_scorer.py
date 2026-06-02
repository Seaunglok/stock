"""closing_bet scorer 순수함수 회귀 테스트 (#11)."""
from src.mcp_servers.closing_bet_mcp.scorer import (
    TechnicalScores,
    compute_technical_scores,
    score_candle_shape,
    score_candle_shape_v2,
)

_SMALL_WICK = [{"open": 100, "high": 101, "low": 98, "close": 100.5}]   # 위꼬리 작음(양봉)
_LARGE_WICK = [{"open": 100, "high": 106, "low": 99, "close": 100.5}]   # 위꼬리 큼


def test_candle_v1_rewards_small_wick():
    # P0: 라이브(=백테스트)는 candle v1 — 위꼬리 작을수록 高점이어야 함
    assert score_candle_shape(_SMALL_WICK)[0] > score_candle_shape(_LARGE_WICK)[0]


def test_candle_v2_is_inverted():
    # v2 는 위꼬리 클수록 高 (라이브에서 쓰면 부호 반대 — 사용 금지 회귀 가드)
    assert score_candle_shape_v2(_LARGE_WICK)[0] > score_candle_shape_v2(_SMALL_WICK)[0]


def test_composite_weights_sum_to_one():
    ts = TechnicalScores(
        volume_surge=100, resistance_proximity=100, candle_shape=100,
        consolidation=100, institutional=100,
    )
    # 0.20+0.20+0.20+0.25+0.15 = 1.0 → 모든 컴포넌트 100이면 composite 100
    assert abs(ts.composite() - 100.0) < 1e-6


def test_composite_weighted_value():
    ts = TechnicalScores(
        volume_surge=50, resistance_proximity=0, candle_shape=0,
        consolidation=0, institutional=0,
    )
    assert abs(ts.composite() - 50 * 0.20) < 1e-6


def test_compute_technical_scores_live_uses_v1_candle():
    # 라이브 진입점 compute_technical_scores 가 candle v1 을 쓰는지 (작은 위꼬리 高점)
    ohlcv = [{"open": 100, "high": 100.5, "low": 98, "close": 100.3,
              "volume": 1000, "value": 1e8}] * 70
    ts = compute_technical_scores(ohlcv)
    assert ts.candle_shape == score_candle_shape(ohlcv)[0]
