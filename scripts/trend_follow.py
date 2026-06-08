"""대형주 추세추종 자동매매 (MOCK 라이브 데몬) — 종가매매와 별개 트랙.

블로그(ppassong) 추세추종/모멘텀(차수재시실 + 손익비 1:3). 검증된 모드: largecap·watchlist(기본).
trend_mcp.signals(순수함수) + closing_bet_mcp(exit_rules ATR) 재사용. 종가매매 코드 무수정.

스케줄(블로그 일일 루틴): 08:50 스크리닝 → 09:30 진입 → 장중 트레일/목표(폴링) → 15:20 청산판단.
매매일지(journal.jsonl) 자동 기록 + 대시보드(:8091, scripts/trend_dashboard.py)에서 열람.

사용:
  python scripts/trend_follow.py --daemon
  python scripts/trend_follow.py --phase screen|entry|intraday|exit
  python scripts/trend_follow.py --status
  python scripts/trend_follow.py --journal-note <id> --psych "..." --mistake "..." --improve "..."
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.Handler.handleError = lambda self, record: None  # noqa: E731
for _n in ("pykrx", "pykrx.website", "FinanceDataReader", "requests", "urllib3", "httpx"):
    logging.getLogger(_n).setLevel(logging.ERROR)
logging.getLogger().setLevel(logging.WARNING)


def _load_env() -> None:
    env = _ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_env()

import contextlib as _ctx, io as _io  # noqa: E402
with _ctx.redirect_stdout(_io.StringIO()):
    from pykrx import stock as krx  # noqa: E402
del _ctx, _io

from src.claude_agents.base.mcp_client import MCPManager  # noqa: E402
from src.mcp_servers.closing_bet_mcp.exit_rules import ratchet_stop  # noqa: E402
from src.mcp_servers.trend_mcp.signals import TrendConfig, entry_signal, atr, moving_average  # noqa: E402

# ─── 설정 ──────────────────────────────────────────────────────────────────
ACCOUNT_NO = os.getenv("KIWOOM_ACCOUNT_NO", "")
MOCK_MODE = os.getenv("MOCK_MODE", "true").lower() == "true"
TRADING_URL = "http://localhost:8030/mcp/"
MARKET_URL  = "http://localhost:8031/mcp/"
INVESTOR_URL = "http://localhost:8033/mcp/"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

UNIVERSE_MODE = os.getenv("TREND_UNIVERSE", "watchlist")   # 기본 watchlist (검증 최고)
WATCHLIST = [c.strip() for c in os.getenv("TREND_WATCHLIST", "005930,000660").split(",") if c.strip()]
TOP_N = int(os.getenv("TREND_TOP_N", "0") or (30 if UNIVERSE_MODE == "gainers" else 100))
MIN_VALUE_KRW = float(os.getenv("TREND_MIN_VALUE_KRW", "100000000000"))
MAX_POS = int(os.getenv("TREND_MAX_POS", "5"))
INVEST_PER_TRADE = float(os.getenv("TREND_INVEST_PER_TRADE", "500000"))
USE_FOREIGN_EXIT = os.getenv("TREND_USE_FOREIGN_EXIT", "true").lower() == "true"
NEWS_VETO = os.getenv("TREND_NEWS_VETO", "true").lower() == "true"
INTRADAY_POLL_MIN = int(os.getenv("TREND_INTRADAY_POLL_MIN", "10"))
TAX_BPS = float(os.getenv("CLOSING_BET_TAX_BPS", "18.0"))
FEE_BPS = float(os.getenv("CLOSING_BET_FEE_BPS", "1.5"))
SLIPPAGE_BPS = float(os.getenv("CLOSING_BET_SLIPPAGE_BPS", "10.0"))
ROUNDTRIP_COST_PCT = (TAX_BPS + 2 * FEE_BPS + 2 * SLIPPAGE_BPS) / 100.0
FORCE_PHASE = os.getenv("TREND_FORCE_PHASE", "false").lower() == "true"

CFG = TrendConfig(
    mode=("largecap" if UNIVERSE_MODE in ("largecap", "watchlist") else "gainers"),
    stop_pct=float(os.getenv("TREND_STOP_PCT", "7")),
    atr_k=float(os.getenv("TREND_ATR_K", "2.0")),
    rr=float(os.getenv("TREND_RR", "3.0")),
    partial_pct=float(os.getenv("TREND_PARTIAL_PCT", "30")),
)

DATA_DIR = _ROOT / "data" / "trend_follow"
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "state.json"
LOCK_FILE = DATA_DIR / "daemon.lock"
JOURNAL_FILE = DATA_DIR / "journal.jsonl"
LOG_DIR = _ROOT / "logs" / "trend_follow"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "trend_follow.log"

_fh = TimedRotatingFileHandler(LOG_FILE, when="midnight", interval=1, backupCount=30, encoding="utf-8")
_fh.suffix = "%Y-%m-%d"
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout), _fh])
logger = logging.getLogger("trend")

SCHEDULE = [(8, 50, "screen"), (9, 30, "entry"), (15, 20, "exit")]


# ─── 알림/상태/락 ──────────────────────────────────────────────────────────
async def notify(msg: str) -> None:
    logger.info("[NOTIFY] %s", msg[:200].replace("\n", " "))
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            await c.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                         json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"})
    except Exception as e:
        logger.warning("[TELEGRAM] %s", e)


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(key: str, content: Any) -> None:
    st = load_state()
    st[key] = content
    st["last_updated"] = datetime.now().isoformat()
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def get_state(key: str, default=None) -> Any:
    return load_state().get(key, default)


def _pid_alive(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        try:
            os.kill(pid, 0); return True
        except OSError:
            return False
        except Exception:
            return True


def acquire_lock() -> bool:
    if LOCK_FILE.exists():
        try:
            old = int(LOCK_FILE.read_text().strip() or "0")
        except Exception:
            old = 0
        if old and old != os.getpid() and _pid_alive(old):
            logger.error("[LOCK] 이미 실행 중 (PID=%d)", old)
            return False
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def release_lock() -> None:
    try:
        if LOCK_FILE.exists() and LOCK_FILE.read_text().strip() == str(os.getpid()):
            LOCK_FILE.unlink()
    except Exception:
        pass


def log_event(event: str, payload: dict) -> None:
    day = DATA_DIR / datetime.now().strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    with (day / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"),
                            "event": event, "payload": payload}, ensure_ascii=False) + "\n")


# ─── 매매일지 ──────────────────────────────────────────────────────────────
def journal_append(rec: dict) -> None:
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), **rec}
    with JOURNAL_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def journal_note(jid: str, psych: str = "", mistake: str = "", improve: str = "") -> None:
    """매매일지 항목에 심리/실수/개선 메모 추가 (대시보드/ CLI)."""
    journal_append({"type": "note", "id": jid,
                    "psych": psych, "mistake": mistake, "improve": improve})
    print(f"매매일지 메모 추가: id={jid}")


# ─── pykrx / MCP 데이터 ────────────────────────────────────────────────────
def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y%m%d")


def _suppress():
    import contextlib, io
    return contextlib.redirect_stdout(io.StringIO())


def get_ohlcv(symbol: str, days: int = 320) -> list[dict]:
    try:
        with _suppress():
            df = krx.get_market_ohlcv_by_date(_days_ago(days + 60), _today(), symbol)
        if df.empty:
            return []
        out = []
        for d, row in df.tail(days).iterrows():
            out.append({"date": d.strftime("%Y-%m-%d"), "open": float(row.get("시가", 0)),
                        "high": float(row.get("고가", 0)), "low": float(row.get("저가", 0)),
                        "close": float(row.get("종가", 0)), "volume": float(row.get("거래량", 0)),
                        "value": float(row.get("거래대금", 0))})
        return out
    except Exception as e:
        logger.debug("[OHLCV] %s %s", symbol, e)
        return []


def get_kospi_closes(days: int = 320) -> list[float]:
    try:
        with _suppress():
            df = krx.get_index_ohlcv_by_date(_days_ago(days + 60), _today(), "1001")
        return [float(c) for c in df["종가"].tail(days).values]
    except Exception:
        try:
            import FinanceDataReader as fdr
            df = fdr.DataReader("^KS11", _days_ago(days + 60), _today())
            return [float(c) for c in df["Close"].tail(days).values]
        except Exception:
            return []


def get_universe() -> list[tuple[str, str]]:
    """모드별 유니버스 [(code, name)]."""
    if UNIVERSE_MODE == "watchlist":
        return [(c, _name(c)) for c in WATCHLIST]
    # 거래대금/등락률 상위는 pykrx 전종목에서
    for off in range(8):
        try:
            date = (datetime.now() - timedelta(days=off)).strftime("%Y%m%d")
            with _suppress():
                df = krx.get_market_ohlcv_by_ticker(date, market="KOSPI")
            if df.empty:
                continue
            df = df[df["거래대금"] >= MIN_VALUE_KRW]
            if UNIVERSE_MODE == "gainers" and "등락률" in df.columns:
                df = df.sort_values("등락률", ascending=False)
            else:  # largecap — 거래대금 상위 근사(시총 캐시 없을 때)
                df = df.sort_values("거래대금", ascending=False)
            codes = list(df.head(TOP_N).index)
            return [(c, _name(c)) for c in codes]
        except Exception:
            continue
    return [(c, _name(c)) for c in WATCHLIST]


def _name(code: str) -> str:
    try:
        return krx.get_market_ticker_name(code)
    except Exception:
        return code


# ─── MCP 주문/시세/수급 ────────────────────────────────────────────────────
def _order_accepted(parsed: Any) -> tuple[bool, str]:
    if not isinstance(parsed, dict):
        return False, "형식오류"
    if parsed.get("success") is False:
        return False, str(parsed.get("error", "실패"))
    d = parsed.get("data", parsed)
    rc = d.get("return_code") if isinstance(d, dict) else None
    if rc in (0, "0", None):
        return True, ""
    return False, f"rc={rc} {str(d.get('return_msg',''))[:80]}"


async def _realtime_price(symbol: str) -> float | None:
    for key, url in [("kiwoom-market-mcp", MARKET_URL), ("trading-domain", TRADING_URL)]:
        try:
            async with MCPManager({key: url}) as mcp:
                if not mcp.tools:
                    continue
                tool = next((t["name"] for t in mcp.tools
                             if any(k in t["name"].lower() for k in ("basic_info", "current_price", "quote"))), None)
                if not tool:
                    continue
                raw = await mcp.call_tool(tool, {"stock_code": symbol})
                p = json.loads(raw) if isinstance(raw, str) else raw
                d = p.get("data", p) if isinstance(p, dict) else {}
                for k in ("cur_prc", "current_price", "현재가", "stck_prpr", "price", "close"):
                    v = d.get(k) if isinstance(d, dict) else None
                    if v:
                        return float(str(v).lstrip("+-").replace(",", ""))
        except Exception:
            continue
    return None


async def _foreign_net_5d(symbol: str) -> float | None:
    try:
        async with MCPManager({"investor-domain": INVESTOR_URL}) as mcp:
            tool = next((t["name"] for t in (mcp.tools or [])
                         if any(k in t["name"].lower() for k in ("foreign", "investor", "trading"))), None)
            if not tool:
                return None
            raw = await mcp.call_tool(tool, {"stock_code": symbol})
            p = json.loads(raw) if isinstance(raw, str) else raw
            d = p.get("data", p) if isinstance(p, dict) else {}
            v = d.get("foreign_net_5d") or d.get("외국인_5일_순매수") if isinstance(d, dict) else None
            return float(v) if v is not None else None
    except Exception:
        return None


async def _place(mcp, side: str, symbol: str, qty: int) -> Any:
    tool = "place_buy_order" if side == "buy" else "place_sell_order"
    raw = await mcp.call_tool(tool, {"stock_code": symbol, "quantity": qty,
                                     "price": None, "order_type": "03", "account_no": ACCOUNT_NO})
    return json.loads(raw) if isinstance(raw, str) else raw


# ─── Phase: 스크리닝 ────────────────────────────────────────────────────────
async def phase_screen() -> list[dict]:
    logger.info("=" * 56); logger.info("[SCREEN] %s  모드=%s", datetime.now().strftime("%H:%M:%S"), UNIVERSE_MODE)
    log_event("phase_start", {"phase": "screen", "mode": UNIVERSE_MODE})
    kospi = get_kospi_closes()
    universe = get_universe()
    held = {p["symbol"] for p in get_state("positions", [])}
    cands: list[dict] = []
    for code, name in universe:
        if code in held:
            continue
        ohlcv = get_ohlcv(code)
        if not ohlcv:
            continue
        foreign, inst = None, None
        sig = entry_signal(ohlcv, kospi, CFG, foreign, inst)
        if sig.passed:
            cands.append({"symbol": code, "name": name, "score": sig.score,
                          "price": ohlcv[-1]["close"], "stop": sig.stop, "target": sig.target,
                          "atr": round(atr(ohlcv, CFG.atr_period), 2), "gates": sig.gates,
                          "breakdown": sig.breakdown})
            logger.info("[SCREEN] ✓ %s %-10s 점수%.1f 손절%.0f 목표%.0f", code, name[:10], sig.score, sig.stop, sig.target)
        else:
            logger.debug("[SCREEN] %s %s — %s", code, name, sig.reason)
    cands.sort(key=lambda x: -x["score"])
    save_state("candidates", cands)
    log_event("screen_done", {"universe": len(universe), "candidates": len(cands),
                              "symbols": [c["symbol"] for c in cands]})
    lines = [f"🔭 추세추종 스크리닝 [{datetime.now().strftime('%m/%d %H:%M')}] 모드:{UNIVERSE_MODE}"]
    lines += [f"• {c['name']}({c['symbol']}) 점수{c['score']} 손절{c['stop']:,.0f} 목표{c['target']:,.0f}" for c in cands[:8]] or ["진입 후보 없음"]
    await notify("\n".join(lines))
    return cands


# ─── Phase: 진입 ────────────────────────────────────────────────────────────
def _phase_done_today(label: str) -> bool:
    if FORCE_PHASE:
        return False
    today = datetime.now().strftime("%Y-%m-%d")
    return label in (get_state("done", {}).get(today) or [])


def _mark_done(label: str) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    done = {today: list(set((get_state("done", {}).get(today) or []) + [label]))}
    save_state("done", done)


async def phase_entry() -> None:
    logger.info("=" * 56); logger.info("[ENTRY] %s", datetime.now().strftime("%H:%M:%S"))
    log_event("phase_start", {"phase": "entry"})
    if _phase_done_today("entry"):
        logger.warning("[ENTRY] 오늘 이미 실행 — 중복 방지")
        return
    cands = get_state("candidates", [])
    positions = get_state("positions", [])
    slots = MAX_POS - len(positions)
    if not cands or slots <= 0:
        await notify(f"ℹ️ 추세추종 진입: 후보 {len(cands)} 슬롯 {slots} — 진입 없음")
        return
    mode_tag = "🧪 MOCK" if MOCK_MODE else "💰 REAL"
    bought = []
    try:
        async with MCPManager({"trading-domain": TRADING_URL}) as mcp:
            if not mcp.tools:
                await notify("❌ trading-domain 연결 실패")
                return
            for c in cands[:slots]:
                price = await _realtime_price(c["symbol"]) or c["price"]
                qty = max(1, int(INVEST_PER_TRADE / price))
                resp = await _place(mcp, "buy", c["symbol"], qty)
                ok, why = _order_accepted(resp)
                if not ok:
                    logger.error("[REJECT] entry %s — %s", c["symbol"], why)
                    log_event("order_reject", {"phase": "entry", "symbol": c["symbol"], "why": why, "raw": resp})
                    await notify(f"❌ 진입 거부 {c['name']}({c['symbol']}) — {why}")
                    continue
                # 실체결가 추정 (없으면 직전가)
                d = resp.get("data", {}) if isinstance(resp, dict) else {}
                fill = d.get("cntr_pric") or d.get("체결가")
                entry = float(str(fill).lstrip("+-").replace(",", "")) if fill else price
                stop = c["stop"]
                target = c["target"]
                jid = uuid.uuid4().hex[:8]
                pos = {"symbol": c["symbol"], "name": c["name"], "mode": UNIVERSE_MODE, "qty": qty,
                       "entry_price": entry, "stop_price": stop, "target": target, "peak_price": entry,
                       "atr": c["atr"], "score": c["score"], "buy_date": datetime.now().strftime("%Y-%m-%d"),
                       "partial_done": False, "journal_id": jid}
                positions.append(pos)
                bought.append(pos)
                journal_append({"type": "entry", "id": jid, "symbol": c["symbol"], "name": c["name"],
                                "mode": UNIVERSE_MODE, "qty": qty, "entry_price": entry, "stop": stop,
                                "target": target, "score": c["score"], "rationale": c.get("gates"),
                                "breakdown": c.get("breakdown")})
                log_event("entry", {"symbol": c["symbol"], "qty": qty, "entry": entry, "stop": stop, "target": target})
                logger.info("[ENTRY] %s %-10s %d주 @%.0f 손절%.0f 목표%.0f %s",
                            c["symbol"], c["name"][:10], qty, entry, stop, target, mode_tag)
    except Exception as e:
        logger.error("[ENTRY] %s", e); await notify(f"❌ 진입 오류: {e}"); return
    save_state("positions", positions)
    if bought:
        _mark_done("entry")
        await notify(f"✅ 추세추종 진입 {mode_tag}\n" +
                     "\n".join(f"• {p['name']}({p['symbol']}) {p['qty']}주 @{p['entry_price']:,.0f} 손절{p['stop_price']:,.0f}" for p in bought))


# ─── 포지션 관리 공통 (트레일/목표/청산) ──────────────────────────────────────
async def _manage(do_exit_signals: bool, when: str) -> None:
    positions = get_state("positions", [])
    if not positions:
        return
    remaining = []
    closed = []
    try:
        async with MCPManager({"trading-domain": TRADING_URL}) as mcp:
            if not mcp.tools:
                logger.warning("[%s] trading-domain 연결 실패", when); return
            for pos in positions:
                sym, entry, qty = pos["symbol"], pos["entry_price"], int(pos["qty"])
                cur = await _realtime_price(sym) or entry
                a = float(pos.get("atr", 0) or 0)
                peak, stop = ratchet_stop(entry, pos.get("peak_price", entry), pos.get("stop_price", 0), cur, a, CFG.atr_k, -CFG.stop_pct)
                pos["peak_price"], pos["stop_price"] = round(peak, 2), round(stop, 2)
                action, reason, sell_qty = None, "", 0
                # 첫 목표 → 30% 부분익절
                if not pos.get("partial_done") and cur >= pos["target"]:
                    sell_qty = max(1, int(qty * CFG.partial_pct / 100))
                    action, reason = "PARTIAL", f"첫 목표 도달 {CFG.partial_pct:.0f}% 익절"
                # 트레일/손절 이탈
                elif cur <= stop:
                    sell_qty, action, reason = qty, "EXIT", f"트레일/손절 이탈 stop {stop:,.0f}"
                elif do_exit_signals:
                    ohlcv = get_ohlcv(sym, 80)
                    ma50 = moving_average([b["close"] for b in ohlcv] + [cur], CFG.ma_support) if ohlcv else None
                    foreign = await _foreign_net_5d(sym) if USE_FOREIGN_EXIT else None
                    if ma50 is not None and cur < ma50:
                        sell_qty, action, reason = qty, "EXIT", f"MA50 이평선 하방돌파 ({cur:,.0f}<{ma50:,.0f})"
                    elif USE_FOREIGN_EXIT and foreign is not None and foreign < 0:
                        sell_qty, action, reason = qty, "EXIT", "외국인 5일 순매도 전환"
                if not action:
                    remaining.append(pos); continue
                resp = await _place(mcp, "sell", sym, sell_qty)
                ok, why = _order_accepted(resp)
                if not ok:
                    logger.error("[REJECT] %s %s — %s", when, sym, why)
                    log_event("order_reject", {"phase": when, "symbol": sym, "why": why, "raw": resp})
                    remaining.append(pos); continue
                pnl_pct = round((cur - entry) / entry * 100, 2)
                if action == "PARTIAL":
                    pos["partial_done"] = True; pos["qty"] = qty - sell_qty
                    remaining.append(pos)
                    journal_append({"type": "partial", "id": pos["journal_id"], "symbol": sym, "qty": sell_qty,
                                    "price": cur, "pnl_pct": pnl_pct, "reason": reason})
                    log_event("partial", {"symbol": sym, "qty": sell_qty, "price": cur, "pnl_pct": pnl_pct})
                    await notify(f"📈 부분익절 {pos['name']}({sym}) {sell_qty}주 @{cur:,.0f} ({pnl_pct:+.2f}%)")
                else:
                    hold_days = (datetime.now() - datetime.strptime(pos["buy_date"], "%Y-%m-%d")).days
                    net = round(pnl_pct - ROUNDTRIP_COST_PCT, 2)
                    rr_real = round((cur - entry) / (entry - pos["stop_price"]), 2) if entry > pos["stop_price"] else None
                    closed.append((pos, cur, net, reason))
                    journal_append({"type": "exit", "id": pos["journal_id"], "symbol": sym, "name": pos["name"],
                                    "qty": sell_qty, "entry_price": entry, "exit_price": cur, "pnl_pct": pnl_pct,
                                    "net_pct": net, "pnl_amount": round((cur - entry) * sell_qty), "rr_realized": rr_real,
                                    "reason": reason, "hold_days": hold_days})
                    log_event("exit", {"symbol": sym, "exit": cur, "net_pct": net, "reason": reason})
    except Exception as e:
        logger.error("[%s] %s", when, e); return
    save_state("positions", remaining)
    if closed:
        await notify(f"📤 추세추종 청산 [{datetime.now().strftime('%m/%d %H:%M')}]\n" +
                     "\n".join(f"{'🟢' if n>0 else '🔴'} {p['name']}({p['symbol']}) net{n:+.2f}% — {r}" for p, c, n, r in closed))


async def phase_intraday() -> None:
    log_event("phase_start", {"phase": "intraday"})
    await _manage(do_exit_signals=False, when="intraday")


async def phase_exit() -> None:
    logger.info("=" * 56); logger.info("[EXIT] %s", datetime.now().strftime("%H:%M:%S"))
    log_event("phase_start", {"phase": "exit"})
    await _manage(do_exit_signals=True, when="exit")


# ─── 데몬 ──────────────────────────────────────────────────────────────────
def _is_weekday(dt: datetime) -> bool:
    return dt.weekday() < 5


def _is_market_hours(dt: datetime) -> bool:
    if not _is_weekday(dt):
        return False
    m = dt.hour * 60 + dt.minute
    return 9 * 60 <= m <= 15 * 60 + 20


def _next_run(h: int, m: int) -> datetime:
    now = datetime.now()
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if now >= t:
        t += timedelta(days=1)
    while not _is_weekday(t):
        t += timedelta(days=1)
    return t


async def scheduler_daemon() -> None:
    logger.info("=" * 56)
    logger.info("[DAEMON] 추세추종 시작 | 모드=%s | MOCK=%s | 08:50 스크린/09:30 진입/장중 트레일/15:20 청산",
                UNIVERSE_MODE, MOCK_MODE)
    if not acquire_lock():
        await notify("⚠️ 추세추종 데몬 중복 기동 차단"); return
    await notify(f"🚀 추세추종 데몬 시작 ({'🧪 MOCK' if MOCK_MODE else '💰 REAL'}) 모드:{UNIVERSE_MODE}")
    funcs = {"screen": phase_screen, "entry": phase_entry, "exit": phase_exit}
    while True:
        now = datetime.now()
        if not _is_weekday(now):
            await asyncio.sleep(1800); continue
        items = sorted([(_next_run(h, m), p) for h, m, p in SCHEDULE], key=lambda x: x[0])
        nxt, phase = items[0]
        wait = (nxt - now).total_seconds()
        logger.info("[DAEMON] 다음: %s @ %s (%.0f분)", phase, nxt.strftime("%m/%d %H:%M"), wait / 60)
        while wait > 0:
            cap = INTRADAY_POLL_MIN * 60 if (get_state("positions") and _is_market_hours(datetime.now())) else 1800
            await asyncio.sleep(min(wait, cap)); wait -= min(wait, cap)
            if get_state("positions") and _is_market_hours(datetime.now()) and datetime.now() < nxt:
                try:
                    await phase_intraday()
                except Exception as e:
                    logger.error("[DAEMON] intraday %s", e)
        if _is_weekday(datetime.now()):
            try:
                await funcs[phase]()
            except Exception as e:
                logger.error("[DAEMON] %s %s", phase, e, exc_info=True)
                await notify(f"❌ {phase} 오류: {e}")


def print_status() -> None:
    st = load_state()
    print(f"\n=== 추세추종 상태 [{st.get('last_updated','?')[:16]}] 모드:{UNIVERSE_MODE} ===")
    pos = st.get("positions", [])
    print(f"보유 {len(pos)}종목:")
    for p in pos:
        print(f"  • {p['name']}({p['symbol']}) {p['qty']}주 @{p['entry_price']:,.0f} 손절{p['stop_price']:,.0f} 목표{p['target']:,.0f} {'(부분익절)' if p.get('partial_done') else ''}")
    print(f"매매일지: {JOURNAL_FILE}")


# ─── 진입점 ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--phase", choices=["screen", "entry", "intraday", "exit"])
    g.add_argument("--daemon", action="store_true")
    g.add_argument("--status", action="store_true")
    g.add_argument("--journal-note", metavar="ID")
    ap.add_argument("--psych", default=""); ap.add_argument("--mistake", default=""); ap.add_argument("--improve", default="")
    args = ap.parse_args()

    if args.status:
        print_status()
    elif args.journal_note:
        journal_note(args.journal_note, args.psych, args.mistake, args.improve)
    elif args.daemon:
        try:
            asyncio.run(scheduler_daemon())
        except KeyboardInterrupt:
            logger.info("[DAEMON] 종료")
        finally:
            release_lock()
    else:
        asyncio.run({"screen": phase_screen, "entry": phase_entry,
                     "intraday": phase_intraday, "exit": phase_exit}[args.phase]())
