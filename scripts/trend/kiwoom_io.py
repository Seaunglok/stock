"""키움 MCP I/O 레이어 — 시세/수급/계좌/주문/업종지수 (scripts/trend/kiwoom_io.py).

모든 함수가 _kiwoom_call(공용 호출) + _num(숫자파싱)을 재사용. 실패 시 graceful 기본값.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from src.claude_agents.base.mcp_client import MCPManager

from trend.config import (
    ACCOUNT_NO, INFO_URL, INVESTOR_URL, MARKET_URL, PORTFOLIO_URL, TRADING_URL, logger,
)

_SECTOR_SKIP = {"종합(KOSPI)", "대형주", "중형주", "소형주"}   # 업종 아님(시장 구분 지수)


def _order_accepted(parsed: Any) -> tuple[bool, str]:
    """주문 응답 검증 — success:true 라도 return_code!=0(예: 8005)이면 거부로 판정(유령 방지)."""
    if not isinstance(parsed, dict):
        return False, "형식오류"
    if parsed.get("success") is False:
        return False, str(parsed.get("error", "실패"))
    d = parsed.get("data", parsed)
    rc = d.get("return_code") if isinstance(d, dict) else None
    if rc in (0, "0", None):
        return True, ""
    return False, f"rc={rc} {str(d.get('return_msg', ''))[:80]}"


async def _kiwoom_call(server_key: str, url: str, tool_kw, args: dict) -> dict:
    """키움 MCP 단일 호출 → data dict. tool_kw: 도구명 부분일치 키워드(str/tuple). 실패 시 {}.

    헬퍼들의 'MCPManager 열기 → tool 검색 → call → json → data' 보일러플레이트 단일화.
    """
    kws = (tool_kw,) if isinstance(tool_kw, str) else tuple(tool_kw)
    try:
        async with MCPManager({server_key: url}) as mcp:
            tool = next((t["name"] for t in (mcp.tools or [])
                         if any(k in t["name"].lower() for k in kws)), None)
            if not tool:
                return {}
            raw = await mcp.call_tool(tool, args)
            p = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(p, dict):
                return {}
            d = p.get("data", p)
            return d if isinstance(d, dict) else {}
    except Exception as e:
        logger.debug("[KIWOOM] %s %s 실패: %s", server_key, kws, e)
        return {}


def _num(d: dict, key: str, abs_val: bool = False) -> float:
    """키움 숫자필드 파싱(콤마/부호/제로패딩 처리). 없으면 0.0. abs_val=True면 절대값."""
    v = d.get(key) if isinstance(d, dict) else None
    if v in (None, ""):
        return 0.0
    try:
        f = float(str(v).replace(",", ""))
    except Exception:
        return 0.0
    return abs(f) if abs_val else f


def _kint(s: Any) -> int:
    """키움 제로패딩/부호 문자열 → int."""
    return int(_num({"_": s}, "_"))


async def _realtime_price(symbol: str) -> float | None:
    for key, url in [("kiwoom-market-mcp", MARKET_URL), ("trading-domain", TRADING_URL)]:
        d = await _kiwoom_call(key, url, ("basic_info", "current_price", "quote"), {"stock_code": symbol})
        for k in ("cur_prc", "current_price", "현재가", "stck_prpr", "price", "close"):
            f = _num(d, k, abs_val=True)
            if f:
                return f
    return None


async def _foreign_net_5d(symbol: str) -> float | None:
    d = await _kiwoom_call("investor-domain", INVESTOR_URL, ("foreign", "investor", "trading"), {"stock_code": symbol})
    for k in ("foreign_net_5d", "외국인_5일_순매수"):
        if d.get(k) not in (None, ""):
            return _num(d, k)
    return None


async def _cur_and_open(symbol: str) -> tuple[float, float]:
    """현재가·당일 시가 (장중 방향 판정용). get_stock_basic_info cur_prc/open_pric."""
    d = await _kiwoom_call("kiwoom-market-mcp", MARKET_URL, "basic_info", {"stock_code": symbol})
    return _num(d, "cur_prc", abs_val=True), _num(d, "open_pric", abs_val=True)


async def _premarket_snapshot(symbol: str) -> dict | None:
    """프리장(장전 동시호가, 08:00~09:00) 예상체결가·예상수량·갭%(기준가 대비).

    키움 get_stock_basic_info 의 exp_cntr_pric(예상체결가)/exp_cntr_qty/base_pric 사용.
    장전 외 시간대엔 보통 exp_cntr_pric=0 → None 반환(표시 생략).
    """
    d = await _kiwoom_call("kiwoom-market-mcp", MARKET_URL, "basic_info", {"stock_code": symbol})
    exp = _num(d, "exp_cntr_pric", abs_val=True)
    base = _num(d, "base_pric", abs_val=True) or _num(d, "cur_prc", abs_val=True)
    if exp <= 0 or base <= 0:
        return None
    return {"exp_price": exp, "exp_qty": _num(d, "exp_cntr_qty", abs_val=True),
            "gap_pct": round((exp - base) / base * 100, 2)}


async def _broker_holdings() -> list[dict]:
    """계좌 보유종목 [{symbol,name,qty,avg,cur}]. get_account_evaluation 파싱."""
    d = await _kiwoom_call("portfolio-domain", PORTFOLIO_URL, "evaluation", {})
    out = []
    for r in (d.get("stk_acnt_evlt_prst") or []):
        code = str(r.get("stk_cd", "")).lstrip("A")
        qty = _kint(r.get("rmnd_qty", 0))
        if not code or qty <= 0:
            continue
        out.append({"symbol": code, "name": r.get("stk_nm", code), "qty": qty,
                    "avg": _kint(r.get("avg_prc", 0)), "cur": _kint(r.get("cur_prc", 0))})
    return out


async def _account_equity() -> tuple[float, float]:
    """(추정예탁자산, 예수금현금) — 포지션 사이징용. 실패 시 (0,0).

    반드시 get_account_evaluation 사용(get_account_balance 엔 prsm_dpst_aset_amt 없음 → 예탁자산 0 폴백 버그).
    """
    d = await _kiwoom_call("portfolio-domain", PORTFOLIO_URL, "evaluation", {})
    equity = _num(d, "prsm_dpst_aset_amt") or _num(d, "tot_est_amt")
    cash = _num(d, "entr") or _num(d, "d2_entra")
    return equity, cash


async def _place(mcp, side: str, symbol: str, qty: int, *, timeout: float = 10.0, retries: int = 1) -> Any:
    """시장가 주문(order_type 03) — 타임아웃 + 재시도. mcp = 열려있는 trading-domain MCPManager.

    호출 자체 실패(타임아웃/예외)는 {"success": False} 반환 → _order_accepted 가 거부로 판정(유령 방지).
    """
    tool = "place_buy_order" if side == "buy" else "place_sell_order"
    args = {"stock_code": symbol, "quantity": qty, "price": None,
            "order_type": "03", "account_no": ACCOUNT_NO}
    last = None
    for attempt in range(retries + 1):
        try:
            raw = await asyncio.wait_for(mcp.call_tool(tool, args), timeout=timeout)
            return json.loads(raw) if isinstance(raw, str) else raw
        except Exception as e:
            last = e
            logger.warning("[ORDER] %s %s 시도%d/%d 실패: %s", side, symbol, attempt + 1, retries + 1, e)
    return {"success": False, "error": f"주문 호출 실패: {last}"}


async def _sector_index_rows() -> list[dict] | None:
    """키움 업종지수 당일 스냅샷 [{sector, change_pct, rising, falling, flat}] (ka20001).

    KOSPI 전 업종의 지수 등락률 + 상승/하락/보합 종목수 — 집단상승(breadth) 판정 소스.
    info-domain(:8032) 미가동/실패 시 None(판정 불가 → fail-open).
    """
    def _f(v: Any) -> float:
        try:
            return float(str(v).replace(",", "").replace("+", ""))
        except Exception:
            return float("nan")

    try:
        async with MCPManager({"kiwoom-info-mcp": INFO_URL}) as mcp:
            if not mcp.tools:
                return None
            raw = await mcp.call_tool("get_sector_code_list", {"market_type": "0"})
            p = json.loads(raw) if isinstance(raw, str) else raw
            codes = (p.get("data", {}) or {}).get("list", []) if isinstance(p, dict) else []
            rows = []
            for it in codes:
                name = str(it.get("name", ""))
                if not name or name in _SECTOR_SKIP:
                    continue
                try:
                    raw2 = await mcp.call_tool("get_sector_current_price",
                                               {"sector_code": it.get("code", ""), "market_type": "0"})
                    p2 = json.loads(raw2) if isinstance(raw2, str) else raw2
                    d = p2.get("data", {}) if isinstance(p2, dict) else {}
                    rows.append({"sector": name, "change_pct": _f(d.get("flu_rt")),
                                 "rising": int(_f(d.get("rising")) or 0),
                                 "falling": int(_f(d.get("fall")) or 0),
                                 "flat": int(_f(d.get("stdns")) or 0)})
                except Exception:
                    continue
            return rows or None
    except Exception as e:
        logger.debug("[SECTOR] 업종지수 조회 실패: %s", e)
        return None
