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
    """외국인 최근 5영업일 순매수 합산 — ka10008, **완성일 기준 + 규모 임계값**(signals.foreign_net_signal).

    2026-07-13 재구현(구 dead code) → 2026-07-15 보강: 삼성생명 오발동(당일 잠정치 부호반전 +
    유통주식 0.001% 노이즈 발동) 재발 방지 — 당일 잠정 행 제외, |5일합| < FOREIGN_MIN_RATIO×20일
    평균거래량 이면 None(노이즈, 룰 미적용). ※ 백테스트 검증은 backtest_trend --foreignexit.
    """
    from datetime import datetime as _dt
    from src.mcp_servers.trend_mcp.signals import foreign_net_signal
    from trend_config import FOREIGN_MIN_RATIO
    d = await _kiwoom_call("investor-domain", INVESTOR_URL, "foreign_trading_trend", {"stock_code": symbol})
    rows = d.get("stk_frgnr")
    if not isinstance(rows, list) or not rows:
        logger.debug("[FOREIGN] %s stk_frgnr 리스트 없음 — 외인 청산룰 미적용", symbol)
        return None
    net = foreign_net_signal(rows, _dt.now().strftime("%Y%m%d"), FOREIGN_MIN_RATIO)
    if net is None:
        logger.info("[FOREIGN] %s 신호 없음(완성일<5 or |5일합|<임계 %.2f×avg20vol) — 룰 미적용",
                    symbol, FOREIGN_MIN_RATIO)
    return net


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


def _is_unknown(resp: Any) -> bool:
    """주문 접수 여부가 **불명**인가(타임아웃/통신실패). True 면 재전송 금지 — 잔고로 대조할 것."""
    return isinstance(resp, dict) and bool(resp.get("unknown"))


async def _place(mcp, side: str, symbol: str, qty: int, *, timeout: float = 10.0) -> Any:
    """시장가 주문(order_type 03) 1회 전송. mcp = 열려있는 trading-domain MCPManager.

    **재전송하지 않는다.** 2026-08-17 이전엔 retries=1 로 타임아웃 시 같은 시장가 주문을 다시
    보냈다 — 브로커가 이미 접수했는데 응답만 늦은 경우 그대로 이중 체결이다(멱등키·주문번호
    대조 없음). 매도는 _sell_with_retry 가 _place 를 두 번 부르므로 최대 4회까지 나갈 수 있었다.

    핵심은 **거부와 불명의 구분**이다:
      - return_code != 0 (거부)  → 접수 안 됨이 확실 → 재시도 안전 (_sell_with_retry 가 담당)
      - 타임아웃/예외 (불명)     → 접수 여부 모름 → 재전송 금지, {"unknown": True} 로 표시.
        매수는 _verify_buy_fills 의 잔고 대조에, 매도는 critical 알림 + 다음 cycle 에 맡긴다.
    """
    tool = "place_buy_order" if side == "buy" else "place_sell_order"
    args = {"stock_code": symbol, "quantity": qty, "price": None,
            "order_type": "03", "account_no": ACCOUNT_NO}
    try:
        raw = await asyncio.wait_for(mcp.call_tool(tool, args), timeout=timeout)
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception as e:
        logger.error("[ORDER] %s %s %d주 응답 불명(재전송 안 함 — 중복체결 방지): %s",
                     side, symbol, qty, e)
        return {"success": False, "unknown": True,
                "error": f"주문 응답 불명(접수 여부 미확인): {e}"}


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


async def _kospi_closes_kiwoom(days: int = 150) -> list[float] | None:
    """KOSPI 종가 시계열 — 키움 ka20006(업종일봉, inds_cd=001). 오래된순 정렬 반환.

    2026-07-22 추가: FDR ^KS11 이 전일 종가를 **다음날 장중에야** 채워 08:50 screen 시점엔
    항상 1영업일 지연 → 개별종목(pykrx, 전일까지)과 날짜가 어긋나 RS 게이트가 매일 하루 묵은
    지수로 판정하던 문제. 키움은 당일 봉까지 제공해 정렬이 맞는다.
    지수값은 ×100 스케일(674795=6747.95) → /100 정규화. 실패 시 None(호출자가 FDR 폴백).
    """
    d = await _kiwoom_call("kiwoom-market-mcp", MARKET_URL, "sector_daily_chart",
                           {"sector_code": "001", "limit": days})
    rows = d.get("inds_dt_pole_qry")
    if not isinstance(rows, list) or not rows:
        logger.debug("[KOSPI] ka20006 배열 없음 — FDR 폴백")
        return None
    pairs = []
    for r in rows:
        dt, px = str(r.get("dt", "")), _num(r, "cur_prc", abs_val=True)
        if len(dt) == 8 and px > 0:
            pairs.append((dt, px / 100.0))
    if len(pairs) < 61:                      # RS(60일) 계산 최소치 미달
        logger.debug("[KOSPI] ka20006 %d봉 — 부족, FDR 폴백", len(pairs))
        return None
    pairs.sort()                             # 최신순 응답 → 오래된순
    return [c for _, c in pairs]


async def kospi_closes() -> list[float]:
    """RS 게이트/일지용 KOSPI 종가 — 키움 ka20006 우선, 실패 시 FDR(순수도메인) 폴백.

    FDR 은 전일 종가를 다음날 장중에 채워 08:50 screen 시점 1영업일 지연 → 개별종목과
    날짜가 어긋나 RS 가 하루 묵은 지수로 판정되던 문제(2026-07-22 수정). 키움은 당일 봉 포함.
    """
    k = await _kospi_closes_kiwoom()
    if k:
        return k
    logger.warning("[KOSPI] 키움 ka20006 실패 — FDR 폴백(1영업일 지연 가능)")
    from src.mcp_servers.trend_mcp.market_data import get_kospi_closes
    return get_kospi_closes()


# ─── universe wrapper ──────────────────────────────────────────────────────
# scripts/trend/market_data.py 가 삭제되면서 데몬용 get_universe (config 자동 주입) 흡수.
def get_universe() -> list[tuple[str, str]]:
    """데몬용: trend_config 의 환경설정값을 trend_mcp.market_data.get_universe 에 주입."""
    from src.mcp_servers.trend_mcp.market_data import get_universe as _gu
    from trend_config import MIN_VALUE_KRW, TOP_N, UNIVERSE_MODE, WATCHLIST
    return _gu(UNIVERSE_MODE, TOP_N, WATCHLIST, MIN_VALUE_KRW)
