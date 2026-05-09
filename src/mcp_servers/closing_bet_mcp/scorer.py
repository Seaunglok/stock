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
    catalyst: float = 0.0              # 기준 1 (재료 — DART 공시 기반)
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
            "catalyst": round(self.catalyst, 1),
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


# 재료 점수: 호재 키워드 → 가산 / 악재 키워드 → 감점.
# 사용처(score_catalyst)에서 단순 매칭만 한다 — 형태소 분석 없이 부분 일치.
_CATALYST_POSITIVE = [
    "단일판매ㆍ공급계약", "단일판매·공급계약", "공급계약체결",
    "신규시설투자", "신규 시설투자",
    "타법인주식및출자증권취득결정", "주식취득결정",
    "유형자산양수", "영업양수",
    "자기주식취득", "자기주식 소각",
    "무상증자",
    "주식분할",
    "신규사업", "사업목적추가",
    "임상시험결과", "임상결과", "품목허가", "신약허가",
    "특허취득",
    "흑자전환", "영업이익증가",
    "수주", "수주공시",
    "합병", "분할합병",
    "배당증가", "현금배당",
]

_CATALYST_NEGATIVE = [
    "유상증자", "전환사채발행", "신주인수권부사채",
    "감자",
    "영업정지", "관리종목지정",
    "회생절차", "거래정지",
    "소송", "고발",
    "유형자산양도",
    "적자전환", "영업이익감소",
    "최대주주변경",  # 중립~부정 (덤핑 가능성)
]


def score_catalyst(
    disclosures: list[dict],
    target_date: str,
    lookback_days: int = 3,
) -> tuple[float, dict[str, Any]]:
    """기준 1: 재료 — DART 공시 기반.

    target_date(YYYY-MM-DD) 기준 직전 lookback_days 영업일 이내의 공시를 보고
    호재 키워드 → 가산, 악재 키워드 → 감점.
    가까운 공시일수록 가중 (T-0=1.0, T-1=0.7, T-2=0.4, ...).

    Args:
        disclosures: load_disclosures()의 출력 — [{"date","report_nm","rcept_no"}]
        target_date: 평가 시점 (보통 종가 매수 검토일)
        lookback_days: 며칠 이내 공시까지 인정할지 (영업일 아닌 달력일)

    Returns: (score 0~100, breakdown dict)
    """
    if not disclosures:
        return 0.0, {"reason": "공시 없음"}

    from datetime import date, timedelta
    try:
        td = date.fromisoformat(target_date)
    except ValueError:
        return 0.0, {"reason": "target_date 형식 오류"}

    score = 0.0
    matched: list[dict] = []
    for d in disclosures:
        try:
            dd = date.fromisoformat(d["date"])
        except (ValueError, KeyError):
            continue
        # target_date 당일 이전 lookback_days 이내만 (당일 포함, 미래 제외)
        delta = (td - dd).days
        if delta < 0 or delta > lookback_days:
            continue

        recency = max(0.0, 1.0 - delta * 0.3)  # 0d=1.0, 1d=0.7, 2d=0.4, 3d=0.1
        title = d.get("report_nm", "").replace(" ", "")

        hit_pos = next((k for k in _CATALYST_POSITIVE if k.replace(" ", "") in title), None)
        hit_neg = next((k for k in _CATALYST_NEGATIVE if k.replace(" ", "") in title), None)

        if hit_pos:
            delta_score = 35.0 * recency
            score += delta_score
            matched.append({"date": d["date"], "report_nm": d.get("report_nm", ""),
                            "kind": "+", "keyword": hit_pos, "delta": round(delta_score, 1)})
        elif hit_neg:
            delta_score = -25.0 * recency
            score += delta_score
            matched.append({"date": d["date"], "report_nm": d.get("report_nm", ""),
                            "kind": "-", "keyword": hit_neg, "delta": round(delta_score, 1)})

    score = max(0.0, min(100.0, score))
    return score, {
        "target_date": target_date,
        "lookback_days": lookback_days,
        "n_disclosures_in_window": sum(
            1 for d in disclosures
            if 0 <= (td - date.fromisoformat(d["date"])).days <= lookback_days
        ) if disclosures else 0,
        "matched": matched,
    }


def compute_technical_scores(
    ohlcv: list[dict],
    foreign_net_5d: float | None = None,
    institutional_net_5d: float | None = None,
    disclosures: list[dict] | None = None,
    target_date: str | None = None,
) -> TechnicalScores:
    """6개 점수 계산 + 합산. disclosures/target_date 가 있으면 catalyst 도 채움."""
    ts = TechnicalScores()
    ts.volume_surge, vs_b = score_volume_surge(ohlcv)
    ts.resistance_proximity, rp_b = score_resistance_proximity(ohlcv)
    ts.candle_shape, cs_b = score_candle_shape(ohlcv)
    ts.consolidation, co_b = score_consolidation(ohlcv)
    ts.institutional, in_b = score_institutional(foreign_net_5d, institutional_net_5d)
    if disclosures is not None and target_date is not None:
        ts.catalyst, ca_b = score_catalyst(disclosures, target_date)
    else:
        ts.catalyst, ca_b = 0.0, {"reason": "공시 데이터 미제공"}
    ts.breakdown = {
        "volume_surge": vs_b,
        "resistance_proximity": rp_b,
        "candle_shape": cs_b,
        "consolidation": co_b,
        "institutional": in_b,
        "catalyst": ca_b,
    }
    return ts


# ───────────────────────────────────────────────────────────────────
# v2 — 2026-05-05 회귀 결과(저항이격·캔들이 음신호)에 따른 재설계.
# ohlcv 데이터 입력 인터페이스는 v1과 동일.
# ───────────────────────────────────────────────────────────────────


def score_resistance_proximity_v2(ohlcv: list[dict]) -> tuple[float, dict[str, Any]]:
    """기준 3 (재설계): 60일 전고 돌파/깊은 눌림에 가산.

    v1은 "거의 고점(-8 ~ -3%)"을 만점으로 봤는데 회귀에서 음신호로 드러남
    (매물대 부담 → 익일 시초가 매도 압력 가설). v2는 분포를 뒤집는다:

    - gap > +2%        → 100 (fresh breakout)
    - 0 < gap ≤ +2%    → 80  (직전 고점 돌파 직후)
    - -3 ≤ gap ≤ 0     → 60  (전고 직하, 모멘텀 잔존)
    - -10 ≤ gap < -3   → 25  (예전 v1 만점 구간 — 매물대)
    - -25 ≤ gap < -10  → 70  (깊은 눌림에서 회복 진입 후보)
    - gap < -25        → 30  (낙폭 과대, 추세 회복 미확인)
    """
    if not ohlcv or len(ohlcv) < 60:
        return 0.0, {"reason": "데이터 부족 (>=60봉 필요)"}

    recent = ohlcv[-60:]
    high_60 = max(_g(d, "high") for d in recent)
    close = _g(ohlcv[-1], "close")
    if high_60 <= 0:
        return 0.0, {"reason": "고가 0"}

    gap_pct = (close - high_60) / high_60 * 100.0

    if gap_pct > 2.0:
        score = 100.0
    elif gap_pct > 0.0:
        score = 80.0
    elif gap_pct >= -3.0:
        score = 60.0
    elif gap_pct >= -10.0:
        score = 25.0
    elif gap_pct >= -25.0:
        score = 70.0
    else:
        score = 30.0

    return score, {
        "high_60d": high_60,
        "current": close,
        "gap_pct": round(gap_pct, 2),
        "regime": (
            "breakout" if gap_pct > 0 else
            "near_high" if gap_pct >= -3 else
            "supply_zone" if gap_pct >= -10 else
            "deep_pullback" if gap_pct >= -25 else
            "extreme_drawdown"
        ),
    }


def score_candle_shape_v2(ohlcv: list[dict]) -> tuple[float, dict[str, Any]]:
    """기준 4 (재설계): 종가 위꼬리에 가산.

    v1은 "위꼬리 짧고 양봉"을 보상했는데 회귀에서 음신호.
    가설: 위꼬리 = 장중 매도세 분출 → 익일 시초가에 추격매수 들어올 여지 큼.
    또한 v1에서 양봉 가산점 +10이 너무 일률적 → v2는 비율 자체에 비례.

    - upper_wick_ratio ≥ 0.4 → 100
    - 0.2 ≤ ratio < 0.4      → 60
    - 0.05 ≤ ratio < 0.2     → 30
    - ratio < 0.05           → 10 (위꼬리 거의 없음 = 추가 상방 여력 적음)
    """
    if not ohlcv:
        return 0.0, {"reason": "데이터 없음"}

    last = ohlcv[-1]
    o, h, l, c = _g(last, "open"), _g(last, "high"), _g(last, "low"), _g(last, "close")
    body_top = max(o, c)
    rng = h - l
    if rng <= 0:
        return 50.0, {"reason": "변동 없음"}

    upper_wick_ratio = (h - body_top) / rng

    if upper_wick_ratio >= 0.4:
        score = 100.0
    elif upper_wick_ratio >= 0.2:
        score = 60.0
    elif upper_wick_ratio >= 0.05:
        score = 30.0
    else:
        score = 10.0

    return score, {
        "open": o, "high": h, "low": l, "close": c,
        "upper_wick_ratio": round(upper_wick_ratio, 3),
        "is_bullish": c >= o,
    }


def compute_technical_scores_hybrid(
    ohlcv: list[dict],
    foreign_net_5d: float | None = None,
    institutional_net_5d: float | None = None,
    disclosures: list[dict] | None = None,
    target_date: str | None = None,
) -> TechnicalScores:
    """하이브리드 — volume v1 / candle v2 / consolidation v1 / resistance v1.

    회귀에서 candle만 v2가 부호 반전(+) 됐다.
    resistance v2는 음신호 중화에 그쳐 의미 없음 → v1 유지(가중 0으로 중립화).
    """
    ts = TechnicalScores()
    ts.volume_surge, vs_b = score_volume_surge(ohlcv)
    ts.resistance_proximity, rp_b = score_resistance_proximity(ohlcv)
    ts.candle_shape, cs_b = score_candle_shape_v2(ohlcv)
    ts.consolidation, co_b = score_consolidation(ohlcv)
    ts.institutional, in_b = score_institutional(foreign_net_5d, institutional_net_5d)
    if disclosures is not None and target_date is not None:
        ts.catalyst, ca_b = score_catalyst(disclosures, target_date)
    else:
        ts.catalyst, ca_b = 0.0, {"reason": "공시 데이터 미제공"}
    ts.breakdown = {
        "volume_surge": vs_b,
        "resistance_proximity": rp_b,
        "candle_shape": cs_b,
        "consolidation": co_b,
        "institutional": in_b,
        "catalyst": ca_b,
    }
    return ts


def compute_technical_scores_v2(
    ohlcv: list[dict],
    foreign_net_5d: float | None = None,
    institutional_net_5d: float | None = None,
    disclosures: list[dict] | None = None,
    target_date: str | None = None,
) -> TechnicalScores:
    """v2 scorer — resistance_proximity·candle_shape 재설계 적용 + catalyst 옵션."""
    ts = TechnicalScores()
    ts.volume_surge, vs_b = score_volume_surge(ohlcv)
    ts.resistance_proximity, rp_b = score_resistance_proximity_v2(ohlcv)
    ts.candle_shape, cs_b = score_candle_shape_v2(ohlcv)
    ts.consolidation, co_b = score_consolidation(ohlcv)
    ts.institutional, in_b = score_institutional(foreign_net_5d, institutional_net_5d)
    if disclosures is not None and target_date is not None:
        ts.catalyst, ca_b = score_catalyst(disclosures, target_date)
    else:
        ts.catalyst, ca_b = 0.0, {"reason": "공시 데이터 미제공"}
    ts.breakdown = {
        "volume_surge": vs_b,
        "resistance_proximity": rp_b,
        "candle_shape": cs_b,
        "consolidation": co_b,
        "institutional": in_b,
        "catalyst": ca_b,
    }
    return ts
