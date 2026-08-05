"""그림자 원장(shadow ledger) — **진입하지 않은 후보**의 사후 성과 추적.

배경(2026-08-05): 게이트(레짐/breadth/서킷/슬롯한도/사이징)가 후보를 걸러도 그 종목이 이후
어떻게 됐는지 기록이 없어, **게이트가 옳았는지 영원히 알 수 없었다**. 08-05 삼성에스디에스가
슬롯 만석으로 스킵된 뒤 당일 +4.78% 상승한 게 계기.

무엇을 재나: 차단 시점의 **가상 진입가**(= 그날 진입시각 분봉 시가, 없으면 종가)로 포지션을
잡았다 치고, 이후 20영업일간 **우리 자신의 청산규칙**(손절/목표)로 판정한다.
  - 손절 선행 → 게이트가 **손실을 막았다**(이득)
  - 목표 선행 → 게이트가 **수익을 놓쳤다**(기회비용)
단순 D+N 수익률도 같이 기록하지만, 판정의 축은 손절/목표 선행 여부다(실제 매매와 같은 잣대).

실제 진입분(reason="taken")도 동일한 방식으로 기록한다 — **같은 자로 재야** 비교가 성립한다.

저장: data/trend_follow/shadow.jsonl (append-only, 레코드별 in-place 갱신)

사용:
  python scripts/shadow_ledger.py --update            # 사후 성과 채우기(장 마감 후, 데몬이 자동 호출)
  python scripts/shadow_ledger.py --report            # 사유별 집계 + 판정
  python scripts/shadow_ledger.py --report --detail   # 레코드별 상세
  python scripts/shadow_ledger.py --report --days 30  # 최근 30일만
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from trend_config import DATA_DIR, ENTRY_TIME, logger  # noqa: E402

from src.mcp_servers.trend_mcp.market_data import get_ohlcv  # noqa: E402

SHADOW_FILE = DATA_DIR / "shadow.jsonl"
MINUTE_DIR = DATA_DIR / "minute"
HORIZONS = (1, 3, 5, 10, 20)
MAX_TRACK_DAYS = 20        # 이 영업일 지나면 미결이어도 확정(추세추종 평균 보유 ~10~20일)

# 사유 코드 → 한글 라벨. 새 게이트 추가 시 여기만 늘리면 리포트에 자동 반영.
REASONS = {
    "taken": "실제 진입(대조군)",
    "no_slot": "슬롯 만석",
    "regime": "레짐 게이트(KOSPI<MA)",
    "breadth": "breadth 게이트",
    "circuit": "서킷브레이커",
    "sector_gate": "주도섹터 게이트",
    "size_zero": "사이징 0주(자본 제약)",
    "cutoff": "진입마감 경과",
    "no_rebound": "장중 미반등",
    "already_held": "이미 보유(물타기 금지)",
    "order_reject": "주문 거부",
    "hist_blocked": "과거 미진입(소급·사유미상)",
}


# ─── 기록 (데몬에서 호출) ────────────────────────────────────────────────────
def _load() -> list[dict]:
    if not SHADOW_FILE.exists():
        return []
    out = []
    for line in SHADOW_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _save(recs: list[dict]) -> None:
    SHADOW_FILE.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n", encoding="utf-8")


def record(reason: str, cands: list[dict], ctx: dict | None = None) -> int:
    """차단/스킵된 후보(또는 진입분)를 원장에 남긴다. **절대 예외를 올리지 않는다**(데몬 보호).

    같은 날 같은 종목은 1회만 기록(먼저 걸린 사유 보존) — 10분 폴링 경로의 중복 방지.
    """
    try:
        if not cands:
            return 0
        today = datetime.now().strftime("%Y-%m-%d")
        recs = _load()
        seen = {(r.get("date"), r.get("symbol")) for r in recs}
        added = []
        for c in cands:
            sym = str(c.get("symbol") or "")
            if not sym or (today, sym) in seen:
                continue
            seen.add((today, sym))
            added.append({
                "date": today,
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "reason": reason,
                "symbol": sym,
                "name": c.get("name") or sym,
                "score": c.get("score"),
                "ref_price": c.get("price"),          # screen 시점(전일 완성봉) 종가
                "stop": c.get("stop"),
                "target": c.get("target"),
                "atr": c.get("atr"),
                "sector": c.get("sector"),
                "ctx": ctx or {},
            })
        if added:
            with SHADOW_FILE.open("a", encoding="utf-8") as f:
                for r in added:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            logger.info("[SHADOW] %s — %d종 기록 (%s)", REASONS.get(reason, reason),
                        len(added), ", ".join(r["symbol"] for r in added))
        return len(added)
    except Exception as e:                                    # noqa: BLE001 — 기록 실패가 매매를 막으면 안 됨
        logger.warning("[SHADOW] 기록 실패(무시): %s", str(e)[:120])
        return 0


def record_one(reason: str, cand: dict, ctx: dict | None = None) -> int:
    return record(reason, [cand], ctx)


# ─── 사후 성과 채우기 ────────────────────────────────────────────────────────
def _minute_open_at(symbol: str, date: str, hhmm: str) -> float | None:
    """그날 진입시각 5분봉 시가 = 가상 체결가. 분봉 미수집이면 None."""
    f = MINUTE_DIR / date / f"{symbol}.json"
    if not f.exists():
        return None
    try:
        rows = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None
    t = hhmm.replace(":", "")
    for b in rows:
        if str(b.get("ts", ""))[8:12] >= t:
            v = float(b.get("open") or 0)
            return v if v > 0 else None
    return None


def _entry_proxy(symbol: str, date: str, day_bar: dict) -> tuple[float, str]:
    """가상 진입가 — 그날 진입시각 분봉 시가 > 그날 종가. (가격, 출처)."""
    m = _minute_open_at(symbol, date, ENTRY_TIME)
    if m:
        return m, "minute"
    return float(day_bar.get("close") or 0), "close"


def _evaluate(rec: dict, bars: list[dict]) -> bool:
    """레코드 1건의 사후 성과 산출. 확정(더 볼 필요 없음)이면 True.

    가상 진입가: 그날 진입시각 분봉 시가 > 그날 종가 > screen 종가(폴백).
    손절/목표 판정은 **익일봉부터** — 진입일 저가/고가는 진입 이전 구간을 포함해 왜곡되므로 제외.
    같은 날 손절·목표를 동시에 스친 경우는 보수적으로 **손절 선행**으로 본다.
    """
    idx = next((i for i, b in enumerate(bars) if b["date"] == rec["date"]), None)
    if idx is None:
        return False                                   # 휴장/미수집 — 다음 update 에서 재시도
    entry, src = _entry_proxy(rec["symbol"], rec["date"], bars[idx])
    entry = entry or float(rec.get("ref_price") or 0)
    if entry <= 0:
        return False
    fut = bars[idx + 1:idx + 1 + MAX_TRACK_DAYS]
    rec["entry_ref"] = round(entry, 2)
    rec["entry_src"] = src
    stop = float(rec.get("stop") or 0)
    target = float(rec.get("target") or 0)
    risk = entry - stop if stop > 0 and entry > stop else 0

    fwd, mfe, mae, outcome, hit_day = {}, 0.0, 0.0, "open", None
    for n, b in enumerate(fut, 1):
        chg = (b["close"] - entry) / entry * 100
        mfe = max(mfe, (b["high"] - entry) / entry * 100)
        mae = min(mae, (b["low"] - entry) / entry * 100)
        if n in HORIZONS:
            fwd[str(n)] = round(chg, 2)
        if outcome == "open":
            if stop > 0 and b["low"] <= stop:
                outcome, hit_day = "stop", n
            elif target > 0 and b["high"] >= target:
                outcome, hit_day = "target", n
    rec["fwd"] = fwd
    rec["mfe"] = round(mfe, 2)
    rec["mae"] = round(mae, 2)
    rec["outcome"] = outcome
    rec["hit_day"] = hit_day
    rec["tracked"] = len(fut)
    last = fut[-1]["close"] if fut else entry
    if outcome == "stop":
        rec["r"] = -1.0
    elif outcome == "target":
        rec["r"] = round((target - entry) / risk, 2) if risk else None
    else:
        rec["r"] = round((last - entry) / risk, 2) if risk else None
    rec["last_pct"] = round((last - entry) / entry * 100, 2) if fut else 0.0
    rec["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return outcome != "open" or len(fut) >= MAX_TRACK_DAYS


def update(verbose: bool = True) -> int:
    """미확정 레코드의 사후 성과를 채운다. 종목당 OHLCV 1회만 조회(캐시)."""
    recs = _load()
    todo = [r for r in recs if not r.get("done")]
    if not todo:
        if verbose:
            logger.info("[SHADOW] 갱신할 레코드 없음 (총 %d건)", len(recs))
        return 0
    cache: dict[str, list[dict]] = {}
    n = 0
    for r in todo:
        sym = r["symbol"]
        if sym not in cache:
            cache[sym] = get_ohlcv(sym, days=120)
        bars = cache[sym]
        if not bars:
            continue
        try:
            if _evaluate(r, bars):
                r["done"] = True
            n += 1
        except Exception as e:                              # noqa: BLE001
            logger.warning("[SHADOW] %s 평가 실패: %s", sym, str(e)[:120])
    _save(recs)
    if verbose:
        logger.info("[SHADOW] %d건 갱신 (확정 %d / 전체 %d)",
                    n, sum(1 for r in recs if r.get("done")), len(recs))
    return n


# ─── 과거 소급 기록 ─────────────────────────────────────────────────────────
def _ticker_name(sym: str) -> str:
    try:
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            from pykrx import stock as krx
            return krx.get_market_ticker_name(sym) or sym
    except Exception:
        return sym



def backfill_from_events() -> int:
    """events.jsonl 로 과거 미진입 후보를 소급 기록 — 도입 이전 구간에도 표본을 만든다.

    `screen_done` 의 후보 심볼 중 그날 `entry` 가 없는 종목 = 어떤 게이트든 걸려 못 산 것.
    사유는 소급 판별이 불가하므로 `hist_blocked` 로 묶는다(사유별 분해는 도입 이후 데이터로).
    손절/목표는 그날까지의 일봉으로 ATR 을 재산출해 **라이브와 동일한 공식**으로 복원한다.
    실제 진입분은 event payload 의 진짜 stop/target 을 그대로 쓴다(대조군).
    """
    from src.mcp_servers.trend_mcp.signals import atr as _atr
    from src.mcp_servers.closing_bet_mcp.exit_rules import init_stop_price as _istop
    from trend_config import CFG

    recs = _load()
    seen = {(r.get("date"), r.get("symbol")) for r in recs}
    cache: dict[str, list[dict]] = {}
    added: list[dict] = []
    for day_dir in sorted(DATA_DIR.iterdir()):
        f = day_dir / "events.jsonl" if day_dir.is_dir() else None
        if not f or not f.exists():
            continue
        date = day_dir.name
        cands, taken = [], {}
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("event") == "screen_done":
                cands = ev["payload"].get("symbols") or []
            elif ev.get("event") == "entry":
                taken[ev["payload"]["symbol"]] = ev["payload"]
        for sym in cands:
            if (date, sym) in seen:
                continue
            if sym not in cache:
                cache[sym] = get_ohlcv(sym, days=200)
            bars = cache[sym]
            idx = next((i for i, b in enumerate(bars) if b["date"] == date), None)
            if idx is None:
                continue
            p = taken.get(sym)
            if p:                                        # 실제 진입 — 진짜 체결가/손절 사용
                rec = {"reason": "taken", "ref_price": p["entry"],
                       "stop": p["stop"], "target": p["target"]}
            else:                                        # 미진입 — 같은 공식으로 손절/목표 복원
                entry, _src = _entry_proxy(sym, date, bars[idx])
                a = _atr(bars[:idx + 1], CFG.atr_period)
                if not entry or not a:
                    continue
                stop = round(_istop(entry, a, CFG.atr_k, -CFG.stop_pct), 2)
                rec = {"reason": "hist_blocked", "ref_price": entry, "stop": stop,
                       "target": round(entry + CFG.rr * (entry - stop), 2), "atr": round(a, 2)}
            seen.add((date, sym))
            added.append({"date": date, "ts": f"{date} 00:00:00", "symbol": sym,
                          "name": _ticker_name(sym), "score": None, "sector": None,
                          "ctx": {"backfill": True}, **rec})
    if added:
        with SHADOW_FILE.open("a", encoding="utf-8") as fh:
            for r in added:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    logger.info("[SHADOW] 소급 기록 %d건 (미진입 %d / 진입 %d)", len(added),
                sum(1 for r in added if r["reason"] == "hist_blocked"),
                sum(1 for r in added if r["reason"] == "taken"))
    return len(added)


# ─── 리포트 ─────────────────────────────────────────────────────────────────
def _avg(v: list[float]) -> float:
    return sum(v) / len(v) if v else 0.0


def report(days: int | None = None, detail: bool = False) -> None:
    recs = _load()
    if not recs:
        print("기록된 그림자 원장이 없습니다. 게이트가 후보를 차단하면 자동으로 쌓입니다.")
        return
    if days:
        cut = (datetime.now().date() - timedelta(days=days)).isoformat()
        recs = [r for r in recs if r["date"] >= cut]
    scored = [r for r in recs if r.get("outcome")]

    print("\n" + "=" * 78)
    print(f"  그림자 원장 — 차단된 후보의 사후 성과   (총 {len(recs)}건 / 평가완료 {len(scored)}건)")
    print("=" * 78)
    if not scored:
        print("\n아직 평가된 레코드가 없습니다.")
        print("  기록일 일봉이 확정(장 마감)돼야 추적이 시작됩니다 — 다음 영업일 마감 후 `--update`.")
        for r in sorted(recs, key=lambda x: x["date"], reverse=True)[:10]:
            print(f"  · {r['date']} {r['name']}({r['symbol']}) — {REASONS.get(r['reason'], r['reason'])}")
        return

    by: dict[str, list[dict]] = defaultdict(list)
    for r in scored:
        by[r["reason"]].append(r)

    hdr = f"{'사유':<22}{'n':>4}{'손절선행':>9}{'목표선행':>9}{'평균R':>8}{'D+5':>9}{'D+20':>9}"
    print("\n" + hdr)
    print("-" * len(hdr))
    for reason, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        n = len(rs)
        stops = sum(1 for r in rs if r["outcome"] == "stop")
        tgts = sum(1 for r in rs if r["outcome"] == "target")
        rmul = [r["r"] for r in rs if r.get("r") is not None]
        d5 = [r["fwd"]["5"] for r in rs if r.get("fwd", {}).get("5") is not None]
        d20 = [r["fwd"]["20"] for r in rs if r.get("fwd", {}).get("20") is not None]
        print(f"{REASONS.get(reason, reason):<22}{n:>4}{stops / n:>8.0%}{tgts / n:>9.0%}"
              f"{_avg(rmul):>+8.2f}{_avg(d5):>+8.2f}%{_avg(d20):>+8.2f}%")

    # 판정 — 차단분(taken 제외)의 평균 R 부호가 게이트 가치의 요약
    blocked = [r for r in scored if r["reason"] != "taken"]
    taken = [r for r in scored if r["reason"] == "taken"]
    print("\n" + "-" * 78)
    if blocked:
        br = [r["r"] for r in blocked if r.get("r") is not None]
        avg_b = _avg(br)
        print(f"차단된 후보 평균 {avg_b:+.2f}R (n={len(br)})", end="")
        if taken:
            tr = [r["r"] for r in taken if r.get("r") is not None]
            print(f"   vs   실제 진입분 평균 {_avg(tr):+.2f}R (n={len(tr)})")
        else:
            print()
        if avg_b < -0.1:
            print("→ 게이트가 **손실을 막고 있다**. 현행 유지.")
        elif avg_b > 0.3:
            print("→ 게이트가 **수익 기회를 버리고 있다**. 임계값 완화를 검토할 근거.")
        else:
            print("→ 아직 판정 유보(차단분 손익이 대체로 중립). 표본을 더 쌓을 것.")
    # 월별 분해 — 전체 평균은 지배적 레짐에 가려진다(2026-08-03 회고 교훈 #1).
    bym: dict[str, list[dict]] = defaultdict(list)
    for r in scored:
        bym[r["date"][:7]].append(r)
    if len(bym) > 1:
        print("\n월별 분해 (전체 평균은 지배적 레짐에 가려진다)")
        print(f"{'월':<9}{'차단n':>6}{'차단R':>8}{'진입n':>6}{'진입R':>8}   판정")
        print("-" * 56)
        for m in sorted(bym):
            rs = bym[m]
            b = [r["r"] for r in rs if r["reason"] != "taken" and r.get("r") is not None]
            t = [r["r"] for r in rs if r["reason"] == "taken" and r.get("r") is not None]
            verdict = ("차단이 이득" if b and _avg(b) < -0.1
                       else "차단이 손해" if b and _avg(b) > 0.3 else "중립")
            print(f"{m:<9}{len(b):>6}{_avg(b):>+8.2f}{len(t):>6}{_avg(t):>+8.2f}   {verdict}")

    n_open = sum(1 for r in recs if r.get("outcome") == "open" and not r.get("done"))
    if n_open:
        print(f"※ 추적 중(미확정) {n_open}건 — 최대 {MAX_TRACK_DAYS}영업일 후 확정")
    print("※ 표본 20건 미만이면 방향 참고용. 사유별로는 30건 이상 쌓인 뒤 판단할 것.")

    if detail:
        print("\n" + "=" * 78)
        print(f"{'날짜':<11}{'종목':<14}{'사유':<18}{'진입가':>9}{'결과':>7}{'일':>4}{'R':>7}{'MFE':>8}{'MAE':>8}")
        print("-" * 78)
        for r in sorted(scored, key=lambda x: x["date"], reverse=True):
            oc = {"stop": "손절", "target": "목표", "open": "미결"}.get(r["outcome"], r["outcome"])
            print(f"{r['date']:<11}{r['name'][:12]:<14}{REASONS.get(r['reason'], r['reason'])[:16]:<18}"
                  f"{r.get('entry_ref') or 0:>9,.0f}{oc:>7}{r.get('hit_day') or 0:>4}"
                  f"{r.get('r') if r.get('r') is not None else 0:>+7.2f}"
                  f"{r.get('mfe', 0):>+7.1f}%{r.get('mae', 0):>+7.1f}%")


def main() -> None:
    ap = argparse.ArgumentParser(description="그림자 원장 — 차단된 후보 사후 추적")
    ap.add_argument("--update", action="store_true", help="사후 성과 갱신(장 마감 후)")
    ap.add_argument("--backfill", action="store_true", help="events.jsonl 로 과거 후보 소급 기록(1회)")
    ap.add_argument("--report", action="store_true", help="사유별 집계 리포트")
    ap.add_argument("--detail", action="store_true", help="리포트에 레코드별 상세 포함")
    ap.add_argument("--days", type=int, help="최근 N일만 집계")
    a = ap.parse_args()
    logging_ready = logger.handlers
    if not logging_ready:                       # 단독 실행 시 콘솔 로그
        import logging
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    if a.backfill:
        backfill_from_events()
    if a.update or not (a.report or a.backfill):
        update()
    if a.report or not (a.update or a.backfill):
        report(days=a.days, detail=a.detail)


if __name__ == "__main__":
    main()
