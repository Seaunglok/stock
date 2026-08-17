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
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))   # scripts/ → trend 패키지 import 가능

from trend_config import (                  # noqa: E402  env·상수·logger·CFG·paths·SCHEDULE
    # 스타 임포트였다(2026-08-17 전환). 상수 47개가 출처 없는 전역으로 들어와 "이 값이 어디서
    # 오는가"를 추적할 수 없었고, `_ROOT`/`logger` 는 밑줄이라 스타에 안 실려 두 번째 import 를
    # 하는 숨은 순서 의존까지 있었다. 실거래 파라미터를 읽는 코드에서 출처 불명은 그 자체가 위험.
    ACCOUNT_NO, ADOPT_MODE, BREADTH_MIN_PCT, CFG, DAILY_LOSS_LIMIT_PCT, DATA_DIR,
    ENTRY_CUTOFF, ENTRY_TIME, ENTRY_WAIT_FALLING, ENV_LOADED, EXIT_MA, FORCE_PHASE,
    FOREIGN_TREND_MA, FUND_BONUS, HARD_STOP_PCT, HEARTBEAT_FILE, HEARTBEAT_INTERVAL_SEC,
    INTRADAY_POLL_MIN,
    INVEST_PER_TRADE, JOURNAL_FILE, MAX_HOLD_DAYS, MAX_NOTIONAL_PCT, MAX_POS, MOCK_MODE,
    POSITION_PCT, PREMARKET_GAPDOWN_VETO, PRODUCTION_MODE, PYRAMID_ADDS, PYRAMID_BYPASS_GATE,
    PYRAMID_LOOKBACK, PYRAMID_MIN_NET, PYRAMID_STEP_R, REGIME_MA, RISK_PCT,
    ROUNDTRIP_COST_PCT, SCHEDULE, SECTOR_BONUS, SECTOR_BREADTH, SECTOR_GATE, SECTOR_MIN_AVG,
    SECTOR_TOP_K, SIZING_MODE, TRADING_URL, UNIVERSE_MODE, USE_FOREIGN_EXIT, WATCHLIST,
    _ROOT, logger, setup_daemon_runtime,
)
from trend_kiwoom_io import (               # noqa: E402
    _account_equity, _broker_holdings, _cur_and_open, _foreign_net_5d,
    _is_unknown, _order_accepted, _place, _premarket_snapshot, _realtime_price, _sector_index_rows,
    get_universe, kospi_closes as _kospi_closes,
)
from shadow_ledger import record as shadow_record  # noqa: E402  차단 후보 사후추적(원장 기록)
from trend_journal import write_daily_journal      # noqa: E402  일별 매매일지 md(보고 계층)
from trend_runtime import (                        # noqa: E402  알림·상태·락·이벤트(인프라 계층)
    StateCorrupted, acquire_lock, get_state, journal_append, journal_note, load_state,
    log_event, notify, release_lock, save_state,
)
from src.mcp_servers.trend_mcp.market_data import get_ohlcv  # noqa: E402

from src.claude_agents.base.mcp_client import MCPManager  # noqa: E402
from src.mcp_servers.closing_bet_mcp.exit_rules import ratchet_stop  # noqa: E402
from src.mcp_servers.trend_mcp.signals import (  # noqa: E402
    entry_signal, atr, levels, moving_average, classify_zone,
    fundamentals_bonus, leading_sectors, market_breadth, position_size, exit_decision, is_rising,
)

# 설정·상수·CFG·paths·logger·SCHEDULE 는 trend_config 로 이동 (import * 로 노출)


async def phase_reconcile() -> None:
    """계좌 보유분 중 데몬 미추적분을 추세 청산규칙 관리 대상으로 편입(adopt).

    트레일 stop 은 '현재가' 기준으로 새로 잡아 편입 즉시 손절을 방지한다(편입 시점부터 추적).
    손익(entry_price)은 실제 평단 기준. 이후 _manage 가 MA50이탈/트레일/외인전환 시 처분.

    ADOPT_MODE 제어 (실전 안전): all=전체 편입(기본·MOCK용), watchlist=WATCHLIST 만, off=편입 안 함.
    실전에선 HTS 수동매수/장기보유분이 trend 청산룰로 강제처분되지 않도록 off/watchlist 권장.
    """
    log_event("phase_start", {"phase": "reconcile", "adopt_mode": ADOPT_MODE})
    if ADOPT_MODE == "off":
        logger.info("[RECONCILE] ADOPT_MODE=off — broker 보유분 편입 생략")
        return
    holdings = await _broker_holdings()
    if not holdings:
        return
    if ADOPT_MODE == "watchlist":
        before = len(holdings)
        holdings = [h for h in holdings if h["symbol"] in WATCHLIST]
        logger.info("[RECONCILE] ADOPT_MODE=watchlist — %d→%d종 (WATCHLIST: %s)",
                    before, len(holdings), ",".join(WATCHLIST))
    positions = get_state("positions", [])
    held = {p["symbol"] for p in positions}
    adopted = []
    for h in holdings:
        if h["symbol"] in held:
            continue
        cur = h["cur"] or h["avg"]
        entry = h["avg"] or cur
        if cur <= 0 or entry <= 0:
            continue
        ohlcv = get_ohlcv(h["symbol"])
        a = round(atr(ohlcv, CFG.atr_period), 2) if ohlcv else round(cur * 0.02, 2)
        # 손절은 '현재가' 기준(편입 즉시 손절 방지 — 편입 시점부터 추적), 목표는 '평단' 기준 1:3.
        stop, target = levels(entry, CFG, atr_value=a, stop_ref=cur)
        jid = uuid.uuid4().hex[:8]
        # 이미 목표가(평단 기준 3R) 위에서 편입되는 장기보유 승자는 partial_done=True —
        # 편입 직후 30% 즉시 매도 방지(편입 취지는 트레일 관리, 신규 진입이 아님).
        pos = {"symbol": h["symbol"], "name": h["name"], "mode": "adopted", "qty": h["qty"],
               "entry_price": entry, "stop_price": stop, "target": target,
               "peak_price": max(cur, entry), "atr": a, "score": 0,
               "buy_date": datetime.now().strftime("%Y-%m-%d"),
               "partial_done": bool(cur >= target), "journal_id": jid}
        _pyramid_init(pos, entry, e_stop)   # 편입분도 평단·평단기준 1R 로 불타기 추적
        positions.append(pos)
        adopted.append(pos)
        journal_append({"type": "entry", "id": jid, "symbol": h["symbol"], "name": h["name"],
                        "mode": "adopted", "qty": h["qty"], "entry_price": entry, "stop": stop,
                        "target": target, "score": 0, "rationale": {"adopted": True}})
        log_event("reconcile_adopt", {"symbol": h["symbol"], "qty": h["qty"], "entry": entry, "stop": stop})
        logger.info("[RECONCILE] 편입 %s %-10s %d주 평단%.0f 트레일stop%.0f",
                    h["symbol"], h["name"][:10], h["qty"], entry, stop)
    if adopted:
        save_state("positions", positions)
        await notify("📥 계좌 보유분 추세관리 편입 (MA50이탈/트레일/외인 시 처분)\n" +
                     "\n".join(f"• <b>{p['name']}</b>({p['symbol']}) {p['qty']}주 평단{p['entry_price']:,.0f} 트레일{p['stop_price']:,.0f}"
                               for p in adopted))


async def _size_qty(price: float, stop: float = 0.0) -> int:
    """가격(+손절가) → 매수 수량. signals.position_size(순수) + 예탁자산 조회.

    risk 모드는 손절폭(price−stop)으로 수량을 정하므로 stop 을 넘겨야 한다(없으면 notional 폴백).
    """
    equity, cash = (await _account_equity()) if SIZING_MODE in ("pct_equity", "risk") else (0.0, 0.0)
    if SIZING_MODE in ("pct_equity", "risk") and equity <= 0:
        logger.warning("[SIZE] 예탁자산 조회 실패 → 고정금액 폴백")
    return position_size(price, mode=SIZING_MODE, equity=equity, cash=cash,
                         pct=POSITION_PCT, invest_fixed=INVEST_PER_TRADE,
                         stop=stop, risk_pct=RISK_PCT, max_notional_pct=MAX_NOTIONAL_PCT)


FUND_CACHE_DIR = _ROOT / "docs_cache" / "dart_fin"   # DART 재무 YoY 30일 캐시


def _fundamentals_yoy(symbol: str) -> dict | None:
    """DART 최신 사업보고서의 매출·영업이익 YoY(%) — finstate 당기/전기 비교.

    30일 디스크 캐시(재무는 분기 단위 갱신). DART_API_KEY 없음/조회 실패 시 None(가점 생략, veto 아님).
    """
    if not os.getenv("DART_API_KEY"):
        return None
    cache = FUND_CACHE_DIR / f"{symbol}.json"
    if cache.exists():
        try:
            d = json.loads(cache.read_text(encoding="utf-8"))
            if (datetime.now() - datetime.fromisoformat(d["cached"])).days < 30:
                return d["yoy"]
        except Exception:
            pass
    try:
        import OpenDartReader
        dart = OpenDartReader(os.getenv("DART_API_KEY"))
        df = None
        for year in (datetime.now().year - 1, datetime.now().year - 2):
            df = dart.finstate(symbol, year)
            if df is not None and not df.empty:
                break
        if df is None or df.empty:
            return None
        fs = df[df["fs_div"] == "CFS"]          # 연결 우선, 없으면 개별
        if fs.empty:
            fs = df[df["fs_div"] == "OFS"]

        def _yoy(names: list[str]) -> float | None:
            for nm in names:
                row = fs[fs["account_nm"] == nm]
                if row.empty:
                    continue
                try:
                    cur = float(str(row.iloc[0]["thstrm_amount"]).replace(",", ""))
                    prv = float(str(row.iloc[0]["frmtrm_amount"]).replace(",", ""))
                except Exception:
                    continue
                if prv:
                    return round((cur - prv) / abs(prv) * 100, 1)
            return None

        yoy = {"revenue_yoy": _yoy(["매출액", "수익(매출액)", "영업수익"]),
               "op_income_yoy": _yoy(["영업이익", "영업이익(손실)"])}
        FUND_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"cached": datetime.now().isoformat(), "yoy": yoy},
                                    ensure_ascii=False), encoding="utf-8")
        return yoy
    except Exception as e:
        logger.debug("[FUND] %s YoY 조회 실패: %s", symbol, str(e)[:80])
        return None


def _sector_map() -> dict[str, str]:
    """KOSPI 종목→업종 매핑 (fdr StockListing, 일별 캐시 → Kiwoom universe 캐시 폴백)."""
    cache_path = DATA_DIR / f"_sector_map_{datetime.now().strftime('%Y%m%d')}.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        import FinanceDataReader as fdr
        df = fdr.StockListing("KOSPI")
        if not df.empty:
            sector_col = next((c for c in ["Sector", "업종", "Industry"] if c in df.columns), None)
            code_col = next((c for c in ["Symbol", "Code", "종목코드"] if c in df.columns), None)
            if sector_col and code_col:
                result = {str(row[code_col]): str(row[sector_col]) for _, row in df.iterrows() if row.get(code_col)}
                cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                return result
    except Exception as e:
        logger.debug("[SECTOR] fdr 업종 맵 실패 → Kiwoom 캐시: %s", e)
    try:
        cache_files = sorted(_ROOT.glob("docs_cache/universe_kiwoom_*.json"), reverse=True)
        if cache_files:
            data = json.loads(cache_files[0].read_text(encoding="utf-8"))
            result = {r["code"]: r.get("sector", "기타") for r in data if r.get("code")}
            cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            return result
    except Exception as e2:
        logger.warning("[SECTOR] Kiwoom 캐시도 실패: %s — 주도섹터 비활성", e2)
    return {}


# ─── Phase: 스크리닝 ────────────────────────────────────────────────────────
async def phase_screen() -> list[dict]:
    logger.info("=" * 56); logger.info("[SCREEN] %s  모드=%s", datetime.now().strftime("%H:%M:%S"), UNIVERSE_MODE)
    log_event("phase_start", {"phase": "screen", "mode": UNIVERSE_MODE})
    kospi = await _kospi_closes()
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
            cl = [b["close"] for b in ohlcv]
            zone = classify_zone(cl[-1], moving_average(cl, 60), moving_average(cl, 120))
            cands.append({"symbol": code, "name": name, "score": sig.score,
                          "price": ohlcv[-1]["close"], "stop": sig.stop, "target": sig.target,
                          "atr": round(atr(ohlcv, CFG.atr_period), 2), "gates": sig.gates,
                          "breakdown": sig.breakdown, "zone": zone})
            logger.info("[SCREEN] ✓ %s %-10s 점수%.1f [%s] 손절%.0f 목표%.0f", code, name[:10], sig.score, zone, sig.stop, sig.target)
        else:
            logger.debug("[SCREEN] %s %s — %s", code, name, sig.reason)
    cands.sort(key=lambda x: -x["score"])
    # 프리장(장전 동시호가) 정보 부착 — 후보에만(표시용). 검증 게이트/점수엔 미반영.
    vetoed = []
    for c in list(cands):
        pm = await _premarket_snapshot(c["symbol"])
        if not pm:
            continue
        c["premarket"] = pm
        if PREMARKET_GAPDOWN_VETO > 0 and pm["gap_pct"] < -PREMARKET_GAPDOWN_VETO:
            cands.remove(c)
            vetoed.append((c["symbol"], c["name"], pm["gap_pct"]))
            logger.info("[SCREEN] ✗ %s %s 프리장 갭다운 %.1f%% → 제외", c["symbol"], c["name"][:10], pm["gap_pct"])
    if vetoed:
        log_event("premarket_veto", {"symbols": vetoed})
    # 실적(재무) 자동 가점 — 후보 한정(차수재시실 '실적'). 게이트 미변경, 순위만 반영.
    if FUND_BONUS > 0:
        for c in cands:
            yoy = _fundamentals_yoy(c["symbol"])
            if not yoy:
                continue
            pts, det = fundamentals_bonus(yoy.get("revenue_yoy"), yoy.get("op_income_yoy"), FUND_BONUS)
            c["fundamental"] = {**det, "bonus": pts}
            if pts > 0:
                c["score"] = round(c["score"] + pts, 1)
        cands.sort(key=lambda x: -x["score"])
    save_state("candidates", cands)
    # 날짜 스탬프 — screen 실패 시 phase_entry 가 전일 후보를 매수하는 사고 방지(당일분만 유효)
    save_state("candidates_date", datetime.now().strftime("%Y-%m-%d"))
    log_event("screen_done", {"universe": len(universe), "candidates": len(cands),
                              "symbols": [c["symbol"] for c in cands]})

    def _scr_line(c: dict) -> str:
        z = f"[{c['zone']}] " if c.get("zone") else ""
        s = f"• {z}{c['name']}({c['symbol']}) 점수{c['score']} 손절{c['stop']:,.0f} 목표{c['target']:,.0f}"
        pm = c.get("premarket")
        if pm:
            s += f"\n   프리장 예상 {pm['exp_price']:,.0f} ({pm['gap_pct']:+.1f}%) 예상량 {pm['exp_qty']:,.0f}"
        f = c.get("fundamental")
        if f and f.get("bonus", 0) > 0:
            s += f"\n   실적 YoY 매출{f['revenue_yoy']:+.1f}% 영업{f['op_income_yoy']:+.1f}% (+{f['bonus']:g}점)"
        return s
    lines = [f"🔭 추세추종 스크리닝 [{datetime.now().strftime('%m/%d %H:%M')}] 모드:{UNIVERSE_MODE}"]
    lines += [_scr_line(c) for c in cands[:8]] or ["진입 후보 없음"]
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


def _save_pending(items: list[dict]) -> None:
    """보류 후보 저장 + 날짜 스탬프 — 데몬 재기동 시 전일 보류분을 익일 오전에 매수하는 사고 방지."""
    save_state("pending_entries", items)
    save_state("pending_date", datetime.now().strftime("%Y-%m-%d"))


def _busdays_since(buy_date: str | None) -> int | None:
    """buy_date 이후 경과 영업일 수(주말 제외 근사 — 공휴일 미반영). 시간청산(MAX_HOLD_DAYS) 판정용.

    파싱 실패 시 **None**(판정 불가). 과거엔 0 을 돌려줘 MAX_HOLD 시간청산이 그 종목에 대해
    영원히 발동하지 않았다 — 무기한 보유가 조용히 성립한다.
    """
    try:
        d0 = datetime.strptime(str(buy_date), "%Y-%m-%d").date()
    except Exception:
        logger.warning("[HOLD] buy_date 파싱 실패(%r) — 보유기간 판정 불가", buy_date)
        return None
    d1 = datetime.now().date()
    return sum(1 for i in range(1, (d1 - d0).days + 1)
               if (d0 + timedelta(days=i)).weekday() < 5)


async def _circuit_broken() -> tuple[bool, str]:
    """일일 최대손실 서킷브레이커 — 당일 실현손실(net)이 예탁자산의 DAILY_LOSS_LIMIT_PCT% 초과 시 (True, 사유).

    신규 진입만 차단(보유분 청산은 계속). DAILY_LOSS_LIMIT_PCT=0 이면 off.
    """
    if DAILY_LOSS_LIMIT_PCT <= 0 or not JOURNAL_FILE.exists():
        return False, ""
    today = datetime.now().strftime("%Y-%m-%d")
    realized = 0.0
    try:
        for line in JOURNAL_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("type") == "exit" and str(r.get("ts", "")).startswith(today):
                realized += r.get("entry_price", 0) * r.get("qty", 0) * r.get("net_pct", 0) / 100.0
    except Exception as e:
        # fail-CLOSED: 당일 손실을 알 수 없으면 서킷이 이미 발동했을 수도 있다.
        # 과거엔 (False,"") 를 돌려줘, 일지가 안 읽히는 순간 서킷이 조용히 무력화됐다.
        logger.error("[CIRCUIT] 매매일지 판독 실패 — 신규 진입 차단(안전측): %s", e)
        return True, f"일일손실 판정 불가(매매일지 판독 실패: {str(e)[:60]})"
    if realized >= 0:
        return False, ""
    equity, _ = await _account_equity()
    if equity <= 0:
        return False, ""
    limit = equity * DAILY_LOSS_LIMIT_PCT / 100.0
    if -realized >= limit:
        return True, f"당일 실현손실 {realized:,.0f}원 ≥ 한도 {limit:,.0f}원({DAILY_LOSS_LIMIT_PCT:g}%)"
    return False, ""


def _pyramid_gate_open() -> tuple[bool, float, int]:
    """equity-curve 레짐 게이트(검증=backtest --pyramidequity) — 최근 PYRAMID_LOOKBACK 청산거래
    net 평균 > PYRAMID_MIN_NET 이면 (True, 평균, 표본수). 이력 부족 시 닫힘(보수).

    "전략이 최근 통할 때만 승자에 불타기" — 횡보장(전략 cold) 증폭손실 차단.
    """
    if PYRAMID_ADDS <= 0:
        return False, 0.0, 0
    if PYRAMID_BYPASS_GATE:                      # MOCK 파일럿용 강제 OPEN — 횡보장 증폭위험 인지 전제
        return True, 0.0, 0
    if not JOURNAL_FILE.exists():
        return False, 0.0, 0
    nets: list[float] = []
    try:
        for line in JOURNAL_FILE.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("type") == "exit" and r.get("net_pct") is not None:
                nets.append(float(r["net_pct"]))
    except Exception:
        return False, 0.0, 0
    recent = nets[-PYRAMID_LOOKBACK:]
    if len(recent) < max(3, PYRAMID_LOOKBACK // 2):    # 이력 부족 → 게이트 닫힘
        return False, 0.0, len(recent)
    avg = sum(recent) / len(recent)
    return avg > PYRAMID_MIN_NET, avg, len(recent)


def _pyramid_init(pos: dict, entry: float, stop: float) -> None:
    """피라미딩 활성 시 포지션에 추가매수 추적 필드 부여. R=초기 손절폭(고정). 부분익절은 끔(불타기와 상충)."""
    if PYRAMID_ADDS <= 0:
        return
    pos["pyramid"] = True
    pos["pyr_base"] = round(entry, 2)        # 추가 트리거 기준(초기 진입가, 고정)
    pos["pyr_R"] = round(entry - stop, 2)    # 초기 1R(고정) — 트레일과 무관
    pos["adds_done"] = 0
    pos["partial_done"] = True               # 부분익절 off (검증: 불타기는 부분익절 없이 트레일)


async def _verify_buy_fills(bought: list[dict], positions: list[dict]) -> tuple[list[dict], list[dict]]:
    """매수 phase 직후 broker 잔고와 대조 — 부분/미체결 감지 시 state qty 보정.

    물타기 금지(1종목 1진입) 전제하에, 신규 매수 종목의 broker 보유수량 = pos.qty 여야 정상.
    broker < state: 부분체결 → state qty 축소(보유분만 추적). broker = 0: 미체결 → state 제거.
    호출 직후 호가/체결 지연을 고려해 짧게 대기. paper 모드는 즉시체결로 보통 정상.
    """
    if not bought:
        return bought, positions
    await asyncio.sleep(2.0)   # 체결 동기화 짧은 대기
    try:
        held = await _broker_holdings()
    except Exception as e:
        # 검증 스킵은 '미체결분이 실포지션으로 등록된 채 남는' 결과가 된다 — 조용히 넘기면 안 된다.
        # state 는 그대로 두되(팔 것도 없는데 지우면 실보유를 놓친다) 사람이 볼 수 있게 알린다.
        logger.error("[VERIFY] broker 조회 실패 — 체결 검증 불가: %s", e)
        log_event("fill_unverified", {"symbols": [p["symbol"] for p in bought], "why": str(e)[:120]})
        await notify("⚠️ <b>체결 검증 불가</b> — broker 잔고 조회 실패\n"
                     + "\n".join(f"• {p['name']}({p['symbol']}) {p['qty']}주" for p in bought)
                     + "\n→ HTS 로 실보유 수량 대조 권장", critical=True)
        return bought, positions
    held_map = {h["symbol"]: h["qty"] for h in held}
    fixed_bought, removed, partial = [], [], []
    for p in bought:
        actual = held_map.get(p["symbol"], 0)
        if actual <= 0:
            removed.append(p)
            log_event("fill_missing", {"symbol": p["symbol"], "requested_qty": p["qty"]})
            logger.error("[VERIFY] %s %s 미체결(broker 보유 0) — state 제거", p["symbol"], p["name"])
            continue
        if actual < p["qty"]:
            partial.append((p, p["qty"], actual))
            log_event("fill_partial", {"symbol": p["symbol"], "requested_qty": p["qty"], "filled_qty": actual})
            logger.warning("[VERIFY] %s %s 부분체결 %d/%d → state 조정", p["symbol"], p["name"], actual, p["qty"])
            p["qty"] = actual
        fixed_bought.append(p)
    if removed:
        rm_syms = {p["symbol"] for p in removed}
        positions = [pp for pp in positions if pp["symbol"] not in rm_syms]
        await notify("⚠️ 미체결 감지 — 진입 취소\n" +
                     "\n".join(f"• {p['name']}({p['symbol']}) 요청{p['qty']}주 → broker 0" for p in removed))
    if partial:
        await notify("⚠️ 부분체결 감지 — state 축소\n" +
                     "\n".join(f"• {p['name']}({p['symbol']}) {req}→{act}주" for p, req, act in partial))
    return fixed_bought, positions


async def _confirm_unknown_buy(sym: str, want_qty: int) -> tuple[float, float]:
    """응답 불명 매수의 실제 체결 여부를 broker 잔고로 확인 → (체결수량, 평단).

    재전송 대신 쓰는 회수 경로다. 물타기 금지(1종목 1진입)라 이 종목의 broker 보유분은
    이번 주문 말고 나올 데가 없다 — 이미 state 에 있으면 애초에 여기 오지 않는다.
    조회 실패 시 (0,0) = 미체결로 간주(보수적: 유령 포지션을 만들지 않는다).
    """
    await asyncio.sleep(2.0)          # 체결 반영 대기
    for attempt in range(2):
        try:
            for h in await _broker_holdings():
                if h["symbol"] == sym and h["qty"] > 0:
                    return float(min(h["qty"], want_qty)), float(h.get("avg") or 0)
            return 0.0, 0.0
        except Exception as e:
            logger.warning("[ORDER] %s 잔고 확인 실패 %d/2: %s", sym, attempt + 1, e)
            await asyncio.sleep(2.0)
    log_event("fill_unverified", {"symbol": sym, "qty": want_qty})
    await notify(f"🚨 <b>체결 확인 불가</b> {sym} {want_qty}주 — 주문 응답도 잔고 조회도 실패\n"
                 f"→ HTS 로 보유 여부 직접 확인 필요(미추적 보유 가능성)", critical=True)
    return 0.0, 0.0


async def _buy_one(mcp, c: dict, mode_tag: str) -> dict | None:
    """후보 1종 매수 → return_code 게이트 → pos/journal/log. 성공 시 pos, 거부/실패 시 None."""
    sym = c["symbol"]
    # 물타기 금지(PDF 절대원칙 #1) — 이미 보유 종목엔 재진입 안 함(1종목 1진입)
    if any(p["symbol"] == sym for p in get_state("positions", [])):
        logger.warning("[ENTRY] %s 이미 보유 — 물타기 금지(1종목 1진입) 스킵", sym)
        shadow_record("already_held", [c])
        return None
    price = await _realtime_price(sym) or c["price"]
    # risk 사이징용 손절가는 사이징 시점 가격 기준으로 추정(체결 후 entry 기준 재계산은 아래에서).
    size_stop, _ = levels(price, CFG, atr_value=float(c["atr"]))
    qty = await _size_qty(price, size_stop)
    if qty < 1:
        logger.warning("[ENTRY] %s 현금 부족/수량 0 — 스킵 (price %.0f)", sym, price)
        shadow_record("size_zero", [c], {"price": round(price), "stop": round(size_stop)})
        return None
    resp = await _place(mcp, "buy", sym, qty)
    ok, why = _order_accepted(resp)
    adopted_qty = adopted_entry = 0.0
    if not ok and _is_unknown(resp):
        # 접수 여부 불명 — 재전송하면 이중 체결이므로, **잔고로 사실을 확인**한다.
        # 체결됐는데 state 에 없으면 손절·트레일이 안 걸리는 미추적 보유가 된다(ADOPT_MODE=off 면
        # reconcile 도 안 줍는다). 여기서 확인해 편입하는 게 유일한 회수 경로다.
        adopted_qty, adopted_entry = await _confirm_unknown_buy(sym, qty)
        if adopted_qty > 0:
            ok, qty, price = True, int(adopted_qty), adopted_entry or price
            logger.warning("[ORDER] %s 응답 불명이었으나 잔고 확인 결과 %d주 체결 — 편입", sym, qty)
        else:
            logger.error("[ORDER] %s 응답 불명 + 잔고 미확인 — 미체결로 간주", sym)
    if not ok:
        tag = "불명" if _is_unknown(resp) else "거부"
        logger.error("[REJECT] entry %s — %s (%s)", sym, why, tag)
        log_event("order_reject", {"phase": "entry", "symbol": sym, "why": why,
                                   "unknown": _is_unknown(resp), "raw": resp})
        shadow_record("order_reject", [c], {"why": why})
        await notify(f"❌ 진입 {tag} {c['name']}({sym}) — {why}",
                     critical=_is_unknown(resp))
        return None
    d = resp.get("data", {}) if isinstance(resp, dict) else {}
    fill = d.get("cntr_pric") or d.get("체결가")
    entry = adopted_entry or (float(str(fill).lstrip("+-").replace(",", "")) if fill else price)
    # 손절/목표는 '실제 체결가' 기준 재계산 — 손익비 1:3 보존(백테스트와 동일).
    stop, target = levels(entry, CFG, atr_value=float(c["atr"]))
    jid = uuid.uuid4().hex[:8]
    pos = {"symbol": sym, "name": c["name"], "mode": UNIVERSE_MODE, "qty": qty,
           "entry_price": entry, "stop_price": stop, "target": target, "peak_price": entry,
           "atr": c["atr"], "score": c["score"], "buy_date": datetime.now().strftime("%Y-%m-%d"),
           "partial_done": False, "journal_id": jid,
           "sector": c.get("sector"), "sector_lead": c.get("sector_lead", False)}
    _pyramid_init(pos, entry, stop)
    journal_append({"type": "entry", "id": jid, "symbol": sym, "name": c["name"],
                    "mode": UNIVERSE_MODE, "qty": qty, "entry_price": entry, "stop": stop,
                    "target": target, "score": c["score"], "rationale": c.get("gates"),
                    "breakdown": c.get("breakdown"), "premarket": c.get("premarket"),
                    "fundamental": c.get("fundamental"), "sector": c.get("sector"),
                    "sector_lead": c.get("sector_lead", False)})
    log_event("entry", {"symbol": sym, "qty": qty, "entry": entry, "stop": stop, "target": target})
    # 대조군 — 차단분과 **같은 잣대**로 재야 게이트 판정이 성립한다(shadow_ledger 참조).
    # entry_actual(실체결가)을 넘겨야 손절/목표와 기준이 맞아 R 이 성립한다.
    shadow_record("taken", [{**c, "stop": stop, "target": target, "entry_actual": entry}],
                  {"qty": qty, "entry": entry})
    logger.info("[ENTRY] %s %-10s %d주 @%.0f 손절%.0f 목표%.0f %s",
                sym, c["name"][:10], qty, entry, stop, target, mode_tag)
    return pos


def _entry_notify_line(p: dict) -> str:
    e, s, t = p["entry_price"], p["stop_price"], p["target"]
    rr = (t - e) / (e - s) if e > s else 0.0
    line = (f"• <b>{p['name']}</b>({p['symbol']}) {p['qty']}주 @{e:,.0f} (≈{e*p['qty']:,.0f}원)\n"
            f"   손절 {s:,.0f} / 목표 {t:,.0f} (손익비 1:{rr:.1f}) · 점수 {p['score']}")
    if p.get("sector_lead"):
        line += f" · 🔥주도섹터({p.get('sector','')})"
    return line


async def _apply_sector_rally(cands: list[dict]) -> list[dict]:
    """주도섹터 집단상승(차수재시실 '시황') — 09:30 키움 업종지수 스냅샷 기준.

    주도섹터 소속 후보 +SECTOR_BONUS 가점 후 재정렬. SECTOR_GATE=true 면 주도섹터만 남김.
    업종지수 미확보(서버 다운/조회 실패) 시 판정 불가 → 원본 그대로(fail-open, 게이트도 미적용).
    """
    if SECTOR_BONUS <= 0 and not SECTOR_GATE:
        return cands
    rows = await _sector_index_rows()
    if rows is None:                # 데이터 없음 — 주도섹터 판정 불가 → fail-open
        logger.info("[SECTOR] 업종지수 데이터 없음 — 주도섹터 판정 생략")
        return cands
    leaders = leading_sectors(rows, min_avg_pct=SECTOR_MIN_AVG,
                              min_breadth=SECTOR_BREADTH, top_k=SECTOR_TOP_K)
    log_event("sector_rally", {"leaders": leaders})
    smap = _sector_map()
    lead_names = {x["sector"] for x in leaders}
    for c in cands:
        c["sector"] = smap.get(c["symbol"], "기타")
        if c["sector"] in lead_names:
            c["sector_lead"] = True
            if SECTOR_BONUS > 0:
                c["score"] = round(c["score"] + SECTOR_BONUS, 1)
            logger.info("[SECTOR] ✓ %s %s 주도섹터(%s) 가점 +%g", c["symbol"], c["name"][:10], c["sector"], SECTOR_BONUS)
    cands.sort(key=lambda x: -x["score"])
    if SECTOR_GATE:
        skipped = [c for c in cands if not c.get("sector_lead")]
        cands = [c for c in cands if c.get("sector_lead")]
        if skipped:
            log_event("entry_skip", {"symbols": [c["symbol"] for c in skipped],
                                     "reason": "주도섹터 아님(SECTOR_GATE)"})
            shadow_record("sector_gate", skipped, {"leaders": sorted(lead_names)})
    return cands


async def _market_gates(cands: list[dict]) -> list[dict] | None:
    """진입 전 시장 게이트 3종 — 레짐 → 서킷 → breadth. 통과 시 후보, 차단 시 None.

    순서에 의미가 있다: 레짐(지수 추세, 하루 단위 판정)이 가장 넓은 그물이라 먼저 걸러
    아래 게이트의 조회 비용을 아낀다. breadth 만 '보류'(장중 회복 시 재시도)이고 나머지는 종착.
    """
    # 레짐 — KOSPI 가 자기 MA 아래면 하락장 → 신규진입 전면 차단(보유분 관리는 계속).
    # breadth 가 '당일 상승종목 비율'만 보는 것과 달리 **지수 추세**를 본다(상호보완).
    # 2026-08-03 도입: 실전 진입 11건 중 10건이 KOSPI<MA60 일 발생 → 실현손실 -33.3%p 회피 추정.
    if REGIME_MA > 0:
        kospi = await _kospi_closes()
        kma = moving_average(kospi, REGIME_MA) if kospi else None
        if kma is None:
            logger.warning("[REGIME] KOSPI MA%d 산출 불가 — 레짐 게이트 미적용(fail-open)", REGIME_MA)
        elif kospi[-1] < kma:
            log_event("regime_block", {"kospi": round(kospi[-1], 1), "ma": round(kma, 1),
                                       "ma_n": REGIME_MA, "candidates": len(cands)})
            shadow_record("regime", cands, {"kospi": round(kospi[-1], 1), "ma": round(kma, 1),
                                            "ma_n": REGIME_MA})
            _mark_done("entry")
            await notify(f"🚫 시장 레짐 게이트 — 신규 진입 차단 (KOSPI {kospi[-1]:,.0f} < MA{REGIME_MA} {kma:,.0f})\n"
                         f"하락장 신규진입 중단 · 후보 {len(cands)}종 스킵 (보유분 청산규칙은 정상 작동)")
            return None
    broken, why = await _circuit_broken()
    if broken:
        log_event("circuit_break", {"phase": "entry", "reason": why})
        shadow_record("circuit", cands, {"why": why})
        await notify(f"🛑 서킷브레이커 — 신규 진입 중단\n{why}")
        return None
    # breadth(2026-06-24 추가): KOSPI universe 양봉비율 < BREADTH_MIN_PCT 시 신규진입 차단.
    # 06-23 사고(9종 동시 hard stop) 같은 광범위 약세장 자동 감지. 백테스트 P10 -9.33→-7.07%(0.5) 검증.
    # 2026-07-03: 단발 차단이 '약한 출발→회복' 장을 통째로 놓치던 문제 → 후보를 버리지 않고 보류로 유지,
    #   _try_pending 이 장중 breadth 재확인해 회복(≥임계)+후보 반등 시 진입(컷오프까지). 약세 유지 시 계속 보류.
    if BREADTH_MIN_PCT > 0:
        rows = await _sector_index_rows()
        if rows:
            breadth = market_breadth(rows)
            if breadth is not None and breadth < BREADTH_MIN_PCT:
                log_event("breadth_block", {"breadth": round(breadth, 3),
                                            "threshold": BREADTH_MIN_PCT, "held": len(cands)})
                _save_pending(cands)   # 버리지 않고 보류 → 장중 회복 시 재시도
                _mark_done("entry")
                await notify(f"🚫 시장 breadth 게이트 — 신규 진입 보류 (양봉비율 {breadth:.1%} < {BREADTH_MIN_PCT:.0%})\n"
                             f"회복(≥{BREADTH_MIN_PCT:.0%}) + 후보 반등 시 진입 재시도 (~{ENTRY_CUTOFF})")
                return None
    return cands


async def _execute_buys(cands: list[dict], positions: list[dict], slots: int,
                        mode_tag: str) -> tuple[bool, list[dict], list[dict]]:
    """후보 순회 매수 → (정상종료, 매수분, 보류분). positions 는 체결분이 append 된다(in-place).

    하락 중인 후보는 사지 않고 보류 → _try_pending 이 장중 반등 시 재시도.
    슬롯이 도중에 소진되면 남은 후보는 그림자 원장에 기회비용으로 남긴다.
    """
    bought, pending = [], []
    held0 = len(positions)          # 매수 전 보유수 — 루프 중 positions 가 늘어나므로 미리 잡는다
    try:
        async with MCPManager({"trading-domain": TRADING_URL}) as mcp:
            if not mcp.tools:
                await notify("❌ trading-domain 연결 실패")
                return False, [], []
            for c in cands:
                if len(bought) >= slots:
                    # 슬롯 소진 — 남은 후보는 오늘 기회를 잃는다. 사후 성과 추적 대상.
                    shadow_record("no_slot", [c], {"held": held0, "max_pos": MAX_POS})
                    continue
                if ENTRY_WAIT_FALLING:
                    cur, opn = await _cur_and_open(c["symbol"])
                    if not is_rising(cur, opn):
                        pending.append(c)
                        logger.info("[ENTRY] %s %-10s 하락중(현재%.0f<시가%.0f) → 보류",
                                    c["symbol"], c["name"][:10], cur, opn)
                        continue
                pos = await _buy_one(mcp, c, mode_tag)
                if pos:
                    positions.append(pos); bought.append(pos)
                    save_state("positions", positions)   # 체결 즉시 영속화 — 이후 예외 시 유령 포지션 방지
    except Exception as e:
        logger.error("[ENTRY] %s", e); await notify(f"❌ 진입 오류: {e}")
        return False, bought, pending
    return True, bought, pending


async def phase_entry() -> None:
    logger.info("=" * 56); logger.info("[ENTRY] %s", datetime.now().strftime("%H:%M:%S"))
    log_event("phase_start", {"phase": "entry"})
    if _phase_done_today("entry"):
        logger.warning("[ENTRY] 오늘 이미 실행 — 중복 방지")
        return
    cands = get_state("candidates", [])
    # stale 가드: 08:50 screen 이 실패(hang/예외)하면 state 엔 전일 후보가 남는다 — 신호는 당일 한정 유효.
    cdate = get_state("candidates_date", "")
    if cands and cdate != datetime.now().strftime("%Y-%m-%d"):
        log_event("entry_skip", {"reason": f"stale candidates({cdate or '?'})",
                                 "symbols": [c["symbol"] for c in cands]})
        await notify(f"⏭️ 진입 차단 — 후보가 오늘 스크리닝분이 아님(screen={cdate or '?'}). "
                     "08:50 screen 실패 여부 확인 필요", critical=True)
        return
    positions = get_state("positions", [])
    slots = MAX_POS - len(positions)
    if not cands or slots <= 0:
        if cands:
            log_event("entry_skip", {"symbols": [c["symbol"] for c in cands],
                                     "reason": f"슬롯 만석({len(positions)}/{MAX_POS})"})
            shadow_record("no_slot", cands, {"held": len(positions), "max_pos": MAX_POS})
        await notify(f"ℹ️ 추세추종 진입: 후보 {len(cands)} 슬롯 {slots} — 진입 없음")
        return
    cands = await _market_gates(cands)
    if cands is None:
        return
    cands = await _apply_sector_rally(cands)
    if not cands:
        await notify("⏭️ 주도섹터 게이트: 주도섹터 소속 후보 없음 — 진입 스킵")
        return
    mode_tag = "🧪 MOCK" if MOCK_MODE else "💰 REAL"
    ok, bought, pending = await _execute_buys(cands, positions, slots, mode_tag)
    if not ok:
        return
    bought, positions = await _verify_buy_fills(bought, positions)
    save_state("positions", positions)
    _save_pending(pending)
    if bought or pending:
        _mark_done("entry")
    if bought:
        await notify(f"✅ 추세추종 진입 {mode_tag}\n" + "\n".join(_entry_notify_line(p) for p in bought))
    if pending:
        await notify("⏳ 하락 중 보류 (반등=시가 회복 시 진입, 끝까지 미반등 시 그날 스킵)\n" +
                     "\n".join(f"• {c['name']}({c['symbol']}) 점수{c['score']}" for c in pending))


def _past_entry_cutoff() -> bool:
    """진입 마감 시각(TREND_ENTRY_CUTOFF) 경과 여부.

    파싱 실패 시 **True**(경과로 간주 = 진입 차단). 과거엔 False 를 돌려줘, 설정이 깨지면
    컷오프가 조용히 사라지고 장 마감까지 진입이 허용됐다 — 안전장치는 실패 시 닫혀야 한다.
    """
    try:
        ch, cm = map(int, ENTRY_CUTOFF.split(":"))
        now = datetime.now()
        return now >= now.replace(hour=ch, minute=cm, second=0, microsecond=0)
    except Exception:
        logger.error("[ENTRY] 컷오프 파싱 실패(%r) — 진입 차단(안전측)", ENTRY_CUTOFF)
        return True


async def _try_pending() -> None:
    """보류(하락중) 후보 재점검 — 시가 회복(반등) 시 슬롯 한도 내 진입. 진입 마감 경과 시 스킵."""
    pending = get_state("pending_entries", [])
    if not pending:
        return
    # stale 가드: 전일 보류분(데몬 crash 로 exit phase 미도달)은 익일 매수 금지 — 신호는 당일 한정.
    pdate = get_state("pending_date", "")
    if pdate != datetime.now().strftime("%Y-%m-%d"):
        log_event("entry_skip", {"symbols": [c["symbol"] for c in pending],
                                 "reason": f"전일 보류분 stale({pdate or '?'})"})
        logger.warning("[PENDING] 전일 보류분(%s) %d종 폐기 — 당일 스크리닝분만 진입", pdate or "?", len(pending))
        _save_pending([])
        return
    if _past_entry_cutoff():
        log_event("entry_skip", {"symbols": [c["symbol"] for c in pending], "reason": f"진입마감({ENTRY_CUTOFF}) 경과"})
        shadow_record("cutoff", pending, {"cutoff": ENTRY_CUTOFF})
        await notify(f"⏭️ 보류 후보 진입마감({ENTRY_CUTOFF}) 경과 → 스킵: " +
                     ", ".join(f"{c['name']}({c['symbol']})" for c in pending))
        _save_pending([])
        return
    positions = get_state("positions", [])
    slots = MAX_POS - len(positions)
    if slots <= 0:
        shadow_record("no_slot", pending, {"held": len(positions), "max_pos": MAX_POS})
        _save_pending([])
        return
    broken, why = await _circuit_broken()
    if broken:
        log_event("circuit_break", {"phase": "pending", "reason": why})
        return
    # 시장 breadth 재확인 — 약세장이면 진입 보류 유지(회복 대기). 09:30 차단분·하락보류분 공통.
    # 회복해야 진입 → '약한 출발→회복' 장 포착하면서 약세 지속 시엔 06-23식 방어 유지.
    if BREADTH_MIN_PCT > 0:
        rows = await _sector_index_rows()
        if rows:
            breadth = market_breadth(rows)
            if breadth is not None and breadth < BREADTH_MIN_PCT:
                logger.info("[PENDING] 시장 breadth %.1f%% < %.0f%% — 진입 보류 유지(회복 대기)",
                            breadth * 100, BREADTH_MIN_PCT * 100)
                return
    mode_tag = "🧪 MOCK" if MOCK_MODE else "💰 REAL"
    still, bought = [], []
    try:
        async with MCPManager({"trading-domain": TRADING_URL}) as mcp:
            if not mcp.tools:
                return                       # 아무것도 안 샀으므로 보류분 그대로 둔다
            for c in pending:
                if len(bought) >= slots:
                    still.append(c); continue
                try:
                    cur, opn = await _cur_and_open(c["symbol"])
                    if is_rising(cur, opn):
                        pos = await _buy_one(mcp, c, mode_tag)
                        if pos:
                            positions.append(pos); bought.append(pos)
                            save_state("positions", positions)   # 체결 즉시 영속화 — 이후 예외 시 유령 방지
                        else:
                            still.append(c)
                    else:
                        still.append(c)
                except Exception as e:       # 한 종목 실패가 나머지 후보를 막지 않게
                    logger.error("[PENDING] %s 처리 실패 — 보류 유지: %s", c.get("symbol"), e)
                    still.append(c)
    except Exception as e:
        # 미처리분은 보류로 되돌린다(신호는 당일 한정이라 잃어도 안전측이지만, 매수분은 반드시 뺀다).
        done = {p["symbol"] for p in bought} | {c["symbol"] for c in still}
        still += [c for c in pending if c["symbol"] not in done]
        logger.error("[PENDING] %s", e)
    # ★ 아래 3줄은 예외 여부와 무관하게 실행돼야 한다. 과거엔 except 에서 return 해버려
    #   이미 매수한 종목이 pending 에 남았고, 다음 intraday 폴링이 그대로 재매수했다.
    bought, positions = await _verify_buy_fills(bought, positions)
    save_state("positions", positions)
    _save_pending(still)
    if bought:
        await notify(f"✅ 추세추종 보류분 진입(반등 확인) {mode_tag}\n" + "\n".join(_entry_notify_line(p) for p in bought))


async def _pyramid_adds(when: str) -> None:
    """피라미딩(승자 불타기) — equity 게이트 open 시, 보유 종목이 진입+ k×STEP_R×R 도달하면 1유닛 추가.

    각 추가 유닛 = 신규 진입과 동일 사이징(_size_qty, 예탁 PCT%). 평단·수량 갱신, 트레일은 공통.
    게이트(최근 청산 평균 net>임계)·서킷브레이커·현금 한도·return_code 모두 통과해야 체결 기록.
    """
    if PYRAMID_ADDS <= 0:
        return
    positions = get_state("positions", [])
    if not any(p.get("pyramid") and p.get("adds_done", 0) < PYRAMID_ADDS for p in positions):
        return
    gate, avg, n = _pyramid_gate_open()
    if not gate:
        return                       # 전략 cold → 불타기 보류(횡보장 증폭 차단)
    broken, _why = await _circuit_broken()
    if broken:
        return
    added = []
    try:
        async with MCPManager({"trading-domain": TRADING_URL}) as mcp:
            if not mcp.tools:
                logger.warning("[PYRAMID] trading-domain 연결 실패"); return
            for pos in positions:
                if not (pos.get("pyramid") and pos.get("adds_done", 0) < PYRAMID_ADDS):
                    continue
                base, R = pos.get("pyr_base", pos["entry_price"]), pos.get("pyr_R", 0)
                if R <= 0:
                    continue
                k = pos["adds_done"] + 1
                trigger = base + k * PYRAMID_STEP_R * R
                # 장중 방향 가드(2026-06-22 추가): 당일 하락 중인 종목엔 추가 보류 →
                # ENTRY_WAIT_FALLING 정신을 불타기에도 적용(승자 + 오늘도 상승 중 = 진짜 모멘텀)
                cur, opn = await _cur_and_open(pos["symbol"])
                if cur <= 0:
                    continue
                if cur < trigger:
                    continue
                if opn > 0 and not is_rising(cur, opn):
                    logger.info("[PYRAMID] %s 하락중(현재%.0f<시가%.0f) — 추가 보류(다음 cycle 재평가)",
                                pos["symbol"], cur, opn)
                    continue
                add_qty = await _size_qty(cur, pos.get("stop_price", 0))   # risk 사이징: 현 트레일 stop 기준
                if add_qty < 1:
                    logger.info("[PYRAMID] %s 현금부족/수량0 — 추가 스킵", pos["symbol"]); continue
                resp = await _place(mcp, "buy", pos["symbol"], add_qty)
                ok, why = _order_accepted(resp)
                if not ok:
                    logger.error("[REJECT] pyramid %s — %s", pos["symbol"], why)
                    log_event("order_reject", {"phase": "pyramid", "symbol": pos["symbol"], "why": why,
                                               "unknown": _is_unknown(resp), "raw": resp})
                    if _is_unknown(resp):
                        # 이미 보유 중인 종목이라 잔고 대조로 추가분을 분리할 수 없다(합산 평단만 보임).
                        # 재전송은 금물 — 알리고 다음 cycle 에 맡긴다(트리거가 유지되면 재평가된다).
                        await notify(f"🚨 <b>불타기 응답 불명</b> {pos['name']}({pos['symbol']}) "
                                     f"{add_qty}주 — 재전송 안 함\n→ HTS 로 보유수량 확인 필요",
                                     critical=True)
                    continue
                d = resp.get("data", {}) if isinstance(resp, dict) else {}
                fill = d.get("cntr_pric") or d.get("체결가")
                add_price = float(str(fill).lstrip("+-").replace(",", "")) if fill else cur
                oq = int(pos["qty"]); nq = oq + add_qty
                pos["entry_price"] = round((pos["entry_price"] * oq + add_price * add_qty) / nq, 2)
                pos["qty"] = nq
                pos["adds_done"] = k
                journal_append({"type": "pyramid", "id": pos["journal_id"], "symbol": pos["symbol"],
                                "name": pos["name"], "add_no": k, "qty": add_qty, "price": add_price,
                                "avg_entry": pos["entry_price"], "gate_avg": round(avg, 2)})
                log_event("pyramid", {"symbol": pos["symbol"], "add_no": k, "qty": add_qty,
                                      "price": add_price, "gate_avg": round(avg, 2)})
                logger.info("[PYRAMID] %s %s +%d주 @%.0f (#%d차) 평단%.0f", pos["symbol"], pos["name"][:10],
                            add_qty, add_price, k, pos["entry_price"])
                added.append((pos, add_qty, add_price, k))
                save_state("positions", positions)   # 체결 즉시 영속화 — 이후 예외 시 평단/수량 유실 방지
    except Exception as e:
        logger.error("[PYRAMID] %s", e); return
    if added:
        await notify(f"🔼 피라미딩 추가매수 (전략 hot · 최근{n}거래 평균 {avg:+.2f}%)\n" +
                     "\n".join(f"• <b>{p['name']}</b>({p['symbol']}) +{q}주 @{pr:,.0f} (#{k}차) · 평단 {p['entry_price']:,.0f}"
                               for p, q, pr, k in added))


# ─── 포지션 관리 공통 (트레일/목표/청산) ──────────────────────────────────────
async def _exit_signals(pos: dict, cur: float) -> dict:
    """15:20 청산 phase 전용 신호 — MA 이탈선·외인 수급·추세확인선·보유만기.

    장중(intraday)엔 평가하지 않는다(트레일/하드손절만) — 일봉 신호는 마감가 기준이라
    장중 판정이 무의미하고 조회 비용만 든다.
    데이터를 못 구하면 해당 신호는 None = 미적용(fail-open) — 조회 실패로 팔지 않는다.
    """
    sym = pos["symbol"]
    ohlcv = get_ohlcv(sym, max(EXIT_MA, FOREIGN_TREND_MA) + 40)
    closes_cur = [b["close"] for b in ohlcv] + [cur] if ohlcv else []
    ma_exit = moving_average(closes_cur, EXIT_MA) if ohlcv else None
    foreign = await _foreign_net_5d(sym) if USE_FOREIGN_EXIT else None
    ma_trend = None
    # 외인 청산 추세 확인선(MA60) — 수급만으로 정상추세 종목을 파는 것 방지.
    # 조건 ON 인데 MA 를 못 구하면 판정 불가 → 외인룰 자체를 스킵(fail-open 일관성).
    if USE_FOREIGN_EXIT and FOREIGN_TREND_MA > 0:
        ma_trend = moving_average(closes_cur, FOREIGN_TREND_MA) if ohlcv else None
        if ma_trend is None and foreign is not None:
            logger.info("[FOREIGN] %s MA%d 산출 불가 — 추세확인 불가로 외인룰 스킵", sym, FOREIGN_TREND_MA)
            foreign = None
    # 시간청산 — 백테스트 max_hold(60영업일 강제 마감)와 동일 조건 유지.
    # buy_date 파싱 실패(None)면 판정 불가 → 미적용(다른 신호들과 같은 fail-open). 경고는 남는다.
    held_days = _busdays_since(pos.get("buy_date"))
    aged = MAX_HOLD_DAYS > 0 and held_days is not None and held_days >= MAX_HOLD_DAYS
    return {"ma_exit": ma_exit, "foreign": foreign, "ma_trend": ma_trend, "aged": aged}


def _exit_line(x: dict) -> str:
    p, n = x["pos"], x["net"]
    rr = f" 손익비 {x['rr']}" if x["rr"] is not None else ""
    return (f"{'🟢' if n > 0 else '🔴'} <b>{p['name']}</b>({p['symbol']}) {x['qty']}주 @{x['cur']:,.0f}\n"
            f"   net {n:+.2f}% ({x['pnl_amt']:+,}원{rr}) · {x['hold']}일 보유 — {x['reason']}")


async def _manage_alerts(when: str, closed: list[dict], sell_failures: list[dict],
                         price_fails: list[str], eval_fails: list[str] | None = None) -> None:
    """포지션 관리 후 알림 — 시세조회 실패·평가 실패·매도거부 누적·청산 요약."""
    # 청산 phase 에서 시세조회 실패 = 청산 기회를 침묵 속에 놓칠 수 있음 → 알림
    if price_fails and when == "exit":
        await notify("⚠️ 청산 phase 시세조회 실패 — 청산판정 보류(다음 cycle 재시도): " + ", ".join(price_fails))
    # 평가 자체가 실패한 종목 = 청산 신호가 있었는지조차 모른다 → 시세실패보다 심각
    if eval_fails:
        await notify(f"🚨 <b>[{when}] 청산판정 실패 {len(eval_fails)}종</b> — 해당 종목은 이번 cycle 미평가\n"
                     + ", ".join(eval_fails) + "\n→ 로그 확인 후 필요 시 HTS 수동 대응", critical=True)
    # 매도 거부 누적이 임계치 초과(시도 절반 이상 또는 3건+) → 시스템적 문제 가능성 → critical alert
    attempts = len(closed) + len(sell_failures)
    if sell_failures and (len(sell_failures) >= 3 or len(sell_failures) >= attempts / 2):
        await notify(f"🚨🚨 <b>[{when}] 매도 거부 누적 {len(sell_failures)}/{attempts}건</b> — 시스템 점검 필요\n"
                     "8005 토큰/계좌권한/거래시간/잔고 확인. 필요 시 `python scripts/trend_panic.py --flatten`",
                     critical=True)
    if closed:
        await notify(f"📤 추세추종 청산 [{datetime.now().strftime('%m/%d %H:%M')}]\n" +
                     "\n".join(_exit_line(x) for x in closed))


async def _sell_with_retry(mcp, when: str, sym: str, qty: int) -> tuple[Any, bool, str]:
    """매도 1회 + **명시적 거부일 때만** 2초 후 1회 재시도 → (raw응답, 수락여부, 사유).

    재시도 조건이 핵심이다:
      - 거부(return_code != 0) → 접수 안 됨이 확실 → 재시도 안전. 8005 토큰만료 등이 여기.
      - 불명(타임아웃/통신실패) → 접수 여부 모름 → **재시도 금지**. 브로커가 이미 받았다면
        재전송은 이중 매도가 된다(보유보다 많이 팔면 결제 사고). 다음 cycle 이 현재가 기준으로
        다시 판정하므로, 여기선 알리고 넘기는 편이 안전하다.
    """
    resp = await _place(mcp, "sell", sym, qty)
    ok, why = _order_accepted(resp)
    if ok:
        return resp, True, why
    if _is_unknown(resp):
        logger.error("[ORDER] %s %s 매도 응답 불명 — 재전송 안 함(이중매도 방지). 다음 cycle 재판정", when, sym)
        return resp, False, f"{why} (접수 여부 불명 — 재전송 안 함)"
    logger.warning("[RETRY] %s %s 매도 거부 (%s) — 2초 후 재시도", when, sym, why)
    await asyncio.sleep(2.0)
    resp = await _place(mcp, "sell", sym, qty)
    ok, why = _order_accepted(resp)
    return resp, ok, why



async def _manage(do_exit_signals: bool, when: str) -> None:
    """보유 포지션 트레일 갱신 + 청산 판정/집행.

    예외 처리 원칙(2026-08-17): **한 종목의 실패가 나머지 포지션의 손절을 막지 않는다.**
    과거엔 루프 전체를 감싼 except 가 `return` 해버려, 3번째 종목에서 예외가 나면 4·5번은
    평가조차 안 되고 로그 한 줄만 남았다 — 트레일 갱신도 폐기되고, 누적 매도거부 critical
    알림(_manage_alerts)도 발송되지 않았다. 손절 대기 중인 포지션이 방치되는 경로다.
    """
    positions = get_state("positions", [])
    if not positions:
        return
    remaining = []
    closed = []
    sell_failures: list[dict] = []   # phase 내 매도 거부 누적 (8005/거부/예외) — 임계 초과 시 critical alert
    price_fails: list[str] = []      # 시세조회 실패 종목 — exit phase 면 알림(무경고 HOLD 방지)
    eval_fails: list[str] = []       # 종목 단위 평가 실패 — 청산판정이 아예 안 된 종목
    async def handle(mcp, idx: int, pos: dict) -> None:
        """포지션 1건: 트레일 갱신 → 청산판정 → 집행. 공유 리스트에 결과를 모은다."""
        sym, entry, qty = pos["symbol"], pos["entry_price"], int(pos["qty"])
        cur = await _realtime_price(sym)
        if not cur:
            # entry 폴백은 pnl 0 으로 위장돼 트레일/손절이 침묵 — 최소한 경고는 남긴다
            price_fails.append(f"{pos['name']}({sym})")
            logger.warning("[%s] %s 시세조회 실패 — entry 폴백(청산판정 보류)", when, sym)
            cur = entry
        a = float(pos.get("atr", 0) or 0)
        peak, stop = ratchet_stop(entry, pos.get("peak_price", entry), pos.get("stop_price", 0), cur, a, CFG.atr_k, -CFG.stop_pct)
        pos["peak_price"], pos["stop_price"] = round(peak, 2), round(stop, 2)
        sig = await _exit_signals(pos, cur) if do_exit_signals else {}
        action, reason, sell_qty = exit_decision(
            entry=entry, cur=cur, qty=qty, target=pos["target"], stop=stop,
            partial_done=bool(pos.get("partial_done")), hard_stop_pct=HARD_STOP_PCT,
            partial_pct=CFG.partial_pct, exit_ma_label=EXIT_MA,
            use_foreign=USE_FOREIGN_EXIT, trend_ma_label=FOREIGN_TREND_MA,
            ma_exit=sig.get("ma_exit"), foreign_net=sig.get("foreign"),
            ma_trend=sig.get("ma_trend"), aged_out=sig.get("aged", False))
        if not action:
            remaining.append(pos); return
        resp, ok, why = await _sell_with_retry(mcp, when, sym, sell_qty)
        if not ok:
            logger.error("[REJECT] %s %s 매도 거부 (재시도 후에도 실패) — %s", when, sym, why)
            log_event("order_reject", {"phase": when, "symbol": sym, "qty": sell_qty,
                                       "reason": reason, "why": why, "raw": resp})
            # 매도 거부는 시장 노출 직결 → critical alert (개별 알림)
            await notify(f"🚨 <b>매도 거부</b> [{when}] {pos['name']}({sym}) {sell_qty}주 "
                         f"@{cur:,.0f} 사유:{reason}\n원인:{why}\n→ HTS 수동매도 검토",
                         critical=True)
            sell_failures.append({"symbol": sym, "name": pos["name"], "qty": sell_qty,
                                  "reason": reason, "why": why})
            remaining.append(pos); return
        pnl_pct = round((cur - entry) / entry * 100, 2)
        if action == "PARTIAL":
            pos["partial_done"] = True; pos["qty"] = qty - sell_qty
            remaining.append(pos)
            save_state("positions", remaining + positions[idx + 1:])   # 매도 즉시 영속화(이중매도 방지)
            journal_append({"type": "partial", "id": pos["journal_id"], "symbol": sym, "qty": sell_qty,
                            "price": cur, "pnl_pct": pnl_pct, "reason": reason})
            log_event("partial", {"symbol": sym, "qty": sell_qty, "price": cur, "pnl_pct": pnl_pct})
            await notify(f"📈 부분익절 <b>{pos['name']}</b>({sym}) {sell_qty}주 @{cur:,.0f} "
                         f"({pnl_pct:+.2f}%) · 잔여 {pos['qty']}주 트레일 추종")
        else:
            save_state("positions", remaining + positions[idx + 1:])   # 매도 즉시 영속화(이중매도 방지)
            hold_days = (datetime.now() - datetime.strptime(pos["buy_date"], "%Y-%m-%d")).days
            net = round(pnl_pct - ROUNDTRIP_COST_PCT, 2)
            rr_real = round((cur - entry) / (entry - pos["stop_price"]), 2) if entry > pos["stop_price"] else None
            pnl_amt = round((cur - entry) * sell_qty)
            closed.append({"pos": pos, "cur": cur, "net": net, "reason": reason, "qty": sell_qty,
                           "pnl_amt": pnl_amt, "rr": rr_real, "hold": hold_days})
            journal_append({"type": "exit", "id": pos["journal_id"], "symbol": sym, "name": pos["name"],
                            "qty": sell_qty, "entry_price": entry, "exit_price": cur, "pnl_pct": pnl_pct,
                            "net_pct": net, "pnl_amount": round((cur - entry) * sell_qty), "rr_realized": rr_real,
                            "reason": reason, "hold_days": hold_days})
            log_event("exit", {"symbol": sym, "exit": cur, "net_pct": net, "reason": reason})

    processed = 0
    try:
        async with MCPManager({"trading-domain": TRADING_URL}) as mcp:
            if not mcp.tools:
                logger.warning("[%s] trading-domain 연결 실패", when); return
            for idx, pos in enumerate(positions):
                try:
                    await handle(mcp, idx, pos)
                except Exception as e:
                    # 이 종목만 포기하고 계속 — 나머지 포지션의 손절이 이것 때문에 멈추면 안 된다.
                    logger.error("[%s] %s 평가 실패 — 보유 유지하고 다음 종목 진행: %s",
                                 when, pos.get("symbol"), e, exc_info=True)
                    eval_fails.append(f"{pos.get('name','?')}({pos.get('symbol','?')})")
                    remaining.append(pos)
                processed += 1
    except Exception as e:
        # 세션/연결 단위 실패 — 미처리 포지션을 remaining 에 되돌려 state 유실을 막는다.
        logger.error("[%s] 청산 세션 실패(%d/%d 처리): %s", when, processed, len(positions), e, exc_info=True)
        remaining += positions[processed:]
        await notify(f"🚨 <b>청산 세션 중단</b> [{when}] {processed}/{len(positions)}종 처리 후 실패\n"
                     f"{str(e)[:200]}\n→ 미처리분은 다음 cycle 재판정", critical=True)
    # ★ 아래 2줄은 예외 여부와 무관하게 실행돼야 한다. 과거엔 except 에서 return 해버려
    #   트레일 갱신이 폐기되고, 누적 매도거부 critical 알림도 발송되지 않았다.
    save_state("positions", remaining)
    await _manage_alerts(when, closed, sell_failures, price_fails, eval_fails)


async def phase_intraday() -> None:
    log_event("phase_start", {"phase": "intraday"})
    await _try_pending()      # 보류(하락중) 후보 반등 시 진입
    await _pyramid_adds("intraday")   # 승자 불타기(equity 게이트, opt-in·기본off)
    await _manage(do_exit_signals=False, when="intraday")


async def phase_exit() -> None:
    logger.info("=" * 56); logger.info("[EXIT] %s", datetime.now().strftime("%H:%M:%S"))
    log_event("phase_start", {"phase": "exit"})
    # 장 마감(15:30) 경과 감지 — 이 시각 이후 매도는 전량 거부(rc=20 505217 장종료)된다.
    # 스케줄 드리프트는 위 데몬 루프에서 고쳤지만, 데몬 지연 기동·수동 실행 등 잔여 경로 방어.
    now_m = datetime.now().hour * 60 + datetime.now().minute
    if now_m >= 15 * 60 + 28 and get_state("positions"):
        log_event("exit_late", {"time": datetime.now().strftime("%H:%M:%S")})
        await notify(f"🚨 <b>청산 phase 지연</b> — {datetime.now().strftime('%H:%M')} 실행 "
                     f"(장 마감 15:30 임박/경과)\n매도 주문이 거부될 수 있습니다. "
                     f"청산 신호 발생 시 HTS 수동매도 검토.", critical=True)
    # 장중 끝까지 반등 못한 보류 후보 → 그날 진입 스킵
    pend = get_state("pending_entries", [])
    if pend:
        log_event("entry_skip", {"symbols": [c["symbol"] for c in pend], "reason": "장중 미반등"})
        shadow_record("no_rebound", pend, {"breadth_min": BREADTH_MIN_PCT})
        await notify("⏭️ 보류 후보 진입 스킵 (장중 시가 회복 실패): " +
                     ", ".join(f"{c['name']}({c['symbol']})" for c in pend))
        _save_pending([])
    await phase_reconcile()   # 신규 계좌 보유분 편입 후 청산판단
    await _manage(do_exit_signals=True, when="exit")
    await write_daily_journal()   # 마감 후 그날 매매일지 자동 작성
    # 분봉 축적(진입 시각 09:30 vs 11:00 검증용 — 일봉 백테스트로는 불가). ka10080 은 ~12영업일치만
    # 주므로 매일 받아야 유실이 없다. 청산·일지에 영향 없도록 완전 격리(실패해도 무시).
    try:
        from collect_minute_bars import collect, _targets
        await collect(_targets())
    except Exception as e:
        logger.warning("[MINUTE] 분봉 수집 실패(무시): %s", str(e)[:120])
    # 그림자 원장 사후 성과 갱신 — 차단된 후보가 이후 어떻게 됐는지(손절/목표 선행) 채운다.
    # 분봉 수집 **뒤에** 호출해야 그날 진입시각 체결가를 가상 진입가로 쓸 수 있다.
    try:
        from shadow_ledger import update as shadow_update
        shadow_update()
    except Exception as e:
        logger.warning("[SHADOW] 원장 갱신 실패(무시): %s", str(e)[:120])


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


def _write_heartbeat() -> None:
    """데몬 진행 heartbeat 기록 — watchdog 가 정체(hung) 감지에 사용."""
    try:
        HEARTBEAT_FILE.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    except Exception:
        pass


async def _heartbeat_loop() -> None:
    """60초마다 heartbeat 기록. 동기 네트워크 호출이 이벤트루프를 막으면(hang) 이 태스크도
    굶어 heartbeat 가 정체 → watchdog 이 stale 감지 후 재기동."""
    while True:
        _write_heartbeat()
        await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)


async def scheduler_daemon() -> None:
    logger.info("=" * 56)
    if PRODUCTION_MODE:
        logger.warning("[DAEMON] ⚠️ PRODUCTION MODE — 실거래 API 사용. 주문은 실제 체결됩니다.")
    else:
        logger.info("[DAEMON] 🧪 MOCK MODE — 모의투자 API. KIWOOM_PRODUCTION_MODE=true 로 실전 전환.")
    _size_desc = f"risk {RISK_PCT}%÷손절폭(상한{MAX_NOTIONAL_PCT:g}%)" if SIZING_MODE == "risk" else f"{SIZING_MODE} {POSITION_PCT}%"
    logger.warning("[DAEMON] 계좌=%s · 사이징=%s · 최대슬롯=%d · HardStop=%s%% · 일일손실서킷=%s%%",
                   (ACCOUNT_NO[:4] + "****") if ACCOUNT_NO else "없음",
                   _size_desc, MAX_POS, HARD_STOP_PCT, DAILY_LOSS_LIMIT_PCT)
    # LIVE-GUARD 는 **PRODUCTION_MODE 와 무관하게 항상** 평가한다.
    # 2026-08-17: 과거엔 이 블록이 `if PRODUCTION_MODE:` 안에 있었다. 그런데 PRODUCTION_MODE 자체가
    # .env 의 KIWOOM_PRODUCTION_MODE 에서 오므로, .env 로드가 실패하면 가드 전체가 건너뛰어진다 —
    # 정작 안전장치가 전부 꺼진 그 순간에. MCP 서버는 여전히 실거래라 주문은 실제로 나가면서
    # 라벨만 MOCK 이 된다(6월에 없앤 '라벨↔주문경로 불일치' footgun 의 재발). 가드가 자기
    # 전제조건에 의존하면 안 된다.
    warns: list[str] = []
    if not ENV_LOADED:
        warns.append(f"⚠️ .env 를 찾지 못했습니다({_ROOT / '.env'}) — 모든 설정이 코드 기본값입니다. "
                     "PRODUCTION_MODE 판정도 신뢰할 수 없으니 주문 경로를 직접 확인하세요")
    if SIZING_MODE == "pct_equity" and POSITION_PCT > 3:
        warns.append(f"POSITION_PCT={POSITION_PCT}% > 권장 3% (실전 첫주 사이즈 과대)")
    if SIZING_MODE == "risk" and RISK_PCT > 2:
        warns.append(f"RISK_PCT={RISK_PCT}% > 권장 ≤1.5% (거래별 리스크 과대 — MDD 급증)")
    if MAX_POS > 5:
        warns.append(f"MAX_POS={MAX_POS} > 권장 5 (실전 첫주 슬롯 과다)")
    if HARD_STOP_PCT <= 0:
        warns.append("HARD_STOP_PCT=0 — 하드손절 비활성 (권장 10%)")
    if DAILY_LOSS_LIMIT_PCT <= 0:
        warns.append("DAILY_LOSS_LIMIT_PCT=0 — 일일손실 서킷 비활성 (권장 2%)")
    if PYRAMID_ADDS > 0:
        warns.append(f"PYRAMID_ADDS={PYRAMID_ADDS} — 피라미딩 ON (실전 첫달 보류 권장)")
    if PYRAMID_BYPASS_GATE:
        warns.append("PYRAMID_BYPASS_GATE=true — equity-curve 안전게이트 비활성 (횡보장 증폭위험)")
    if ADOPT_MODE == "all":
        warns.append("ADOPT_MODE=all — broker 모든 보유분이 trend 청산룰로 처분됨 (HTS 수동매수 위험). watchlist/off 권장")
    if BREADTH_MIN_PCT <= 0:
        warns.append("BREADTH_MIN_PCT=0 — 시장 breadth 게이트 비활성 (06-23 같은 광범위 약세장 무방어). 0.4 권장")
    if REGIME_MA <= 0:
        warns.append("REGIME_MA=0 — 시장 레짐 게이트 비활성 (하락장 신규진입 무방어). 60 권장")
    for w in warns:
        logger.warning("[DAEMON][LIVE-GUARD] ⚠️ %s", w)
    if warns:
        await notify(f"⚠️ 가드 경고 {len(warns)}건 ({'💰REAL' if PRODUCTION_MODE else '🧪MOCK'}): "
                     + "; ".join(warns), critical=True)
    logger.info("[DAEMON] 추세추종 시작 | 유니버스=%s | 08:50 스크린/%s 진입(보류마감 %s)/장중 트레일/15:20 청산",
                UNIVERSE_MODE, ENTRY_TIME, ENTRY_CUTOFF)
    if not acquire_lock():
        await notify("⚠️ 추세추종 데몬 중복 기동 차단"); return
    _write_heartbeat()
    asyncio.create_task(_heartbeat_loop())   # hang 감지용 heartbeat (watchdog 이 stale 시 재기동)
    await notify(f"🚀 추세추종 데몬 시작 ({'🧪 MOCK' if MOCK_MODE else '💰 REAL'}) 모드:{UNIVERSE_MODE}")
    try:
        await phase_reconcile()   # 기동 시 계좌 보유분 편입(추세 청산규칙 관리)
    except Exception as e:
        logger.error("[DAEMON] reconcile %s", e)
    funcs = {"screen": phase_screen, "entry": phase_entry, "exit": phase_exit}
    while True:
        now = datetime.now()
        if not _is_weekday(now):
            await asyncio.sleep(1800); continue
        items = sorted([(_next_run(h, m), p) for h, m, p in SCHEDULE], key=lambda x: x[0])
        nxt, phase = items[0]
        logger.info("[DAEMON] 다음: %s @ %s (%.0f분)", phase, nxt.strftime("%m/%d %H:%M"),
                    (nxt - now).total_seconds() / 60)
        # 대기는 **절대시각 기준 재계산**. 과거엔 sleep 시간만 wait 에서 차감해 phase_intraday()
        # 실행시간이 누적 드리프트로 쌓였다(10분 폴링 × 수십 회 → exit 이 15:20→15:36 로 밀림).
        # 2026-07-30·31 매도 거부(장종료 505217) 5건의 근본 원인 — 15:30 마감 후 주문 시도.
        while True:
            now2 = datetime.now()
            wait = (nxt - now2).total_seconds()
            if wait <= 0:
                break
            active = bool(get_state("positions") or get_state("pending_entries"))
            cap = INTRADAY_POLL_MIN * 60 if (active and _is_market_hours(now2)) else 1800
            await asyncio.sleep(min(wait, cap))
            if (get_state("positions") or get_state("pending_entries")) and _is_market_hours(datetime.now()) and datetime.now() < nxt:
                try:
                    await phase_intraday()
                except Exception as e:
                    logger.error("[DAEMON] intraday %s", e)
        if _is_weekday(datetime.now()):
            try:
                await funcs[phase]()
            except StateCorrupted as e:
                # 보유 포지션을 알 수 없다 — 추측으로 거래를 이어가면 안 된다(무방비 방치/이중매도).
                logger.critical("[DAEMON] state 손상 — %s", e, exc_info=True)
                await notify(f"🚨 <b>state.json 손상</b> — 보유 포지션 불명으로 {phase} 중단\n"
                             f"{e}\n→ HTS 로 실보유분 확인 후 state 복구 필요", critical=True)
            except Exception as e:
                logger.error("[DAEMON] %s %s", phase, e, exc_info=True)
                await notify(f"❌ {phase} 오류: {e}")


def print_status() -> None:
    st = load_state()
    print(f"\n=== 추세추종 상태 [{st.get('last_updated','?')[:16]}] 모드:{UNIVERSE_MODE} ===")
    pos = st.get("positions", [])
    print(f"보유 {len(pos)}종목:")
    for p in pos:
        cl = [b["close"] for b in get_ohlcv(p["symbol"], 130)]
        zone = classify_zone(cl[-1], moving_average(cl, 60), moving_average(cl, 120),
                             held=True, stop_price=p.get("stop_price")) if cl else "?"
        print(f"  • [{zone}] {p['name']}({p['symbol']}) {p['qty']}주 @{p['entry_price']:,.0f} "
              f"손절{p['stop_price']:,.0f} 목표{p['target']:,.0f} {'(부분익절)' if p.get('partial_done') else ''} [{p.get('mode','')}]")
    pend = st.get("pending_entries", [])
    if pend:
        print(f"보류(하락중·반등대기) {len(pend)}종목: " + ", ".join(f"{c['name']}({c['symbol']})" for c in pend))
    print(f"매매일지: {JOURNAL_FILE}")


# ─── 진입점 ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    setup_daemon_runtime()   # 소켓 타임아웃·파일로깅·stdout UTF-8 (데몬 진입점에서만)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--phase", choices=["screen", "entry", "intraday", "exit", "reconcile",
                                       "journal", "shadow"])
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
    elif args.phase == "shadow":
        from shadow_ledger import report as shadow_report, update as shadow_update
        shadow_update(); shadow_report(detail=True)
    else:
        asyncio.run({"screen": phase_screen, "entry": phase_entry,
                     "intraday": phase_intraday, "exit": phase_exit,
                     "reconcile": phase_reconcile, "journal": write_daily_journal}[args.phase]())
