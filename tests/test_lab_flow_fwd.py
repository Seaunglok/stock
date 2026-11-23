"""외국인 극단 순매도 뒤 인버스 20일(lab_flow_fwd, FLOW-S1 — 11-23 선언, 앞으로만) — 신호·보유·판정이 선언대로."""
from __future__ import annotations

import csv
import datetime as dt
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import aggr_shadow as A  # noqa: E402
import lab_flow_fwd as W  # noqa: E402
import lab_flows as FL  # noqa: E402
import lab_trials as T  # noqa: E402


def _wdays(start: str, n: int) -> list[str]:
    d, out = dt.date.fromisoformat(start), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def test_declaration_reuses_lab_flows_and_is_forward_only():
    assert (W.SIGNAL, W.INV, W.CASH, W.HOLD) == ("S1", "114800", "488770", 20)
    assert (W.ANCHOR, W.START, W.JUDGE_MIN_TRADES, W.MAX_MDD_PCT, W.EQUITY) == \
        ("2026-11-23", "2026-11-24", 10, 30.0, 500_000.0)
    assert (FL.Z_WIN, FL.Z_EXTREME) == (60, 2.0)                       # 신호 정의를 새로 고르지 않는다
    row = [r for r in T.TRIALS if r[3] == "scripts/lab_flow_fwd.py"]
    assert len(row) == 1 and row[0][2] == 1 and row[0][0] == W.DECLARED_ON
    assert W.NAME in A.MEMBERS and W.NAME in A.DISPLAY and W.INV in A.DAILY


def test_plan_enters_next_open_holds_20_and_skips_signals_inside():
    days = _wdays("2026-11-24", 60)
    sig = {days[2], days[5], days[30]}                                  # days[5] 는 보유 중 — 건너뜀
    targets, trades = W.plan(days, sig)
    assert targets[2] == {W.INV: 1.0} and 5 not in targets              # 신호 날 종가 판단 → 다음 날 시가
    assert targets[22] == {W.CASH: 1.0}                                 # 진입(3) + 20 → 청산 판단 22 → 23 시가
    assert trades[0] == (3, 23) and trades[1] == (31, 51)
    assert 23 - 3 == W.HOLD


def test_plan_signal_on_exit_day_extends_holding():
    days = _wdays("2026-11-24", 60)
    targets, trades = W.plan(days, {days[2], days[22]})                 # 청산 판단일(22)에 또 신호
    assert 22 not in targets and targets[42] == {W.CASH: 1.0} and trades == [(3, 43)]


def test_plan_open_trade_at_end():
    days = _wdays("2026-11-24", 10)
    _, trades = W.plan(days, {days[5]})
    assert trades == [(6, -1)]


def _flows_csv(path: Path, days: list[str], foreign: dict[str, float]):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "kospi_foreign_eok", "kospi_inst_eok", "prog_nonarb", "check"])
        w.writeheader()
        for k, d in enumerate(days):
            w.writerow({"date": d, "kospi_foreign_eok": foreign.get(d, 100.0 * (1 if k % 2 else -1)),
                        "kospi_inst_eok": 0.0, "prog_nonarb": 0.0, "check": "ok"})


def test_signal_days_reads_real_csv_and_excludes_before_start(tmp_path):
    """실제 수급 이력 형식(writer)으로 쓰고 lab_flows.load(reader)로 — START 전 극단 매도(11-20 같은 날)는 넣지 않는다."""
    days = _wdays("2026-08-03", 90)
    before = [d for d in days if d < W.START][-1]
    after = [d for d in days if d >= W.START][3]
    p = tmp_path / "daily.csv"
    _flows_csv(p, days, {before: -9000.0, after: -9000.0})
    assert W.signal_days(p) == {after}


def _px(days, inv_opens):
    inv = {d: {"open": o, "close": o} for d, o in zip(days, inv_opens)}
    flat = {d: {"open": 100.0, "close": 100.0} for d in days}
    return {"069500": flat, W.INV: inv, W.CASH: flat}


def test_run_records_trade_and_verdict_waits_for_ten_trades():
    days = [W.ANCHOR] + _wdays("2026-11-24", 40)
    opens = [1000.0] * 5 + [1000.0 - 5 * k for k in range(36)]           # 진입 뒤 인버스가 내려간다(손실 거래)
    r = W.run(_px(days, opens), days[-1], sig={days[3]})
    assert len(r["trades"]) == 1 and r["trades"][0]["entry"] == days[4] and r["trades"][0]["ret"] < 0
    assert r["curve"][0] == (W.ANCHOR, W.EQUITY) and r["curve"][-1][1] < W.EQUITY
    assert W.verdict(r["curve"], r["trades"]) == {"judged": False, "why": "완료 거래 1/10"}
    ten = [{"ret": 0.01}] * 10
    v = W.verdict([("a", 100.0), ("b", 110.0)], ten)
    assert v["judged"] and v["pass"]
    v = W.verdict([("a", 100.0), ("b", 110.0)], [{"ret": -0.01}] * 10)
    assert v["judged"] and not v["pass"] and not v["checks"]["거래당>0"]


def test_aggr_league_runs_member_without_inverse_data():
    """합성 자료에 인버스가 없으면 빈 기록(오류 아님) — 기존 멤버 시험 자료를 그대로 써도 리그가 멈추지 않는다."""
    days = _wdays("2026-10-28", 5)
    flat = {d: {"open": 100.0, "close": 100.0} for d in days}
    r = W.run({"069500": flat, W.CASH: flat}, days[-1], sig=set())
    assert r["curve"] == [] and r["trades"] == []
