"""데몬 순수 헬퍼 회귀 — 2026-08-17.

원칙: **안전장치는 실패 시 닫힌다(fail-closed).** 이 파일이 잠그는 건 그 방향이다.

과거엔 전부 반대였다 — 예외가 나면 "안전한 척" 기본값을 돌려줘서, 판정 근거를 못 구하는
순간 서킷브레이커·진입컷오프·시간청산이 조용히 꺼졌다. 에러도 알림도 없이.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT))

import trend_follow as tf  # noqa: E402


# ─── _busdays_since: 판정 불가 → None (0 아님) ─────────────────────────────
def test_busdays_counts_weekdays_only():
    d0 = datetime.now().date() - timedelta(days=7)
    n = tf._busdays_since(d0.strftime("%Y-%m-%d"))
    assert n == 5, "7일 전 = 영업일 5일(주말 2일 제외)"


def test_busdays_same_day_is_zero():
    assert tf._busdays_since(datetime.now().strftime("%Y-%m-%d")) == 0


@pytest.mark.parametrize("bad", [None, "", "not-a-date", "2026/08/17", 20260817, {}])
def test_busdays_unparsable_returns_none(bad):
    """★ 0 을 돌려주면 MAX_HOLD 시간청산이 그 종목에 영원히 발동하지 않는다(무기한 보유)."""
    assert tf._busdays_since(bad) is None


def test_aged_out_not_triggered_when_unknown():
    """None 은 '만기'로도 '미만기'로도 단정하지 않는다 — 비교 연산에서 터지지도 않아야 한다."""
    held = tf._busdays_since("garbage")
    aged = tf.MAX_HOLD_DAYS > 0 and held is not None and held >= tf.MAX_HOLD_DAYS
    assert aged is False


# ─── _past_entry_cutoff: 파싱 실패 → True(차단) ────────────────────────────
def test_cutoff_parse_failure_blocks_entry(monkeypatch):
    """★ False 를 돌려주면 컷오프가 사라져 장 마감까지 진입이 허용된다."""
    monkeypatch.setattr(tf, "ENTRY_CUTOFF", "쓰레기")
    assert tf._past_entry_cutoff() is True


@pytest.mark.parametrize("bad", ["", "25:00", "10", "abc:def"])
def test_cutoff_malformed_blocks(monkeypatch, bad):
    monkeypatch.setattr(tf, "ENTRY_CUTOFF", bad)
    assert tf._past_entry_cutoff() is True


def test_cutoff_before_now_is_past(monkeypatch):
    monkeypatch.setattr(tf, "ENTRY_CUTOFF", "00:01")
    assert tf._past_entry_cutoff() is True


def test_cutoff_after_now_is_not_past(monkeypatch):
    monkeypatch.setattr(tf, "ENTRY_CUTOFF", "23:59")
    assert tf._past_entry_cutoff() is False


# ─── _circuit_broken: 일지 판독 실패 → 차단 ────────────────────────────────
# pytest-asyncio 미설치 환경이라 asyncio.run 으로 직접 구동한다(pytest.ini 의 asyncio_mode 는 무효).
def test_circuit_fails_closed_on_unreadable_journal(monkeypatch, tmp_path):
    """★ 당일 손실을 알 수 없으면 이미 서킷이 발동했을 수도 있다 → 신규 진입 차단."""
    bad = tmp_path / "journal.json"
    bad.write_text("{ 깨진 JSON", encoding="utf-8")
    monkeypatch.setattr(tf, "JOURNAL_FILE", bad)
    monkeypatch.setattr(tf, "DAILY_LOSS_LIMIT_PCT", 2.0)
    broken, why = asyncio.run(tf._circuit_broken())
    assert broken is True and "판정 불가" in why


def test_circuit_off_when_limit_zero(monkeypatch, tmp_path):
    """서킷을 명시적으로 끈 경우엔 일지가 깨져도 차단하지 않는다(설정 존중)."""
    bad = tmp_path / "journal.json"
    bad.write_text("{ 깨진 JSON", encoding="utf-8")
    monkeypatch.setattr(tf, "JOURNAL_FILE", bad)
    monkeypatch.setattr(tf, "DAILY_LOSS_LIMIT_PCT", 0.0)
    assert asyncio.run(tf._circuit_broken())[0] is False


def test_circuit_ignores_blank_lines(monkeypatch, tmp_path):
    """빈 줄이 섞였다고 서킷이 발동하면 오탐이다(append 로그의 흔한 형태)."""
    j = tmp_path / "journal.json"
    j.write_text('\n{"type":"note","id":"x"}\n\n', encoding="utf-8")
    monkeypatch.setattr(tf, "JOURNAL_FILE", j)
    monkeypatch.setattr(tf, "DAILY_LOSS_LIMIT_PCT", 2.0)
    assert asyncio.run(tf._circuit_broken())[0] is False


# ─── 스케줄 헬퍼 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("wd,expected", [(0, True), (4, True), (5, False), (6, False)])
def test_is_weekday(wd, expected):
    base = datetime(2026, 8, 17)                      # 월요일
    assert tf._is_weekday(base + timedelta(days=wd)) is expected


@pytest.mark.parametrize("hh,mm,expected", [
    (8, 50, False),    # screen 시각 — 아직 장중 아님
    (9, 0, True),
    (12, 0, True),
    (15, 20, True),    # 상한 = exit phase 시각(포함)
    (15, 21, False),   # 이후 장중 폴링 안 함
])
def test_is_market_hours(hh, mm, expected):
    assert tf._is_market_hours(datetime(2026, 8, 18, hh, mm)) is expected


def test_market_hours_false_on_weekend():
    assert tf._is_market_hours(datetime(2026, 8, 22, 12, 0)) is False   # 토요일


def test_next_run_is_future():
    nxt = tf._next_run(15, 20)
    assert nxt > datetime.now()


def test_next_run_rolls_to_tomorrow_when_past():
    """이미 지난 시각이면 내일로 넘어가야 한다 — 안 그러면 스케줄러가 즉시 재실행 루프에 빠진다."""
    nxt = tf._next_run(0, 1)
    assert nxt.date() >= datetime.now().date()
    assert (nxt - datetime.now()).total_seconds() > 0


# ─── heartbeat 주기 ↔ watchdog stale 임계 (두 파일에 흩어진 한 쌍) ─────────────
def test_heartbeat_pair_consistent():
    """watchdog 은 stdlib 만 의존해야 해서 임계값을 자기 파일에 literal 로 갖는다.
    기록 주기만 늘리면 watchdog 이 정상 데몬을 hung 으로 오판해 taskkill /F /T 한다 —
    한 쌍이라는 사실을 여기서 잠근다."""
    import re
    from trend_config import HEARTBEAT_INTERVAL_SEC, HEARTBEAT_STALE_SEC
    assert HEARTBEAT_STALE_SEC == HEARTBEAT_INTERVAL_SEC * 10
    src = (_ROOT / "scripts" / "trend_watchdog.py").read_text(encoding="utf-8")
    m = re.search(r"^HEARTBEAT_STALE_SEC\s*=\s*(\d+)", src, re.M)
    assert m and int(m.group(1)) == HEARTBEAT_STALE_SEC, \
        f"watchdog({m.group(1) if m else '?'}) != config({HEARTBEAT_STALE_SEC})"
