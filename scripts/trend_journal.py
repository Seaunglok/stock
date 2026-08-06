"""일별 매매일지 md 생성 — docs/YYYY-MM-DD-trend-journal.md.

trend_follow.py 에서 분리(2026-08-06). 주문 경로와 무관한 **보고 계층**이라
여기를 고쳐도 실거래 로직은 건드리지 않는다. 집계는 순수 함수라 단독 테스트 가능.

15:20 청산 phase 자동 호출 + `trend_follow.py --phase journal` 수동.
"""
from __future__ import annotations

from datetime import datetime

from trend_config import PRODUCTION_MODE, UNIVERSE_MODE, _ROOT, logger
from trend_kiwoom_io import _realtime_price, kospi_closes
from trend_runtime import get_state, log_event, notify, read_events, read_journal

# events.jsonl 이벤트 → 마감 요약 카운터. (카운터키, md 라벨, 텔레그램 약칭)
_SAFETY_SPEC = (
    ("hard_stop",    "🔴 하드손절 발동",       "하드손절"),
    ("circuit_break", "🛑 서킷브레이커 발동",   "서킷"),
    ("sell_reject",  "🚨 매도 거부",           "매도거부"),
    ("fill_missing", "⚠️ 미체결 감지",          "미체결"),
    ("fill_partial", "⚠️ 부분체결 감지",        "부분체결"),
    ("adopted",      "📥 계좌보유분 편입",      None),
    ("pyramid",      "📈 피라미딩 추가매수",    None),
)
_SELL_PHASES = ("exit", "intraday", "force_close")


def safety_event_counts(events: list[dict]) -> dict[str, int]:
    """events.jsonl 레코드 → 안전 이벤트 카운터. 운영 모니터링용(순수 함수)."""
    c = {k: 0 for k, _, _ in _SAFETY_SPEC}
    for ev in events:
        name = ev.get("event", "")
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        payload = payload or {}
        if name == "exit" and "하드" in str(payload.get("reason", "")):
            c["hard_stop"] += 1
        elif name == "circuit_break":
            c["circuit_break"] += 1
        elif name == "order_reject" and payload.get("phase") in _SELL_PHASES:
            c["sell_reject"] += 1
        elif name == "reconcile_adopt":
            c["adopted"] += 1
        elif name == "fill_partial":
            c["fill_partial"] += 1
        elif name == "fill_missing":
            c["fill_missing"] += 1
        elif name == "pyramid_add":
            c["pyramid"] += 1
    return c


def _safety_md(counts: dict[str, int]) -> list[str]:
    if not any(counts.values()):
        return []
    out = ["", "## ⚙️ 안전 이벤트 (당일)"]
    out += [f"- {label} **{counts[k]}건**" for k, label, _ in _SAFETY_SPEC if counts.get(k)]
    return out


def _safety_line(counts: dict[str, int]) -> str:
    """텔레그램 마감 메시지용 1줄 요약(즉시대응 필요분만 — 편입/피라미딩 제외)."""
    bits = [f"{short} {counts[k]}" for k, _, short in _SAFETY_SPEC if short and counts.get(k)]
    return "\n⚠️ " + " · ".join(bits) if bits else ""


def _market_line(closes: list[float]) -> str:
    if len(closes) < 2:
        return "N/A"
    prev, last = closes[-2], closes[-1]
    return f"{prev:,.1f} → {last:,.1f} ({(last - prev) / prev * 100:+.2f}%)"


async def _position_rows() -> tuple[list[tuple], float]:
    """보유분 현재가 조회 → (정렬된 행, 평가손익 합계). 손익률 내림차순."""
    rows, tot = [], 0.0
    for p in get_state("positions", []):
        live = await _realtime_price(p["symbol"]) or p["entry_price"]
        pnl = (live - p["entry_price"]) / p["entry_price"] * 100 if p["entry_price"] else 0.0
        amt = (live - p["entry_price"]) * p["qty"]
        tot += amt
        rows.append((p, live, pnl, amt))
    rows.sort(key=lambda x: -x[2])
    return rows, tot


def _trade_md(entries: list[dict], exits: list[dict], partials: list[dict]) -> list[str]:
    L = [f"## 매매 (신규 {len(entries)} · 청산 {len(exits)} · 부분익절 {len(partials)})"]
    if entries:
        L += ["| 종목 | 진입가 | 수량 | 금액 | 점수 |", "|------|--------|------|------|------|"]
        L += [f"| {e['name']}({e['symbol']}) | {e['entry_price']:,.0f} | {e['qty']} | "
              f"{e['entry_price'] * e['qty']:,.0f} | {e.get('score', '')} |" for e in entries]
    L += [f"- 청산 {e['name']}({e['symbol']}) {e['qty']}주 @{e['exit_price']:,.0f} "
          f"net {e.get('net_pct', 0):+.2f}% — {e.get('reason', '')}" for e in exits]
    if not entries and not exits:
        L.append("- 신규/청산 없음 (보유 유지)")
    return L


async def write_daily_journal() -> None:
    """그날 매매일지 md 자동 생성 — journal(진입/청산/부분) + 보유 P&L + KOSPI + 안전 이벤트."""
    today = datetime.now().strftime("%Y-%m-%d")
    todays = read_journal(today)
    entries = [r for r in todays if r.get("type") == "entry"]
    exits = [r for r in todays if r.get("type") == "exit"]
    partials = [r for r in todays if r.get("type") == "partial"]

    mode_tag = "💰 REAL" if PRODUCTION_MODE else "🧪 MOCK"
    rows, tot = await _position_rows()
    realized = sum(e.get("entry_price", 0) * e.get("qty", 0) * e.get("net_pct", 0) / 100.0
                   for e in exits)

    L = [f"# 추세추종 매매일지 — {today}", "",
         f"> 대형주 추세추종 ({mode_tag}) · 모드 {UNIVERSE_MODE} · 자동 생성 · 대시보드 :8091", "",
         f"## 시장\n- KOSPI {_market_line(await kospi_closes())}", ""]
    L += _trade_md(entries, exits, partials)
    L += ["", f"## 보유 {len(rows)}종 · 평가손익 **{tot:+,.0f}원** (당일 실현 {realized:+,.0f}원)",
          "| 종목 | 수량 | 진입 | 현재 | 손익 | 평가손익 |", "|------|------|------|------|------|------|"]
    L += [f"| {p['name']}({p['symbol']}) | {p['qty']} | {p['entry_price']:,.0f} | "
          f"{live:,.0f} | {pnl:+.2f}% | {amt:+,.0f} |" for p, live, pnl, amt in rows]

    counts = safety_event_counts(read_events(today))
    L += _safety_md(counts)
    L += ["", "*자동 생성. 심리/실수/개선은 `--journal-note <id>` 또는 대시보드에서 추가.*", ""]

    out = _ROOT / "docs" / f"{today}-trend-journal.md"
    out.write_text("\n".join(L), encoding="utf-8")
    logger.info("[JOURNAL] 매매일지 자동작성: %s", out.name)
    log_event("journal_write", {"file": out.name, "entries": len(entries),
                                "exits": len(exits), "eval_pnl": round(tot)})
    await notify(f"📓 <b>마감 {today}</b> ({mode_tag})\n"
                 f"진입 {len(entries)} · 청산 {len(exits)} · 보유 {len(rows)}\n"
                 f"실현 {realized:+,.0f}원 · 평가 {tot:+,.0f}원" + _safety_line(counts))
