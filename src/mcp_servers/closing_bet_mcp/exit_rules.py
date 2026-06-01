"""청산 규칙 + 시장 필터 — 순수 함수.

데이터 fetching 없음. 호출자가 KOSPI 등락률을 인자로 전달.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class ExitDecision:
    action: str
    urgency: str
    reason: str
    suggested_qty_pct: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "urgency": self.urgency,
            "reason": self.reason,
            "suggested_qty_pct": self.suggested_qty_pct,
        }


def evaluate_exit(
    entry_price: float,
    current_price: float,
    after_hours_price: float | None = None,
    now: datetime | None = None,
    stop_loss_pct: float = -2.0,
) -> ExitDecision:
    """매수 후 청산 신호 (HOLD/PARTIAL_SELL/SELL_ALL/STOP_LOSS).

    Args:
        stop_loss_pct: 손절 임계 (음수 %, 기본 -2.0%). 외부 베스트 프랙티스(-1~-2%)에 맞춤.
                       호출자가 환경변수 등으로 조정 가능.
    """
    now = now or datetime.now()
    pnl_pct = (current_price - entry_price) / entry_price * 100.0 if entry_price > 0 else 0.0

    # 1) 시간외 하락 → 단, 시초가도 약할 때만 즉시 전량 매도.
    #    (P1) 과거엔 18:05 시간외가 < 평단이면 09:00 무조건 SELL_ALL 이라
    #    밤사이 회복해 시초 갭업한 종목까지 투매했다. 이제 09:00 실시간가(current_price)도
    #    평단 이하일 때만 동반 약세로 보고 청산하고, 시초 회복(current > 평단) 시엔 정상 룰에 위임.
    if (
        after_hours_price is not None
        and after_hours_price < entry_price
        and current_price <= entry_price
    ):
        ah_pct = (after_hours_price - entry_price) / entry_price * 100.0
        return ExitDecision(
            action="SELL_ALL",
            urgency="high",
            reason=f"시간외+시초 동반 약세 (시간외 {ah_pct:+.2f}%, 현재 {pnl_pct:+.2f}%) — 즉시 매도",
            suggested_qty_pct=100,
        )

    # 2) 매수 평단 stop_loss_pct 이탈 (정규장)
    threshold_ratio = 1.0 + stop_loss_pct / 100.0  # -2.0 → 0.98
    if current_price < entry_price * threshold_ratio:
        return ExitDecision(
            action="STOP_LOSS",
            urgency="high",
            reason=f"손절 트리거 ({pnl_pct:+.2f}%) — {stop_loss_pct:.1f}% 이탈",
            suggested_qty_pct=100,
        )

    # 3) 시간 기반
    market_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
    fast_exit = now.replace(hour=9, minute=5, second=0, microsecond=0)

    if market_open <= now <= fast_exit and pnl_pct > 0:
        return ExitDecision(
            action="PARTIAL_SELL",
            urgency="medium",
            reason=f"시초가 수익 ({pnl_pct:+.2f}%) — 1/3 매도",
            suggested_qty_pct=33,
        )

    if now > fast_exit and now.hour < 15 and pnl_pct >= 2.0:
        return ExitDecision(
            action="SELL_ALL",
            urgency="medium",
            reason=f"9:05 경과 + 수익 {pnl_pct:+.2f}% — 전량 매도 (탐욕 X)",
            suggested_qty_pct=100,
        )

    if pnl_pct >= 3.0:
        return ExitDecision(
            action="PARTIAL_SELL",
            urgency="medium",
            reason=f"수익 {pnl_pct:+.2f}% — 일부 익절",
            suggested_qty_pct=50,
        )

    return ExitDecision(
        action="HOLD",
        urgency="low",
        reason=f"보유 ({pnl_pct:+.2f}%) — 청산 조건 미충족",
        suggested_qty_pct=0,
    )


# ───────────────────────────────────────────────────────────────────
# (a) N영업일 보유 + (c) ATR 기반 트레일링 스톱 — 순수 함수.
#   백테스트(backtest_walkforward.py 'atr2_h3')에서 p1 대비 OOS 우위 검증:
#   동일 진입 기준 승률↑·기대값↑·우측꼬리(P90)↑. 고정 -2% 일봉 근사를 대체.
# ───────────────────────────────────────────────────────────────────

def _atr_band(entry_price: float, atr: float, atr_k: float, fallback_stop_pct: float) -> float:
    """손절 밴드(원). ATR 있으면 atr_k*ATR, 없으면 |fallback_stop_pct|%."""
    if atr and atr > 0:
        return atr_k * atr
    return abs(fallback_stop_pct) / 100.0 * entry_price


def init_stop_price(
    entry_price: float,
    atr: float,
    atr_k: float = 2.0,
    fallback_stop_pct: float = -2.0,
) -> float:
    """매수 직후 초기 손절가 = 평단 - 밴드."""
    return entry_price - _atr_band(entry_price, atr, atr_k, fallback_stop_pct)


def ratchet_stop(
    entry_price: float,
    peak_price: float,
    stop_price: float,
    current_price: float,
    atr: float,
    atr_k: float = 2.0,
    fallback_stop_pct: float = -2.0,
) -> tuple[float, float]:
    """트레일링: 종가(현재가) 최고점 갱신 시 손절가를 위로만 끌어올린다.

    Returns: (new_peak, new_stop) — stop 은 절대 내려가지 않음.
    """
    band = _atr_band(entry_price, atr, atr_k, fallback_stop_pct)
    new_peak = max(peak_price or entry_price, current_price)
    new_stop = max(stop_price, new_peak - band)
    return new_peak, new_stop


def evaluate_hold_exit(
    entry_price: float,
    current_price: float,
    stop_price: float,
    aged_out: bool,
) -> ExitDecision:
    """N일 보유 + 트레일 청산 판정.

    우선순위: 트레일/손절 이탈(전량) → 보유기간 만료(시간청산, 전량) → 보유.
    부분청산 없음 — 우측꼬리를 끝까지 잡기 위해 승자를 조기 절단하지 않는다.
    """
    pnl = (current_price - entry_price) / entry_price * 100.0 if entry_price > 0 else 0.0
    if stop_price > 0 and current_price <= stop_price:
        return ExitDecision(
            action="SELL_ALL", urgency="high",
            reason=f"트레일/손절 이탈 ({pnl:+.2f}%) — stop {stop_price:,.0f}",
            suggested_qty_pct=100,
        )
    if aged_out:
        return ExitDecision(
            action="SELL_ALL", urgency="medium",
            reason=f"보유기간 만료 ({pnl:+.2f}%) — 시간청산",
            suggested_qty_pct=100,
        )
    return ExitDecision(
        action="HOLD", urgency="low",
        reason=f"보유 ({pnl:+.2f}%) — 트레일 유지 (stop {stop_price:,.0f})",
        suggested_qty_pct=0,
    )


def classify_regime(
    kospi_today_pct: float,
    advance_ratio: float,
    weak_kospi_pct: float = -1.0,
    weak_adv_ratio: float = 0.35,
    strong_kospi_pct: float = 0.5,
    strong_adv_ratio: float = 0.55,
) -> str:
    """시장 레짐 분류: 'weak' | 'neutral' | 'strong'.

    Args:
        kospi_today_pct: KOSPI 당일 등락률 (%)
        advance_ratio:   KOSPI 전 종목 중 등락률 > 0 비율 (0.0 ~ 1.0)
    """
    if kospi_today_pct > strong_kospi_pct and advance_ratio >= strong_adv_ratio:
        return "strong"
    if kospi_today_pct < weak_kospi_pct or advance_ratio < weak_adv_ratio:
        return "weak"
    return "neutral"


def evaluate_market_filter(
    kospi_today_pct: float,
    kospi_5d_pct: float | None = None,
    kospi_volatility: float | None = None,
) -> dict[str, Any]:
    """오늘 종베 적합한 시장인가? — 수치 입력 기반.

    Args:
        kospi_today_pct: KOSPI 당일 등락률 (%)
        kospi_5d_pct: KOSPI 5일 누적 등락률 (%)
        kospi_volatility: 20일 일간 변동성 표준편차 (%)
    """
    if kospi_today_pct <= -1.5:
        return {
            "ok": False,
            "kospi_today_pct": kospi_today_pct,
            "kospi_5d_pct": kospi_5d_pct,
            "kospi_volatility": kospi_volatility,
            "reason": f"KOSPI 오늘 {kospi_today_pct:+.2f}% — 약세장 (종베 비추천)",
        }

    if kospi_5d_pct is not None and kospi_5d_pct <= -3.0:
        return {
            "ok": False,
            "kospi_today_pct": kospi_today_pct,
            "kospi_5d_pct": kospi_5d_pct,
            "kospi_volatility": kospi_volatility,
            "reason": f"KOSPI 최근 5일 {kospi_5d_pct:+.2f}% — 추세 약세",
        }

    return {
        "ok": True,
        "kospi_today_pct": kospi_today_pct,
        "kospi_5d_pct": kospi_5d_pct,
        "kospi_volatility": kospi_volatility,
        "reason": "시장 환경 양호 — 종베 가능",
    }
