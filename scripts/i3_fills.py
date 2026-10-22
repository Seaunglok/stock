"""I3 체결 기록 — 실제 체결가 vs 주문 직전 현재가 (2026-10-22, 개선 백로그 P1-②).

모든 백테스트가 편도 11.5bp(수수료 1.5 + 슬리피지 10) 비용을 가정한다. 매매가 잦은 계열은 이 가정이 순위를
뒤집는다(변동성돌파 −11% ↔ 비용 0 +14%). 실계좌 체결을 매번 남겨 3개월 뒤 비용 가정을 실측으로 바꾼다.

기록(data/i3/fills.jsonl 한 줄 = 주문 하나): 날짜·종목·매수/매도·수량·주문 방식·지정가·주문 직전 현재가·
체결가(체결내역 ka10076 가중평균)·체결 수량·슬리피지(bp, 매수는 현재가 대비 높을수록 +, 매도는 낮을수록 +).
"""
from __future__ import annotations

import json
from typing import Any


def _num(v: Any) -> float:
    try:
        return abs(float(str(v).replace(",", "").replace("+", "")))
    except (TypeError, ValueError):
        return 0.0


def parse_fills(payload: Any, symbol: str, side: str, since_hhmmss: str = "000000") -> tuple[int, int, float] | None:
    """체결내역(get_order_executions, ka10076) → 이 종목 side('매수'|'매도') 주문의 (주문수량, 체결수량, 평균체결가).
    trend_kiwoom_io._parse_sell_orders 와 같은 규칙(취소·정정·거부 제외, since 이후 주문만). 응답이 이상하면 None."""
    try:
        p = json.loads(payload) if isinstance(payload, str) else payload
    except Exception:
        return None
    if not isinstance(p, dict) or p.get("success") is False:
        return None
    d = p.get("data", p)
    if not isinstance(d, dict) or str(d.get("return_code", "0")) != "0":
        return None
    rows = d.get("cntr")
    if not isinstance(rows, list):
        return None
    ordered = filled = 0
    amount = 0.0
    for r in rows:
        if not isinstance(r, dict) or str(r.get("stk_cd", "")).lstrip("A") != symbol:
            continue
        s, status = str(r.get("io_tp_nm", "")), str(r.get("ord_stt", ""))
        if side not in s or any(x in s + status for x in ("취소", "정정", "거부")):
            continue
        if str(r.get("ord_tm", "")).zfill(6) < since_hhmmss:
            continue
        cq = int(_num(r.get("cntr_qty", 0)))
        ordered += int(_num(r.get("ord_qty", 0)))
        filled += cq
        amount += cq * _num(r.get("cntr_pric", 0))
    return ordered, filled, (amount / filled if filled else 0.0)


def slippage_bp(side: str, ref: float, fill: float) -> float | None:
    """비용 쪽이 + : 매수는 기준보다 비싸게, 매도는 싸게 체결될수록 +."""
    if not ref or not fill:
        return None
    return ((fill / ref - 1) if side == "buy" else (1 - fill / ref)) * 1e4


def fill_record(day: str, side: str, code: str, qty: int, order_type: str, limit: float | None,
                ref: float | None, parsed: tuple[int, int, float] | None) -> dict:
    filled, price = (parsed[1], parsed[2]) if parsed else (None, None)
    return {"date": day, "side": side, "code": code, "qty": qty, "order_type": order_type, "limit": limit,
            "ref_price": ref, "fill_qty": filled, "fill_price": round(price, 2) if price else None,
            "slippage_bp": None if not price or not ref else round(slippage_bp(side, ref, price), 2),
            "parsed": parsed is not None}
