"""그림자 원장(shadow ledger) — **진입하지 않은 후보**의 사후 성과 추적.

배경(2026-08-05): 게이트(레짐/breadth/서킷/슬롯한도/사이징)가 후보를 걸러도 그 종목이 이후
어떻게 됐는지 기록이 없어, **게이트가 옳았는지 영원히 알 수 없었다**. 08-05 삼성에스디에스가
슬롯 만석으로 스킵된 뒤 당일 +4.78% 상승한 게 계기.

무엇을 재나: 차단 시점의 **가상 진입가**(= 그날 진입시각 분봉 시가, 없으면 종가)로 포지션을
잡았다 치고, 이후 20영업일간 **초기 손절 / 첫 목표(1:3)** 중 뭐가 먼저 닿는지로 판정한다.
  - 손절 선행 → 게이트가 **손실을 막았다**(이득)
  - 목표 선행 → 게이트가 **수익을 놓쳤다**(기회비용)
※ 라이브 청산규칙 **전체가 아니다** — 트레일 래칫·부분익절·MA120·외인·시간청산은 미반영.
   게이트 판정용 척도이지 실손익 추정치가 아니다(docs/shadow_ledger.md §2).

실제 진입분(reason="taken")도 동일한 방식으로 기록한다 — **같은 자로 재야** 비교가 성립한다.
단 taken 은 손절/목표가 실체결가 기준이므로 평가 진입가도 **실체결가**(`entry_actual`)를 쓴다.

저장: data/trend_follow/shadow.jsonl (append-only, 레코드별 in-place 갱신)

사용:
  python scripts/shadow_ledger.py --update            # 사후 성과 채우기(장 마감 후, 데몬이 자동 호출)
  python scripts/shadow_ledger.py --recompute         # 확정분 포함 전량 재평가(평가 로직 변경 시)
  python scripts/shadow_ledger.py --report            # 사유별 집계 + 판정
  python scripts/shadow_ledger.py --report --detail   # 레코드별 상세
  python scripts/shadow_ledger.py --report --days 30  # 최근 30일만
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from trend_config import DATA_DIR, ENTRY_TIME, logger, setup_daemon_runtime  # noqa: E402

from src.mcp_servers.trend_mcp.market_data import get_ohlcv  # noqa: E402

SHADOW_FILE = DATA_DIR / "shadow.jsonl"
MINUTE_DIR = DATA_DIR / "minute"
HORIZONS = (1, 3, 5, 10, 20)
MAX_TRACK_DAYS = 20        # 이 영업일 지나면 미결이어도 확정(추세추종 평균 보유 ~10~20일)
GIVEUP_AFTER_DAYS = 55     # 이 달력일 지나도 해당일 일봉을 못 찾으면 포기(상장폐지·거래정지·조회범위 초과)

# 진입 시각 이력 — 과거 레코드를 **그 당시 시각**으로 평가하기 위한 매핑(2026-08-05 D3 수정).
# (시행일, HH:MM) 오름차순. 이후 변경은 레코드의 `entry_time` 스탬프가 처리한다.
_ENTRY_TIME_HISTORY = (("2026-08-03", "11:00"),)
_ENTRY_TIME_INITIAL = "09:30"

# 사유 코드 → 한글 라벨. 새 게이트 추가 시 여기만 늘리면 리포트에 자동 반영.
# ※ breadth 는 항목이 없다 — 09:30 차단은 종착이 아니라 보류라서 `no_rebound`/`cutoff` 로 귀결된다.
REASONS = {
    "taken": "실제 진입(대조군)",
    "no_slot": "슬롯 만석",
    "regime": "레짐 게이트(KOSPI<MA)",
    "circuit": "서킷브레이커",
    "sector_gate": "주도섹터 게이트",
    "size_zero": "사이징 0주(자본 제약)",
    "cutoff": "진입마감 경과",
    "no_rebound": "장중 미반등",
    "already_held": "이미 보유(물타기 금지)",
    "order_reject": "주문 거부",
    "price_fail": "시세조회 실패(사이징 불가)",
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


def _write_all(recs: list[dict]) -> None:
    SHADOW_FILE.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n", encoding="utf-8")


def _save(recs: list[dict]) -> None:
    """전량 재기록 — **디스크를 다시 읽어 병합**한다.

    `update()` 가 도는 동안 데몬이 `record()` 로 append 할 수 있다(수동 --update 와 데몬 15:20 동시 실행).
    메모리 스냅샷을 그대로 덮어쓰면 그 사이 들어온 레코드가 사라진다 → 디스크에만 있는 건 살린다.
    """
    known = {(r.get("date"), r.get("symbol")) for r in recs}
    extra = [d for d in _load() if (d.get("date"), d.get("symbol")) not in known]
    if extra:
        logger.info("[SHADOW] 저장 중 신규 %d건 병합(동시 기록 감지)", len(extra))
    _write_all(recs + extra)


def record(reason: str, cands: list[dict], ctx: dict | None = None) -> int:
    """차단/스킵된 후보(또는 진입분)를 원장에 남긴다. **절대 예외를 올리지 않는다**(데몬 보호).

    같은 날 같은 종목은 1회만 기록(먼저 걸린 사유 보존) — 10분 폴링 경로의 중복 방지.
    예외: `taken` 은 기존 레코드를 **교체**한다 — 오전에 size_zero/already_held 로 막혔다가
    장중 재시도(_try_pending)로 실제 체결되는 경로가 있어, 안 그러면 대조군 표본이 유실되고
    실제로 산 종목이 '차단됨'으로 오분류된다.
    """
    try:
        if not cands:
            return 0
        today = datetime.now().strftime("%Y-%m-%d")
        recs = _load()
        seen = {(r.get("date"), r.get("symbol")) for r in recs}
        added, replaced = [], []
        for c in cands:
            sym = str(c.get("symbol") or "")
            if not sym:
                continue
            if (today, sym) in seen:
                if reason != "taken":
                    continue
                replaced.append(sym)          # taken 은 덮어쓴다
            seen.add((today, sym))
            added.append({
                "date": today,
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "reason": reason,
                "symbol": sym,
                "name": c.get("name") or sym,
                "score": c.get("score"),
                "ref_price": c.get("price"),          # screen 시점(전일 완성봉) 종가
                # 실제 체결가 — 있으면 평가 진입가로 이걸 쓴다(손절/목표와 기준을 맞춰야 R 이 성립).
                "entry_actual": c.get("entry_actual"),
                "entry_time": ENTRY_TIME,             # 그날의 진입 시각(설정 변경 이력 대응)
                "stop": c.get("stop"),
                "target": c.get("target"),
                "atr": c.get("atr"),
                "sector": c.get("sector"),
                "ctx": ctx or {},
            })
        if not added:
            return 0
        if replaced:
            keep = [r for r in recs
                    if not (r.get("date") == today and r.get("symbol") in replaced)]
            _write_all(keep + added)
            logger.info("[SHADOW] %s — %d종 기록 (교체 %s)", REASONS.get(reason, reason),
                        len(added), ", ".join(replaced))
        else:
            with SHADOW_FILE.open("a", encoding="utf-8") as f:
                for r in added:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            logger.info("[SHADOW] %s — %d종 기록 (%s)", REASONS.get(reason, reason),
                        len(added), ", ".join(r["symbol"] for r in added))
        return len(added)
    except Exception as e:                                    # noqa: BLE001 — 기록 실패가 매매를 막으면 안 됨
        logger.warning("[SHADOW] 기록 실패(무시): %s", str(e)[:120])
        return 0


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


def _entry_time_for(date: str, rec: dict | None = None) -> str:
    """그날 실제로 적용됐던 진입 시각. 레코드 스탬프 > 이력 테이블 > 최초값.

    ENTRY_TIME 은 현재 설정값이라 과거 레코드에 그대로 쓰면 안 된다(07-31 이전은 09:30 진입).
    """
    if rec and rec.get("entry_time"):
        return str(rec["entry_time"])
    for start, hhmm in reversed(_ENTRY_TIME_HISTORY):
        if date >= start:
            return hhmm
    return _ENTRY_TIME_INITIAL


def _entry_proxy(symbol: str, date: str, day_bar: dict, rec: dict | None = None) -> tuple[float, str]:
    """가상 진입가 — 그날 진입시각 분봉 시가 > 그날 종가. (가격, 출처).

    실제 체결가(`entry_actual`)가 있으면 그것이 최우선 — 손절/목표가 실제 체결가 기준으로
    잡혀 있으므로 진입가만 프록시로 쓰면 risk(=entry−stop) 가 뒤틀려 R 이 무의미해진다.
    """
    if rec and rec.get("entry_actual"):
        v = float(rec["entry_actual"])
        if v > 0:
            return v, "actual"
    m = _minute_open_at(symbol, date, _entry_time_for(date, rec))
    if m:
        return m, "minute"
    return float(day_bar.get("close") or 0), "close"


def _too_old(date: str) -> bool:
    try:
        return (datetime.now().date() - datetime.strptime(date, "%Y-%m-%d").date()).days > GIVEUP_AFTER_DAYS
    except Exception:
        return False


def _evaluate(rec: dict, bars: list[dict]) -> bool:
    """레코드 1건의 사후 성과 산출. 확정(더 볼 필요 없음)이면 True.

    진입가: 실제 체결가 > 그날 진입시각 분봉 시가 > 그날 종가 > screen 종가(폴백).
    손절/목표 판정은 **익일봉부터** — 진입일 저가/고가는 진입 이전 구간을 포함해 왜곡되므로 제외.
    같은 날 손절·목표를 동시에 스친 경우는 보수적으로 **손절 선행**으로 본다.
    확정은 **추적 기간을 다 채웠을 때만** — 손절/목표가 났다고 조기 확정하면 그 레코드의
    D+10·D+20 이 영구 결측돼 리포트 표본에서 패자만 빠지는 생존편향이 생긴다.
    """
    idx = next((i for i, b in enumerate(bars) if b["date"] == rec["date"]), None)
    if idx is None:
        if _too_old(rec["date"]):                      # 상장폐지·거래정지·조회범위 초과 → 포기
            rec["outcome"] = "unknown"
            rec["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            logger.info("[SHADOW] %s %s 일봉 확보 불가 — 추적 포기", rec["date"], rec["symbol"])
            return True
        return False                                   # 휴장/미수집 — 다음 update 에서 재시도
    entry, src = _entry_proxy(rec["symbol"], rec["date"], bars[idx], rec)
    entry = entry or float(rec.get("ref_price") or 0)
    if entry <= 0:
        return _too_old(rec["date"])
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
    # 손절/목표가 이미 났어도 D+N 지표를 마저 채우기 위해 추적 기간을 다 채울 때까지 계속 본다.
    # (outcome·hit_day 는 위 루프의 `if outcome == "open"` 가드로 첫 도달에 고정 — 덮어써지지 않는다.)
    return len(fut) >= MAX_TRACK_DAYS or _too_old(rec["date"])


def _migrate(recs: list[dict]) -> int:
    """구 레코드 보정 — `entry_actual` 이 도입(2026-08-05) 이전에 기록된 taken 을 살린다.

    소급분은 실체결가가 `ref_price` 에, 라이브 기록분은 `ctx.entry` 에 들어 있었다.
    """
    n = 0
    for r in recs:
        if r.get("reason") != "taken" or r.get("entry_actual"):
            continue
        v = (r.get("ctx") or {}).get("entry") or r.get("ref_price")
        if v:
            r["entry_actual"] = float(v)
            r.pop("done", None)                      # 진입가가 바뀌므로 재평가 필요
            n += 1
    return n


def update(verbose: bool = True, recompute: bool = False) -> int:
    """미확정 레코드의 사후 성과를 채운다. 종목당 OHLCV 1회만 조회(캐시).

    recompute=True 면 확정분까지 전부 다시 계산한다(평가 로직을 고쳤을 때).
    """
    recs = _load()
    migrated = _migrate(recs)
    if migrated and verbose:
        logger.info("[SHADOW] 구 taken 레코드 %d건에 실체결가 보정 — 재평가", migrated)
    if recompute:
        for r in recs:
            r.pop("done", None)
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
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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
    from src.mcp_servers.trend_mcp.signals import atr as _atr, levels as _levels
    from trend_config import CFG

    recs = _load()
    seen = {(r.get("date"), r.get("symbol")) for r in recs}
    cache: dict[str, list[dict]] = {}
    added: list[dict] = []
    for day_dir in sorted(p for p in DATA_DIR.iterdir() if p.is_dir() and _DATE_RE.match(p.name)):
        f = day_dir / "events.jsonl"
        if not f.exists():
            continue
        date = day_dir.name
        cands, taken = [], {}
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
                payload = ev.get("payload") or {}
                if ev.get("event") == "screen_done":
                    cands = payload.get("symbols") or []
                elif ev.get("event") == "entry" and payload.get("symbol"):
                    taken[payload["symbol"]] = payload
            except Exception:                       # 깨진 줄 하나가 소급 전체를 막지 않게
                continue
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
                rec = {"reason": "taken", "ref_price": p["entry"], "entry_actual": p["entry"],
                       "stop": p["stop"], "target": p["target"]}
            else:                                        # 미진입 — 같은 공식으로 손절/목표 복원
                entry, _src = _entry_proxy(sym, date, bars[idx])
                a = _atr(bars[:idx + 1], CFG.atr_period)
                if not entry or not a:
                    continue
                stop, target = _levels(entry, CFG, atr_value=a)   # 라이브와 동일 공식(단일 정본)
                rec = {"reason": "hist_blocked", "ref_price": entry, "stop": stop,
                       "target": target, "atr": round(a, 2)}
            seen.add((date, sym))
            added.append({"date": date, "ts": f"{date} 00:00:00", "symbol": sym,
                          "name": _ticker_name(sym), "score": None, "sector": None,
                          "entry_time": _entry_time_for(date), "ctx": {"backfill": True}, **rec})
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
    scored = [r for r in recs if r.get("outcome") and r["outcome"] != "unknown"]
    n_unknown = sum(1 for r in recs if r.get("outcome") == "unknown")

    print("\n" + "=" * 78)
    print(f"  그림자 원장 — 차단된 후보의 사후 성과   (총 {len(recs)}건 / 평가완료 {len(scored)}건"
          + (f" / 추적불가 {n_unknown}건" if n_unknown else "") + ")")
    print("=" * 78)
    if not scored:
        print("\n아직 평가된 레코드가 없습니다.")
        print("  기록일 일봉이 확정(장 마감)돼야 추적이 시작됩니다 — 다음 영업일 마감 후 `--update`.")
        for r in sorted(recs, key=lambda x: x["date"], reverse=True)[:10]:
            print(f"  · {r['date']} {r['name']}({r['symbol']}) — {REASONS.get(r['reason'], r['reason'])}")
        return

    _print_by_reason(scored)
    _print_verdict(scored)
    _print_monthly(scored)

    n_open = sum(1 for r in recs if r.get("outcome") == "open" and not r.get("done"))
    if n_open:
        print(f"※ 추적 중(미확정) {n_open}건 — 최대 {MAX_TRACK_DAYS}영업일 후 확정")
    print("※ 표본 20건 미만이면 방향 참고용. 사유별로는 30건 이상 쌓인 뒤 판단할 것.")
    print("※ D+N 은 그 기간을 채운 레코드만의 평균 — 괄호 안이 실제 표본 수(n 열과 다를 수 있음).")

    if detail:
        _print_detail(scored)


def _print_by_reason(scored: list[dict]) -> None:
    by: dict[str, list[dict]] = defaultdict(list)
    for r in scored:
        by[r["reason"]].append(r)
    hdr = f"{'사유':<22}{'n':>4}{'손절선행':>9}{'목표선행':>9}{'평균R':>8}{'D+5':>14}{'D+20':>14}"
    print("\n" + hdr)
    print("-" * len(hdr))
    for reason, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        n = len(rs)
        stops = sum(1 for r in rs if r["outcome"] == "stop")
        tgts = sum(1 for r in rs if r["outcome"] == "target")
        rmul = [r["r"] for r in rs if r.get("r") is not None]
        d5 = [r["fwd"]["5"] for r in rs if r.get("fwd", {}).get("5") is not None]
        d20 = [r["fwd"]["20"] for r in rs if r.get("fwd", {}).get("20") is not None]
        # D+N 은 분모가 n 과 다르다(아직 기간 미도달) → 표본 수를 같이 찍어 착시 방지.
        print(f"{REASONS.get(reason, reason):<22}{n:>4}{stops / n:>8.0%}{tgts / n:>9.0%}"
              f"{_avg(rmul):>+8.2f}{_avg(d5):>+8.2f}% (n={len(d5):>2}){_avg(d20):>+8.2f}% (n={len(d20):>2})")


def _print_verdict(scored: list[dict]) -> None:
    """차단분(taken 제외) 평균 R 부호 = 게이트 가치의 요약."""
    blocked = [r for r in scored if r["reason"] != "taken"]
    taken = [r for r in scored if r["reason"] == "taken"]
    print("\n" + "-" * 78)
    if not blocked:
        return
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


def _print_monthly(scored: list[dict]) -> None:
    """월별 분해 — 전체 평균은 지배적 레짐에 가려진다(2026-08-03 회고 교훈 #1)."""
    bym: dict[str, list[dict]] = defaultdict(list)
    for r in scored:
        bym[r["date"][:7]].append(r)
    if len(bym) <= 1:
        return
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


def _print_detail(scored: list[dict]) -> None:
    print("\n" + "=" * 84)
    print(f"{'날짜':<11}{'종목':<14}{'사유':<18}{'진입가':>9}{'출처':>7}{'결과':>7}{'일':>4}{'R':>7}{'MFE':>8}{'MAE':>8}")
    print("-" * 84)
    for r in sorted(scored, key=lambda x: x["date"], reverse=True):
        oc = {"stop": "손절", "target": "목표", "open": "미결", "unknown": "불가"}.get(r["outcome"], r["outcome"])
        print(f"{r['date']:<11}{r['name'][:12]:<14}{REASONS.get(r['reason'], r['reason'])[:16]:<18}"
              f"{r.get('entry_ref') or 0:>9,.0f}{r.get('entry_src', '-'):>7}{oc:>7}{r.get('hit_day') or 0:>4}"
              f"{r.get('r') if r.get('r') is not None else 0:>+7.2f}"
              f"{r.get('mfe', 0):>+7.1f}%{r.get('mae', 0):>+7.1f}%")


def main() -> None:
    ap = argparse.ArgumentParser(description="그림자 원장 — 차단된 후보 사후 추적")
    ap.add_argument("--update", action="store_true", help="사후 성과 갱신(장 마감 후)")
    ap.add_argument("--recompute", action="store_true", help="확정분 포함 전량 재평가(평가 로직 변경 시)")
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
    if a.update or a.recompute or not (a.report or a.backfill):
        update(recompute=a.recompute)
    if a.report or not (a.update or a.recompute or a.backfill):
        report(days=a.days, detail=a.detail)


if __name__ == "__main__":
    setup_daemon_runtime()   # 파일로깅·소켓 타임아웃 (스크립트 진입점에서만)
    main()
