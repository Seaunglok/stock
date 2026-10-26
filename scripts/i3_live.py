"""I3 실전 — 장 마감 후 '판단', 다음 날 장 시작 전 '매매' (2026-10-22 운용자 승인).

Windows 작업 스케줄러가 단발로 부른다(상주 데몬 아님 — hang·락 문제를 원천 제거):
    python scripts/i3_live.py --phase decide   # 평일 15:50 — 오늘 종가로 내일 목표 비중 결정
    python scripts/i3_live.py --phase trade    # 평일 08:50 — 동시호가에 매도, 09:00 체결 뒤 매수
    python scripts/i3_live.py --phase status   # 상태 보기

안전장치
--------
- **I3_DRY_RUN=true 가 기본**이다. 이 상태에선 주문 도구를 부르지 않고 계획만 기록·알림한다.
  며칠 모의로 돌려 계획이 맞는지 확인한 뒤 운용자가 false 로 바꾼다. I3_HALT=true 면 매매 단계 전체 정지.
- 판단은 **15:35 이후**에만 — 장중엔 오늘 일봉이 미완성(현재가)이다.
- 오늘 일봉이 없으면(휴장·데이터 미갱신) 판단하지 않는다. 키움 최근 일봉과 장기 이력(FDR)이 겹치는
  날 종가가 0.5% 넘게 다르면 판단을 멈추고 알린다.
- 계좌 조회 실패를 '보유 0' 으로 믿지 않는다(`_broker_holdings_checked` 가 None → 중단).
- 주문 응답 불명은 **재전송하지 않는다** — 매매 후 잔고 대조로 확인하고 알린다.
  success:true 라도 return_code≠0 이면 거부로 본다(8005 유령 사고와 같은 규칙).
- **매수는 지정가**(2026-10-22, 실주문 전환 직전 발견): 키움은 시장가 매수를 상한가 매수로 보고 증거금을
  상한가(+30%)로 잡는다 — 자산의 99% 를 시장가로 사면 '주문가능금액 부족' 거부. 그래서 매수는 **09:05:30 이후**
  (LP 호가 의무 시간) **현재가 +1% 지정가**(5원 올림, 즉시 체결)로, 수량은 **실제 주문가능금액** 안으로 줄인다. 현재가·주문가능금액을
  못 읽으면 사지 않고 알린다(추측 주문 금지). 매도는 시장가(증거금 무관, 08:50 동시호가).
- 하루 한 번: 같은 날 판단·매매는 다시 돌려도 중복되지 않는다(상태 파일 기록).

운용 자금: 계좌 추정예탁자산 − I3 외 보유분(현재 SK이노베이션 — 추세추종 데몬이 청산 관리) = I3 자산.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import sys
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any, Protocol

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import i3_core as K  # noqa: E402
import i3_fills as FL  # noqa: E402
import i3_flows as F  # noqa: E402

DATA_DIR = _ROOT / "data" / "i3"
STATE_FILE = DATA_DIR / "state.json"
EVENTS_FILE = DATA_DIR / "events.jsonl"
LOG_DIR = _ROOT / "logs" / "i3"
DECIDE_AFTER = dtime(15, 35)
TRADE_WINDOW = (dtime(8, 30), dtime(9, 20))
MAX_PLAN_AGE_DAYS = 4
CONSISTENCY_TOL = 0.005
BUY_LIMIT_PCT = 0.01      # 매수 지정가 = 현재가 × 1.01 — 즉시 체결되면서 상한가 증거금을 피한다
# 매수 시각 — ETF 유동성공급자(LP)의 호가 의무가 없는 09:00~09:05 를 피한다(호가 공백 시 +1% 상한까지 밀릴 수
# 있다). 시가 체결 자체는 유지: lab_exec_timing(사전선언 c9534b4)에서 '다음 날 종가'(10시 이후의 끝점) −1.2%p,
# '당일 종가' −2.8%p 로 둘 다 비열위 미달 — 매도는 08:50 동시호가(=검증의 시가) 그대로.
BUY_AFTER = dtime(9, 5, 30)
# 매매 단계 시작 때 MCP(계좌 조회)가 응답할 때까지 기다리는 한도 — PC 가 08:20 부팅, 로그온 뒤 워치독이 MCP 를
# 띄운다(10-22 실측: 서버 기동 08:40). 로그온이 늦어도 매매를 건너뛰지 않게 30초 간격으로 이 시각까지 다시 본다.
BROKER_WAIT_UNTIL = dtime(9, 15)
BROKER_WAIT_EVERY = 30.0
PRICE_STEP = 5            # 지정가 올림 단위 — ETF 호가 1원(머니마켓)·5원(KODEX200) 어느 쪽에도 유효
FEE_BUF = 0.001           # 주문가능금액 대비 수수료·반올림 여유

log = logging.getLogger("i3")
_FLOW_ARGS: dict = {}            # --phase flow 인자(main 이 채운다)


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None or not v.strip() else v.strip().lower() in ("1", "true", "yes")


# ── 상태 (원자적 쓰기) ────────────────────────────────────────────────────────
def load_state(path: Path = STATE_FILE) -> dict:
    if not path.exists():
        return {}
    txt = path.read_text(encoding="utf-8")
    d = json.loads(txt)        # 깨졌으면 예외 — 빈 상태로 덮어쓰지 않는다
    if not isinstance(d, dict):
        raise ValueError(f"{path} 형식 오류")
    return d


def save_state(st: dict, path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    st["updated"] = datetime.now().isoformat(timespec="seconds")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    if path.exists():
        os.replace(path, path.with_suffix(".bak"))
    os.replace(tmp, path)


def log_event(event: str, payload: dict, path: Path = EVENTS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), "event": event,
                            "payload": payload}, ensure_ascii=False) + "\n")


# ── 외부 의존 (테스트에서 가짜로 바꾼다) ──────────────────────────────────────
class Market(Protocol):
    async def base_bars(self) -> dict[str, dict]: ...
    async def kospi_bars(self) -> dict[str, dict]: ...
    async def recent(self, code: str) -> dict[str, dict]: ...     # 키움 최근 일봉(날짜 포함)


class Broker(Protocol):
    async def holdings(self) -> list[dict] | None: ...
    async def equity(self) -> tuple[float, float]: ...
    async def price(self, code: str) -> float | None: ...                   # 현재가(장중)
    async def orderable(self, code: str, price: int) -> float | None: ...    # 매수 주문가능금액
    async def place(self, side: str, code: str, qty: int, price: int | None = None) -> Any: ...
    async def executions(self, day: str) -> Any: ...                        # 그날 체결내역 원응답(ka10076)


class Notifier(Protocol):
    async def __call__(self, msg: str, critical: bool = False) -> None: ...


# ── 판단 ─────────────────────────────────────────────────────────────────────
def sleeve_nav(equity: float, holdings: list[dict]) -> float:
    """I3 자산 = 추정예탁자산 − I3 가 아닌 보유분 평가액(현재가)."""
    other = sum(h["qty"] * h["cur"] for h in holdings if h["symbol"] not in (K.BASE, K.CASH))
    return equity - other


def check_consistency(long_hist: dict[str, dict], recent: dict[str, dict], today: str,
                      tol: float = CONSISTENCY_TOL) -> str | None:
    """키움 최근 일봉과 장기 이력이 겹치는 날(오늘 제외 최근 20일) 종가 차이 — 문제면 설명 문자열."""
    common = sorted(d for d in recent if d in long_hist and d < today)[-20:]
    if len(common) < 5:
        return f"겹치는 날이 {len(common)}일뿐 — 데이터 출처 확인 필요"
    worst = max(abs(recent[d]["close"] / long_hist[d]["close"] - 1) for d in common)
    return f"종가 최대 차이 {worst:.2%} > {tol:.1%}" if worst > tol else None


async def phase_decide(market: Market, broker: Broker, notify: Notifier, now: datetime,
                       state_path: Path = STATE_FILE, events_path: Path = EVENTS_FILE,
                       dry_run: bool = True) -> dict:
    today = now.strftime("%Y-%m-%d")
    if now.time() < DECIDE_AFTER:
        return {"skip": f"{DECIDE_AFTER:%H:%M} 이전 — 오늘 일봉이 미완성"}
    long_base, long_kospi = await market.base_bars(), await market.kospi_bars()
    rb, rk = await market.recent(K.BASE), await market.recent("KOSPI")
    if today not in rb or today not in rk:
        log_event("decide_skip", {"reason": "오늘 일봉 없음(휴장·미갱신)"}, events_path)
        # 운용자(10-26): 조용히 건너뛰면 평일 데이터 지연을 모르고 지나간다 — 휴장일엔 정상이라 일반 알림
        await notify(f"ℹ️ [I3] {today} 판단 건너뜀 — 오늘 일봉이 없다. 휴장일이면 정상, 평일이면 데이터 미갱신 확인 "
                     f"필요(이 경우 내일 아침 매매도 없다)")
        return {"skip": "오늘 일봉 없음 — 휴장이거나 데이터 미갱신"}
    for name, lh, rc in (("KODEX200", long_base, rb), ("KOSPI", long_kospi, rk)):
        bad = check_consistency(lh, rc, today)
        if bad:
            await notify(f"⛔ [I3] {name} 데이터 불일치로 판단 중단 — {bad}", critical=True)
            log_event("decide_abort", {"reason": f"{name} {bad}"}, events_path)
            return {"abort": f"{name} {bad}"}
    base = {**long_base, **rb}
    kospi = {**long_kospi, **rk}
    hold = await broker.holdings()
    if hold is None:
        await notify("⛔ [I3] 계좌 조회 실패 — 판단 중단(보유 0 으로 믿지 않는다)", critical=True)
        return {"abort": "계좌 조회 실패"}
    eq, _cash = await broker.equity()
    if eq <= 0:
        await notify("⛔ [I3] 예탁자산 조회 실패 — 판단 중단", critical=True)
        return {"abort": "예탁자산 0"}
    nav = sleeve_nav(eq, hold)

    st = load_state(state_path)
    # 입출금 보정(P1-①, i3_flows): 낙폭 예산은 '성과 지수'(실제 자산 ÷ 좌수)로 본다 — 출금이 손실로 보이지 않게.
    acct = st.get("acct")
    if acct and acct["date"] < today:
        st["acct_prev"] = acct
    acct_base = acct if acct and acct["date"] < today else st.get("acct_prev")
    declared_rows = [f for f in st.get("flows_declared", []) if f.get("applied_on") in (None, today)]
    declared = sum(float(f["amount"]) for f in declared_rows)
    traded_since = bool(acct_base) and st.get("traded_on", "") > acct_base["date"]
    last_trade = st.get("last_trade") or {}
    trades = (last_trade.get("fills") if traded_since and last_trade.get("date", "") > acct_base["date"] else None)
    flow, how, resid = F.detect_flow(acct_base["snap"] if acct_base else None, hold, nav, traded_since, declared,
                                     trades, today)
    idx, units = F.apply_flow(acct_base["index"] if acct_base else None,
                              acct_base["units"] if acct_base else None, nav, flow)
    for f in declared_rows:
        f["applied_on"] = today
    navs = [x for x in st.get("navs", []) if x[0] != today] + [[today, idx]]
    eng = K.engine_state(base, kospi, today)
    if eng.last_date != today:
        return {"abort": f"엔진 마지막 날짜 {eng.last_date} ≠ 오늘"}
    w, need, reason = K.decide(eng, [n for _, n in navs], st.get("w"))
    e = K.budget_exposure([n for _, n in navs])
    rec = {"date": today, "nav": round(nav), "engine_holding": eng.holding, "engine_changed": eng.changed_today,
           "exposure": round(e, 4), "w": round(w, 4), "trade": need, "reason": reason,
           "close": {K.BASE: base[today]["close"], K.CASH: (await market.recent(K.CASH)).get(today, {}).get("close")},
           "index": round(idx, 2), "units": round(units, 10),
           "flow": {"amount": round(flow), "how": how, "resid": round(resid)}}
    st["navs"] = navs[-600:]
    st["acct"] = {"date": today, "snap": F.snapshot(hold, nav, (K.BASE, K.CASH)), "index": idx, "units": units}
    st["last_decision"] = rec
    if need:
        st["w"] = w
        st["pending"] = {"decided_on": today, "w": w, "reason": reason}
    save_state(st, state_path)
    log_event("decide", rec, events_path)
    tag = "🧪 모의" if dry_run else "💰 실전"
    await notify(f"[I3 {tag}] {today} 판단 — 엔진 {'보유' if eng.holding else '이탈'} · 낙폭예산 {e:.0%} → "
                 f"KODEX200 목표 {w:.0%} · {'내일 매매' if need else '매매 없음'} ({reason}) · I3 자산 {nav:,.0f}원")
    if how == "auto-withdrawal":
        await notify(f"⚠️ [I3] 출금으로 보고 자동 보정 — 설명 안 되는 감소 {-resid:,.0f}원(매매 없는 날). "
                     f"낙폭 예산(성과 지수)은 영향 없음. 출금한 적이 없다면 HTS 로 확인 필요", critical=True)
    elif how == "auto-deposit":
        await notify(f"ℹ️ [I3] 입금으로 보고 자동 반영 — +{resid:,.0f}원(입금·I3 밖 종목 매도 대금). 성과 지수 영향 없음. "
                     f"분배금이었다면 알려 달라")
    elif how == "distribution":
        await notify(f"ℹ️ [I3] KODEX200 분배금으로 보고 성과에 포함 — +{resid:,.0f}원")
    return rec


def record_flow(amount: float, memo: str, now: datetime, state_path: Path = STATE_FILE) -> dict:
    """운용자 입출금 기록(+입금 / −출금) — 다음 판단 때 성과 지수에서 뺀다(i3_flows). 매매일에도 반영된다."""
    st = load_state(state_path)
    row = {"date": now.strftime("%Y-%m-%d"), "amount": float(amount), "memo": memo, "applied_on": None}
    st.setdefault("flows_declared", []).append(row)
    save_state(st, state_path)
    return row


# ── 매매 ─────────────────────────────────────────────────────────────────────
def limit_price(cur: float, pct: float = BUY_LIMIT_PCT, step: int = PRICE_STEP) -> int:
    """현재가 → 매수 지정가(step 단위 올림). 현재가보다 위라 즉시 체결된다."""
    return int(math.ceil(cur * (1 + pct) / step) * step)


def affordable(cash: float, limit: int, fee_buf: float = FEE_BUF) -> int:
    """주문가능금액으로 지정가에 살 수 있는 주식수(내림)."""
    return int(cash // (limit * (1 + fee_buf))) if cash > 0 and limit > 0 else 0


def order_status(resp: Any) -> str:
    """'ok' | 'rejected' | 'unknown'. success:true 라도 return_code≠0 이면 거부
    (trend_kiwoom_io._order_accepted 와 같은 규칙 — 8005 유령 포지션 사고)."""
    if isinstance(resp, dict) and resp.get("unknown"):
        return "unknown"
    if not isinstance(resp, dict) or resp.get("success") is False:
        return "rejected"
    d = resp.get("data", resp)
    rc = d.get("return_code") if isinstance(d, dict) else None
    return "ok" if rc in (0, "0", None) else "rejected"


async def phase_trade(broker: Broker, notify: Notifier, now: datetime, prices: dict[str, float],
                      state_path: Path = STATE_FILE, events_path: Path = EVENTS_FILE,
                      dry_run: bool = True, halt: bool = False, wait_after_open=None,
                      before_check=None, fills_path: Path | None = None) -> dict:
    today = now.strftime("%Y-%m-%d")
    in_window = TRADE_WINDOW[0] <= now.time() <= TRADE_WINDOW[1]
    # 아침 알림(운용자 10-26 "1번 2번 다"): 할 일이 없거나 정지 중이어도 예약 시간대엔 한 줄 — 수동 실행엔 울리지 않는다
    if halt:
        if in_window:
            await notify(f"⏸️ [I3] {today} 매매 정지 중(I3_HALT=true) — 주문 안 함. 다시 켜려면 .env 에서 false")
        return {"skip": "I3_HALT=true"}
    if not in_window:
        return {"skip": f"매매 시간대({TRADE_WINDOW[0]:%H:%M}~{TRADE_WINDOW[1]:%H:%M}) 밖"}
    st = load_state(state_path)
    plan = st.get("pending")
    if not plan:
        await notify(f"ℹ️ [I3] {today} 매매 없음 — 대기 중인 판단 없음(전날 판단이 '매매 없음'). 정상")
        return {"skip": "대기 중인 판단 없음"}
    if st.get("traded_on") == today:
        return {"skip": "오늘 이미 매매함"}
    age = (now.date() - datetime.strptime(plan["decided_on"], "%Y-%m-%d").date()).days
    if age > MAX_PLAN_AGE_DAYS or plan["decided_on"] >= today:
        await notify(f"⚠️ [I3] 판단({plan['decided_on']})이 오래됐거나 오늘 것 — 매매 안 함", critical=True)
        st.pop("pending", None)
        save_state(st, state_path)
        return {"skip": "오래된 판단"}
    hold = await broker.holdings()
    if hold is None:
        await notify("⛔ [I3] 계좌 조회 실패 — 매매 중단", critical=True)
        return {"abort": "계좌 조회 실패"}
    eq, _ = await broker.equity()
    nav = sleeve_nav(eq, hold)
    cur = {h["symbol"]: h["qty"] for h in hold if h["symbol"] in (K.BASE, K.CASH)}
    if any(prices.get(c, 0) <= 0 for c in (K.BASE, K.CASH)):
        await notify("⛔ [I3] 기준가 없음 — 매매 중단", critical=True)
        return {"abort": "기준가 없음"}
    tgt = K.target_shares(plan["w"], nav, prices)
    orders = K.order_plan(cur, tgt)
    rec = {"date": today, "w": plan["w"], "nav": round(nav), "current": cur, "target": tgt,
           "orders": orders, "dry_run": dry_run, "results": []}
    if dry_run or not orders:
        rec["note"] = "모의 — 주문 미전송" if dry_run else "주문 필요 없음"
    else:
        sells = [o for o in orders if o[0] == "sell"]
        buys = [o for o in orders if o[0] == "buy"]
        for side, code, qty in sells:                       # 시장가 — 08:50 동시호가, 09:00 체결
            rec["results"].append([side, code, qty, await broker.place(side, code, qty)])
        if buys and wait_after_open is not None:
            await wait_after_open()            # 매수는 09:00 체결 뒤 — 매도 대금 확보 + 현재가로 지정가
        rec["buys"] = {}
        for side, code, planned in buys:
            px = await broker.price(code)
            if not px or px <= 0:
                await notify(f"⛔ [I3] {code} 현재가 조회 실패 — 매수 안 함(추측 주문 금지)", critical=True)
                rec["buys"][code] = {"planned": planned, "skip": "현재가 없음"}
                continue
            lim = limit_price(px)
            cash = await broker.orderable(code, lim)
            if cash is None:
                await notify(f"⛔ [I3] {code} 주문가능금액 조회 실패 — 매수 안 함", critical=True)
                rec["buys"][code] = {"planned": planned, "cur": px, "limit": lim, "skip": "주문가능금액 없음"}
                continue
            qty = min(planned, affordable(cash, lim))
            rec["buys"][code] = {"planned": planned, "qty": qty, "cur": px, "limit": lim, "cash": round(cash)}
            if qty <= 0:
                await notify(f"⚠️ [I3] {code} 살 수 있는 수량 0 — 주문가능 {cash:,.0f}원 · 지정가 {lim:,}원",
                             critical=True)
                continue
            rec["results"].append([side, code, qty, await broker.place(side, code, qty, lim)])
        status = [(s, c, q, order_status(r)) for s, c, q, r in rec["results"]]
        unknown = [x for x in status if x[3] == "unknown"]
        rejected = [x for x in status if x[3] == "rejected"]
        if unknown:
            await notify(f"⚠️ [I3] 응답 불명 주문 {len(unknown)}건 — 재전송 안 함, 잔고로 확인 필요: "
                         + ", ".join(f"{s} {c} {q}주" for s, c, q, _ in unknown), critical=True)
        if rejected:
            await notify(f"⚠️ [I3] 거부된 주문 {len(rejected)}건: "
                         + ", ".join(f"{s} {c} {q}주" for s, c, q, _ in rejected), critical=True)
        # 매매 후 잔고 대조 — 보낸 주문(거부 제외)이 다 체결됐으면 나올 보유와 비교. 재전송은 하지 않는다.
        expect = {c: cur.get(c, 0) for c in (K.BASE, K.CASH)}
        for s, c, q, stt in status:
            if stt != "rejected":
                expect[c] += q if s == "buy" else -q
        if before_check is not None:
            await before_check()
        after = await broker.holdings()
        if after is None:
            await notify("⚠️ [I3] 매매 후 잔고 조회 실패 — HTS 로 확인 필요", critical=True)
        else:
            got = {h["symbol"]: h["qty"] for h in after if h["symbol"] in (K.BASE, K.CASH)}
            diff = {c: (got.get(c, 0), q) for c, q in expect.items() if got.get(c, 0) != q}
            rec["after"] = got
            if diff:
                await notify("⚠️ [I3] 매매 후 잔고가 주문과 다름(미체결·부분체결, 재전송 안 함): "
                             + ", ".join(f"{c} 보유 {g} / 기대 {q}" for c, (g, q) in diff.items()),
                             critical=True)
        # 체결 기록(P1-②, i3_fills) — 실제 체결가 vs 주문 직전 현재가(매수)·판단 종가(매도). 비용 가정 실측용.
        # 조회가 실패해도 매매 결과엔 영향 없다(기록만 '파싱 실패'로 남긴다).
        sent = [(s, c, q, r) for s, c, q, r in rec["results"] if order_status(r) != "rejected"]
        if sent:
            try:
                raw = await broker.executions(today.replace("-", ""))
            except Exception as e:
                log.warning("[FILL] 체결내역 조회 실패: %s", e)
                raw = None
            since = now.strftime("%H%M%S")
            fills = []
            for s, c, q, _r in sent:
                parsed = FL.parse_fills(raw, c, "매수" if s == "buy" else "매도", since) if raw is not None else None
                if s == "buy":
                    b = rec["buys"].get(c, {})
                    fills.append(FL.fill_record(today, s, c, q, "지정가", b.get("limit"), b.get("cur"), parsed))
                else:
                    fills.append(FL.fill_record(today, s, c, q, "시장가", None, prices.get(c), parsed))
            rec["fills"] = fills
            fp = fills_path or state_path.parent / "fills.jsonl"
            fp.parent.mkdir(parents=True, exist_ok=True)
            with fp.open("a", encoding="utf-8") as f:
                for x in fills:
                    f.write(json.dumps(x, ensure_ascii=False) + "\n")
    st["traded_on"] = today
    st.pop("pending", None)
    st["last_trade"] = {k: v for k, v in rec.items() if k != "results"} | {
        "results": [[s, c, q, order_status(r)] for s, c, q, r in rec["results"]]}
    save_state(st, state_path)
    log_event("trade", st["last_trade"], events_path)
    tag = "🧪 모의" if dry_run else "💰 실전"
    if dry_run or not orders:
        lines = " · ".join(f"{'매도' if s == 'sell' else '매수'} {c} {q}주" for s, c, q in orders) or "주문 없음"
    else:
        lines = " · ".join(
            f"{'매도' if s == 'sell' else '매수'} {c} {q}주"
            + (f"(지정가 {rec['buys'][c]['limit']:,})" if s == "buy" else "(시장가)") + f" {order_status(r)}"
            for s, c, q, r in rec["results"]) or "주문 없음"
    filled = [f"{x['code']} {x['fill_qty']}주 @{x['fill_price']:,.0f}"
              + (f"({x['slippage_bp']:+.1f}bp)" if x.get("slippage_bp") is not None else "")
              for x in rec.get("fills", []) if x.get("fill_price")]
    await notify(f"[I3 {tag}] {today} 매매 — 목표 KODEX200 {plan['w']:.0%} · {lines}"
                 + (f" · 체결 {', '.join(filled)}" if filled else ""))
    return rec


# ── 실제 연결 ────────────────────────────────────────────────────────────────
class KiwoomMarket:
    """장기 이력은 FDR(검증과 같은 출처), 최근·오늘 일봉은 키움(날짜 포함·당일 반영)."""

    async def base_bars(self):
        import strategy_lab as L
        return L.load_bars(K.BASE, "2014-01-01", (datetime.now()).strftime("%Y-%m-%d"))

    async def kospi_bars(self):
        import strategy_lab as L
        return L.load_bars("^KS11", "1996-01-01", (datetime.now()).strftime("%Y-%m-%d"))

    async def recent(self, code: str):
        from trend_config import MARKET_URL
        from trend_kiwoom_io import _kiwoom_call, _num
        if code == "KOSPI":
            d = await _kiwoom_call("kiwoom-market-mcp", MARKET_URL, "sector_daily_chart",
                                   {"sector_code": "001", "limit": 150})
            rows, scale = d.get("inds_dt_pole_qry") or [], 100.0
        else:
            d = await _kiwoom_call("kiwoom-market-mcp", MARKET_URL, "get_daily_chart",
                                   {"stock_code": code, "limit": 150})
            rows, scale = d.get("stk_dt_pole_chart_qry") or [], 1.0
        out = {}
        for r in rows:
            dt = str(r.get("dt", ""))
            c = _num(r, "cur_prc", abs_val=True) / scale
            o = _num(r, "open_pric", abs_val=True) / scale or c
            if len(dt) == 8 and c > 0:      # 고가·저가도 담는다(리그 변동성돌파가 같은 함수를 쓴다 — 판단은 시가·종가만 본다)
                out[f"{dt[:4]}-{dt[4:6]}-{dt[6:]}"] = {
                    "open": o, "close": c,
                    "high": (_num(r, "high_pric", abs_val=True) / scale) or max(o, c),
                    "low": (_num(r, "low_pric", abs_val=True) / scale) or min(o, c)}
        return out


class KiwoomBroker:
    async def holdings(self):
        from trend_kiwoom_io import _broker_holdings_checked
        return await _broker_holdings_checked()

    async def equity(self):
        from trend_kiwoom_io import _account_equity
        return await _account_equity()

    async def price(self, code):
        from trend_config import MARKET_URL
        from trend_kiwoom_io import _kiwoom_call, _num
        d = await _kiwoom_call("kiwoom-market-mcp", MARKET_URL, "basic_info", {"stock_code": code})
        return _num(d, "cur_prc", abs_val=True) or None

    async def orderable(self, code, price):
        """kt00010 주문가능금액(ord_alowa). 응답이 이상하면 None — 0 으로 믿지 않는다."""
        from trend_config import TRADING_URL
        from trend_kiwoom_io import _kiwoom_call, _num
        d = await _kiwoom_call("trading-domain", TRADING_URL, "orderable_amount",
                               {"stock_code": code, "trade_type": "buy", "price": price})
        if str(d.get("return_code")) != "0" or "ord_alowa" not in d:
            return None
        return _num(d, "ord_alowa")

    async def place(self, side, code, qty, price=None):
        """주문 1회 — price 가 있으면 지정가(01), 없으면 시장가(03). **재전송하지 않는다**: 예외·타임아웃은
        접수 여부 불명({"unknown": True})으로 돌려 잔고 대조에 맡긴다(trend_kiwoom_io._place 와 같은 원칙)."""
        from src.claude_agents.base.mcp_client import MCPManager
        from trend_config import ACCOUNT_NO, TRADING_URL
        tool = "place_buy_order" if side == "buy" else "place_sell_order"
        args = {"stock_code": code, "quantity": qty, "price": price,
                "order_type": "01" if price else "03", "account_no": ACCOUNT_NO}
        try:
            async with MCPManager({"trading-domain": TRADING_URL}) as mcp:
                raw = await asyncio.wait_for(mcp.call_tool(tool, args), timeout=10.0)
            return json.loads(raw) if isinstance(raw, str) else raw
        except Exception as e:
            log.error("[ORDER] %s %s %d주 응답 불명(재전송 안 함): %s", side, code, qty, e)
            return {"success": False, "unknown": True, "error": f"주문 응답 불명: {e}"}

    async def executions(self, day):
        """그날 체결내역 원응답(ka10076) — 체결가 기록용. 실패는 호출자가 '파싱 실패'로 남긴다."""
        from src.claude_agents.base.mcp_client import MCPManager
        from trend_config import ACCOUNT_NO, TRADING_URL
        async with MCPManager({"trading-domain": TRADING_URL}) as mcp:
            return await asyncio.wait_for(mcp.call_tool("get_order_executions",
                                                        {"account_no": ACCOUNT_NO, "start_date": day,
                                                         "end_date": day}), timeout=10.0)


async def _notify(msg: str, critical: bool = False) -> None:
    from trend_runtime import notify
    await notify(msg, critical=critical)


def _setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    h = logging.FileHandler(LOG_DIR / "i3_live.log", encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)


async def wait_broker_ready(broker: Broker, deadline: datetime, sleep=asyncio.sleep, clock=datetime.now,
                            every: float = BROKER_WAIT_EVERY) -> bool:
    """계좌 조회가 될 때까지(None 이 아닐 때까지) every 초 간격으로 deadline 까지 기다린다. 못 되면 False —
    그 뒤 phase_trade 가 '계좌 조회 실패 — 매매 중단' critical 로 멈춘다(추측으로 주문하지 않는다)."""
    while True:
        try:
            if await broker.holdings() is not None:
                return True
        except Exception as e:
            log.warning("[TRADE] 계좌 조회 대기 중 예외: %s", e)
        if clock() >= deadline:
            return False
        log.info("[TRADE] MCP/계좌 조회 아직 안 됨 — %.0f초 뒤 다시(한도 %s)", every, deadline.strftime("%H:%M"))
        await sleep(every)


async def _main(phase: str) -> int:
    if phase == "status":
        print(json.dumps(load_state(), ensure_ascii=False, indent=2))
        return 0
    if phase == "flow":
        if _FLOW_ARGS.get("amount") is None:
            print("사용법: python scripts/i3_live.py --phase flow --amount <+입금|-출금 원> [--memo 메모]")
            return 2
        row = record_flow(_FLOW_ARGS["amount"], _FLOW_ARGS.get("memo", ""), datetime.now())
        print(json.dumps({"기록": row, "안내": "다음 판단(15:50) 때 성과 지수에서 뺀다"}, ensure_ascii=False))
        return 0
    try:
        return await _run_phase(phase)
    except Exception as e:                      # 조용히 끝나면 '판단 없음'을 아무도 모른다
        log.exception("[%s] 예외", phase)
        await _notify(f"⛔ [I3] {phase} 단계 예외 — {type(e).__name__}: {str(e)[:150]}", critical=True)
        return 1


async def _run_phase(phase: str) -> int:
    dry = _env_bool("I3_DRY_RUN", True)
    halt = _env_bool("I3_HALT", False)
    now = datetime.now()
    if phase == "decide":
        res = await phase_decide(KiwoomMarket(), KiwoomBroker(), _notify, now, dry_run=dry)
    else:
        st = load_state()
        close = (st.get("last_decision") or {}).get("close") or {}
        prices = {c: float(close.get(c) or 0) for c in (K.BASE, K.CASH)}

        async def wait_until(t: dtime):
            secs = (datetime.combine(now.date(), t) - datetime.now()).total_seconds()
            if secs > 0:
                await asyncio.sleep(secs)

        async def wait_buy():
            await wait_until(BUY_AFTER)        # 매도 대금 확보 + LP 호가 의무 시간에 현재가로 지정가

        async def settle():
            await wait_until(dtime(9, 0, 30))  # 동시호가 매도는 09:00 에 체결 — 그 전엔 대조하지 않는다
            await asyncio.sleep(15)

        broker = KiwoomBroker()
        if not halt and st.get("pending") and st.get("traded_on") != now.strftime("%Y-%m-%d") \
                and TRADE_WINDOW[0] <= now.time() <= TRADE_WINDOW[1]:
            await wait_broker_ready(broker, datetime.combine(now.date(), BROKER_WAIT_UNTIL))
        res = await phase_trade(broker, _notify, now, prices, dry_run=dry, halt=halt,
                                wait_after_open=wait_buy, before_check=settle)
    log.info("[%s] %s", phase, json.dumps(res, ensure_ascii=False, default=str)[:500])
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=["decide", "trade", "status", "flow"])
    ap.add_argument("--amount", type=float, help="flow: +입금 / -출금 (원)")
    ap.add_argument("--memo", default="", help="flow: 메모")
    args = ap.parse_args()
    _FLOW_ARGS.update(amount=args.amount, memo=args.memo)
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    _setup_logging()
    return asyncio.run(_main(args.phase))


if __name__ == "__main__":
    raise SystemExit(main())
