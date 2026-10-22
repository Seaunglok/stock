"""I3 입출금 보정 — 출금을 손실로, 입금을 수익으로 착각하지 않게 (2026-10-22, 개선 백로그 P1-①).

문제: I3 자산 = 예탁자산 − I3 외 보유분. 출금하면 자산이 줄어 **낙폭 예산이 손실로 보고 비중을 깎는다**.
입금·I3 외 종목 매도(SK이노베이션)도 수익처럼 보인다.

해법 — 좌수(units) 방식:
  성과 지수 = 실제 자산 ÷ 좌수.  입출금 F 가 있는 날: 지수 = (자산 − F) ÷ 어제 좌수, 좌수 = 자산 ÷ 지수.
  낙폭 예산은 **성과 지수**로 판단하고, 주문 수량은 실제 자산으로 정한다. 입출금이 없으면 지수 == 자산(기존과 같음).

입출금 찾기:
  - 운용자 기록(`i3_live.py --phase flow --amount ±원`)은 항상 반영.
  - 자동 감지 — **매매가 없던 날만**: 기대 자산 = 어제 판단 때 보유 수량 × 오늘 현재가 + 어제 현금(자산 − 평가액).
    차이(기록분 제외)가 max(1만원, 자산의 0.3%) 이상이면:
      · **음수(출금)** → 자동으로 입출금 처리 + critical 알림 (가짜 손실로 비중이 깎이는 위험한 쪽)
      · 양수 → 성과로 둔다(분배금일 수 있다) + 알림만 — 입금이었다면 운용자가 기록
  - 매매가 있던 날은 장중 체결이 섞여 기대 자산을 정확히 못 낸다 → 자동 감지 건너뜀(기록분만).
"""
from __future__ import annotations

FLOW_MIN_WON = 10_000.0
FLOW_MIN_PCT = 0.003


def snapshot(hold: list[dict], nav_real: float, codes: tuple[str, ...]) -> dict:
    """판단 시점 구성 — {q: {종목: 수량}, px: {종목: 현재가}, cash: 자산 − 평가액}."""
    q = {h["symbol"]: float(h["qty"]) for h in hold if h["symbol"] in codes}
    px = {h["symbol"]: float(h["cur"]) for h in hold if h["symbol"] in codes}
    return {"q": q, "px": px, "cash": nav_real - sum(q[c] * px[c] for c in q)}


def detect_flow(prev: dict | None, hold_now: list[dict], nav_real: float, traded_since: bool,
                declared: float = 0.0) -> tuple[float, str, float]:
    """(반영할 입출금, 방식, 설명 안 된 차이). 방식: declared · auto-withdrawal · unexplained-gain · skip-trade · none."""
    if prev is None:
        return declared, "declared" if declared else "none", 0.0
    if traded_since:
        return declared, "skip-trade", 0.0
    cur = {h["symbol"]: float(h["cur"]) for h in hold_now}
    expected = prev["cash"] + sum(q * cur.get(c, prev["px"].get(c, 0.0)) for c, q in prev["q"].items())
    resid = nav_real - expected - declared
    tol = max(FLOW_MIN_WON, FLOW_MIN_PCT * nav_real)
    if resid <= -tol:
        return declared + resid, "auto-withdrawal", resid
    if resid >= tol:
        return declared, "unexplained-gain", resid
    return declared, "declared" if declared else "none", resid


def apply_flow(prev_index: float | None, prev_units: float | None, nav_real: float, flow: float) -> tuple[float, float]:
    """(성과 지수, 좌수). 첫날은 좌수 1 · 지수 = 자산."""
    if prev_index is None or not prev_units:
        return nav_real, 1.0
    index = (nav_real - flow) / prev_units
    if index <= 0:
        raise ValueError(f"입출금 반영 뒤 지수가 0 이하 — 자산 {nav_real:,.0f} · 입출금 {flow:,.0f}")
    return index, nav_real / index
