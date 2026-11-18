"""구조적 수급 날짜 판정대(lab_calendar) · 시험 횟수 장부(lab_trials) — 날짜 규칙·판정·장부가 선언과 같은지 (11-18, 측정 전)."""
from __future__ import annotations

import math
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_calendar as C  # noqa: E402
import lab_trials as T  # noqa: E402


def weekdays(a: str, b: str, closed: set[str] = frozenset()) -> list[str]:
    out, x, end = [], date.fromisoformat(a), date.fromisoformat(b)
    while x <= end:
        if x.weekday() < 5 and x.isoformat() not in closed:
            out.append(x.isoformat())
        x += timedelta(days=1)
    return out


# ── 날짜 규칙 ────────────────────────────────────────────────────────────────
def test_second_thursday_known_dates():
    assert C.second_thursday(2026, 11) == date(2026, 11, 12)
    assert C.second_thursday(2026, 10) == date(2026, 10, 8)
    assert C.second_thursday(2024, 8) == date(2024, 8, 8)       # 1일이 목요일인 달


def test_expiry_moves_to_previous_trading_day_when_closed():
    """둘째 목요일이 휴장이면 그 전 거래일 — 2026-10-08 을 닫아 본다."""
    days = weekdays("2026-10-01", "2026-10-30", {"2026-10-08"})
    ks = C.expiry_days(days)
    assert [days[k] for k in ks] == ["2026-10-07"]


def test_month_end_window_is_minus1_to_plus3():
    """C1 진입 = 마지막 거래일 전날 종가, 창 4일 → 다음 달 3번째 거래일 종가."""
    days = weekdays("2026-09-21", "2026-10-15", {"2026-10-05"})
    k = C.entries("C1", days)[0]
    assert days[k] == "2026-09-29" and days[k + 4] == "2026-10-06"   # 10-01·02·(10-05 휴장)·06 = 3번째 거래일
    assert C.CANDIDATES["C1"][2] == ("cc", 4)


def test_holiday_eve_ignores_weekends():
    days = weekdays("2026-09-21", "2026-10-09", {"2026-09-24", "2026-09-25", "2026-10-09"})
    eves = [days[i] for i in C.holiday_eves(days)]
    assert eves == ["2026-09-23"]                  # 10-08 은 다음 거래일이 없어(자료 끝) 모른다 · 금요일 → 월요일은 휴장 아님
    ks = C.entries("C2", days)
    assert [days[k] for k in ks] == ["2026-09-22"]  # 그 전날 종가 진입


def test_fomc_skips_korean_holiday():
    days = weekdays("2026-09-14", "2026-09-30", {"2026-09-16"})
    assert C.fomc_days(days, ("2026-09-16", "2026-09-23")) == [days.index("2026-09-23")]
    ks = C.entries("C5", days)
    assert all(days[k + 1] in C.FOMC_DATES for k in ks)


def test_fomc_list_is_scheduled_meetings_only():
    by_year = {}
    for d in C.FOMC_DATES:
        by_year[d[:4]] = by_year.get(d[:4], 0) + 1
    assert all(v == 8 for y, v in by_year.items() if y != "2020") and by_year["2020"] == 7
    assert "2020-03-15" not in C.FOMC_DATES and sorted(C.FOMC_DATES) == list(C.FOMC_DATES)


# ── 판정 ────────────────────────────────────────────────────────────────────
def test_window_returns_and_non_overlap():
    days = ["d0", "d1", "d2", "d3", "d4", "d5"]
    bars = {d: {"open": 100.0 + i, "close": 101.0 + i} for i, d in enumerate(days)}
    assert C.window_ret(bars, days, ("cc", 4), 0) == pytest.approx(105 / 101 - 1)
    assert C.window_ret(bars, days, ("cc", 4), 2) is None           # 미래 자료 없음
    assert C.window_ret(bars, days, ("oc", 0), 1) == pytest.approx(102 / 101 - 1)
    assert C.non_overlapping([0, 2, 4], ("cc", 4)) == [0, 4]        # 0~4 안의 2 는 버림, 4 는 맞닿음
    assert C.non_overlapping([1, 1, 2], ("oc", 0)) == [1, 2]


def test_judge_rules_cost_direction_and_hurdle(monkeypatch):
    """하락 가설(C3)은 부호를 뒤집어 재고, P3 은 왕복 비용을 뺀다, P4 는 통과선."""
    days = weekdays("2010-01-04", "2026-11-17")
    bars = {d: {"open": 100.0, "close": 100.0} for d in days}
    exp = {days[k] for k in C.expiry_days(days)}
    for d in exp:
        bars[d] = {"open": 100.0, "close": 99.0 + (0.2 if int(d[-2:]) % 2 else 0.0)}   # 만기일마다 −0.8~−1%
    r = C.judge(bars, days, "C3", hurdle_t=3.46, cost=0.00115)
    for s in r["periods"].values():
        assert s["n"] >= C.MIN_EVENTS and s["mean"] > 0.0099 * 0.7 and all(s["checks"].values())
    assert r["pooled"]["P4"] and r["pass"]
    r2 = C.judge(bars, days, "C3", hurdle_t=3.46, cost=0.02)        # 비용이 효과보다 크면 P3 탈락
    assert not r2["pass"] and not any(s["checks"]["P3"] for s in r2["periods"].values())


def test_judge_no_effect_fails_p4():
    days = weekdays("2010-01-04", "2026-11-17")
    bars, px = {}, 100.0
    for i, d in enumerate(days):                                    # 결정적 흔들림 — 날짜와 무관한 수익
        r = 0.01 * math.sin(i * 1.7)
        bars[d] = {"open": px, "close": px * (1 + r)}
        px *= 1 + r
    for n in C.CANDIDATES:
        assert not C.judge(bars, days, n, hurdle_t=3.46, cost=0.00115)["pooled"]["P4"]


# ── 시험 횟수 장부 ───────────────────────────────────────────────────────────
def test_trials_ledger_and_hurdle():
    assert T.total() == sum(r[2] for r in T.TRIALS)
    assert T.total("2026-11-17") == 88 and T.total_through("scripts/lab_calendar.py") == 93
    assert C.trials() == 93                                         # 같은 날 2묶음(lab_jkp)을 더해도 이 묶음의 통과선은 그대로
    with pytest.raises(KeyError):
        T.total_through("scripts/없는_판정대.py")
    assert T.hurdle_t(5) == 3.0                                     # 적게 쟀어도 하한 3.0(Harvey·Liu·Zhu)
    assert T.hurdle_t(93) == pytest.approx(3.46, abs=0.01)
    hs = [T.hurdle_t(n) for n in (10, 50, 100, 200, 500, 1000)]
    assert hs == sorted(hs) and hs[-1] < 4.2                        # 많이 잴수록 오르되 천천히
    with pytest.raises(ValueError):
        T.hurdle_t(0)


def test_this_batch_is_registered_before_measuring():
    """선언과 장부가 같다 — 후보 수 = 장부의 이 묶음 행 · 통과선은 그 행까지 합친 수로."""
    row = [r for r in T.TRIALS if r[0] == C.DECLARED_ON and "lab_calendar" in r[3]]
    assert len(row) == 1 and row[0][2] == len(C.CANDIDATES)
    assert C.hurdle() == T.hurdle_t(T.total_through("scripts/lab_calendar.py"))
