"""수급 판정대(lab_flows) — 선언한 숫자·계산이 적힌 대로인지. 합성 자료만(실측은 선언 커밋 뒤)."""
from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_flows as F  # noqa: E402
import market_flows as MF  # noqa: E402


def test_declared_numbers():
    assert (F.Z_WIN, F.Z_EXTREME, F.Z_JOINT, F.H, F.H_REPORT) == (60, 2.0, 1.0, 5, (1, 20))
    assert (F.MIN_EVENTS, F.HIT_GAIN_PP, F.EXCESS_MIN_PCT) == (20, 5.0, 0.3)
    assert F.PERIODS == {"앞": ("2010-04-01", "2020-12-31"), "뒤": ("2021-01-01", "2026-11-13")}
    assert {s: d for s, (_, d) in F.SIGNALS.items()} == {"S1": -1, "S2": 1, "S3": 1, "S4": -1, "S5": -1}
    assert abs(F.side_cost() - 0.00115) < 1e-12


def test_zscore_uses_only_previous_days():
    xs = [float(x) for x in range(1, 62)]                # 1..61
    z = F.zscores(xs, win=60)
    prev = xs[:60]
    assert z[:60] == [None] * 60
    assert abs(z[60] - (61 - statistics.fmean(prev)) / statistics.stdev(prev)) < 1e-12
    assert F.zscores([1.0, None, 3.0, 4.0], win=2)[3] is None          # 창에 빈 값 → None
    assert F.zscores([5.0, 5.0, 5.0], win=2)[2] is None                # 표준편차 0 → None


def test_signal_thresholds_are_inclusive():
    assert F.fires("S1", {"f": -2.0}) and not F.fires("S1", {"f": -1.99})
    assert F.fires("S2", {"f": 2.0}) and not F.fires("S2", {"f": None})
    assert F.fires("S3", {"f": 1.0, "i": 1.0}) and not F.fires("S3", {"f": 1.0, "i": 0.9})
    assert F.fires("S4", {"f": -1.0, "i": -1.5}) and not F.fires("S4", {"f": -1.0, "i": None})
    assert F.fires("S5", {"p": -2.5}) and not F.fires("S5", {"p": -1.0})


def test_forward_enters_next_open_and_exits_h_days_later():
    """★ 검증 = 운용: d 수급은 d+1 아침에 확정 → d+1 시가 진입, 그 h 거래일 뒤 시가 청산. d 의 시가·종가는 쓰지 않는다."""
    days = ["d0", "d1", "d2", "d3", "d4"]
    opens = {"d0": 999.0, "d1": 100.0, "d2": 102.0, "d3": 105.0, "d4": 110.0}
    f = F.forward(days, opens, 2)
    assert abs(f["d0"] - (105 / 100 - 1)) < 1e-12 and abs(f["d1"] - (110 / 102 - 1)) < 1e-12
    assert "d2" not in f                                   # 미래 자료 없음


def test_trades_do_not_overlap_and_pay_costs():
    days = [f"d{k}" for k in range(12)]
    fwd = {d: 0.01 for d in days}
    got = F.trades(["d0", "d1", "d4", "d5", "d9"], days, fwd, +1, 5, 0.001)
    assert len(got) == 2 and all(abs(x - (0.01 - 0.002)) < 1e-12 for x in got)   # d0 진입 뒤 d5 부터 다시
    short = F.trades(["d0"], days, fwd, -1, 5, 0.001)
    assert abs(short[0] - (-0.01 - 0.002)) < 1e-12


def test_judge_checks():
    days = [f"d{k:03d}" for k in range(200)]
    fwd = {d: (0.02 if k % 10 == 0 else -0.001) for k, d in enumerate(days)}
    sig = [d for k, d in enumerate(days) if k % 10 == 0]              # 신호 날은 늘 +2%
    r = F.judge(sig, days, fwd, +1, 5, 0.00115)
    assert r["n"] == 20 and r["checks"] == {"P1": True, "P2": True, "P3": True, "P4": True} and r["pass"]
    r2 = F.judge(sig[:19], days, fwd, +1, 5, 0.00115)
    assert r2["checks"]["P1"] is False and r2["pass"] is False
    r3 = F.judge(sig, days, fwd, -1, 5, 0.00115)                      # 방향을 거꾸로 걸면 떨어진다
    assert r3["pass"] is False


def test_load_reads_only_confirmed_rows(tmp_path):
    p = tmp_path / "daily.csv"
    rows = [{"date": "2020-01-02", "kospi_foreign_eok": "100", "kospi_inst_eok": "-5", "prog_nonarb": "7", "check": "ok"},
            {"date": "2020-01-03", "kospi_foreign_eok": "9", "kospi_inst_eok": "9", "prog_nonarb": "9", "check": "bad:+1.00%"},
            {"date": "2020-01-06", "kospi_foreign_eok": "", "kospi_inst_eok": "1", "prog_nonarb": "2", "check": "ok"}]
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MF.COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    days, flows = F.load(p)
    assert days == ["2020-01-02", "2020-01-06"] and flows["f"] == [100.0, None] and flows["p"] == [7.0, 2.0]
