"""I3 입출금 보정 — 출금을 손실로, 입금을 수익으로 착각하지 않게 (2026-10-22, 개선 백로그 P1-①).

문제: I3 자산 = 예탁자산 − I3 외 보유분. 출금하면 자산이 줄어 **낙폭 예산이 손실로 보고 비중을 깎는다**.
입금·I3 외 종목 매도(SK이노베이션)도 수익처럼 보인다.

해법 — 좌수(units) 방식:
  성과 지수 = 실제 자산 ÷ 좌수.  입출금 F 가 있는 날: 지수 = (자산 − F) ÷ 어제 좌수, 좌수 = 자산 ÷ 지수.
  낙폭 예산은 **성과 지수**로 판단하고, 주문 수량은 실제 자산으로 정한다. 입출금이 없으면 지수 == 자산(기존과 같음).

입출금 찾기 — **자동**(운용자 요청 10-22 "입출금 기록도 자동으로"):
  기대 자산 = 어제 판단 때 구성(보유 수량·현금) + 그사이 매매(체결 기록 i3_fills 의 체결가·수수료) → 오늘 현재가로 평가.
  차이가 max(1만원, 자산의 0.3%) 이상이면:
    · 음수 → **출금**(자동 보정 + critical — 가짜 손실로 비중이 깎이는 위험한 쪽)
    · 양수 → **입금**(자동 보정 — 입금·I3 밖 종목 매도 대금). 단 KODEX200 분배금 지급 시기(2·5·8·11월 1~15일)에
      KODEX200 을 들고 있었고 차이가 그 평가액의 3% 이하이면 **분배금**으로 보고 성과로 둔다.
  매매가 있었는데 체결가를 모르면(체결 조회 실패) 자동 감지를 건너뛴다.
  운용자 기록(`i3_live.py --phase flow --amount ±원`)은 덮어쓰기용으로 남는다(기록분은 먼저 뺀다).
"""
from __future__ import annotations

FLOW_MIN_WON = 10_000.0
FLOW_MIN_PCT = 0.003
FEE_BPS = 1.5                    # 실제 수수료(키움 ETF 0.015%) — 매매 반영 때 현금에서 뺀다(ETF 매도세 없음)
DIST_MONTHS = (2, 5, 8, 11)      # KODEX200 분배금 지급 달(기준일 1·4·7·10월 말 → 다음 달 초 지급)
DIST_MAX_DAY = 15
DIST_MAX_PCT = 0.03              # 분배금으로 볼 수 있는 상한(KODEX200 평가액 대비)
BASE_CODE = "069500"


def in_dist_window(day: str) -> bool:
    return int(day[5:7]) in DIST_MONTHS and int(day[8:10]) <= DIST_MAX_DAY


def apply_trades(prev: dict, trades: list[dict], fee_bps: float = FEE_BPS) -> dict | None:
    """어제 구성에 그사이 매매(체결 기록)를 반영한 구성. 체결가를 모르는 주문이 하나라도 있으면 None."""
    q, cash = dict(prev["q"]), float(prev["cash"])
    for t in trades:
        filled, px = t.get("fill_qty"), t.get("fill_price")
        if filled is None or (filled and not px):
            return None                                  # 체결 여부·가격 모름
        if not filled:
            continue                                     # 미체결 — 구성 변화 없음
        amt, fee = filled * px, filled * px * fee_bps / 1e4
        if t["side"] == "buy":
            q[t["code"]] = q.get(t["code"], 0.0) + filled
            cash -= amt + fee
        else:
            q[t["code"]] = q.get(t["code"], 0.0) - filled
            cash += amt - fee
    return {"q": q, "px": prev["px"], "cash": cash}


def snapshot(hold: list[dict], nav_real: float, codes: tuple[str, ...]) -> dict:
    """판단 시점 구성 — {q: {종목: 수량}, px: {종목: 현재가}, cash: 자산 − 평가액}."""
    q = {h["symbol"]: float(h["qty"]) for h in hold if h["symbol"] in codes}
    px = {h["symbol"]: float(h["cur"]) for h in hold if h["symbol"] in codes}
    return {"q": q, "px": px, "cash": nav_real - sum(q[c] * px[c] for c in q)}


def detect_flow(prev: dict | None, hold_now: list[dict], nav_real: float, traded_since: bool,
                declared: float = 0.0, trades: list[dict] | None = None,
                day: str = "") -> tuple[float, str, float]:
    """(반영할 입출금, 방식, 설명 안 된 차이).
    방식: none · declared · auto-withdrawal · auto-deposit · distribution · skip-trade."""
    if prev is None:
        return declared, "declared" if declared else "none", 0.0
    base = apply_trades(prev, trades) if traded_since and trades else (None if traded_since else prev)
    if base is None:
        return declared, "skip-trade", 0.0
    cur = {h["symbol"]: float(h["cur"]) for h in hold_now}
    expected = base["cash"] + sum(q * cur.get(c, base["px"].get(c, 0.0)) for c, q in base["q"].items())
    resid = nav_real - expected - declared
    tol = max(FLOW_MIN_WON, FLOW_MIN_PCT * nav_real)
    if resid <= -tol:
        return declared + resid, "auto-withdrawal", resid
    if resid >= tol:
        base_val = base["q"].get(BASE_CODE, 0.0) * cur.get(BASE_CODE, base["px"].get(BASE_CODE, 0.0))
        if day and in_dist_window(day) and base_val > 0 and resid <= DIST_MAX_PCT * base_val:
            return declared, "distribution", resid
        return declared + resid, "auto-deposit", resid
    return declared, "declared" if declared else "none", resid


def apply_flow(prev_index: float | None, prev_units: float | None, nav_real: float, flow: float) -> tuple[float, float]:
    """(성과 지수, 좌수). 첫날은 좌수 1 · 지수 = 자산."""
    if prev_index is None or not prev_units:
        return nav_real, 1.0
    index = (nav_real - flow) / prev_units
    if index <= 0:
        raise ValueError(f"입출금 반영 뒤 지수가 0 이하 — 자산 {nav_real:,.0f} · 입출금 {flow:,.0f}")
    return index, nav_real / index
