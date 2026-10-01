"""Notion 매매일지 동기화 보조 — 계산은 파이썬이, Notion 반영만 에이전트가 (2026-10-01).

배경
----
09-28 TrendJournalNotion 실행이 Notion API rate limit 에 걸려 결과 없이 끝났다. 예약작업 결과는
0x0 이라 아무도 몰랐고, 동기화 규칙이 '오늘 거래만' 넣는 방식이라 다음 날에도 메워지지 않았다.
09-28 매수 2건이 매매일지DB 에서 빠진 채 9월 결산 매수가 0 으로 집계됐다(10-01 수동 보완).
08-25 KB금융 매도 행도 증권사 체결가 정정이 Notion 에 반영되지 않은 채 남아 있었다.

    prep   최근 LOOKBACK_DAYS 일의 매매기록(journal.json)을 Notion 행 모양으로 계산해 OUT_FILE 에 쓴다.
           에이전트는 이 파일과 DB 를 대조해 **없는 행만** 추가한다 — 하루를 놓쳐도 다음 실행이 메운다.
           실현손익 같은 값은 여기서 계산한다. LLM 이 마크다운을 해석하거나 산수를 하지 않게.
    check  에이전트 실행이 끝난 뒤, **이번 실행분 로그**에 결과 줄이 없거나 ❌ 이면 텔레그램
           critical 알림 + exit 1. 예약작업 결과(0x0)는 프로세스 종료코드일 뿐 반영 성공이 아니다.

주문·상태 경로와 무관하다(읽기는 journal.json, 쓰기는 OUT_FILE 과 알림뿐).

사용법
------
    python scripts/notion_sync.py prep
    python scripts/notion_sync.py check --log %TEMP%\\notion_journal.log --offset <실행 전 로그 크기>
    python scripts/notion_sync.py check ... --dry-run     # 알림 대신 출력
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

LOOKBACK_DAYS = 7          # 대조 창 — 추석(3일)+주말에 하루 실패가 겹쳐도 다음 실행이 메운다
OUT_FILE = _ROOT / "data" / "trend_follow" / "notion_sync_trades.json"
RESULT_TAG = "결과:"       # 에이전트가 마지막에 찍는 한 줄 — notion_journal_task.md 의 규약


# ── prep ────────────────────────────────────────────────────────────────────
def notion_rows(records: list[dict], since: str) -> list[dict]:
    """매매기록 → 매매일지DB 행. since(YYYY-MM-DD) 이후 진입·청산만.

    값 규약은 기존 DB 행과 같다(10-01 실측 대조):
      총체결금액 = 체결단가 × 수량
      실현손익   = 진입금액(진입가 × 수량) × net% — 비용 반영. 예) 삼성E&A 149,550 × -4.74% = -7,089
    청산 기록은 증권사 체결가로 정정된 값(corrected)이 이미 반영돼 있다 — 그대로 쓴다.
    부분익절·피라미딩·메모는 넣지 않는다(현 구성에서 꺼져 있다).
    """
    rows: list[dict] = []
    for r in records:
        kind, day = r.get("type"), str(r.get("ts", ""))[:10]
        if kind not in ("entry", "exit") or day < since:
            continue
        sym = str(r.get("symbol") or "")
        name = f"{r.get('name') or sym}({sym})"
        qty = int(r.get("qty") or 0)
        if not sym or qty <= 0:
            continue
        if kind == "entry":
            px = float(r["entry_price"])
            detail = ", ".join(x for x in (str(r.get("mode") or ""),
                                           f"점수 {r['score']}" if r.get("score") is not None else "") if x)
            rows.append({"key": f"{sym}|매수|{day}", "종목명": name, "매매구분": "매수", "매수일자": day,
                         "체결단가": round(px), "체결수량": qty, "총체결금액": round(px * qty),
                         "매매이유": "🤖 추세추종 신규 진입" + (f" ({detail})" if detail else "")})
        else:
            px, net = float(r["exit_price"]), float(r["net_pct"])
            rows.append({"key": f"{sym}|매도|{day}", "종목명": name, "매매구분": "매도", "매도일자": day,
                         "체결단가": round(px), "체결수량": qty, "총체결금액": round(px * qty),
                         "실현손익": round(float(r["entry_price"]) * qty * net / 100), "수익률(%)": net,
                         "매매이유": f"🤖 추세추종 청산 — {r.get('reason', '')}".rstrip(" —")})
    return rows


def build_payload(records: list[dict], today: datetime, lookback: int = LOOKBACK_DAYS) -> dict:
    since = (today - timedelta(days=lookback)).strftime("%Y-%m-%d")
    rows = notion_rows(records, since)
    months = sorted({(r.get("매수일자") or r.get("매도일자"))[:7] for r in rows} | {today.strftime("%Y-%m")})
    return {"generated_at": today.isoformat(timespec="seconds"), "since": since,
            "lookback_days": lookback, "months": months, "rows": rows}


def prep(today: datetime | None = None) -> dict:
    from trend_runtime import read_journal
    payload = build_payload(read_journal(), today or datetime.now())
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return payload


def prep_summary(payload: dict) -> str:
    """로그에 남는 한 줄. **결과 태그를 쓰지 않는다** — check 가 이 줄을 에이전트 결과로 오인하면 안 된다."""
    n_buy = sum(1 for r in payload["rows"] if r["매매구분"] == "매수")
    return (f"[notion_sync prep] {payload['since']}~ 거래 {len(payload['rows'])}행"
            f"(매수 {n_buy}·매도 {len(payload['rows']) - n_buy}) · 결산월 {','.join(payload['months'])}")


# ── check ───────────────────────────────────────────────────────────────────
def judge(new_log: str) -> tuple[bool, str]:
    """이번 실행분 로그 → (성공, 사유). 마지막 결과 줄로 판정한다."""
    lines = [ln.strip().strip("`") for ln in new_log.splitlines() if RESULT_TAG in ln]
    if not lines:
        return False, "결과 줄 없음 — 동기화가 중간에 끝났다(rate limit·타임아웃·중단)"
    last = lines[-1]
    if "❌" in last:
        return False, last
    return True, last


def read_new_log(log: Path, offset: int) -> str:
    if not log.exists():
        return ""
    with log.open("rb") as f:
        f.seek(max(0, offset))
        return f.read().decode("utf-8", errors="replace")


def check(log: Path, offset: int, dry_run: bool = False) -> int:
    ok, why = judge(read_new_log(log, offset))
    if ok:
        print(f"[notion_sync check] ok — {why[:160]}")
        return 0
    msg = ("🚨 <b>Notion 일지 동기화 미완료</b>\n" + why[:300] +
           f"\n→ 다음 실행이 최근 {LOOKBACK_DAYS}일을 대조해 자동으로 메웁니다. "
           "반복되면 scripts\\notion_journal.cmd 수동 실행 · 로그 %TEMP%\\notion_journal.log")
    print(f"[notion_sync check] FAIL — {why[:160]}")
    if dry_run:
        print("[dry-run] 알림 생략:", msg.replace("\n", " | "))
    else:
        from trend_runtime import notify
        asyncio.run(notify(msg, critical=True))
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prep")
    c = sub.add_parser("check")
    c.add_argument("--log", required=True)
    c.add_argument("--offset", type=int, default=0)
    c.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.cmd == "prep":
        print(prep_summary(prep()))
        return 0
    return check(Path(args.log), args.offset, args.dry_run)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
