"""키움 MCP I/O 레이어 — 시세/수급/계좌/주문/업종지수 (scripts/trend_kiwoom_io.py).

모든 함수가 _kiwoom_call(공용 호출) + _num(숫자파싱)을 재사용. 실패 시 graceful 기본값.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from src.claude_agents.base.mcp_client import MCPManager

from trend_config import (
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
    """외국인 최근 5영업일 순매수(보유변동수량) 합산 — ka10008 주식외국인종목별매매동향.

    2026-07-13 재구현: 과거엔 존재하지 않는 foreign_net_5d 키를 찾아 항상 None(외인 청산룰 dead code).
    응답 stk_frgnr[] 일별 리스트(최신순)의 chg_qty(전일대비 외인 보유수량 변동 = 일별 순매수)를
    최근 5행 합산. 음수 = 5일 누적 순매도 → exit_decision 외인전환 청산 트리거.
    리스트/필드 부재 시 None(fail-open — 룰 미적용). ※ 이 룰은 백테스트 미검증(발동 시 journal 로 추적).
    """
    d = await _kiwoom_call("investor-domain", INVESTOR_URL, "foreign_trading_trend", {"stock_code": symbol})
    rows = d.get("stk_frgnr")
    if not isinstance(rows, list) or not rows:
        logger.debug("[FOREIGN] %s stk_frgnr 리스트 없음 — 외인 청산룰 미적용", symbol)
        return None
    recent = [r for r in rows[:5] if isinstance(r, dict) and r.get("chg_qty") not in (None, "")]
    if not recent:
        logger.debug("[FOREIGN] %s chg_qty 필드 없음 — 외인 청산룰 미적용", symbol)
        return None
    return sum(_num(r, "chg_qty") for r in recent)


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
    """키움 전업종지수 당일 스냅샷 [{sector, change_pct, rising, falling, flat}] (ka20003, 단일 호출).

    KOSPI 전 업종의 지수 등락률 + 상승/하락/보합 종목수 — 집단상승(breadth) 판정 소스.
    2026-07-09: 업종별 개별조회(ka20001) 다회(~27) 호출 → 전업종지수(ka20003) 1회로 대체(entry ~3분→수초).
    skip 집합은 기존과 동일(_SECTOR_SKIP: 종합/대형/중형/소형주) → breadth 값 불변(ka20001·ka20003 종목수 일치 검증).
    info-domain(:8032) 미가동/실패 시 None(판정 불가 → fail-open).
    """
    def _f(v: Any) -> float:
        try:
            return float(str(v).replace(",", "").replace("+", ""))
        except Exception:
            return float("nan")

    def _i(v: Any) -> int:
        f = _f(v)
        return int(f) if f == f else 0   # nan → 0

    try:
        async with MCPManager({"kiwoom-info-mcp": INFO_URL}) as mcp:
            if not mcp.tools:
                return None
            raw = await mcp.call_tool("get_all_sector_index", {"sector_code": "001"})
            p = json.loads(raw) if isinstance(raw, str) else raw
            arr = (p.get("data", {}) or {}).get("all_inds_idex", []) if isinstance(p, dict) else []
            rows = []
            for it in arr:
                name = str(it.get("stk_nm", ""))
                if not name or name in _SECTOR_SKIP:
                    continue
                rows.append({"sector": name, "change_pct": _f(it.get("flu_rt")),
                             "rising": _i(it.get("rising")),
                             "falling": _i(it.get("fall")),
                             "flat": _i(it.get("stdns"))})
            # 필드 소실 감지: rising/fall/stdns 가 전부 0/부재면 market_breadth 가 None 을 돌려
            # breadth 게이트(06-23 방어)가 조용히 꺼진다 — 무음 해제 대신 경고 남김.
            if rows and all(r["rising"] + r["falling"] + r["flat"] == 0 for r in rows):
                logger.warning("[SECTOR] ka20003 rising/fall/stdns 전부 0 — breadth 게이트 판정 불가(fail-open)")
            return rows or None
    except Exception as e:
        logger.debug("[SECTOR] 전업종지수 조회 실패: %s", e)
        return None


# ─── universe wrapper ──────────────────────────────────────────────────────
# scripts/trend/market_data.py 가 삭제되면서 데몬용 get_universe (config 자동 주입) 흡수.
def get_universe() -> list[tuple[str, str]]:
    """데몬용: trend_config 의 환경설정값을 trend_mcp.market_data.get_universe 에 주입."""
    from src.mcp_servers.trend_mcp.market_data import get_universe as _gu
    from trend_config import MIN_VALUE_KRW, TOP_N, UNIVERSE_MODE, WATCHLIST
    return _gu(UNIVERSE_MODE, TOP_N, WATCHLIST, MIN_VALUE_KRW)
