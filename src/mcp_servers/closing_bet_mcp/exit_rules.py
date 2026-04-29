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
) -> ExitDecision:
    """매수 후 청산 신호 (HOLD/PARTIAL_SELL/SELL_ALL/STOP_LOSS)."""
    now = now or datetime.now()
    pnl_pct = (current_price - entry_price) / entry_price * 100.0 if entry_price > 0 else 0.0

    # 1) 시간외 하락 → 즉시 매도
    if after_hours_price is not None and after_hours_price < entry_price:
        ah_pct = (after_hours_price - entry_price) / entry_price * 100.0
        return ExitDecision(
            action="SELL_ALL",
            urgency="high",
            reason=f"시간외 하락 ({ah_pct:+.2f}%) — 평단 이탈, 즉시 매도",
            suggested_qty_pct=100,
        )

    # 2) 매수 평단 이탈 (정규장)
    if current_price < entry_price * 0.99:
        return ExitDecision(
            action="STOP_LOSS",
            urgency="high",
            reason=f"평단 이탈 ({pnl_pct:+.2f}%) — 손절",
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
