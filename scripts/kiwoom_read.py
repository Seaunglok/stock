"""키움 조회 — 한 곳에서, 오류를 버리지 않고 (2026-11-12, 리팩터링 1번 — 운용자 "지금 진행해줘. 1번부터").

왜
--
  운용 코드가 키움에 들어가는 길이 네 갈래였다: MCP `trend_kiwoom_io._kiwoom_call`(예외·return_code 를 삼키고 {} ·
  debug 로그) · MCPManager 직접(주문) · REST 클라이언트 직접(수급·일지·연결 점검) · market 서버 객체를 프로세스 안에서
  만들기(분봉). `_kiwoom_call` 이 8050(IP 미등록)과 '빈 응답'을 구분하지 못해 11-09 엔 판단이 '휴장'으로 지나갔고,
  11-10 장치(`i3_live.missing_bar_reason`)도 빈 응답을 보고 거꾸로 추정한다. 주문가능금액 조회 실패 알림엔 원인이 빠진다.

무엇
----
  · 시세·주문가능금액 조회는 여기 — `KiwoomRESTAPIClient` 직접(MCP 서버가 떠 있지 않아도 된다).
    결과는 `Result(data, status, detail)` · status = 'ok' | 'ip'(8050 IP 미등록) | 'fail'. **밖으로 예외를 던지지 않고
    원인 문구를 담는다** — 호출자가 '조회 실패'를 '0'·'휴장'으로 믿지 않게.
  · 요청은 MCP 서버가 보내던 것과 **같은 API·같은 인자**다(ka10081·ka20006·ka10001·kt00010·ka10080). 일봉은 MCP 와 같이
    최신 DAILY_LIMIT(150)개로 자른다. 11-12 밤 두 길의 결과가 같은지 실데이터로 대조한 뒤 바꿨다.
  · 연속 호출 사이 최소 간격 MIN_GAP_S(MCP 서버는 매 호출 2초를 쉬었다), 'fail' 은 RETRIES 번 다시(8050 은 다시 해도
    같으니 바로 판정).
  · 주문은 그대로 trading-domain MCP(검증된 경로 — 지정가 코드 변환·응답 불명 처리), 계좌 평가(보유·예탁)도 당분간
    portfolio-domain MCP(`trend_kiwoom_io._broker_holdings_checked` — 실패를 None 으로 돌려주는 검증된 함수). 다음 단계.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger("kiwoom_read")

MIN_GAP_S = 0.3
RETRIES = 2
RETRY_GAP_S = 1.0
DAILY_LIMIT = 150
API = {"daily": "ka10081", "sector_daily": "ka20006", "basic": "ka10001", "orderable": "kt00010",
       "minute": "ka10080"}
_last = {"t": 0.0}


@dataclass
class Result:
    data: dict = field(default_factory=dict)
    status: str = "fail"
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def why(self) -> str:
        """알림에 붙일 한 줄 — 8050 은 무엇을 해야 하는지까지."""
        if self.status == "ip":
            return f"8050 IP 미등록(키움 REST API 사용신청에서 공인 IP 등록) — {self.detail[:120]}"
        return self.detail[:200]


# ── 순수 함수 ────────────────────────────────────────────────────────────────
def classify(result: dict | None, error: str | None) -> tuple[str, str]:
    """키움 응답 → ('ok' | 'ip' | 'fail', 설명). 8050 은 토큰 단계(예외 문구)·조회 단계(return_msg) 어디서든 온다
    (11-12 실측: 토큰은 살아 있는데 일봉 조회가 return_code 3 · 8050 으로 막혔다)."""
    if error is not None:
        return ("ip" if "8050" in error else "fail"), error
    if not isinstance(result, dict):
        return "fail", "응답 없음"
    rc, msg = result.get("return_code"), str(result.get("return_msg") or "")
    if "8050" in msg:
        return "ip", msg
    if rc in (0, "0"):
        return "ok", msg or "정상"
    return "fail", f"rc={rc} {msg}".strip()


def num(d: dict, key: str, abs_val: bool = False) -> float:
    """키움 숫자필드(콤마·부호·제로패딩) → float. 없으면 0.0 (trend_kiwoom_io._num 과 같은 규칙)."""
    v = d.get(key) if isinstance(d, dict) else None
    if v in (None, ""):
        return 0.0
    try:
        f = float(str(v).replace(",", ""))
    except Exception:  # noqa: BLE001
        return 0.0
    return abs(f) if abs_val else f


def won(price: float | None) -> str | None:
    """가격 → 키움 단가 문자열(trading_domain._won 과 같은 규칙 — 정수면 소수점 없이)."""
    if not price:
        return None
    f = float(price)
    return str(int(f)) if f.is_integer() else str(f)


def parse_daily(rows: list[dict], scale: float = 1.0) -> dict[str, dict]:
    """일봉 행 → {YYYY-MM-DD: {open, close, high, low}} (i3_live.KiwoomMarket.recent 가 하던 그대로)."""
    out = {}
    for r in rows:
        dt = str(r.get("dt", ""))
        c = num(r, "cur_prc", abs_val=True) / scale
        o = num(r, "open_pric", abs_val=True) / scale or c
        if len(dt) == 8 and c > 0:
            out[f"{dt[:4]}-{dt[4:6]}-{dt[6:]}"] = {
                "open": o, "close": c,
                "high": (num(r, "high_pric", abs_val=True) / scale) or max(o, c),
                "low": (num(r, "low_pric", abs_val=True) / scale) or min(o, c)}
    return out


# ── 호출 ────────────────────────────────────────────────────────────────────
async def raw_call(api_id: str, params: dict) -> tuple[dict | None, str | None]:
    """키움 REST 1번 — (응답, 예외 문구). 예외를 던지지 않는다."""
    from src.mcp_servers.kiwoom_mcp.common.client.kiwoom_restapi_client import KiwoomRESTAPIClient
    c = KiwoomRESTAPIClient()
    try:
        return await c.call_api(api_id, params), None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"
    finally:
        if hasattr(c, "close"):
            try:
                await c.close()
            except Exception:  # noqa: BLE001
                pass


async def _pace(sleep=None, clock=time.monotonic) -> None:
    sleep = sleep or asyncio.sleep                    # 부를 때 찾는다(기본값으로 묶으면 테스트가 바꿔 끼울 수 없다)
    wait = MIN_GAP_S - (clock() - _last["t"])
    if wait > 0:
        await sleep(wait)
    _last["t"] = clock()


async def call(api_id: str, params: dict, retries: int = RETRIES, sleep=None) -> Result:
    sleep = sleep or asyncio.sleep
    status, detail, r = "fail", "", None
    for k in range(1 + retries):
        await _pace(sleep)
        r, err = await raw_call(api_id, params)
        status, detail = classify(r, err)
        if status in ("ok", "ip"):
            break
        if k < retries:
            await sleep(RETRY_GAP_S * (k + 1))
    if status != "ok":
        log.warning("[KIWOOM] %s %s → %s: %s", api_id, params.get("stk_cd") or params.get("inds_cd"), status,
                    detail[:200])
    return Result(r if isinstance(r, dict) else {}, status, detail)


async def daily_bars(code: str, base_dt: str, limit: int = DAILY_LIMIT) -> tuple[dict, Result]:
    """최근 일봉 — code 'KOSPI' 는 업종 001(×100 스케일). MCP get_daily_chart·get_sector_daily_chart 와 같은 요청."""
    if code == "KOSPI":
        r = await call(API["sector_daily"], {"inds_cd": "001", "base_dt": base_dt})
        rows, scale = (r.data.get("inds_dt_pole_qry") or []) if r.ok else [], 100.0
    else:
        r = await call(API["daily"], {"stk_cd": code, "base_dt": base_dt, "upd_stkpc_tp": "1"})
        rows, scale = (r.data.get("stk_dt_pole_chart_qry") or []) if r.ok else [], 1.0
    return parse_daily(rows[:limit] if limit > 0 else rows, scale), r


async def current_price(code: str) -> tuple[float | None, Result]:
    r = await call(API["basic"], {"stk_cd": code})
    p = num(r.data, "cur_prc", abs_val=True) if r.ok else 0.0
    return (p or None), r


async def orderable_amount(code: str, price: float) -> tuple[float | None, Result]:
    """kt00010 매수 주문가능금액(ord_alowa). 응답이 이상하면 None — 0 으로 믿지 않는다."""
    r = await call(API["orderable"], {"stk_cd": code, "trde_tp": "2", "uv": won(price) or "0"})
    if not r.ok or "ord_alowa" not in r.data:
        if r.ok:
            r = Result(r.data, "fail", "응답에 ord_alowa 없음")
        return None, r
    return num(r.data, "ord_alowa"), r


async def minute_rows(code: str) -> tuple[list[dict], Result]:
    """1분봉(키움은 최근 ~900봉) — collect_i3_minutes 가 쓰던 요청 그대로."""
    r = await call(API["minute"], {"stk_cd": code, "tic_scope": "1", "upd_stkpc_tp": "1"})
    return ((r.data.get("stk_min_pole_chart_qry") or []) if r.ok else []), r
