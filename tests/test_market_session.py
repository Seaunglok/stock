"""장 시간(market_session, 백로그 ⑲ 11-23) — 평소 날은 옛 상수와 같고, 바뀐 날은 개장·마감을 따른다. 일정이 깨지면 믿지 않는다."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import claude_guard as G  # noqa: E402
import i3_live as LV  # noqa: E402
import market_session as MS  # noqa: E402


# ── 옛 길 == 새 길(평소 날) ──────────────────────────────────────────────────
def test_normal_day_equals_old_constants():
    """★ 평소 날의 모든 시각이 바꾸기 전 상수와 같다 — 하나라도 어긋나면 평소 매매가 바뀐다."""
    s = MS.Session("2026-11-23")
    assert not s.shifted
    assert s.decide_after == LV.DECIDE_AFTER == time(15, 35)
    assert s.trade_window == LV.TRADE_WINDOW == (time(8, 30), time(9, 20))
    assert s.sell_at == time(8, 50)                                  # 예약작업 I3Trade 시각
    assert s.buy_after == LV.BUY_AFTER == time(9, 5, 30)
    assert s.settle_at == time(9, 0, 30)                             # 옛 settle() 의 dtime(9, 0, 30)
    assert s.broker_wait_until == LV.BROKER_WAIT_UNTIL == time(9, 15)
    assert s.guard_windows() == G.WINDOWS


def test_every_ordinary_weekday_through_2027_is_normal():
    """실제 일정 파일 — 장 시간 항목이 있는 날만 바뀌고, 나머지 평일은 전부 평소(옛 길)."""
    shifted = MS.load_sessions()
    d = date(2026, 10, 22)
    while d <= date(2027, 12, 31):
        s = MS.session_for(d.isoformat())
        assert s.shifted == (d.isoformat() in shifted and shifted[d.isoformat()].shifted)
        d += timedelta(days=1)


# ── 바뀐 날(실제 일정 파일) ──────────────────────────────────────────────────
def test_suneung_2026_from_real_calendar():
    s = MS.session_for("2026-11-19")
    assert (s.open, s.close, s.confirmed) == (time(10, 0), time(16, 30), True)
    assert s.decide_after == time(16, 35)                            # 11-19 은 손으로 16:45 로 옮겼던 날
    assert s.trade_window == (time(9, 30), time(10, 20)) and s.sell_at == time(9, 50)
    assert s.guard_windows() == ((time(8, 30), time(10, 20)), (time(15, 50), time(16, 45)))


def test_new_year_2027_from_real_calendar():
    """2027-01-04 — 10:00 개장 · 마감 그대로 · 아직 공지 전(관행으로 적음)."""
    s = MS.session_for("2027-01-04")
    assert (s.open, s.close, s.confirmed) == (time(10, 0), time(15, 30), False)
    assert s.decide_after == time(15, 35)                            # 마감이 같으면 판단도 그대로
    assert (s.sell_at, s.buy_after, s.settle_at, s.broker_wait_until) == \
        (time(9, 50), time(10, 5, 30), time(10, 0, 30), time(10, 15))
    assert s.guard_windows() == ((time(8, 30), time(10, 20)), (time(15, 50), time(16, 0)))
    assert [x.day for x in MS.upcoming("2026-12-30")] == ["2027-01-04"]
    assert MS.upcoming("2026-12-27") == [] and MS.upcoming("2027-01-04") == []


# ── 일정이 깨지면 믿지 않는다 ────────────────────────────────────────────────
@pytest.mark.parametrize("body", [
    "{깨짐",
    json.dumps({"date": "2027-01-04"}),                                          # 목록 아님
    json.dumps([{"date": "2027-01-04", "open": "10:00", "close": "09:30"}]),      # 개장 ≥ 마감
    json.dumps([{"date": "2027-01-04", "open": "1000"}]),                         # 형식
    json.dumps([{"date": "2027-01-04", "open": "03:00"}]),                        # 말이 안 되는 시각
    json.dumps([{"date": "2027-13-04", "open": "10:00"}]),                        # 날짜
])
def test_broken_calendar_raises(tmp_path, body):
    p = tmp_path / "cal.json"
    p.write_text(body, encoding="utf-8")
    with pytest.raises(Exception):
        MS.load_sessions(p)
    s, soon, err = LV.session_today("2027-01-04", p)              # 실전 연결: 평소 시간 + 오류(→ critical)
    assert not s.shifted and soon == [] and err


def test_missing_calendar_is_an_error_not_normal(tmp_path):
    s, _, err = LV.session_today("2027-01-04", tmp_path / "없음.json")
    assert not s.shifted and err and "FileNotFoundError" in err


def test_event_only_entries_do_not_change_hours(tmp_path):
    p = tmp_path / "cal.json"
    p.write_text(json.dumps([{"date": "2026-12-09", "event": "FOMC"}]), encoding="utf-8")
    assert MS.load_sessions(p) == {} and not MS.session_for("2026-12-09", p).shifted


# ── 기다림·평일 수 ───────────────────────────────────────────────────────────
def test_wait_seconds():
    now = datetime(2027, 1, 4, 8, 50)
    assert MS.wait_seconds(now, time(9, 50), timedelta(hours=2)) == 3600
    assert MS.wait_seconds(now, time(8, 40), timedelta(hours=2)) == 0
    assert MS.wait_seconds(now, time(11, 0), timedelta(hours=2)) is None


@pytest.mark.parametrize("a, b, n", [
    ("2026-12-30", "2027-01-04", 3),     # 연말연시 — 달력 5일, 평일 3일(12-31·01-01 휴장 + 01-04)
    ("2026-11-20", "2026-11-23", 1),     # 금 → 월
    ("2027-02-04", "2027-02-09", 3),     # 목 → 화(사이 평일 휴장 이틀 — 설·추석이 주말에 붙는 모양)
    ("2025-10-02", "2025-10-10", 6),     # 2025 추석 같은 긴 연휴
    ("2026-11-23", "2026-11-23", 0),
])
def test_weekdays_between(a, b, n):
    assert MS.weekdays_between(a, b) == n
