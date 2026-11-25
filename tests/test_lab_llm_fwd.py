"""Claude 뉴스 판단 5일 양방향(lab_llm_fwd, LLM-N1 — 11-25 선언, 앞으로만) — 신호·보유·바꿔 타기·판정이 선언대로."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import aggr_shadow as A  # noqa: E402
import atomic_io as AIO  # noqa: E402
import lab_llm_fwd as W  # noqa: E402
import lab_trials as T  # noqa: E402
import llm_news as N  # noqa: E402


def _wdays(start: str, n: int) -> list[str]:
    d, out = dt.date.fromisoformat(start), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def test_declaration_is_forward_only_and_registered():
    assert (W.INV, W.LONG, W.CASH, W.HOLD) == ("114800", "069500", "488770", 5)
    assert (W.ANCHOR, W.START, W.JUDGE_DAYS, W.JUDGE_MIN_TRADES, W.MAX_MDD_PCT, W.EQUITY) == \
        ("2026-11-25", "2026-11-26", 120, 10, 30.0, 500_000.0)
    assert W.HOLD == N.H                                                # 질문(다음 5거래일)과 같은 보유
    row = [r for r in T.TRIALS if r[3] == "scripts/lab_llm_fwd.py"]
    assert len(row) == 1 and row[0][2] == 1 and row[0][0] == W.DECLARED_ON
    assert W.NAME in A.MEMBERS and W.NAME in A.DISPLAY and {W.INV, W.LONG, W.CASH} <= set(A.DAILY)


def test_plan_enters_next_open_holds_5_and_skips_signals_inside():
    days = _wdays("2026-11-26", 30)
    targets, trades = W.plan(days, {days[2]: -1, days[4]: +1, days[15]: +1})   # days[4] 는 보유 중 — 건너뜀
    assert targets[2] == {W.INV: 1.0} and 4 not in targets
    assert targets[7] == {W.CASH: 1.0}                                         # 진입 3 + 5 → 청산 판단 7 → 8 시가
    assert targets[15] == {W.LONG: 1.0}
    assert trades == [(3, 8, -1), (16, 21, +1)] and 8 - 3 == W.HOLD == N.H


def test_plan_exit_day_signal_extends_or_switches():
    days = _wdays("2026-11-26", 30)
    _, same = W.plan(days, {days[2]: -1, days[7]: -1})                        # 청산 판단일에 같은 방향 — 이어서
    assert same == [(3, 13, -1)]
    targets, flip = W.plan(days, {days[2]: -1, days[7]: +1})                  # 반대 방향 — 그 시가에 바꿔 탄다
    assert targets[7] == {W.LONG: 1.0} and flip == [(3, 8, -1), (8, 13, +1)]


def test_signals_read_real_llm_news_file_and_skip_before_start(tmp_path):
    """llm_news 가 쓰는 형식(writer)으로 쓰고 signals(reader)로 — START 전(11-25)·0 은 넣지 않는다."""
    p = tmp_path / "daily.csv"
    rows = [{"date": "2026-11-25", "direction": -2}, {"date": "2026-11-26", "direction": 0},
            {"date": "2026-11-27", "direction": -1}, {"date": "2026-11-30", "direction": 2}]
    AIO.write_csv(p, N.COLS, ({k: r.get(k, "") for k in N.COLS} for r in rows))
    assert W.signals(p) == {"2026-11-27": -1, "2026-11-30": 1}


def _px(days, inv_opens, long_opens=None):
    inv = {d: {"open": o, "close": o} for d, o in zip(days, inv_opens)}
    lg = {d: {"open": o, "close": o} for d, o in zip(days, long_opens or [100.0] * len(days))}
    flat = {d: {"open": 100.0, "close": 100.0} for d in days}
    return {"069500": lg, W.INV: inv, W.CASH: flat}


def test_run_records_trade_and_verdict_waits_for_records_and_trades():
    days = [W.ANCHOR] + _wdays("2026-11-26", 20)
    opens = [1000.0] * 4 + [1000.0 + 10 * k for k in range(17)]              # 진입 뒤 인버스가 오른다(이익 거래)
    r = W.run(_px(days, opens), days[-1], sig={days[2]: -1})
    assert len(r["trades"]) == 1 and r["trades"][0]["entry"] == days[3] and r["trades"][0]["exit"] == days[8]
    assert r["trades"][0]["ret"] > 0 and r["curve"][0] == (W.ANCHOR, W.EQUITY) and r["curve"][-1][1] > W.EQUITY
    assert W.verdict(r["curve"], r["trades"], 1) == {"judged": False, "why": "판단 기록 1/120 · 완료 거래 1/10"}
    ten = [{"ret": 0.01}] * 10
    assert not W.verdict([("a", 100.0), ("b", 110.0)], ten, 119)["judged"]   # 거래는 넉넉해도 기록 120 전엔 판정 안 함
    v = W.verdict([("a", 100.0), ("b", 110.0)], ten, 120)
    assert v["judged"] and v["pass"]


def test_aggr_league_runs_member_without_signals():
    """판단이 아직 없거나 전부 0 이면 현금 자리(488770)만 — 처음 살 때 비용만 빠지고 그대로(오류 아님, FLOW-S1 과 같다)."""
    days = [W.ANCHOR] + _wdays("2026-11-26", 5)
    r = W.run(_px(days, [1000.0] * len(days)), days[-1], sig={})
    vals = [v for _, v in r["curve"][1:]]
    assert r["trades"] == [] and r["on_today"] == 0 and len(set(vals)) == 1 and W.EQUITY * 0.998 < vals[0] < W.EQUITY
