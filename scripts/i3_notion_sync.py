"""I3 → Notion 동기화 보조 — 계산은 파이썬이, Notion 반영만 에이전트가 (2026-10-22).

운용자(10-22): "노션에 매일매일 추가해야 하는데, I3 페이지에만 추가하면 계속 길어진다. 한눈에 보기 좋게,
매매일지·history 를 제대로 남기는 방법을 추가해 달라."
→ 매일 쌓이는 것은 **DB 의 행**으로만 남긴다(페이지는 고치지 않는다 — 대시보드는 DB 바로가기만 둔다).
  설계 근거는 docs/notion-guide.md.

    prep   최근 LOOKBACK_DAYS 일의 I3 기록을 Notion 행 모양으로 계산해 OUT_FILE 에 쓴다.
             daily   — 일일 기록DB: 판단·자산·성과·매매·입출금·리그 (하루 1행)
             trades  — 주식 매매일지DB: 체결 1건 = 1행(매매이유 MARK "🛡️ 방어형 ETF 자동매매(I3) …"), 매도는 평균단가 기준
             months  — 월별 결산DB: "🛡️ 방어형 ETF 자동매매(I3) YYYY년 M월" 1행(매수·매도·실현손익·비용·월 수익률)
             Notion 에 보이는 이름은 줄임말 단독 금지 — TRACK·DISPLAY(풀네임(줄임말), 운용자 10-22)
           에이전트는 파일과 DB 를 대조해 **없는 행만** 추가하고 월 행만 갱신한다 — 하루를 놓쳐도 다음 실행이 메운다.
           산수는 여기서 한다. LLM 이 계산하지 않게(추세추종 notion_sync 와 같은 원칙, 2026-10-01).
    check  에이전트 실행이 끝난 뒤 **이번 실행분 로그**에 결과 줄이 없거나 ❌ 면 텔레그램 critical + exit 1.
           예약작업 결과(0x0)는 프로세스 종료코드일 뿐 반영 성공이 아니다(2026-07 OAuth 은폐 · 09-28 rate limit 사고).

주문·상태 경로와 무관하다(읽기만: data/i3/{events.jsonl,state.json,fills.jsonl,shadow_history.csv}).

사용법
------
    python scripts/i3_notion_sync.py prep
    python scripts/i3_notion_sync.py check --log %TEMP%\\i3_notion.log --offset <실행 전 로그 크기>
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

DATA_DIR = _ROOT / "data" / "i3"
OUT_FILE = DATA_DIR / "notion_sync.json"
LOOKBACK_DAYS = 10         # 대조 창 — 연휴(최대 5일)에 하루 실패가 겹쳐도 다음 실행이 메운다
RESULT_TAG = "결과:"       # 에이전트가 마지막에 찍는 한 줄 — i3_notion_task.md 의 규약
FEE_BPS = 1.5              # 편도 수수료(i3_flows.FEE_BPS 와 같은 값) — ETF 매도는 거래세 없음
NAMES = {"069500": "KODEX 200", "488770": "KODEX 머니마켓액티브", "153130": "KODEX 단기채권"}
WEEKDAY = "월화수목금토일"

# Notion 에 보이는 이름 — 운용자(10-22): "노션에서는 줄임말을 풀네임(줄임말)로". 코드 식별자(I3·R1…)는 그대로 둔다.
TRACK = "방어형 ETF 자동매매(I3)"
MARK = f"🛡️ {TRACK}"       # 매매일지 매매이유·월별 결산 제목의 앞머리 = i3_notion_task.md 의 조회 키(바꾸면 같이 바꾼다)
DISPLAY = {                 # 리그 멤버 이름이 영문 줄임말이면 여기 풀네임이 있어야 한다(테스트가 확인)
    "I3": TRACK,
    "R1": "재진입 리셋(R1)",
    "R6": "1년 1회 리셋·250일선 상승 때만(R6)",
    "I1a": "재진입 확인 엔진만(I1a)",
    "MA60": "KOSPI 60일 이동평균(MA60)",
    "Faber10": "파버 10개월 이동평균(Faber10)",
    "TSMOM": "시계열 모멘텀(TSMOM)",
    "RSI2": "2일 상대강도지수(RSI2)",
    "D5a": "방어 자산 추세 현금 자리(D5a)",
    "T6c": "장기 추세 연동 예산 배수 8/4(T6c)",
    "V7a": "추세 연동 배수 + 변동성 브레이크(V7a)",
}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln:
            out.append(json.loads(ln))
    return out


def _title(day: str) -> str:
    return f"{day} ({WEEKDAY[date.fromisoformat(day).weekday()]})"


def _pct(a: float | None, b: float | None) -> float | None:
    return None if not a or not b else round((a / b - 1) * 100, 2)


# ── 리그 ────────────────────────────────────────────────────────────────────
def league_text(rows: list[dict], day: str, slug_names: dict[str, str], champion: str = TRACK) -> str | None:
    """shadow_history.csv 의 그날 행 → '1위 X +a% · 방어형 ETF 자동매매(I3) n위/m · 실계좌 +b%'.
    slug_names 는 열 이름 → Notion 표시 이름(champion 도 표시 이름).
    수익의 기준은 **공통 출발 자산**(첫 live_nav = 실전 시작일 자산) — 리그 멤버는 모두 그날 그 자산으로 출발한다.
    열마다 첫 값을 기준으로 삼으면 나중에 추가한 멤버(첫 기록이 출발 다음 날)의 첫날 손익이 0 으로 사라진다
    (10-23 T6c·V7a·D5a 가 −0.11% 인데 0% 로 보여 챔피언 순위가 13 → 17위로 잘못 나온 결함). live_nav 가 없으면 열마다 첫 값."""
    first: dict[str, float] = {}
    today = None
    for r in rows:
        for k, v in r.items():
            if (k.endswith("_nav") or k == "live_nav") and v not in ("", None) and k not in first:
                first[k] = float(v)
        if r.get("date") == day:
            today = r
    if not today:
        return None
    common = first.get("live_nav")
    rets = {}
    for k, v in today.items():
        if k.endswith("_nav") and k != "live_nav" and v not in ("", None) and first.get(k):
            rets[slug_names.get(k[:-4], k[:-4])] = (float(v) / (common or first[k]) - 1) * 100
    if not rets:
        return None
    rets = {n: round(r, 2) for n, r in rets.items()}   # 표시 정밀도(0.01%p)로 순위 — 1원 미만 차이가 순위를 가르지 않게
    best = max(rets.values())                          # (10-23 한미반반이 원 단위 미만 0.57원 많아 챔피언 위로 셌다)
    tops = sorted(n for n, r in rets.items() if r == best)
    txt = f"1위 {tops[0]} {best:+.2f}%" if len(tops) == 1 else f"공동 1위 {len(tops)}개 {best:+.2f}%"
    if champion in rets:                     # 동률은 같은 순위(첫날처럼 모두 같으면 1위)
        rank = 1 + sum(r > rets[champion] for r in rets.values())
        txt += f" · {champion} {rank}위/{len(rets)}"
    lv = today.get("live_nav")
    if lv not in ("", None) and first.get("live_nav"):
        txt += f" · 실계좌 {(float(lv) / first['live_nav'] - 1) * 100:+.2f}%"
    return txt


# ── 매매 ────────────────────────────────────────────────────────────────────
def _fill_px(f: dict) -> float | None:
    return f.get("fill_price") or None


def trade_rows(fills: list[dict], since: str, plans: dict[str, dict], fee_bps: float = FEE_BPS) -> tuple[list[dict], list[str]]:
    """체결 기록 → 매매일지DB 행(since 이후). 매도 실현손익은 **평균단가**(전체 체결 이력으로 계산) 기준, 수수료 반영.

    체결가를 못 읽은 기록(parsed false)은 행을 만들지 않고 경고로 돌려준다 — 추정가로 장부를 쓰지 않는다.
    plans: 매매일 → {"w", "reason"}(그 매매를 만든 판단). 매도 행엔 현 보유 구간의 첫 매수일·보유기간을 붙인다.
    """
    fee = fee_bps / 1e4
    pos: dict[str, dict] = {}            # code → {"qty", "cost"(수수료 포함 매수원가), "since"}
    rows, warns = [], []
    for f in sorted(fills, key=lambda x: (x["date"], 0 if x["side"] == "sell" else 1)):
        code, day, side = f["code"], f["date"], f["side"]
        px, qty = _fill_px(f), int(f.get("fill_qty") or 0)
        if not px or qty <= 0:
            if day >= since:
                warns.append(f"{day} {side} {code} {f.get('qty')}주 체결가 미확인 — HTS 로 확인")
            continue
        p = pos.setdefault(code, {"qty": 0, "cost": 0.0, "since": None})
        name = f"{NAMES.get(code, code)}({code})"
        plan = plans.get(day, {})
        why = []
        if plan.get("w") is not None:
            why.append(f"목표 KODEX200 {plan['w'] * 100:.0f}%" + (f" ({plan['reason']})" if plan.get("reason") else ""))
        if side == "buy" and f.get("limit"):
            why.append(f"지정가 {f['limit']:,.0f}")
        if f.get("slippage_bp") is not None:
            why.append(f"슬리피지 {f['slippage_bp']:+.1f}bp")
        reason = f"{MARK} {'매수' if side == 'buy' else '매도'}" + (" — " + " · ".join(why) if why else "")
        if side == "buy":
            if p["qty"] == 0:
                p["since"] = day
            p["qty"] += qty
            p["cost"] += px * qty * (1 + fee)
            if day >= since:
                rows.append({"key": f"{code}|매수|{day}", "종목명": name, "매매구분": "매수", "매수일자": day,
                             "체결단가": round(px, 2), "체결수량": qty, "총체결금액": round(px * qty),
                             "매매비용": round(px * qty * fee), "매매이유": reason})
        else:
            sell_q = min(qty, p["qty"]) if p["qty"] > 0 else 0
            avg = p["cost"] / p["qty"] if p["qty"] > 0 else None
            row = {"key": f"{code}|매도|{day}", "종목명": name, "매매구분": "매도", "매도일자": day,
                   "체결단가": round(px, 2), "체결수량": qty, "총체결금액": round(px * qty), "매매이유": reason}
            if avg and sell_q:
                proceeds = px * sell_q * (1 - fee)
                row["실현손익"] = round(proceeds - avg * sell_q)
                row["수익률(%)"] = round((proceeds / (avg * sell_q) - 1) * 100, 2)
                row["매매비용"] = round(px * qty * fee + (avg / (1 + fee)) * sell_q * fee)
                if p["since"]:
                    row["매수일자"] = p["since"]
                    row["보유기간(일)"] = (date.fromisoformat(day) - date.fromisoformat(p["since"])).days
                p["cost"] -= avg * sell_q
                p["qty"] -= sell_q
                if p["qty"] == 0:
                    p["cost"], p["since"] = 0.0, None
            elif day >= since:
                warns.append(f"{day} 매도 {code} {qty}주 — I3 체결 기록에 매수 원가 없음(실현손익 비움)")
            if day >= since:
                rows.append(row)
    return rows, warns


def month_rows(fills: list[dict], trades_all: list[dict], navs: list[list], months: list[str]) -> list[dict]:
    """월별 결산 — 그 달 I3 매수·매도·실현손익·비용 합계 + 성과 지수 월 수익률(입출금 제외)."""
    out = []
    idx = {d: float(v) for d, v in navs}
    days = sorted(idx)
    for m in months:
        ts = [t for t in trades_all if (t.get("매도일자") or t.get("매수일자", ""))[:7] == m]
        buy = sum(t["총체결금액"] for t in ts if t["매매구분"] == "매수")
        sell = sum(t["총체결금액"] for t in ts if t["매매구분"] == "매도")
        pnl = sum(t.get("실현손익", 0) for t in ts if t["매매구분"] == "매도")
        cost = sum(t.get("매매비용", 0) for t in ts)
        in_m = [d for d in days if d[:7] == m]
        prev = [d for d in days if d[:7] < m]
        ret = None
        if in_m:
            base = idx[prev[-1]] if prev else idx[in_m[0]]
            ret = _pct(idx[in_m[-1]], base)
        y, mo = m.split("-")
        out.append({"key": m, "월": f"{MARK} {y}년 {int(mo)}월 (💰 실거래)", "총 매수 금액": round(buy),
                    "총 매도 금액": round(sell), "총 실현손익": round(pnl), "총 매매 비용": round(cost),
                    "월 수익률(%)": ret, "기준일": in_m[-1] if in_m else None})
    return out


# ── 일일 기록 ───────────────────────────────────────────────────────────────
def _trade_text(tr: dict) -> str:
    if tr.get("note"):
        return tr["note"]
    fills = {(x["side"], x["code"]): x for x in tr.get("fills", [])}
    parts = []
    for s, c, q, st in tr.get("results", []):
        f = fills.get((s, c), {})
        t = f"{'매수' if s == 'buy' else '매도'} {NAMES.get(c, c)} {q}주"
        if f.get("fill_price"):
            t += f" @{f['fill_price']:,.0f}"
            if f.get("slippage_bp") is not None:
                t += f"({f['slippage_bp']:+.1f}bp)"
        if st != "ok":
            t += f" [{st}]"
        parts.append(t)
    return " · ".join(parts) or "주문 없음"


FLOW_LABEL = {"declared": "신고", "auto-withdrawal": "출금(자동)", "auto-deposit": "입금(자동)",
              "distribution": "분배금", "skip-trade": "매매일 — 판정 보류"}


def daily_rows(events: list[dict], navs: list[list], league: dict[str, str], since: str) -> list[dict]:
    """events.jsonl + 성과 지수 → 일일 기록DB 행. 하루에 판단이 여러 번이면 마지막 것."""
    by_day: dict[str, dict] = {}
    for e in events:
        p = e.get("payload") or {}
        day = p.get("date") or str(e.get("ts", ""))[:10]
        by_day.setdefault(day, {})[e["event"]] = p
    idx = {d: float(v) for d, v in navs}
    days_i = sorted(idx)
    prev_close = None
    rows = []
    for day in sorted(by_day):
        ev = by_day[day]
        dec = ev.get("decide")
        close = (dec or {}).get("close", {}).get("069500")
        if day >= since:
            row: dict = {"key": day, "날짜": _title(day), "일자": day}
            notes = []
            if dec:
                row.update({"판단": "내일 매매" if dec.get("trade") else "매매 없음",
                            "엔진": "보유" if dec.get("engine_holding") else "이탈",
                            "낙폭 예산(%)": round(dec["exposure"] * 100, 1),
                            "목표 KODEX200(%)": round(dec["w"] * 100, 1),
                            "사유": dec.get("reason", ""), "운용 자산": dec.get("nav")})
                if close:
                    row["KODEX200 종가"] = close
                    row["KODEX200 일간(%)"] = _pct(close, prev_close)
                fl = dec.get("flow") or {}
                if fl.get("how") and fl["how"] != "none":
                    row["입출금"] = f"{FLOW_LABEL.get(fl['how'], fl['how'])} {fl.get('amount', 0):+,}원"
            elif "decide_abort" in ev:
                row["판단"] = "판단 중단"
                notes.append(ev["decide_abort"].get("reason", ""))
            elif "decide_skip" in ev:
                row["판단"] = "판단 건너뜀"
                row["사유"] = ev["decide_skip"].get("reason", "")
            if day in idx:
                k = days_i.index(day)
                row["누적(%)"] = _pct(idx[day], idx[days_i[0]])
                row["일간(%)"] = _pct(idx[day], idx[days_i[k - 1]]) if k else 0.0
            if "trade" in ev:
                tr = ev["trade"]
                row["매매"] = ("🧪 " if tr.get("dry_run") else "") + _trade_text(tr)
                bad = [f"{s} {c} {st}" for s, c, q, st in tr.get("results", []) if st != "ok"]
                if bad:
                    notes.append("주문 " + ", ".join(bad))
            if league.get(day):
                row["리그"] = league[day]
            if notes:
                row["특이사항"] = " · ".join(n for n in notes if n)
            if "판단" in row or "매매" in row:
                rows.append(row)
        if close:
            prev_close = close
    return rows


def plans_by_trade_day(events: list[dict]) -> dict[str, dict]:
    """매매일 → 그 매매를 만든 판단(직전 '내일 매매' 판단의 목표 비중·사유)."""
    out, last = {}, None
    for e in events:
        p = e.get("payload") or {}
        if e["event"] == "decide" and p.get("trade"):
            last = {"w": p.get("w"), "reason": p.get("reason")}
        elif e["event"] == "trade" and last:
            out[p.get("date")] = last
    return out


def build_payload(events: list[dict], navs: list[list], fills: list[dict], league_rows: list[dict],
                  slug_names: dict[str, str], today: datetime, lookback: int = LOOKBACK_DAYS) -> dict:
    since = (today - timedelta(days=lookback)).strftime("%Y-%m-%d")
    league = {}
    for r in league_rows:
        d = r.get("date", "")
        if d >= since:
            t = league_text(league_rows, d, slug_names)
            if t:
                league[d] = t
    daily = daily_rows(events, navs, league, since)
    plans = plans_by_trade_day(events)
    trades_all, _ = trade_rows(fills, "0000-00-00", plans)
    trades, warns = trade_rows(fills, since, plans)
    months = sorted({(t.get("매도일자") or t.get("매수일자"))[:7] for t in trades}
                    | {d["일자"][:7] for d in daily} | {today.strftime("%Y-%m")})
    return {"generated_at": today.isoformat(timespec="seconds"), "since": since, "lookback_days": lookback,
            "daily": daily, "trades": trades, "months": month_rows(fills, trades_all, navs, months),
            "warnings": warns}


def _league_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def prep(today: datetime | None = None, data_dir: Path = DATA_DIR, out: Path = OUT_FILE) -> dict:
    import i3_shadow as S
    st = json.loads((data_dir / "state.json").read_text(encoding="utf-8")) if (data_dir / "state.json").exists() else {}
    payload = build_payload(_read_jsonl(data_dir / "events.jsonl"), st.get("navs") or [],
                            _read_jsonl(data_dir / "fills.jsonl"), _league_rows(data_dir / "shadow_history.csv"),
                            {S._slug(m.name): DISPLAY.get(m.name, m.name) for m in S.MEMBERS}, today or datetime.now())
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(out)
    return payload


def prep_summary(payload: dict) -> str:
    """로그 한 줄. **결과 태그를 쓰지 않는다** — check 가 이 줄을 에이전트 결과로 오인하면 안 된다."""
    w = f" · 경고 {len(payload['warnings'])}" if payload["warnings"] else ""
    return (f"[i3_notion prep] {payload['since']}~ 일일 {len(payload['daily'])}행 · 매매 {len(payload['trades'])}행"
            f" · 결산월 {','.join(m['key'] for m in payload['months'])}{w}")


# ── check ───────────────────────────────────────────────────────────────────
def judge(new_log: str) -> tuple[bool, str]:
    """이번 실행분 로그 → (성공, 사유). 마지막 결과 줄로 판정한다."""
    lines = [ln.strip().strip("`") for ln in new_log.splitlines() if RESULT_TAG in ln]
    if not lines:
        return False, "결과 줄 없음 — 동기화가 중간에 끝났다(rate limit·타임아웃·인증·중단)"
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
        print(f"[i3_notion check] ok — {why[:160]}")
        return 0
    msg = ("🚨 <b>[I3] Notion 기록 미완료</b>\n" + why[:300] +
           f"\n→ 다음 실행이 최근 {LOOKBACK_DAYS}일을 대조해 자동으로 메웁니다. "
           "반복되면 scripts\\i3_notion.cmd 수동 실행 · 로그 %TEMP%\\i3_notion.log")
    print(f"[i3_notion check] FAIL — {why[:160]}")
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
