"""놓친 phase 복구 회귀 — 2026-09-09.

배경: watchdog 이 08:50:22 에 데몬을 재기동했고 새 데몬이 08:50:27 에 떴다.
`_next_run(8,50)` 이 **27초 차이로** 슬롯을 내일로 넘겨 그날 스크린이 통째로 사라졌다.
중복 실행 가드(`_phase_done_today`)는 있었는데 그 반대 — **미실행** — 를 메우는 장치가
없었고, 건너뛴 사실을 즉시 알리지도 않았다(11:00 stale-candidate 가드가 2시간 뒤에 잡음).

watchdog 이 장 시작 무렵 데몬을 재기동하는 것은 매일 있는 일이므로(밤샘 절전 → 08:40
MCP 복구) 이 경로는 언제든 재발한다. 그래서 테스트로 잠근다.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))


@pytest.fixture
def tf(monkeypatch, tmp_path):
    """state 를 임시 파일로 돌린 trend_follow — 실제 운영 state 를 건드리지 않는다."""
    import trend_runtime as RT
    monkeypatch.setattr(RT, "STATE_FILE", tmp_path / "state.json")
    RT._STATE_CACHE = None if hasattr(RT, "_STATE_CACHE") else None
    import trend_follow as TF
    return TF


def _at(h, m, s=0):
    return datetime(2026, 9, 9, h, m, s)          # 수요일


# ─── 슬롯이 아직 안 왔으면 아무것도 안 한다 ──────────────────────────────────
def test_before_slot_is_not_missed(tf):
    assert tf._missed_phases(_at(8, 30)) == []


# ─── ★ 27초 차이로 슬롯을 넘긴 그 상황 ───────────────────────────────────────
def test_screen_missed_by_seconds_is_detected(tf, monkeypatch):
    """★ 2026-09-09 재현 — 08:50:27 기동 시 screen 이 '놓침'으로 잡혀야 한다.

    과거엔 `_next_run` 이 조용히 내일로 넘겨 아무도 몰랐다.
    """
    monkeypatch.setattr(tf, "_phase_done_today", lambda _p: False)
    missed = tf._missed_phases(_at(8, 50, 27))
    assert [p for p, _s, _g in missed] == ["screen"], missed
    _phase, slot, in_grace = missed[0]
    assert slot == _at(8, 50), "슬롯 시각이 어긋난다"
    assert in_grace is True, "진입(11:00) 전이므로 복구 유예 안이어야 한다"


def test_done_phase_is_not_reported_missed(tf, monkeypatch):
    """이미 실행된 phase 는 놓침이 아니다 — 중복 실행하면 안 된다."""
    monkeypatch.setattr(tf, "_phase_done_today", lambda p: p == "screen")
    assert [p for p, _s, _g in tf._missed_phases(_at(9, 0))] == []


def test_missed_marker_stops_repeat_alerts(tf, monkeypatch):
    """포기 표식(!missed)이 찍히면 다시 보고하지 않는다 — 매 루프 알림 폭탄 방지."""
    monkeypatch.setattr(tf, "_phase_done_today",
                        lambda p: p == "screen" + tf._MISSED_SUFFIX)
    assert [p for p, _s, _g in tf._missed_phases(_at(9, 0))] == []


# ─── 유예 경계 — 늦게 하는 게 더 위험한 지점 ────────────────────────────────
def test_screen_grace_ends_at_entry_time(tf, monkeypatch):
    """screen 후보는 entry 가 소비한다 — 진입 시각을 넘기면 복구할 이유가 없다."""
    monkeypatch.setattr(tf, "_phase_done_today", lambda _p: False)
    before = dict((p, g) for p, _s, g in tf._missed_phases(_at(10, 59)))
    after = dict((p, g) for p, _s, g in tf._missed_phases(_at(11, 1)))
    assert before["screen"] is True
    assert after["screen"] is False, "진입 시각 이후에도 screen 을 복구하려 한다"


def test_entry_grace_ends_at_cutoff(tf, monkeypatch):
    """★ 진입 복구는 기존 '보류→반등' 마감(ENTRY_CUTOFF)과 같은 선에서 끝나야 한다.

    그보다 늦은 진입은 검증된 조건 밖이다 — 실계좌에 검증 안 된 시각의 주문이 나간다.
    """
    monkeypatch.setattr(tf, "_phase_done_today", lambda _p: False)
    h, m = (int(x) for x in tf.ENTRY_CUTOFF.split(":"))
    cut = _at(h, m)
    before = dict((p, g) for p, _s, g in tf._missed_phases(cut - timedelta(minutes=1)))
    after = dict((p, g) for p, _s, g in tf._missed_phases(cut + timedelta(minutes=1)))
    assert before["entry"] is True
    assert after["entry"] is False, "마감 뒤에도 진입을 복구하려 한다"


def test_exit_grace_ends_before_market_close(tf, monkeypatch):
    """★ 장 마감(15:30) 뒤 매도는 rc 505217 로 전량 거부된다 — 그 전에 끊어야 한다."""
    monkeypatch.setattr(tf, "_phase_done_today", lambda _p: False)
    before = dict((p, g) for p, _s, g in tf._missed_phases(_at(15, 27)))
    after = dict((p, g) for p, _s, g in tf._missed_phases(_at(15, 29)))
    assert before["exit"] is True
    assert after["exit"] is False, "장 마감 임박/경과인데 청산을 복구하려 한다"
    h, m = (int(x) for x in tf._CATCHUP_DEADLINE["exit"].split(":"))
    assert h * 60 + m < 15 * 60 + 30, "청산 유예선이 장 마감을 넘는다"


# ─── 유예 설정 자체의 무결성 ─────────────────────────────────────────────────
def test_every_scheduled_phase_has_a_deadline(tf):
    """★ SCHEDULE 에 phase 를 추가하고 유예를 안 넣으면 KeyError 로 데몬 루프가 죽는다."""
    for _h, _m, phase in tf.SCHEDULE:
        assert phase in tf._CATCHUP_DEADLINE, f"{phase} 의 복구 유예가 없다"


def test_deadlines_are_after_their_slots(tf):
    """유예선이 슬롯보다 이르면 복구가 영원히 불가능하다(조용히 항상 '포기')."""
    for h, m, phase in tf.SCHEDULE:
        dh, dm = (int(x) for x in tf._CATCHUP_DEADLINE[phase].split(":"))
        assert dh * 60 + dm > h * 60 + m, f"{phase}: 유예선이 슬롯보다 이르다"


def test_missed_suffix_does_not_collide_with_phase_names(tf):
    """표식이 phase 이름과 섞이면 '실행됨'과 '포기'를 구분할 수 없다."""
    names = {p for _h, _m, p in tf.SCHEDULE}
    for n in names:
        assert n + tf._MISSED_SUFFIX not in names
