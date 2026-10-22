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
- 하루 한 번: 같은 날 판단·매매는 다시 돌려도 중복되지 않는다(상태 파일 기록).

운용 자금: 계좌 추정예탁자산 − I3 외 보유분(현재 SK이노베이션 — 추세추종 데몬이 청산 관리) = I3 자산.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
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

DATA_DIR = _ROOT / "data" / "i3"
STATE_FILE = DATA_DIR / "state.json"
EVENTS_FILE = DATA_DIR / "events.jsonl"
LOG_DIR = _ROOT / "logs" / "i3"
DECIDE_AFTER = dtime(15, 35)
TRADE_WINDOW = (dtime(8, 30), dtime(9, 20))
MAX_PLAN_AGE_DAYS = 4
CONSISTENCY_TOL = 0.005

log = logging.getLogger("i3")


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
    async def place(self, side: str, code: str, qty: int) -> Any: ...


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
    navs = [x for x in st.get("navs", []) if x[0] != today] + [[today, nav]]
    eng = K.engine_state(base, kospi, today)
    if eng.last_date != today:
        return {"abort": f"엔진 마지막 날짜 {eng.last_date} ≠ 오늘"}
    w, need, reason = K.decide(eng, [n for _, n in navs], st.get("w"))
    e = K.budget_exposure([n for _, n in navs])
    rec = {"date": today, "nav": round(nav), "engine_holding": eng.holding, "engine_changed": eng.changed_today,
           "exposure": round(e, 4), "w": round(w, 4), "trade": need, "reason": reason,
           "close": {K.BASE: base[today]["close"], K.CASH: (await market.recent(K.CASH)).get(today, {}).get("close")}}
    st["navs"] = navs[-600:]
    st["last_decision"] = rec
    if need:
        st["w"] = w
        st["pending"] = {"decided_on": today, "w": w, "reason": reason}
    save_state(st, state_path)
    log_event("decide", rec, events_path)
    tag = "🧪 모의" if dry_run else "💰 실전"
    await notify(f"[I3 {tag}] {today} 판단 — 엔진 {'보유' if eng.holding else '이탈'} · 낙폭예산 {e:.0%} → "
                 f"KODEX200 목표 {w:.0%} · {'내일 매매' if need else '매매 없음'} ({reason}) · I3 자산 {nav:,.0f}원")
    return rec


# ── 매매 ─────────────────────────────────────────────────────────────────────
async def phase_trade(broker: Broker, notify: Notifier, now: datetime, prices: dict[str, float],
                      state_path: Path = STATE_FILE, events_path: Path = EVENTS_FILE,
                      dry_run: bool = True, halt: bool = False, wait_after_open=None,
                      before_check=None) -> dict:
    today = now.strftime("%Y-%m-%d")
    if halt:
        return {"skip": "I3_HALT=true"}
    if not (TRADE_WINDOW[0] <= now.time() <= TRADE_WINDOW[1]):
        return {"skip": f"매매 시간대({TRADE_WINDOW[0]:%H:%M}~{TRADE_WINDOW[1]:%H:%M}) 밖"}
    st = load_state(state_path)
    plan = st.get("pending")
    if not plan:
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
        for side, code, qty in sells:
            rec["results"].append([side, code, qty, await broker.place(side, code, qty)])
        if buys and sells and wait_after_open is not None:
            await wait_after_open()            # 09:00 체결 뒤에 매수(매도 대금 확보)
        for side, code, qty in buys:
            rec["results"].append([side, code, qty, await broker.place(side, code, qty)])
        unknown = [r for r in rec["results"] if isinstance(r[3], dict) and r[3].get("unknown")]
        rejected = [r for r in rec["results"] if isinstance(r[3], dict) and r[3].get("success") is False
                    and not r[3].get("unknown")]
        if unknown:
            await notify(f"⚠️ [I3] 응답 불명 주문 {len(unknown)}건 — 재전송 안 함, 잔고로 확인 필요: "
                         + ", ".join(f"{s} {c} {q}주" for s, c, q, _ in unknown), critical=True)
        if rejected:
            await notify(f"⚠️ [I3] 거부된 주문 {len(rejected)}건: "
                         + ", ".join(f"{s} {c} {q}주" for s, c, q, _ in rejected), critical=True)
        # 매매 후 잔고 대조 — 응답 불명·부분체결을 여기서 잡는다(재전송은 하지 않는다)
        if before_check is not None:
            await before_check()
        after = await broker.holdings()
        if after is None:
            await notify("⚠️ [I3] 매매 후 잔고 조회 실패 — HTS 로 확인 필요", critical=True)
        else:
            got = {h["symbol"]: h["qty"] for h in after if h["symbol"] in (K.BASE, K.CASH)}
            diff = {c: (got.get(c, 0), q) for c, q in tgt.items() if got.get(c, 0) != q}
            rec["after"] = got
            if diff:
                await notify("⚠️ [I3] 매매 후 잔고가 목표와 다름(재전송 안 함): "
                             + ", ".join(f"{c} 보유 {g} / 목표 {q}" for c, (g, q) in diff.items()),
                             critical=True)
    st["traded_on"] = today
    st.pop("pending", None)
    st["last_trade"] = {k: v for k, v in rec.items() if k != "results"} | {
        "results": [[s, c, q, "unknown" if isinstance(r, dict) and r.get("unknown") else
                     ("rejected" if isinstance(r, dict) and r.get("success") is False else "ok")]
                    for s, c, q, r in rec["results"]]}
    save_state(st, state_path)
    log_event("trade", st["last_trade"], events_path)
    tag = "🧪 모의" if dry_run else "💰 실전"
    lines = " · ".join(f"{'매도' if s == 'sell' else '매수'} {c} {q}주" for s, c, q in orders) or "주문 없음"
    await notify(f"[I3 {tag}] {today} 매매 — 목표 KODEX200 {plan['w']:.0%} · {lines}")
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
            if len(dt) == 8 and c > 0:
                out[f"{dt[:4]}-{dt[4:6]}-{dt[6:]}"] = {"open": o, "close": c}
        return out


class KiwoomBroker:
    async def holdings(self):
        from trend_kiwoom_io import _broker_holdings_checked
        return await _broker_holdings_checked()

    async def equity(self):
        from trend_kiwoom_io import _account_equity
        return await _account_equity()

    async def place(self, side, code, qty):
        from src.claude_agents.base.mcp_client import MCPManager
        from trend_config import TRADING_URL
        from trend_kiwoom_io import _place
        async with MCPManager({"trading-domain": TRADING_URL}) as mcp:
            return await _place(mcp, side, code, qty)


async def _notify(msg: str, critical: bool = False) -> None:
    from trend_runtime import notify
    await notify(msg, critical=critical)


def _setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    h = logging.FileHandler(LOG_DIR / "i3_live.log", encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)


async def _main(phase: str) -> int:
    if phase == "status":
        print(json.dumps(load_state(), ensure_ascii=False, indent=2))
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

        async def wait_open():
            target = datetime.combine(now.date(), dtime(9, 0, 30))
            secs = (target - datetime.now()).total_seconds()
            if secs > 0:
                await asyncio.sleep(secs)
        async def wait_settle():
            await wait_open()
            await asyncio.sleep(5)

        async def settle():
            await wait_open()                  # 동시호가 매도는 09:00 에 체결 — 그 전엔 대조하지 않는다
            await asyncio.sleep(15)

        res = await phase_trade(KiwoomBroker(), _notify, now, prices, dry_run=dry, halt=halt,
                                wait_after_open=wait_settle, before_check=settle)
    log.info("[%s] %s", phase, json.dumps(res, ensure_ascii=False, default=str)[:500])
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=["decide", "trade", "status"])
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    _setup_logging()
    return asyncio.run(_main(args.phase))


if __name__ == "__main__":
    raise SystemExit(main())
