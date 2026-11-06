"""시장 수급 이력 — 연구용 단일 파일 data/market_flows/daily.csv (2026-11-06, 운용자 "채워줘").

키움 ka10051(코스피·코스닥 종합 투자자별 순매수, **KRX**, 억원)과 ka90010(코스피 프로그램 매매, 백만원 · KOSPI200 ·
선물 베이시스)을 거래일마다 한 줄로. 지난 날짜도 확정치를 준다(2010-01-04 까지 확인) → 2010 부터 한꺼번에 채우고,
그 뒤로는 매일 아침 market_journal.fill_final_flows 가 전 거래일을 덧붙인다.

- 조회만(주문 무관). 이어받기 — 이미 있는 날은 건너뛴다. 50행마다 원자적 저장. 실패는 3번까지 다시, 그래도 안 되면
  그날은 비워 두고 다음 실행이 채운다.
- **가드(날짜 대조)**: ka10051 응답에는 날짜가 없다. 요청한 날이 아닌 값을 주면 조용히 틀린 날짜로 쌓이고, 그 위의
  연구가 전부 무효가 된다(08-27 '--start 무시' 결함과 같은 종류). 그래서 응답의 코스피 지수를 그날 FDR ^KS11 종가와
  대조해 CHECK_TOL(0.5%)을 넘으면 check='bad:…' 로 남긴다 — 연구는 check=='ok' 인 줄만 쓴다.
- 열(ASCII): 금액 단위는 열 이름 끝에 — *_eok = 억원, prog_* = 백만원.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

FLOWS_FILE = _ROOT / "data" / "market_flows" / "daily.csv"
START = "2010-01-04"
CHECK_TOL = 0.005
SAVE_EVERY = 50
CALL_PAUSE_S = 0.05
RETRIES = 3
INVESTORS = {"외국인": "foreign", "기관": "inst", "개인": "indiv", "기타법인": "corp", "금융투자": "fininv",
             "연기금": "pension"}
COLS = (["date", "kospi", "kospi_chg_pct"] + [f"kospi_{v}_eok" for v in INVESTORS.values()]
        + ["kosdaq", "kosdaq_chg_pct"] + [f"kosdaq_{v}_eok" for v in INVESTORS.values()]
        + ["prog_arb", "prog_nonarb", "prog_total", "kospi200", "basis", "check", "fetched_at"])


# ── 순수 함수 ────────────────────────────────────────────────────────────────
def check_index(ix_close: float | None, ks_close: float | None, tol: float = CHECK_TOL) -> str:
    """응답의 코스피 지수 vs 그날 FDR ^KS11 종가 — 'ok' · 'bad:+1.23%' · 'unchecked'(대조할 값이 없음)."""
    if ix_close is None or not ks_close:
        return "unchecked"
    d = ix_close / ks_close - 1
    return "ok" if abs(d) <= tol else f"bad:{d * 100:+.2f}%"


def row_from(day: str, kospi: dict | None, kosdaq: dict | None, program: dict | None, ks_close: float | None,
             fetched_at: str) -> dict:
    """market_journal.index_flows / program_flows 결과 → CSV 한 줄."""
    r: dict = {"date": day, "fetched_at": fetched_at}
    for name, ix in (("kospi", kospi), ("kosdaq", kosdaq)):
        ix = ix or {}
        r[name], r[f"{name}_chg_pct"] = ix.get("지수"), ix.get("등락(%)")
        for k, v in INVESTORS.items():
            r[f"{name}_{v}_eok"] = ix.get(k)
    p = program or {}
    r.update(prog_arb=p.get("차익"), prog_nonarb=p.get("비차익"), prog_total=p.get("전체"), kospi200=p.get("KOSPI200"),
             basis=p.get("베이시스"))
    r["check"] = check_index((kospi or {}).get("지수"), ks_close)
    return r


def mark_duplicate(row: dict, prev: dict | None) -> dict:
    """앞 거래일과 지수·외국인 순매수가 똑같으면 check='dup' — 달력에 휴장일이 섞였을 때 키움이 전날 값을 다시 준 날."""
    if prev and row.get("kospi") is not None and row.get("kospi") == prev.get("kospi") \
            and row.get("kospi_foreign_eok") == prev.get("kospi_foreign_eok"):
        row = {**row, "check": "dup"}
    return row


def load_rows(path: Path = FLOWS_FILE) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {r["date"]: r for r in csv.DictReader(f)}


def upsert(rows: list[dict], path: Path = FLOWS_FILE) -> int:
    """같은 날짜는 바꿔 쓰고 날짜순으로 원자적 저장. 저장 후 행 수."""
    cur = load_rows(path)
    for r in rows:
        cur[r["date"]] = {k: ("" if r.get(k) is None else r.get(k)) for k in COLS}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(cur[d] for d in sorted(cur))
    tmp.replace(path)
    return len(cur)


def ks_closes(start: str, end: str) -> dict[str, float]:
    """거래소 달력 겸 대조값 — FDR ^KS11 종가."""
    import strategy_lab as L
    return {d: v["close"] for d, v in L.load_bars("^KS11", start, end).items()}


# ── 키움 조회 ────────────────────────────────────────────────────────────────
async def _call(c, api: str, params: dict) -> dict:
    last = None
    for attempt in range(RETRIES):
        try:
            await asyncio.sleep(CALL_PAUSE_S * (1 + 20 * attempt))
            return await c.call_api(api, params)
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


async def index_day(c, day: str) -> tuple[dict | None, dict | None]:
    import market_journal as MJ
    d = day.replace("-", "")
    kp = await _call(c, "ka10051", {"mrkt_tp": "0", "amt_qty_tp": "0", "base_dt": d, "stex_tp": "1"})
    kq = await _call(c, "ka10051", {"mrkt_tp": "1", "amt_qty_tp": "0", "base_dt": d, "stex_tp": "1"})
    return MJ.index_flows(kp.get("inds_netprps") or []), MJ.index_flows(kq.get("inds_netprps") or [])


async def program_history(c, days: list[str]) -> dict[str, dict]:
    """ka90010 은 요청일부터 과거로 100거래일을 준다 → 가장 늦은 날부터 거꾸로 이어 받는다(약 42번이면 2010 까지)."""
    import market_journal as MJ
    want, out = sorted(days), {}
    cursor = want[-1] if want else None
    while cursor and cursor >= want[0]:
        r = await _call(c, "ka90010", {"date": cursor.replace("-", ""), "amt_qty_tp": "1", "mrkt_tp": "P00101",
                                       "min_tic_tp": "0", "stex_tp": "1"})
        rows = r.get("prm_trde_trnsn") or []
        if not rows:
            break
        for row in rows:
            k = str(row.get("cntr_tm", ""))[:8]
            day = f"{k[:4]}-{k[4:6]}-{k[6:]}"
            out.setdefault(day, MJ.program_flows([row], day))
        oldest = min(str(row.get("cntr_tm", ""))[:8] for row in rows)
        nxt = (date(int(oldest[:4]), int(oldest[4:6]), int(oldest[6:])) - timedelta(days=1)).isoformat()
        if nxt >= cursor:
            break
        cursor = nxt
    return out


async def backfill(start: str = START, end: str | None = None, path: Path = FLOWS_FILE) -> dict:
    from src.mcp_servers.kiwoom_mcp.common.client.kiwoom_restapi_client import KiwoomRESTAPIClient
    end = end or datetime.now().strftime("%Y-%m-%d")
    ks = ks_closes(start, end)
    have = load_rows(path)
    todo = [d for d in sorted(ks) if d not in have]
    print(f"[market_flows] {start}~{end} 거래일 {len(ks)} · 이미 있음 {len(have)} · 받을 날 {len(todo)}", flush=True)
    if not todo:
        return {"added": 0}
    c = KiwoomRESTAPIClient()
    added, bad, failed, buf, prev = 0, [], [], [], None
    try:
        prog = await program_history(c, todo)
        print(f"[market_flows] 프로그램 매매 {len(prog)}일치 받음", flush=True)
        for i, day in enumerate(todo, 1):
            try:
                kp, kq = await index_day(c, day)
            except Exception as e:  # noqa: BLE001
                failed.append(day)
                print(f"  ! {day} 실패 {type(e).__name__}: {str(e)[:80]}", flush=True)
                continue
            row = row_from(day, kp, kq, prog.get(day), ks.get(day), datetime.now().isoformat(timespec="seconds"))
            row, prev = mark_duplicate(row, prev), row
            if row["check"] != "ok":
                bad.append((day, row["check"]))
            buf.append(row)
            if len(buf) >= SAVE_EVERY:
                upsert(buf, path)
                added += len(buf)
                buf = []
            if i % 200 == 0:
                print(f"  {i}/{len(todo)} {day} · 대조 어긋남 {len(bad)} · 실패 {len(failed)}", flush=True)
        if buf:
            upsert(buf, path)
            added += len(buf)
    finally:
        if hasattr(c, "close"):
            await c.close()
    print(f"[market_flows] 끝 — 추가 {added} · 대조 어긋남 {len(bad)} {bad[:10]} · 실패 {len(failed)} {failed[:10]}", flush=True)
    return {"added": added, "bad": bad, "failed": failed}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backfill", action="store_true", required=True)
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=None)
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    r = asyncio.run(backfill(args.start, args.end))
    return 1 if r.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
