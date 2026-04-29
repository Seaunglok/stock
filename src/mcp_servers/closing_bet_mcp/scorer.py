"""기준 2-6 점수화 로직 — 순수 함수.

입력은 호출자가 다른 MCP로 수집한 표준 dict/list.
이 모듈은 데이터 fetching 안 함. pandas 의존 없음.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TechnicalScores:
    volume_surge: float = 0.0          # 기준 2
    resistance_proximity: float = 0.0  # 기준 3
    candle_shape: float = 0.0          # 기준 4
    consolidation: float = 0.0         # 기준 5
    institutional: float = 0.0         # 기준 6
    breakdown: dict[str, Any] = field(default_factory=dict)

    def composite(self) -> float:
        return (
            self.volume_surge * 0.25
            + self.resistance_proximity * 0.20
            + self.candle_shape * 0.15
            + self.consolidation * 0.20
            + self.institutional * 0.20
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "volume_surge": round(self.volume_surge, 1),
            "resistance_proximity": round(self.resistance_proximity, 1),
            "candle_shape": round(self.candle_shape, 1),
            "consolidation": round(self.consolidation, 1),
            "institutional": round(self.institutional, 1),
            "composite": round(self.composite(), 1),
            "breakdown": self.breakdown,
        }


def _safe_pct(val: float, lo: float, hi: float) -> float:
    if hi == lo:
        return 50.0
    pct = (val - lo) / (hi - lo) * 100.0
    return max(0.0, min(100.0, pct))


# OHLCV item 표준 키: {"date","open","high","low","close","volume","value"(거래대금)}
# 호출자가 한국어 키든 영어 키든 던져도 동작하도록 alias 매핑 사용.
_KEY_MAP = {
    "open":   ["open", "시가", "Open"],
    "high":   ["high", "고가", "High"],
    "low":    ["low", "저가", "Low"],
    "close":  ["close", "종가", "Close"],
    "volume": ["volume", "거래량", "Volume"],
    "value":  ["value", "거래대금", "trade_value"],
}


def _g(d: dict, key: str, default: float = 0.0) -> float:
    for k in _KEY_MAP[key]:
        if k in d:
            v = d[k]
            try:
                return float(v) if v is not None else default
            except (TypeError, ValueError):
                return default
    return default


def score_volume_surge(ohlcv: list[dict]) -> tuple[float, dict[str, Any]]:
    """기준 2: 오늘 거래대금 / 20일 평균 거래대금 비율.

    1.5배 → 50점, 3배 → 90점, 5배+ → 100점
    """
    if not ohlcv or len(ohlcv) < 21:
        return 0.0, {"reason": "데이터 부족 (>=21봉 필요)"}

    today = ohlcv[-1]
    today_value = _g(today, "value") or _g(today, "volume")
    history = ohlcv[-21:-1]
    values = [_g(d, "value") or _g(d, "volume") for d in history]
    values = [v for v in values if v > 0]
    if not values:
        return 0.0, {"reason": "히스토리 거래대금 0"}

    avg20 = sum(values) / len(values)
    if avg20 <= 0:
        return 0.0, {"reason": "평균 0"}

    ratio = today_value / avg20
    score = _safe_pct(ratio, 1.0, 5.0)
    return score, {
        "today_value": today_value,
        "avg20_value": avg20,
        "ratio": round(ratio, 2),
    }


def score_resistance_proximity(ohlcv: list[dict]) -> tuple[float, dict[str, Any]]:
    """기준 3: 60일 전고점 대비 현재가 이격.

    -8% ~ -3% = 만점 (저항 근처지만 부담 없음).
    """
    if not ohlcv or len(ohlcv) < 60:
        return 0.0, {"reason": "데이터 부족 (>=60봉 필요)"}

    recent = ohlcv[-60:]
    high_60 = max(_g(d, "high") for d in recent)
    close = _g(ohlcv[-1], "close")
    if high_60 <= 0:
        return 0.0, {"reason": "고가 0"}

    gap_pct = (close - high_60) / high_60 * 100.0

    if -8.0 <= gap_pct <= -3.0:
        score = 100.0
    elif -3.0 < gap_pct <= 0.0:
        score = 70.0
    elif 0.0 < gap_pct <= 3.0:
        score = 40.0
    elif -15.0 <= gap_pct < -8.0:
        score = 60.0
    else:
        score = max(0.0, 50.0 + gap_pct)

    return max(0.0, min(100.0, score)), {
        "high_60d": high_60,
        "current": close,
        "gap_pct": round(gap_pct, 2),
    }


def score_candle_shape(ohlcv: list[dict]) -> tuple[float, dict[str, Any]]:
    """기준 4: 오늘 캔들의 위꼬리 비율 (짧을수록 좋음, 양봉 가산)."""
    if not ohlcv:
        return 0.0, {"reason": "데이터 없음"}

    last = ohlcv[-1]
    o, h, l, c = _g(last, "open"), _g(last, "high"), _g(last, "low"), _g(last, "close")
    body_top = max(o, c)
    rng = h - l
    if rng <= 0:
        return 50.0, {"reason": "변동 없음"}

    upper_wick_ratio = (h - body_top) / rng
    is_bullish = c >= o

    wick_score = max(0.0, 100.0 - upper_wick_ratio * 200.0)
    if is_bullish:
        wick_score = min(100.0, wick_score + 10.0)

    return wick_score, {
        "open": o, "high": h, "low": l, "close": c,
        "upper_wick_ratio": round(upper_wick_ratio, 3),
        "is_bullish": is_bullish,
    }


def score_consolidation(ohlcv: list[dict]) -> tuple[float, dict[str, Any]]:
    """기준 5: 충분한 기간 조정 (N자형/W형) — 60일 고점 → 조정 → 회복."""
    if not ohlcv or len(ohlcv) < 60:
        return 0.0, {"reason": "데이터 부족 (>=60봉 필요)"}

    recent = ohlcv[-60:]
    highs = [_g(d, "high") for d in recent]
    lows = [_g(d, "low") for d in recent]
    high_60 = max(highs)
    high_pos = highs.index(high_60)
    if high_pos < len(recent) - 1:
        low_after = min(lows[high_pos:])
    else:
        low_after = min(lows)
    close = _g(ohlcv[-1], "close")

    if high_60 <= 0 or low_after <= 0:
        return 0.0, {"reason": "데이터 이상"}

    drawdown_pct = (low_after - high_60) / high_60 * 100.0
    recovery_pct = (close - low_after) / low_after * 100.0

    if -25.0 <= drawdown_pct <= -8.0:
        dd_score = 100.0
    elif -8.0 < drawdown_pct <= 0.0:
        dd_score = 40.0
    elif drawdown_pct < -25.0:
        dd_score = max(0.0, 80.0 + (drawdown_pct + 25.0) * 2.0)
    else:
        dd_score = 0.0

    rec_score = min(100.0, recovery_pct * 5.0) if recovery_pct > 0 else 0.0
    score = dd_score * 0.7 + rec_score * 0.3

    return score, {
        "high_60d": high_60,
        "low_after_high": low_after,
        "current": close,
        "drawdown_pct": round(drawdown_pct, 2),
        "recovery_pct": round(recovery_pct, 2),
    }


def score_institutional(
    foreign_net_5d: float | None,
    institutional_net_5d: float | None,
) -> tuple[float, dict[str, Any]]:
    """기준 6: 외인·기관 양매수 (최근 5일 누적 순매수 부호).

    Args:
        foreign_net_5d: 외국인 5일 누적 순매수 (단위 무관, 부호만 사용)
        institutional_net_5d: 기관 5일 누적 순매수
    """
    if foreign_net_5d is None and institutional_net_5d is None:
        return 0.0, {"reason": "데이터 없음"}

    foreign_buy = (foreign_net_5d or 0) > 0
    inst_buy = (institutional_net_5d or 0) > 0

    if foreign_buy and inst_buy:
        score = 100.0
    elif foreign_buy or inst_buy:
        score = 60.0
    else:
        score = 0.0

    return score, {
        "foreign_net_5d": foreign_net_5d,
        "institutional_net_5d": institutional_net_5d,
        "foreign_buy": foreign_buy,
        "institutional_buy": inst_buy,
    }


def compute_technical_scores(
    ohlcv: list[dict],
    foreign_net_5d: float | None = None,
    institutional_net_5d: float | None = None,
) -> TechnicalScores:
    """5개 기술 점수 계산 + 합산"""
    ts = TechnicalScores()
    ts.volume_surge, vs_b = score_volume_surge(ohlcv)
    ts.resistance_proximity, rp_b = score_resistance_proximity(ohlcv)
    ts.candle_shape, cs_b = score_candle_shape(ohlcv)
    ts.consolidation, co_b = score_consolidation(ohlcv)
    ts.institutional, in_b = score_institutional(foreign_net_5d, institutional_net_5d)
    ts.breakdown = {
        "volume_surge": vs_b,
        "resistance_proximity": rp_b,
        "candle_shape": cs_b,
        "consolidation": co_b,
        "institutional": in_b,
    }
    return ts
