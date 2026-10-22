"""I3 실전 판단 핵심 — 순수 함수 (2026-10-22, 운용자 승인 실전 적용).

**검증한 코드를 그대로 쓴다.** 엔진은 `lab_dd_control.reentry_confirmed`, 상수는 `lab_holdout` 의
선언값을 import 한다. 실전 판단을 따로 다시 구현하면, 검증한 전략과 실제로 도는 전략이 조용히
갈린다(08-28 `simulate_trade` 사다리 불일치 사고와 같은 종류).

판단 = 엔진 보유 여부(가격만으로 결정 — 검증과 같은 시작일부터 재생) × 낙폭 예산(실계좌 자기 자산 이력).

  · 엔진: 2015-07-28 부터 오늘까지 KODEX200·KOSPI 일봉으로 I1a 를 재생해 오늘의 보유/이탈 상태를 얻는다.
          시작일이 검증과 같으므로 오늘 상태도 검증 실행의 같은 날 상태와 같다.
  · 낙폭 예산: 실전 시작 이후 기록한 자기 자산(종가 기준) 최근 252개의 최고치 × 82% 가 바닥선,
               비중 e = min(1, 6 × (자산−바닥)/자산).
  · 매매 조건: 엔진 신호가 바뀌었거나, 목표 비중이 직전 대비 10%p 이상 바뀌었거나, 0 으로 내려갈 때.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lab_dd_control import reentry_confirmed  # noqa: E402
from lab_holdout import I3_BAND, I3_DEFAULT, I3_FLOOR_DD  # noqa: E402

BASE = "069500"            # KODEX200
# 현금 자리 = KODEX 머니마켓액티브 (2026-10-22 운용자 승인, 구 153130 KODEX 단기채권).
# 근거: docs/2026-10-22-etf-choice.md §5-C — 153130 보다 연 +0.6~0.8%p, 낙폭 ~0, I3 현금 비중 평균 39%.
# 판단과 무관하다: 엔진은 이 코드를 이탈 신호의 이름표로만 쓴다(test_engine_ignores_cash_code 가 잠근다).
# 검증(lab_holdout)은 153130 으로 했다 — 머니마켓은 2024-08 상장이라 2015~ 이력이 없다.
CASH = "488770"
REPLAY_START = "2015-07-28"
ENGINE_X, ENGINE_N = 10, 20
M, LOOKBACK = I3_DEFAULT   # (6, 252)
FLOOR_DD = I3_FLOOR_DD     # 18
BAND = I3_BAND             # 0.10


@dataclass
class EngineState:
    holding: bool          # 오늘 종가 기준 엔진이 보유 신호인가
    changed_today: bool    # 오늘 신호가 바뀌었나(보유↔이탈)
    last_date: str         # 재생한 마지막 날짜


def engine_state(base_bars: dict[str, dict], kospi_bars: dict[str, dict], upto: str) -> EngineState:
    """검증과 같은 시작일부터 upto 까지 엔진을 재생 → 오늘의 보유 상태.

    base_bars 의 날짜가 달력이다(KODEX200 거래일). upto 이후 데이터는 보지 않는다.
    """
    days = sorted(d for d in base_bars if REPLAY_START <= d <= upto)
    if not days:
        raise ValueError(f"재생할 일봉이 없다: {REPLAY_START}~{upto}")
    t = reentry_confirmed(base_bars, kospi_bars, BASE, ENGINE_X, ENGINE_N, CASH)
    holding, changed = True, False
    for i, d in enumerate(days):
        w = t(i, d)
        changed = False
        if w is not None:
            new = BASE in w
            changed = (i > 0) and (new != holding)
            holding = new
    return EngineState(holding=holding, changed_today=changed, last_date=days[-1])


def budget_exposure(navs: list[float], m: float = M, lookback: int = LOOKBACK,
                    floor_dd: float = FLOOR_DD) -> float:
    """최근 lookback 개 자기 자산의 최고치 대비 바닥선까지의 쿠션 × m (0~1)."""
    if not navs or navs[-1] <= 0:
        return 0.0
    nav = navs[-1]
    floor = (1 - floor_dd / 100.0) * max(navs[-lookback:])
    return min(1.0, max(0.0, m * (nav - floor) / nav))


def decide(engine: EngineState, navs: list[float], prev_w: float | None,
           band: float = BAND) -> tuple[float, bool, str]:
    """(목표 KODEX200 비중, 매매 필요 여부, 사유). 나머지 비중은 현금 자리 ETF(CASH)."""
    e = budget_exposure(navs)
    w = e if engine.holding else 0.0
    if prev_w is None:
        return w, True, "첫 판단"
    if engine.changed_today:
        return w, True, "엔진 신호 " + ("보유 전환" if engine.holding else "이탈 전환")
    if w == 0.0 and prev_w > 0:
        return w, True, "비중 0 으로"
    if abs(w - prev_w) >= band:
        return w, True, f"비중 변화 {prev_w:.2f}→{w:.2f}"
    return prev_w, False, f"유지(목표 {w:.2f} · 직전 {prev_w:.2f}, 차이 < {band:.0%})"


def target_shares(w: float, nav: float, prices: dict[str, float], buffer: float = 0.01) -> dict[str, int]:
    """목표 비중 → 목표 주식수(내림). 체결가 변동·비용 대비 buffer 만큼 덜 산다."""
    usable = nav * (1 - buffer)
    out = {}
    for code, weight in ((BASE, w), (CASH, 1.0 - w)):
        px = prices.get(code, 0.0)
        out[code] = int(usable * weight // px) if px > 0 and weight > 0 else 0
    return out


def order_plan(current: dict[str, int], target: dict[str, int]) -> list[tuple[str, str, int]]:
    """[(side, code, qty)] — **매도 먼저**(현금 확보), 그다음 매수."""
    sells = [("sell", c, current.get(c, 0) - q) for c, q in target.items() if current.get(c, 0) > q]
    buys = [("buy", c, q - current.get(c, 0)) for c, q in target.items() if q > current.get(c, 0)]
    return sells + buys
